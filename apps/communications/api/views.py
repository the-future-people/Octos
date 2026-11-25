import logging

from rest_framework import generics, filters, status
from rest_framework.pagination import PageNumberPagination
from django.db.models import Case, Count, F, IntegerField, Min, Q, Value, When
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

logger = logging.getLogger(__name__)

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


class InboxPage(PageNumberPagination):
    """
    The inbox a page at a time (17 Nov 2026): 40 chats, then the next 40 as
    the list is scrolled, back to the very first chat. It used to stop at the
    first 20, so older chats were out of reach.
    """
    page_size = 40
    page_size_query_param = 'page_size'
    max_page_size = 100


# The inbox's filters, the same as its chips.
INBOX_FILTERS = {
    'needs':  Q(handled_by=Conversation.STAFF) & ~Q(handoff_reason=''),
    'octos':  Q(handled_by=Conversation.OCTOS),
    'people': Q(handled_by=Conversation.STAFF, handoff_reason=''),
}


class ConversationListView(generics.ListAPIView):
    """
    GET /api/v1/communications/?channel=WHATSAPP&filter=needs&search=ama&page=2

    Chats that need a person first, then the newest. Search reaches every
    chat, not only the ones already loaded.
    """
    serializer_class = ConversationListSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = InboxPage
    filter_backends = [filters.SearchFilter]
    search_fields = ['contact_phone', 'contact_email', 'contact_name', 'contact_username',
                     'last_message_preview', 'customer__first_name', 'customer__last_name',
                     'jobs__job_number']

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
        chip = INBOX_FILTERS.get(self.request.query_params.get('filter') or '')
        if chip is not None:
            qs = qs.filter(chip)

        return qs.annotate(
            needs_person=Case(When(INBOX_FILTERS['needs'], then=Value(1)), default=Value(0),
                              output_field=IntegerField()),
        ).order_by('-needs_person', F('last_message_at').desc(nulls_last=True), '-pk')


class InboxCountsView(APIView):
    """
    GET /api/v1/communications/counts/

    The inbox's numbers over every chat this person can see, not only the
    ones loaded: unread chats, chats waiting for a person and since when,
    and per channel how many want attention. For the menu's badge, the
    window title and the inbox's tabs (17 Nov 2026).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        chats = visible_conversations(request.user).exclude(status=Conversation.SPAM)
        needs = chats.filter(INBOX_FILTERS['needs'])
        wanting = chats.filter(Q(unread_count__gt=0) | INBOX_FILTERS['needs'])
        by_channel = {row['channel']: row['n'] for row in
                      wanting.values('channel').annotate(n=Count('id')).order_by()}
        oldest = needs.aggregate(since=Min('handled_since'))['since']
        return Response({
            'unread': chats.filter(unread_count__gt=0).count(),
            'needs': needs.count(),
            'waiting_since': oldest.isoformat() if oldest else None,
            'by_channel': by_channel,
        })


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
        # Someone has this chat open: Octos stays quiet while they're looking
        # (14 Nov 2026). Cheap on every fetch; the spine hears of it at most
        # every 10 minutes.
        from apps.communications.services.opened import chat_opened
        # Only a real open counts (15 Nov 2026). The inbox reloads an open
        # chat by itself, every 20 seconds and on every change, always asking
        # for what's new 'after' the last message: that's a screen left on,
        # not a person looking, so it doesn't keep the chat "in focus".
        if not self.request.query_params.get('after'):
            chat_opened(obj, self.request.user)
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


class ChatCustomerView(APIView):
    """
    POST /api/v1/communications/<id>/customer/
    The customer behind this chat, for a job at the counter: its own, an
    existing record with the number, or a light one made from the chat
    (11 Nov 2026). Returns {customer_id, phone, name, created}, or 404 for a
    chat with no number (a WhatsApp username).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        conversation = _visible(request, pk)
        if conversation is None:
            return _not_found()
        from apps.communications.services.chat_customer import customer_for_chat
        customer, created = customer_for_chat(conversation)
        if customer is None:
            return Response({'detail': 'This chat has no number to save a customer by.'},
                            status=status.HTTP_404_NOT_FOUND)
        return Response({'customer_id': customer.pk, 'phone': customer.phone,
                         'name': str(customer), 'created': created})


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

        # 'job' too: the new-job form sent that by mistake until 11 Nov 2026,
        # and a missing job_id reads as "unlink everything".
        job_id = request.data.get('job_id', request.data.get('job'))

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

        # The chat shows it; on the spine the visit closes as a job made.
        from apps.communications.services.job_link import link_to_chat
        link_to_chat(conversation, job, request.user)

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

class ArrivalsView(APIView):
    """
    GET /api/v1/communications/arrivals/
    Customers with files nobody has picked up yet, oldest first: the
    attendant's Claim strip (11 Nov 2026). The tap itself is at-counter.
    A thin wrapper: the answer comes from apps/spine/arrivals.py.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.spine.arrivals import arrivals
        branch = getattr(request.user, 'branch', None)
        rows = arrivals(branch=branch)
        return Response([{
            'conversation_id': row['conversation'].pk,
            'name': row['name'],
            'number_tail': row['number_tail'],
            'since': row['since'],
            'presence': row['presence'],
            'p': row['p'],
            'files': MessageSerializer(row['files'], many=True, context={'request': request}).data,
        } for row in rows])


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
        from apps.spine import kinds
        from apps.spine.models import Event
        from apps.spine.recorder import record
        record(kinds.COUNTER_CLAIMED, actor=Event.STAFF, actor_user=request.user,
               conversation=conversation, customer=conversation.customer,
               reason=f'{request.user.full_name} marked the customer at the counter.')
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
# The approved messages live with the others (services/templates.py, 22 Nov 2026).
from apps.communications.services.templates import MARKETING_TEMPLATES, START_TEMPLATES  # noqa: E402


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
        if request.query_params.get('download'):
            # The inbox's Open: a person is taking this file to work on (11 Nov 2026).
            from apps.communications.services.opened import file_opened
            file_opened(message, request.user)
        name = message.media_name or message.media_file.name.rsplit('/', 1)[-1]
        if request.query_params.get('link'):
            # A signed link straight to the file in R2, for the person just
            # checked above (15 Nov 2026): the browser downloads from R2's
            # edge, not through this server. None where files are on disk
            # (a laptop): the screen then asks for the file itself.
            return Response({'url': _signed_link(message, name, bool(request.query_params.get('download')))})
        response = FileResponse(message.media_file.open('rb'),
                                as_attachment=bool(request.query_params.get('download')),
                                filename=name,
                                content_type=message.media_mime or 'application/octet-stream')
        # Private: never kept by a shared cache, only the asker's browser.
        response['Cache-Control'] = 'private, max-age=3600'
        return response


LINK_SECONDS = 3600


def _signed_link(message, name, download):
    """A link to the file in R2, good for an hour; None where files are on disk."""
    from urllib.parse import quote
    storage = message.media_file.storage
    connection = getattr(storage, 'connection', None)
    if connection is None:
        return None
    disposition = f"{'attachment' if download else 'inline'}; filename*=UTF-8''{quote(name)}"
    return connection.meta.client.generate_presigned_url(
        'get_object',
        Params={
            'Bucket': storage.bucket_name,
            'Key': storage._normalize_name(message.media_file.name),
            'ResponseContentDisposition': disposition,
            'ResponseContentType': message.media_mime or 'application/octet-stream',
        },
        ExpiresIn=LINK_SECONDS,
    )


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


class MessageOpenedView(APIView):
    """
    POST /api/v1/communications/messages/<id>/opened/

    A person looked at this customer's photo full size in the inbox's photo
    viewer (20 Nov 2026). Thumbnails load by themselves and prove nothing;
    the viewer is a person choosing to look, so it counts as opening, and
    Octos doesn't ask the customer what the photos are for.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        message = Message.objects.filter(pk=pk).only('id', 'conversation_id', 'direction', 'media_name').first()
        if message is None or _visible(request, message.conversation_id) is None:
            return _not_found()
        from apps.communications.services.opened import file_opened
        file_opened(message, request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


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
        # Opening them as one PDF is opening them (20 Nov 2026): Octos had
        # gone on to ask the customer what the photos were for.
        from apps.communications.services.opened import file_opened
        for message in photos:
            file_opened(message, request.user)

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


# ── Customer files: Keep and Delete (25 Nov 2026) ────────────────────────────
# services/customer_files.py: kept 14 days unless kept, deleted on request
# with a reason, never while a job of theirs is open below the BM.

def _file_row(message):
    from apps.communications.services import customer_files
    on = customer_files.deletes_on(message)
    return {
        'id': message.pk, 'name': message.media_name or 'File', 'pages': message.media_pages,
        'size': message.media_size, 'kept': bool(message.kept_at),
        'deletes_on': on.isoformat() if on else None,
    }


class ConversationFilesView(APIView):
    """
    GET /api/v1/communications/<id>/files/
    The customer's files in this chat still in storage, and whether a job of
    theirs holds them (locked) and whether this person may lift that.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        from apps.communications.services import customer_files
        conversation = _visible(request, pk)
        if conversation is None:
            return _not_found()
        held = customer_files.open_job(conversation)
        return Response({
            'retain_days': customer_files.RETAIN.days,
            'locked': customer_files.lock_text(held),
            'may_delete': customer_files.may_delete(request.user),
            'may_unlock': customer_files.may_unlock(request.user),
            'reasons': [{'value': k, 'label': v} for k, v in customer_files.REASONS.items()],
            'files': [_file_row(m) for m in customer_files.chat_files(conversation)],
        })


class ConversationFilesDeleteView(APIView):
    """POST /api/v1/communications/<id>/files/delete/   {ids, reason, note}"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from apps.communications.services import customer_files
        conversation = _visible(request, pk)
        if conversation is None:
            return _not_found()
        ids = [int(i) for i in request.data.get('ids') or [] if str(i).isdigit()]
        reason = str(request.data.get('reason') or '')
        note = str(request.data.get('note') or '').strip()[:150]
        if reason not in customer_files.REASONS:
            return Response({'detail': 'Choose why these files are being deleted.'}, status=status.HTTP_400_BAD_REQUEST)
        if reason == 'other' and not note:
            return Response({'detail': 'Say why, in a few words.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            done = customer_files.delete_by_hand(conversation, ids, request.user, reason, note)
        except customer_files.FilesRefused as e:
            return Response({'detail': str(e)}, status=status.HTTP_409_CONFLICT)
        return Response({'deleted': [m.pk for m in done]})


class ConversationFilesUnlockView(APIView):
    """POST /api/v1/communications/<id>/files/unlock/   {ids, reason, note}: ask the owner on his line."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from apps.communications.services import customer_files
        conversation = _visible(request, pk)
        if conversation is None:
            return _not_found()
        ids = [int(i) for i in request.data.get('ids') or [] if str(i).isdigit()]
        try:
            asked = customer_files.ask_owner(conversation, ids, request.user,
                                             str(request.data.get('reason') or ''),
                                             str(request.data.get('note') or '').strip()[:150])
        except customer_files.FilesRefused as e:
            return Response({'detail': str(e)}, status=status.HTTP_409_CONFLICT)
        if asked is None:
            return Response({'detail': "Khofi's line isn't set up, so he can't be asked. Ask the BM."},
                            status=status.HTTP_409_CONFLICT)
        return Response({'asked': True})


class MessageKeepView(APIView):
    """POST /api/v1/communications/messages/<id>/keep/   {keep: true|false}"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from apps.communications.services import customer_files
        message = Message.objects.filter(pk=pk).select_related('conversation').first()
        if message is None or _visible(request, message.conversation_id) is None:
            return _not_found()
        if not message.media_file or message.file_deleted_at:
            return Response({'detail': 'This file is already gone.'}, status=status.HTTP_409_CONFLICT)
        keep_it = request.data.get('keep', True) not in (False, 'false', 0, '0')
        customer_files.keep([message], request.user, keep_it)
        message.refresh_from_db()
        return Response(_file_row(message))
