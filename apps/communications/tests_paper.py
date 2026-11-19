"""
Paper sizes in plain words, and a picture of them (19 Nov 2026).

A customer found Octos too technical about paper sizes, asked to see what
B6 and A4 look like, and was led to think sizes below A4 aren't printed.
Every size below A4 is printed on A4 and cut; photos usually go on normal
paper, not photo paper.
"""
from datetime import timedelta
from unittest.mock import patch

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


class RulesTests(SimpleTestCase):

    def test_octos_talks_about_paper_in_everyday_words(self):
        self.assertIn('never like a spec sheet', prompt.RULES)
        self.assertIn('Never mention paper weight (gsm)', prompt.RULES)

    def test_small_sizes_are_printed_and_photos_go_on_normal_paper(self):
        self.assertIn('Never say we can\'t print a small size', prompt.RULES)
        self.assertIn('A photo is not a photo-paper job by default', prompt.RULES)
        self.assertIn('"On normal paper, or glossy photo paper?"', prompt.RULES)

    def test_the_tool_is_offered(self):
        self.assertIn('paper_sizes', [t['name'] for t in brain.TOOL_SPECS])


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
