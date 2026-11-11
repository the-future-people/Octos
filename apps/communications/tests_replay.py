"""
Golden scenarios from real conversations, 9-10 Nov 2026, anonymised (Layer 1, Step 1.4).

Each is a conversation that went wrong (or right) in the shop, replayed through
the real pipeline. If a change makes Octos repeat a mistake it made with a real
customer, the build fails here before it reaches the counter.

Run: docker compose run --rm web python manage.py test apps.communications.tests_replay -v 2
"""
from django.test import override_settings

from apps.communications.replay import MODEL_REPLY, Replay
from apps.communications.tests import CommunicationsTestBase

QR = "Hi, I'm at the Westland counter"


@override_settings(ANTHROPIC_API_KEY='test-key', OCTOS_ASSISTANT_MODE='live')
class GoldenScenarios(CommunicationsTestBase):
    def setUp(self):
        super().setUp()               # a branch and a signed-in staff member, as the inbox tests use
        self.branch.is_trading = True
        self.branch.save()

    # ── At the counter ───────────────────────────────────────

    def test_priscilla_qr_then_a_photo_seconds_later_gets_nothing(self):
        with Replay() as r:
            qr = r.customer(QR)
            r.wait(seconds=5)
            photo = r.customer(file=True)
            r.wait(seconds=3)
            r.octos_turn(qr)                 # skipped: a newer message
            r.wait(minutes=2)
            r.octos_turn(photo)
            self.assertEqual(r.said(), [])
            self.assertEqual(r.visits()[0].presence, 'AT_COUNTER')

    def test_mr_tee_one_acknowledgement_then_silence_for_photos(self):
        with Replay() as r:
            qr = r.customer(QR)
            r.wait(seconds=8)
            r.octos_turn(qr)
            r.wait(minutes=1)
            first = r.customer(file=True)
            second = r.customer(file=True)
            r.wait(minutes=2)
            r.octos_turn(first)
            r.octos_turn(second)
            said = r.said()
            self.assertEqual(len(said), 1)
            self.assertIn('pick them up', said[0])
            self.assertNotIn('ends in', said[0])      # no phone digits (11 Nov 2026)

    def test_samysela_served_and_job_recorded_gets_no_message_later(self):
        with Replay() as r:
            qr = r.customer(QR)
            files = [r.customer(file=True), r.customer(file=True)]
            r.wait(seconds=8)
            r.octos_turn(qr)
            r.at_counter_tap()
            r.wait(minutes=2)
            r.octos_turn(files[-1])
            r.wait(minutes=5)
            r.job_created()
            r.wait(minutes=45)
            r.handover_watch()
            r.wait(minutes=15)
            r.handover_watch()
            said = r.said()
            self.assertLessEqual(len(said), 1)      # at most the counter acknowledgement
            self.assertEqual(r.visits()[0].outcome, 'JOB_CREATED')

    # ── Files without the QR ─────────────────────────────────

    def test_files_handled_after_a_take_over_get_no_message_on_take_back(self):
        # Arthur and Kojo, 9 Nov: staff took over to open the files, never typed,
        # and 40 minutes later Octos took back and sent the stock reply.
        with Replay() as r:
            photo = r.customer(file=True)
            r.wait(seconds=10)
            r.take_over(self.user)
            r.wait(minutes=2)
            r.octos_turn(photo)                  # silent: a person has it
            r.wait(minutes=29)
            r.handover_watch()                   # the reminder
            r.wait(minutes=11)
            r.handover_watch()                   # the take-back
            r.octos_turn(photo)                  # the run the take-back wakes
            self.assertEqual(r.said(), [])

    # ── Remote customers ─────────────────────────────────────

    def test_albion_unpaid_link_is_abandoned_after_two_quiet_hours(self):
        with Replay(shop_open=False) as r:
            ask = r.customer('I want to print this as a 3 x 3 sticker')
            r.wait(seconds=8)
            r.octos_turn(ask)
            r.payment_link_sent()
            r.wait(hours=2, minutes=10)
            r.sweep()
            [visit] = r.visits()
            self.assertEqual(visit.outcome, 'ABANDONED')
            self.assertTrue(visit.timed_out)

    def test_peoples_kofi_a_question_after_collection_is_a_new_visit_and_answered(self):
        with Replay() as r:
            hello = r.customer('Hi, I want to print something')
            r.wait(seconds=8)
            r.octos_turn(hello)
            r.job_created()
            r.wait(minutes=20)
            question = r.customer('How much will it cost?')
            r.wait(seconds=8)
            r.octos_turn(question)
            self.assertEqual(len(r.visits()), 2)
            self.assertEqual(r.said()[-1], MODEL_REPLY)

    def test_kings_hub_three_jobs_in_a_day_are_three_visits(self):
        with Replay() as r:
            r.customer('Good morning')
            r.wait(hours=2, minutes=30)
            r.customer(file=True)
            r.wait(hours=10)
            r.customer("Hi Farhat, I'd like to send a print job.")
            self.assertEqual(len(r.visits()), 3)
