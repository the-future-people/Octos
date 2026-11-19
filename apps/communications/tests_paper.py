"""
Paper sizes in plain words, and a picture of them (19 Nov 2026).

A customer found Octos too technical about paper sizes, asked to see what
B6 and A4 look like, and was led to think sizes below A4 aren't printed.
Every size below A4 is printed on A4 and cut; photos usually go on normal
paper, not photo paper.
"""
from datetime import timedelta
from io import BytesIO
from unittest.mock import patch

from django.core.files.base import ContentFile
from PIL import Image

from django.test import SimpleTestCase, TestCase, override_settings

from apps.communications.assistant import brain, paper, prompt
from apps.communications.models import Message
from apps.communications.tests import make_conversation, make_org
from apps.communications.tests_whatsapp_outbound import customer_wrote

PHONE = '+233244777031'


class SizeTests(SimpleTestCase):

    def test_sizes_are_read_however_the_customer_writes_them(self):
        for said, key in [('b6', 'B6'), ('A 5', 'A5'), ('4 by 6', '4X6'), ('6x4', '4X6'), ('half A4', 'A5'),
                          ('postcard size', 'A6'), ('A4 paper', 'A4'), ('business card', 'CARD')]:
            self.assertEqual(paper.key_for(said), key, said)
        self.assertIsNone(paper.key_for('massive'))

    def test_how_many_fit_on_one_a4(self):
        self.assertEqual(paper.fits_on_a4(148, 210), 2)    # A5
        self.assertEqual(paper.fits_on_a4(105, 148), 4)    # A6
        self.assertEqual(paper.fits_on_a4(125, 176), 2)    # B6
        self.assertEqual(paper.fits_on_a4(74, 105), 8)     # A7

    def test_smaller_than_a4_is_printed_on_a4_and_cut(self):
        b6 = paper.facts(['B6'], copies=7)['sizes'][0]
        self.assertIn('printed on an A4 sheet and cut to size', b6['how_we_print'])
        self.assertEqual((b6['fit_on_one_a4'], b6['a4_sheets_needed']), (2, 4))
        self.assertEqual(b6['centimetres'], '12.5 x 17.6 cm')
        self.assertIn('storybook', b6['like'])

    def test_a4_a3_and_bigger(self):
        got = {r['size']: r['how_we_print'] for r in paper.facts(['A4', 'A3', 'B4', 'A2'])['sizes']}
        self.assertEqual(got['A4'], 'printed on an A4 sheet as it is')
        self.assertEqual(got['A3'], 'printed on an A3 sheet as it is')
        self.assertIn('A3 sheet and cut', got['B4'])
        self.assertIn('Hand it to a person', got['A2'])

    def test_an_unknown_size_is_asked_about_not_guessed(self):
        got = paper.facts(['huge'])
        self.assertEqual(got['not_known'], ['huge'])
        self.assertIn('width and height', got['say'])

    def test_the_picture_is_a_png(self):
        png = paper.render(['B6', 'A5', 'A6'])
        self.assertTrue(png.startswith(b'\x89PNG'))
        self.assertIsNotNone(paper.render(['A4']))
        self.assertIsNone(paper.render(['huge']))


def photo_bytes(w=900, h=1600):
    buf = BytesIO()
    Image.new('RGB', (w, h), (70, 130, 180)).save(buf, 'JPEG')
    return buf.getvalue()


class PreviewTests(SimpleTestCase):

    def test_their_photo_on_the_sheet_with_the_piece_beside_it(self):
        png, got = paper.preview(photo_bytes(), 'A5', copies=4)
        self.assertTrue(png.startswith(b'\x89PNG'))
        self.assertEqual((got['sheet'], got['fit_on_one_sheet'], got['sheets_needed']), ('A4', 2, 2))

    def test_a_photo_the_wrong_shape_is_flagged_so_octos_can_ask(self):
        _, tall = paper.preview(photo_bytes(900, 1600), 'A5')          # a 9:16 phone photo
        self.assertTrue(tall['photo_shape_differs'])
        self.assertIn('white edges', tall['say'])
        _, close = paper.preview(photo_bytes(1480, 2100), 'A5')        # A5's own shape
        self.assertFalse(close['photo_shape_differs'])
        self.assertNotIn('say', close)

    def test_fill_trims_the_edges(self):
        _, got = paper.preview(photo_bytes(), 'B6', fill=True)
        self.assertEqual(got['shown'], 'filling the piece, edges trimmed')

    def test_whole_sheets_and_a3(self):
        self.assertEqual(paper.preview(photo_bytes(), 'A4')[1]['fit_on_one_sheet'], 1)
        self.assertEqual(paper.preview(photo_bytes(), 'A3')[1]['sheet'], 'A3')

    def test_what_it_cannot_draw(self):
        self.assertIn('error', paper.preview(b'not a photo', 'A5')[1])
        self.assertIn('error', paper.preview(photo_bytes(), 'huge')[1])
        self.assertIn('large format', paper.preview(photo_bytes(), 'A2')[1]['error'])

    def test_the_layout_turns_pieces_to_fit_most(self):
        self.assertEqual(paper._layout(148, 210, paper.A4), (210, 148, 1, 2))   # A5: two, turned
        self.assertEqual(paper._layout(105, 148, paper.A4), (105, 148, 2, 2))   # A6: four, upright


class RulesTests(SimpleTestCase):

    def test_octos_talks_about_paper_in_everyday_words(self):
        self.assertIn('never like a spec sheet', prompt.RULES)
        self.assertIn('Never mention paper weight (gsm)', prompt.RULES)

    def test_small_sizes_are_printed_and_photos_go_on_normal_paper(self):
        self.assertIn('Never say we can\'t print a small size', prompt.RULES)
        self.assertIn('A photo is not a photo-paper job by default', prompt.RULES)
        self.assertIn('"On normal paper, or glossy photo paper?"', prompt.RULES)

    def test_the_tools_are_offered(self):
        names = [t['name'] for t in brain.TOOL_SPECS]
        self.assertIn('paper_sizes', names)
        self.assertIn('print_preview', names)

    def test_the_fixes_from_the_testers_chat(self):
        self.assertIn('Never promise how a print will come out', prompt.RULES)
        self.assertIn('never repeat its caption', prompt.RULES)
        self.assertIn('"Take your time 😊 Just say yes when you\'re ready."', prompt.RULES)
        self.assertIn('show them with print_preview', prompt.RULES)


class PictureInTheChatTests(TestCase):

    def setUp(self):
        branch = make_org()
        self.conv = make_conversation(None, contact_phone=PHONE)
        customer_wrote(self.conv, timedelta(seconds=30))
        self.ctx = brain.Context(conversation=self.conv, branches=[branch])

    @override_settings(OCTOS_ASSISTANT_MODE='live')
    def test_live_the_picture_goes_into_the_chat(self):
        with patch('apps.communications.tasks.deliver_whatsapp.delay'), \
                self.captureOnCommitCallbacks(execute=True):
            got = brain._run_tool('paper_sizes', {'sizes': ['B6'], 'show_picture': True}, self.ctx)
        self.assertIn('Sent in the chat', got['picture'])
        sent = Message.objects.filter(conversation=self.conv, direction=Message.OUTBOUND).get()
        self.assertEqual(sent.message_type, Message.IMAGE)
        self.assertEqual(sent.media_name, 'paper-sizes.png')

    @override_settings(OCTOS_ASSISTANT_MODE='shadow')
    def test_in_shadow_nothing_reaches_the_customer(self):
        got = brain._run_tool('paper_sizes', {'sizes': ['B6'], 'show_picture': True}, self.ctx)
        self.assertIn('Shadow mode', got['picture'])
        self.assertFalse(Message.objects.filter(conversation=self.conv, direction=Message.OUTBOUND).exists())

    def test_without_show_picture_it_only_describes(self):
        got = brain._run_tool('paper_sizes', {'sizes': ['A6'], 'copies': 10}, self.ctx)
        self.assertNotIn('picture', got)
        self.assertEqual(got['sizes'][0]['a4_sheets_needed'], 3)


class PreviewInTheChatTests(TestCase):

    def setUp(self):
        branch = make_org()
        self.conv = make_conversation(None, contact_phone=PHONE)
        customer_wrote(self.conv, timedelta(seconds=30))
        self.ctx = brain.Context(conversation=self.conv, branches=[branch])
        self.photo = Message.objects.create(conversation=self.conv, direction=Message.INBOUND,
                                            channel=Message.WHATSAPP, message_type=Message.IMAGE,
                                            media_mime='image/jpeg', media_name='me.jpg')
        self.photo.media_file.save('me.jpg', ContentFile(photo_bytes()), save=True)

    @override_settings(OCTOS_ASSISTANT_MODE='live')
    def test_live_their_preview_goes_into_the_chat(self):
        with patch('apps.communications.tasks.deliver_whatsapp.delay'), \
                self.captureOnCommitCallbacks(execute=True):
            got = brain._run_tool('print_preview', {'file': self.photo.pk, 'size': 'A5', 'copies': 4}, self.ctx)
        self.assertIn('Sent in the chat', got['picture'])
        self.assertEqual(got['sheets_needed'], 2)
        sent = Message.objects.filter(conversation=self.conv, direction=Message.OUTBOUND).get()
        self.assertEqual((sent.message_type, sent.media_name), (Message.IMAGE, 'print-preview.png'))

    @override_settings(OCTOS_ASSISTANT_MODE='shadow')
    def test_in_shadow_the_preview_is_not_sent(self):
        got = brain._run_tool('print_preview', {'file': self.photo.pk, 'size': 'A5'}, self.ctx)
        self.assertIn('Shadow mode', got['picture'])
        self.assertFalse(Message.objects.filter(conversation=self.conv, direction=Message.OUTBOUND).exists())

    def test_only_their_own_photos(self):
        doc = Message.objects.create(conversation=self.conv, direction=Message.INBOUND, channel=Message.WHATSAPP,
                                     message_type=Message.DOCUMENT, media_mime='application/pdf',
                                     media_name='cv.pdf')
        doc.media_file.save('cv.pdf', ContentFile(b'%PDF-1.4'), save=True)
        self.assertIn('photos only', brain._run_tool('print_preview', {'file': doc.pk, 'size': 'A5'},
                                                     self.ctx)['error'])
        self.assertIn('not one this customer sent',
                      brain._run_tool('print_preview', {'file': 999999, 'size': 'A5'}, self.ctx)['error'])
