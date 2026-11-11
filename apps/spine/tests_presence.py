"""
The presence belief, number by number (Layer 2, Step 2.2).
"""
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.spine.presence import AT_COUNTER, AWAY, UNSURE, believe, texture


class BeliefArithmeticTests(SimpleTestCase):
    def test_the_art_paper_question_45_minutes_after_the_qr_is_away(self):
        b = believe('signed_qr', 45, 'info_question')
        self.assertAlmostEqual(b.p, 0.037, places=2)
        self.assertEqual(b.band, AWAY)

    def test_a_file_3_minutes_after_the_qr_is_at_the_counter(self):
        b = believe('signed_qr', 3, 'file_no_words')
        self.assertGreater(b.p, 0.9)
        self.assertEqual(b.band, AT_COUNTER)

    def test_time_alone_fades_the_belief(self):
        self.assertGreater(believe('signed_qr', 5, 'greeting').p, believe('signed_qr', 60, 'greeting').p)

    def test_a_bare_hi_with_no_proof_while_open_is_not_sure(self):
        self.assertEqual(believe(None, 0, 'greeting', shop_open=True).band, UNSURE)

    def test_a_wordless_file_with_no_proof_is_not_sure(self):
        self.assertEqual(believe(None, 0, 'file_no_words', shop_open=True).band, UNSURE)

    def test_a_statement_with_no_proof_is_answered(self):
        self.assertEqual(believe(None, 0, 'words', shop_open=True).band, AWAY)

    def test_anything_while_closed_is_away(self):
        self.assertEqual(believe(None, 0, 'file_no_words', shop_open=False).band, AWAY)

    def test_a_job_made_since_the_anchor_points_away(self):
        before = believe('signed_qr', 10, 'words').p
        after = believe('signed_qr', 10, 'words', outcome_since=True).p
        self.assertLess(after, before)

    def test_a_file_someone_opened_keeps_octos_quiet_on_more_files(self):
        self.assertEqual(believe('opened', 2, 'file_no_words').band, AT_COUNTER)

    def test_a_question_after_a_file_was_opened_goes_to_the_attendant_first(self):
        self.assertEqual(believe('opened', 2, 'info_question').band, UNSURE)

    def test_the_reasons_say_why(self):
        b = believe('signed_qr', 3, 'file_no_words')
        self.assertIn('signed qr 3 min ago', b.why)
        self.assertIn('file no words', b.why)


def _msg(body='', file=False):
    return SimpleNamespace(body=body, direction='INBOUND', message_type='IMAGE' if file else 'TEXT',
                           media_name='', media_id='m' if file else '')


class TextureTests(SimpleTestCase):
    def test_textures(self):
        self.assertEqual(texture(_msg('Hi')), 'greeting')
        self.assertEqual(texture(_msg('Good morning 🙂')), 'greeting')
        self.assertEqual(texture(_msg('Hi, please do you guys print on art paper')), 'info_question')
        self.assertEqual(texture(_msg('How much for A4 colour?')), 'info_question')
        self.assertEqual(texture(_msg('Is my order ready')), 'status_question')
        self.assertEqual(texture(_msg("I'm on my way")), 'on_the_way')
        self.assertEqual(texture(_msg('I want to print something')), 'words')
        self.assertEqual(texture(_msg(file=True)), 'file_no_words')
