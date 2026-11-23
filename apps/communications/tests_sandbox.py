"""
The Can-Do Sandbox (23 Nov 2026): "can you do this?" with a photo, video or
GIF, on WhatsApp and on the website. What it is first (with the web), then
whether Farhat can make it, from our own catalogue and price list only.
"""
import io
import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient

from apps.communications.models import Message, SandboxCase
from apps.communications.services import sandbox
from apps.communications.tests import make_conversation, make_org
from apps.communications.tests_assistant_brain import Model, says, text, tool
from apps.jobs.models import PricingRule, Service

IDENTITY = {'first_look': 'A flat panel on a wall with raised letters',
            'what': 'A frosted acrylic signboard with cut vinyl letters',
            'detail': 'Wall mounted on metal standoffs, about 60 x 40 cm.',
            'made_how': 'Vinyl letters cut on a plotter, applied to frosted acrylic, drilled for standoffs.',
            'size_guess': 'about 60 x 40 cm', 'quantity': 1, 'confidence': 'high', 'is_print_file': False,
            'question': ''}


def png(w=800, h=600, colour='white'):
    buf = io.BytesIO()
    Image.new('RGB', (w, h), colour).save(buf, 'PNG')
    return buf.getvalue()


def gif():
    frames = [Image.new('RGB', (200, 200), c) for c in ('red', 'green', 'blue', 'white', 'black')]
    buf = io.BytesIO()
    frames[0].save(buf, 'GIF', save_all=True, append_images=frames[1:], duration=100)
    return buf.getvalue()


def identified(found=IDENTITY, searched=True):
    blocks = [SimpleNamespace(type='server_tool_use', name='web_search', input={'query': 'frosted acrylic sign'}),
              text(json.dumps(found))] if searched else [text(json.dumps(found))]
    return says(*blocks)


class PicturesTests(SimpleTestCase):

    def test_photos_are_made_small_enough(self):
        out = sandbox.pictures([(png(4000, 3000), 'image/png')])
        img = Image.open(io.BytesIO(out[0]))
        self.assertLessEqual(max(img.size), sandbox.IMAGE_SIDE)
        self.assertEqual(img.format, 'JPEG')

    def test_a_gif_gives_a_few_frames(self):
        self.assertEqual(len(sandbox.pictures([(gif(), 'image/gif')])), 4)

    def test_never_more_than_six(self):
        self.assertEqual(len(sandbox.pictures([(png(), 'image/png')] * 9)), sandbox.MAX_IMAGES)

    def test_a_broken_file_is_skipped(self):
        self.assertEqual(sandbox.pictures([(b'not an image', 'image/jpeg')]), [])


@override_settings(ANTHROPIC_API_KEY='test-key', OCTOS_ASSISTANT_MODE='live')
class EngineTests(TestCase):

    def setUp(self):
        self.branch = make_org('-SBX')
        self.branch.is_trading = True
        self.branch.save()
        self.service = Service.objects.create(code='T-ACRYLIC', name='Acrylic Signage', category='LARGE_FORMAT',
                                              unit='piece', is_active=True)
        PricingRule.objects.create(service=self.service, branch=None, base_price=Decimal('450.00'), is_active=True)

    def answered(self, answer):
        return says(text(json.dumps(answer)))

    def test_what_it_is_first_then_farhat_with_a_checked_price(self):
        model = Model(
            identified(),
            says(tool('find_services', {'query': 'acrylic signage'}), stop='tool_use'),
            says(tool('quote', {'service_code': 'T-ACRYLIC', 'quantity': 1}, id='t2'), stop='tool_use'),
            self.answered({'can_do': 'yes', 'why': 'We make acrylic signs at Westland.',
                           'how': ['Design', 'Cut the letters', 'Fit on acrylic'], 'services': ['T-ACRYLIC'],
                           'price_from': 'GHS 450.00', 'price_to': None, 'assumptions': 'about 60 x 40 cm, 1 piece',
                           'ready': '', 'questions': ['Exact size?', 'One colour or two?'], 'nearest': ''}))
        case = SandboxCase.objects.create(source=SandboxCase.WEB)
        with patch('anthropic.Anthropic', return_value=model):
            sandbox.run(case, files=[(png(), 'image/png')])
        case.refresh_from_db()
        self.assertEqual(case.status, SandboxCase.DONE)
        self.assertEqual(case.stage, 4)
        self.assertEqual(case.findings[:2], [IDENTITY['first_look'], IDENTITY['what']])
        self.assertEqual(case.result['price_from'], 'GHS 450.00')
        self.assertTrue(case.result['searched'])
        # The first question is asked with pictures and web search, and nothing of Farhat's.
        first = model.calls[0]
        self.assertEqual(first['tools'][0]['type'], 'web_search_20250305')
        self.assertEqual(first['messages'][0]['content'][0]['type'], 'image')
        self.assertNotIn('find_services', json.dumps(first['tools']))

    def test_a_price_no_quote_gave_is_dropped(self):
        model = Model(identified(searched=False), self.answered({
            'can_do': 'yes', 'why': 'We can.', 'price_from': 'GHS 999.00', 'price_to': None, 'questions': []}))
        case = SandboxCase.objects.create(source=SandboxCase.WEB)
        with patch('anthropic.Anthropic', return_value=model):
            sandbox.run(case, files=[(png(), 'image/png')])
        case.refresh_from_db()
        self.assertIsNone(case.result['price_from'])
        self.assertEqual(case.result['assumptions'], 'A person at Farhat will price this.')

    def test_not_sure_asks_its_question_and_the_boss(self):
        unsure = {**IDENTITY, 'what': 'Something carved, maybe wood', 'confidence': 'low',
                  'question': 'Is it carved wood or printed?'}
        case = SandboxCase.objects.create(source=SandboxCase.WEB)
        with patch('anthropic.Anthropic', return_value=Model(identified(unsure))), \
                patch('apps.communications.services.owner_line.tell') as tell:
            sandbox.run(case, files=[(png(), 'image/png')])
        case.refresh_from_db()
        self.assertEqual(case.status, SandboxCase.UNSURE)
        self.assertEqual(case.result['questions'], ['Is it carved wood or printed?'])
        self.assertIn('Can we do this?', tell.call_args.args[1])
        self.assertIsNotNone(tell.call_args.kwargs['card'])                # he sees the photo

    def test_a_file_we_cannot_open_fails_kindly(self):
        case = SandboxCase.objects.create(source=SandboxCase.WEB)
        sandbox.run(case, files=[(b'junk', 'image/jpeg')])
        case.refresh_from_db()
        self.assertEqual(case.status, SandboxCase.FAILED)
        self.assertIn("couldn't open", case.result['message'])

    def test_the_bosss_answer_is_kept_and_used_next_time(self):
        chat = make_conversation(None, contact_phone='+233244880001')
        case = SandboxCase.objects.create(source=SandboxCase.WHATSAPP, conversation=chat, status=SandboxCase.UNSURE,
                                          result={'what': 'A laser engraved wooden keyholder'})
        sandbox.remember_answer(chat, 'Yes, through a partner, GHS 25 each')
        case.refresh_from_db()
        self.assertEqual(case.owner_answer, 'Yes, through a partner, GHS 25 each')
        past = sandbox._past_cases({'what': 'Engraved wooden keyholder for a wedding'})
        self.assertEqual(past[0]['farhat_answered'], 'Yes, through a partner, GHS 25 each')


@override_settings(ANTHROPIC_API_KEY='test-key')
class PublicApiTests(TestCase):

    def setUp(self):
        self.api = APIClient()

    def upload(self, *files, note='For my shop front'):
        return self.api.post('/api/v1/sandbox/', {'files': list(files), 'note': note}, format='multipart',
                             REMOTE_ADDR='41.66.1.2')

    def photo(self, name='sign.png'):
        return SimpleUploadedFile(name, png(), content_type='image/png')

    def test_a_visitor_uploads_and_watches_it_work(self):
        with patch('apps.communications.tasks.run_sandbox.delay') as later, self.captureOnCommitCallbacks(execute=True):
            r = self.upload(self.photo())
        self.assertEqual(r.status_code, 201, r.data)
        code = r.data['code']
        later.assert_called_once()
        case = SandboxCase.objects.get(code=code)
        self.assertEqual((case.source, case.note, len(case.files)), (SandboxCase.WEB, 'For my shop front', 1))
        seen = self.api.get(f'/api/v1/sandbox/{code}/').data
        self.assertEqual((seen['status'], seen['stage'], seen['result']), ('QUEUED', 0, None))
        self.assertEqual(len(seen['steps']), 4)
        SandboxCase.objects.filter(pk=case.pk).update(status='DONE', stage=4, result={'what': 'A sign'})
        self.assertEqual(self.api.get(f'/api/v1/sandbox/{code}/').data['result'], {'what': 'A sign'})

    def test_five_looks_a_day(self):
        with patch('apps.communications.tasks.run_sandbox.delay'):
            for _ in range(5):
                self.assertEqual(self.upload(self.photo()).status_code, 201)
            r = self.upload(self.photo())
        self.assertEqual(r.status_code, 429)
        self.assertIn("today's five looks", r.data['detail'])

    def test_only_pictures_videos_and_gifs(self):
        r = self.upload(SimpleUploadedFile('notes.pdf', b'%PDF', content_type='application/pdf'))
        self.assertEqual(r.status_code, 400)
        r = self.upload(*[self.photo(f'{i}.png') for i in range(4)])
        self.assertIn('Up to 3 photos', r.data['detail'])

    def test_a_whatsapp_case_is_not_shown_on_the_website(self):
        case = SandboxCase.objects.create(source=SandboxCase.WHATSAPP)
        self.assertEqual(self.api.get(f'/api/v1/sandbox/{case.code}/').status_code, 404)


@override_settings(ANTHROPIC_API_KEY='test-key', OCTOS_ASSISTANT_MODE='live')
class WhatsAppTests(TestCase):

    def setUp(self):
        from django.core.files.base import ContentFile
        make_org('-SBW')
        self.chat = make_conversation(None, contact_phone='+233244880002')
        self.photo = Message.objects.create(conversation=self.chat, direction=Message.INBOUND,
                                            channel=Message.WHATSAPP, message_type=Message.IMAGE,
                                            media_id='m-sb1', media_mime='image/jpeg', body='Can you do this?')
        self.photo.media_file.save('mug.png', ContentFile(png()), save=True)

    def test_octos_looks_and_says_so_while_it_works(self):
        from apps.communications.assistant import brain
        ctx = SimpleNamespace(conversation=self.chat, branches=[])
        model = Model(identified({**IDENTITY, 'what': 'A white mug with a wraparound print'}),
                      says(text(json.dumps({'can_do': 'no', 'why': "We don't print mugs yet.", 'questions': [],
                                            'nearest': 'Branded T-shirts'}))))
        with patch('anthropic.Anthropic', return_value=model), self.captureOnCommitCallbacks(execute=False):
            r = brain._run_tool('what_is_this', {'files': [self.photo.pk], 'note': 'with our logo'}, ctx)
        self.assertEqual(r['can_do'], 'no')
        self.assertIn("Don't promise", r['say'])
        self.assertEqual(self.chat.messages.filter(direction=Message.OUTBOUND).first().body, 'Let me take a look 👀')
        case = SandboxCase.objects.get(code=r['case'])
        self.assertEqual((case.source, case.conversation, case.note), (SandboxCase.WHATSAPP, self.chat, 'with our logo'))

    def test_only_files_from_this_chat(self):
        from apps.communications.assistant import brain
        ctx = SimpleNamespace(conversation=make_conversation(None, contact_phone='+233244880003'), branches=[])
        self.assertIn('error', brain._run_tool('what_is_this', {'files': [self.photo.pk]}, ctx))

    def test_a_visitor_from_the_website_is_carried_on_from(self):
        from apps.communications.assistant import brain
        case = SandboxCase.objects.create(source=SandboxCase.WEB, status=SandboxCase.DONE,
                                          result={'what': 'A frosted acrylic signboard', 'price_from': 'GHS 450.00'})
        Message.objects.create(conversation=self.chat, direction=Message.INBOUND, channel=Message.WHATSAPP,
                               body=f'Hi, about my photo {case.code}')
        note = brain._website_case_note(self.chat)
        self.assertIn('frosted acrylic signboard', note)
        self.assertIn('never ask them to explain again', note)
        case.refresh_from_db()
        self.assertEqual(case.conversation, self.chat)

    def test_the_rule(self):
        from apps.communications.assistant import prompt
        self.assertIn('call what_is_this with its file numbers', prompt.RULES)
