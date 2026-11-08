"""
Two more templates, and a customer's no is respected (8 Nov 2026).
"""
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from apps.communications.tests import make_conversation, make_org


class OptOutWordsTests(SimpleTestCase):

    def test_saying_no_counts(self):
        from apps.communications.services.whatsapp_inbound import OPT_OUT
        for words in ('STOP', 'please stop', "Don't message me again", 'no more messages', 'Not interested', 'unsubscribe'):
            self.assertTrue(OPT_OUT.search(words), words)

    def test_talking_about_a_job_does_not(self):
        from apps.communications.services.whatsapp_inbound import _opt_out_if_asked
        class Chat: marketing_opt_out = False
        self.assertFalse(_opt_out_if_asked(Chat(), 'stop the printing, I will change the file and send it again'))
        self.assertFalse(_opt_out_if_asked(Chat(), 'thank you'))
        self.assertFalse(_opt_out_if_asked(Chat(), 'Stop the job please'))
        self.assertFalse(_opt_out_if_asked(Chat(), 'Not interested in the A3, A4 please'))


class ReconnectTests(TestCase):

    def setUp(self):
        make_org()
        self.api = APIClient()
        self.api.force_authenticate(get_user_model().objects.create_user(
            email='bm2@farhat.test', password='x', first_name='Ama', last_name='Mensah'))

    def test_reconnect_is_never_sent_to_someone_who_said_no(self):
        conv = make_conversation(None, contact_phone='+233244000666')
        conv.marketing_opt_out = True
        conv.save()
        response = self.api.post('/api/v1/communications/start/', {
            'phone': '+233244000666', 'template': 'reconnect', 'params': ['Ama']}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('asked not to receive', response.json()['detail'])

    def test_the_new_templates_are_offered_with_their_kind(self):
        listed = {t['name']: t for t in self.api.get('/api/v1/communications/start/').json()['templates']}
        self.assertEqual(listed['reconnect']['kind'], 'marketing')
        self.assertEqual((listed['general_followup']['kind'], listed['general_followup']['params']), ('service', 1))
