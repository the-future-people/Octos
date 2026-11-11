from rest_framework import generics, filters, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from apps.communications.models import Conversation, Message
from apps.communications.services import handover
from apps.communications.services.access import visible_conversations
from apps.accounts.models import CustomUser
from .serializers import (
    ConversationListSerializer, ConversationDetailSerializer,
    MessageSerializer, MessageCreateSerializer, ConversationAssignSerializer
)

# What staff are told when WhatsApp's 24-hour window is shut. Plain words:
# staff don't need to know what a template is, only when it will work again.
WINDOW_CLOSED = (
    "This customer hasn't written to us in the last 24 hours, so WhatsApp "
    "won't deliver a normal message. It will work again as soon as they write."
)


def _visible(request, pk):
    """The conversation, if this user may see it; None if not, or if it doesn't exist."""
    return visible_conversations(request.user).filter(pk=pk).first()


def _not_found():
    return Response({'detail': 'Conversation not found.'}, status=status.HTTP_404_NOT_FOUND)


class ConversationListView(generics.ListAPIView):
    serializer_class = ConversationListSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['contact_phone', 'contact_email', 'contact_name']

    def get_queryset(self):
        # The user's branch plus every company (WhatsApp) conversation;
        # everything for a user with no branch. See services/access.py.
        qs = visible_conversations(self.request.user).select_related(
            'branch', 'customer', 'assigned_to'
        )

        # Optional query param overrides (for managers with multi-branch access)
        branch_id    = self.request.query_params.get('branch')
        channel      = self.request.query_params.get('channel')
        status_param = self.request.query_params.get('status')
        assigned_to  = self.request.query_params.get('assigned_to')

        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        if channel:
            qs = qs.filter(channel=channel)
        if status_param:
            qs = qs.filter(status=status_param)
        if assigned_to:
            qs = qs.filter(assigned_to_id=assigned_to)

        return qs


class ConversationDetailView(generics.RetrieveAPIView):
    serializer_class = ConversationDetailSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return visible_conversations(self.request.user).select_related(
            'branch', 'customer', 'assigned_to'
        ).prefetch_related('messages', 'jobs')

    def get_object(self):
        obj = super().get_object()
        # Reset the unread count when opened: only if there is one, and without
        # a save (9 Nov 2026). Saving on every fetch, every 3 seconds, made
        # every portal fetch again once chats were announced: a loop.
        if obj.unread_count:
            type(obj).objects.filter(pk=obj.pk).update(unread_count=0)
            obj.unread_count = 0
        return obj

    def get_serializer_context(self):
        # ?after=<message id>: only what's new since then (9 Nov 2026).
        context = super().get_serializer_context()
        after = self.request.query_params.get('after', '')
        context['after'] = int(after) if after.isdigit() else None
        return context


class ConversationReplyView(APIView):
    """
    POST /api/v1/communications/<id>/reply/
    Body: { body, message_type?, is_internal_note? }

    A reply on a WhatsApp conversation is really sent: through
    whatsapp_outbound.send_text, which checks the 24-hour window, records
    the message as QUEUED and has the worker deliver it. Its status then
    follows Meta's receipts. A shut window is refused with a plain reason;
    nothing is saved that wasn't sent.

    Internal notes, and replies on other channels, are recorded as before.
    Replying to an unclaimed conversation claims it for the replying user,
    once the reply has actually gone.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        conversation = _visible(request, pk)
        if conversation is None:
            return _not_found()

        # Files: documents and photos sent on WhatsApp, or kept on a note
        # for staff (7 Nov 2026). Text alongside goes after them.
        files = request.FILES.getlist('attachments') if hasattr(request, 'FILES') else []
        if files:
            return _reply_with_files(request, conversation, files)

        serializer = MessageCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        is_note = data.get('is_internal_note', False)
        quoted = _quoted_in(conversation, request.data.get('reply_to'))

        if conversation.channel == Conversation.WHATSAPP and not is_note:
            from apps.communications.services import whatsapp_outbound
            try:
                message = whatsapp_outbound.send_text(
                    conversation, data.get('body', ''), sent_by=request.user, reply_to=quoted,
                )
            except whatsapp_outbound.WindowClosed:
                return Response({'detail': WINDOW_CLOSED}, status=status.HTTP_400_BAD_REQUEST)
            except ValueError as exc:
                return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        else:
            # Use SYSTEM channel for internal notes, otherwise the conversation's channel
            channel = Message.SYSTEM if is_note else conversation.channel
            message = Message.objects.create(
                conversation=conversation,
                direction=Message.OUTBOUND,
                channel=channel,
                sent_by=request.user,
                reply_to=quoted,
                **data
            )

        if not is_note:
            # A reply to the customer takes the conversation over from Octos,
            # which must never talk over a person, and clears any reminder.
            # An internal note is not a reply: it changes neither.
            from apps.communications.services import handover
            handover.staff_replied(conversation, request.user)

        # Auto-claim if unclaimed, now that something was actually sent or noted
        if not conversation.assigned_to:
            conversation.assigned_to = request.user
            conversation.save(update_fields=['assigned_to'])

        return Response(MessageSerializer(message).data, status=status.HTTP_201_CREATED)


class ConversationAssignView(APIView):
    """
    POST /api/v1/communications/<id>/assign/
    Body: { user_id }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        conversation = _visible(request, pk)
        if conversation is None:
            return _not_found()

        serializer = ConversationAssignSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = CustomUser.objects.get(pk=serializer.validated_data['user_id'])
        except CustomUser.DoesNotExist:
            return Response(
                {'detail': 'User not found.'},
                status=status.HTTP_404_NOT_FOUND
            )

        previous = conversation.assigned_to
        conversation.assigned_to = user
        conversation.save(update_fields=['assigned_to'])

        # System note — only log if it's a reassignment
        note = (
            f"Reassigned from {previous.full_name} to {user.full_name}"
            if previous
            else f"Assigned to {user.full_name} by {request.user.full_name}"
        )
        Message.objects.create(
            conversation=conversation,
            direction=Message.OUTBOUND,
            channel=Message.SYSTEM,
            message_type=Message.NOTE,
            is_internal_note=True,
            body=note,
            sent_by=request.user,
        )

        return Response({
            'success'        : True,
            'assigned_to'    : user.full_name,
            'assigned_to_id' : user.id,
        })


class ConversationResolveView(APIView):
    """
    POST /api/v1/communications/<id>/resolve/
    Marks conversation as RESOLVED and logs a system note.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        conversation = _visible(request, pk)
        if conversation is None:
            return _not_found()

        if conversation.status == Conversation.RESOLVED:
            return Response(
                {'detail': 'Conversation is already resolved.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        conversation.status = Conversation.RESOLVED
        conversation.save(update_fields=['status'])
        # Resolved means handled: no longer "needs you", and Octos answers
        # whatever the customer sends next.
        handover.resolved(conversation)

        Message.objects.create(
            conversation=conversation,
            direction=Message.OUTBOUND,
            channel=Message.SYSTEM,
            message_type=Message.NOTE,
            is_internal_note=True,
            body=f"Conversation resolved by {request.user.full_name}",
            sent_by=request.user,
        )

        return Response({'success': True, 'status': 'RESOLVED'})


class ConversationLinkJobView(APIView):
    """
    POST /api/v1/communications/<id>/link-job/
    Body: { job_id }          — links job to conversation
    Body: { job_id: null }    — clears all linked jobs (unlink)
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        conversation = _visible(request, pk)
        if conversation is None:
            return _not_found()

        job_id = request.data.get('job_id')

        # Unlink — job_id explicitly null
        if job_id is None:
            conversation.jobs.clear()
            return Response({'success': True, 'linked': False})

        from apps.jobs.models import Job
        try:
            job = Job.objects.get(pk=job_id)
        except Job.DoesNotExist:
            return Response(
                {'detail': 'Job not found.'},
                status=status.HTTP_404_NOT_FOUND
            )

        conversation.jobs.add(job)

        return Response({
            'success'               : True,
            'linked'                : True,
            'job_id'                : job.id,
            'linked_to_conversation': conversation.id,
        })

class ConversationTakeOverView(APIView):
    """
    POST /api/v1/communications/<id>/take-over/
    A person answers from now on; Octos goes quiet in this thread.
    Taking over a conversation Octos handed over clears its reason, since
    someone has now come.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        conversation = _visible(request, pk)
        if conversation is None:
            return _not_found()

        from apps.communications.services import handover
        already_mine = (
            conversation.handled_by == Conversation.STAFF
            and not conversation.handoff_reason
            and conversation.assigned_to_id == request.user.pk
        )
        if not already_mine:
            handover.take_over(conversation, request.user)
        return Response({'handled_by': conversation.handled_by})


class ConversationServeAtCounterView(APIView):
    """
    POST /api/v1/communications/<id>/serve-at-counter/
    A person is serving this customer in person. Octos goes quiet; no
    reminder, no take-back; it ends when the visit ends (11 Nov 2026).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        conversation = _visible(request, pk)
        if conversation is None:
            return _not_found()

        from apps.communications.services import handover
        if conversation.handled_by != Conversation.COUNTER:
            handover.serve_at_counter(conversation, request.user)
        return Response({'handled_by': conversation.handled_by})


class ConversationHandBackView(APIView):
    """
    POST /api/v1/communications/<id>/hand-back/
    Octos answers from now on.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        conversation = _visible(request, pk)
        if conversation is None:
            return _not_found()

        from apps.communications.services import handover
        if conversation.handled_by != Conversation.OCTOS:
            handover.hand_back(conversation, request.user)
        return Response({'handled_by': conversation.handled_by})



class ConversationAtCounterView(APIView):
    """
    POST /api/v1/communications/<id>/at-counter/
    The attendant's one tap: this customer is at the counter. Octos stays
    quiet for the visit (30 minutes after their last message), then comes
    back by itself. Unlike Take over, it never needs handing back.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        conversation = _visible(request, pk)
        if conversation is None:
            return _not_found()
        from apps.communications.assistant import counter
        counter.start_visit(conversation)
        Message.objects.create(
            conversation=conversation, direction=Message.OUTBOUND, channel=Message.SYSTEM,
            message_type=Message.NOTE, is_internal_note=True, sent_by=request.user,
            body=f'{request.user.full_name} marked the customer at the counter. Octos is quiet for this visit.',
        )
        return Response({'counter_until': conversation.counter_until})


# ── Files in replies, and starting a chat (7 Nov 2026, Khofi) ─────────────
MAX_ATTACHMENT = 16 * 1024 * 1024        # what we accept; WhatsApp's own limits are higher
MAX_PHOTO = 5 * 1024 * 1024              # WhatsApp's limit for an image sent as a photo


def _as_png(content):
    """A photo as PNG bytes, since images go out labelled as PNG; None if it can't be read."""
    import io
    try:
        from PIL import Image
        with Image.open(io.BytesIO(content)) as picture:
            out = io.BytesIO()
            picture.convert('RGBA' if picture.mode in ('RGBA', 'LA', 'P') else 'RGB').save(out, 'PNG', optimize=True)
            return out.getvalue()
    except Exception:
        return None


def _send_file(conversation, user, content, name, mime):
    """One file to the customer: a photo as a photo when it can be, anything else as a document."""
    from apps.communications.services import whatsapp_outbound
    if mime in ('image/jpeg', 'image/png', 'image/webp') and len(content) <= MAX_PHOTO:
        png = content if mime == 'image/png' else _as_png(content)
        if png is not None and len(png) <= MAX_PHOTO:
            stem = name.rsplit('.', 1)[0] if '.' in name else name
            return _caption_optional(lambda body: whatsapp_outbound.send_text(
                conversation, body, sent_by=user, image=png, filename=f'{stem}.png'), name)
    return _caption_optional(lambda body: whatsapp_outbound.send_text(
        conversation, body, sent_by=user, document=content, filename=name,
        document_mime=mime or 'application/octet-stream'), name)


def _caption_optional(send, name):
    """A file needs no caption; if the sender insists on one, its name will do."""
    try:
        return send('')
    except ValueError:
        return send(name)


def _reply_with_files(request, conversation, files):
    from django.core.files.base import ContentFile
    from .serializers import MessageSerializer as _Out
    from apps.communications.services import handover, whatsapp_outbound

    text = (request.data.get('body') or '').strip()
    is_note = str(request.data.get('is_internal_note', '')).lower() in ('1', 'true', 'yes', 'on')
    too_big = [f.name for f in files if f.size > MAX_ATTACHMENT]
    if too_big:
        return Response({'detail': f"{', '.join(too_big)} is over 16 MB. Send a smaller file, or share a link."},
                        status=status.HTTP_400_BAD_REQUEST)
    if not is_note and conversation.channel != Conversation.WHATSAPP:
        return Response({'detail': 'Files can only be sent on WhatsApp. Save it as a note instead.'},
                        status=status.HTTP_400_BAD_REQUEST)

    made = []
    try:
        for f in files:
            content, name = f.read(), f.name
            mime = (f.content_type or 'application/octet-stream').split(';')[0]
            if is_note:
                note = Message(
                    conversation=conversation, direction=Message.OUTBOUND, channel=Message.SYSTEM,
                    sent_by=request.user, is_internal_note=True, body=text or name,
                    message_type=Message.IMAGE if mime.startswith('image/') else Message.DOCUMENT,
                    media_name=name, media_mime=mime, media_size=len(content),
                )
                note.media_file.save(name, ContentFile(content), save=False)
                note.save()
                made.append(note)
            else:
                made.append(_send_file(conversation, request.user, content, name, mime))
        if text and not is_note:
            made.append(whatsapp_outbound.send_text(conversation, text, sent_by=request.user,
                                                    reply_to=_quoted_in(conversation, request.data.get('reply_to'))))
    except whatsapp_outbound.WindowClosed:
        return Response({'detail': WINDOW_CLOSED}, status=status.HTTP_400_BAD_REQUEST)
    except ValueError as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    if not is_note:
        handover.staff_replied(conversation, request.user)
    return Response(_Out(made, many=True).data, status=status.HTTP_201_CREATED)


# The approved WhatsApp messages a chat may start with. Each must be approved
# in WhatsApp Manager under this exact name, in English, before it can be sent.
START_TEMPLATES = {
    'order_ready': 'Hello {1}, your order {2} is ready to collect at Farhat Printing Press, Westland.',
    'job_question': 'Hello {1}, about your job {2}: please reply when you can.',
    'proforma_ready': 'Hello {1}, your proforma {2} is ready. Reply to receive it here.',
    # Checking in after a past job (utility), and reaching customers who have
    # gone quiet (marketing), in Farhat's own warm voice (Khofi, 8 Nov 2026).
    'general_followup': ('Hello {1}, it\u2019s Farhat Printing Press at Westland. We were thinking about the '
                         'last job we did for you and wanted to check in. How did it all turn out? We\u2019d love '
                         'to hear from you whenever you have a moment.'),
    'reconnect': ('Hello {1}! It\u2019s the team at Farhat Printing Press, Westland. We haven\u2019t seen you in a '
                  'while and just wanted to say we\u2019re still here for you, from a single copy to a big order. '
                  'Send us a message anytime. If you\u2019d prefer not to hear from us, just let us know.'),
}
# Marketing, by WhatsApp's rules: never sent to a customer who asked not to be.
MARKETING_TEMPLATES = {'reconnect'}


def _e164(phone):
    """'024 400 0776' -> '+233244000776'; '' when it isn't a phone number."""
    digits = ''.join(ch for ch in str(phone or '') if ch.isdigit())
    if digits.startswith('0') and len(digits) == 10:
        digits = '233' + digits[1:]
    return f'+{digits}' if 11 <= len(digits) <= 15 else ''


class ConversationStartView(APIView):
    """
    POST /api/v1/communications/start/  { phone, name?, template, params: [..] }

    Reaching a customer who hasn't written (Khofi, 7 Nov 2026). WhatsApp
    allows only an approved message until they reply; this sends one and
    opens (or reuses) their chat. Returns { conversation }.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({'templates': [{'name': k, 'text': v, 'params': v.count('{'),
                                        'kind': 'marketing' if k in MARKETING_TEMPLATES else 'service'}
                                       for k, v in START_TEMPLATES.items()]})

    def post(self, request):
        from apps.communications.services import whatsapp_client
        name = request.data.get('template')
        params = [str(p).strip() for p in (request.data.get('params') or [])]
        text = START_TEMPLATES.get(name)
        if text is None:
            return Response({'detail': 'Choose one of the approved messages.'}, status=status.HTTP_400_BAD_REQUEST)
        if len(params) != text.count('{') or not all(params):
            return Response({'detail': 'Fill in every blank in the message.'}, status=status.HTTP_400_BAD_REQUEST)
        phone = _e164(request.data.get('phone'))
        if not phone:
            return Response({'detail': "That doesn't look like a phone number."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            from apps.core.phones import lookup_forms
            forms = list(lookup_forms(phone)) or [phone]
        except Exception:
            forms = [phone]
        conversation = (Conversation.objects.filter(channel=Conversation.WHATSAPP, contact_phone__in=forms)
                        .order_by('-id').first())
        if conversation is None:
            conversation = Conversation.objects.create(
                channel=Conversation.WHATSAPP, contact_phone=phone,
                contact_name=(request.data.get('name') or '').strip())

        if name in MARKETING_TEMPLATES and getattr(conversation, 'marketing_opt_out', False):
            return Response({'detail': 'This customer asked not to receive messages like this, so it won\u2019t be '
                                       'sent. Messages about their jobs still can be.'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            wamid = whatsapp_client.send_template(conversation.contact_phone, name, params=params)
        except Exception:
            logger.warning('Starting a chat with %s failed', name, exc_info=True)
            return Response({'detail': "WhatsApp didn't accept that message. If it was added recently, Meta "
                                       "may not have approved it yet."}, status=status.HTTP_400_BAD_REQUEST)

        body = text
        for number, value in enumerate(params, start=1):
            body = body.replace('{%d}' % number, value)
        Message.objects.create(
            conversation=conversation, direction=Message.OUTBOUND, channel=conversation.channel,
            sent_by=request.user, body=body, kind='template', status='SENT',
            external_id=wamid if isinstance(wamid, str) else '',
        )
        return Response({'conversation': conversation.id}, status=status.HTTP_201_CREATED)


class MessageFileView(APIView):
    """
    GET /api/v1/communications/messages/<id>/file/   (?download=1 to save it)

    A chat message's file, for someone who may see that chat (8 Nov 2026).
    Nothing is served straight from the bucket: customers' files at an
    address anyone could open would be a real exposure, so every file goes
    through a view that checks who is asking (see settings.py).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        from django.http import FileResponse
        message = Message.objects.filter(pk=pk).only('id', 'conversation_id', 'media_file', 'media_name',
                                                    'media_mime').first()
        if message is None or not message.media_file or _visible(request, message.conversation_id) is None:
            return _not_found()
        name = message.media_name or message.media_file.name.rsplit('/', 1)[-1]
        response = FileResponse(message.media_file.open('rb'),
                                as_attachment=bool(request.query_params.get('download')),
                                filename=name,
                                content_type=message.media_mime or 'application/octet-stream')
        # Private: never kept by a shared cache, only the asker's browser.
        response['Cache-Control'] = 'private, max-age=3600'
        return response


def _quoted_in(conversation, pk):
    """The message being replied to, if it belongs to this very conversation."""
    try:
        pk = int(pk)
    except (TypeError, ValueError):
        return None
    return Message.objects.filter(pk=pk, conversation=conversation).first()


class ConversationLinkCustomerView(APIView):
    """
    POST /api/v1/communications/<id>/link-customer/  { customer }

    Staff link a chat to the customer they recognise (9 Nov 2026), e.g. a
    WhatsApp username chat with no number: the chat takes the record's number.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from apps.communications.services import identity
        from apps.customers.models import CustomerProfile
        conversation = _visible(request, pk)
        if conversation is None:
            return _not_found()
        customer = CustomerProfile.objects.filter(pk=request.data.get('customer')).first()
        if customer is None:
            return Response({'detail': 'That customer could not be found.'}, status=status.HTTP_400_BAD_REQUEST)
        identity.link_customer(conversation, customer)
        return Response({'customer': customer.pk, 'phone': conversation.contact_phone})


class ConversationPhotosPdfView(APIView):
    """
    POST /api/v1/communications/<id>/photos-pdf/  { messages: [ids] }

    Photos a customer sent together, as one PDF to print once (9 Nov 2026):
    one photo per A4 page, turned upright and fitted, the page turned to suit
    the photo. Up to 40 photos, all from this chat.
    """
    permission_classes = [IsAuthenticated]
    DPI = 150
    A4 = (1240, 1754)          # A4 at 150 dpi
    MARGIN = 45

    def post(self, request, pk):
        import io
        from django.http import HttpResponse
        from PIL import Image, ImageOps
        conversation = _visible(request, pk)
        if conversation is None:
            return _not_found()
        ids = [int(i) for i in (request.data.get('messages') or []) if str(i).isdigit()][:40]
        chosen = {m.pk: m for m in Message.objects.filter(conversation=conversation, pk__in=ids)
                  if m.media_file and (m.media_mime or '').startswith('image/')}
        photos = [chosen[i] for i in ids if i in chosen]
        if not photos:
            return Response({'detail': 'None of those photos is ready yet.'}, status=status.HTTP_400_BAD_REQUEST)

        pages = []
        for message in photos:
            with message.media_file.open('rb') as handle:
                image = ImageOps.exif_transpose(Image.open(handle))
                image = image.convert('RGB')
            width, height = self.A4 if image.height >= image.width else self.A4[::-1]
            room = (width - 2 * self.MARGIN, height - 2 * self.MARGIN)
            image.thumbnail(room, Image.LANCZOS) if image.width > room[0] or image.height > room[1] else None
            if image.width < room[0] and image.height < room[1]:
                scale = min(room[0] / image.width, room[1] / image.height)
                image = image.resize((int(image.width * scale), int(image.height * scale)), Image.LANCZOS)
            page = Image.new('RGB', (width, height), 'white')
            page.paste(image, ((width - image.width) // 2, (height - image.height) // 2))
            pages.append(page)

        out = io.BytesIO()
        pages[0].save(out, 'PDF', save_all=True, append_images=pages[1:], resolution=self.DPI)
        name = f'{(conversation.contact_name or "Photos").strip()[:40]}, {len(pages)} photos.pdf'
        response = HttpResponse(out.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{name}"'
        return response
