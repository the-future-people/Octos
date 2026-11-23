"""
Farhat Trade Partners, part one (23 Nov 2026): applying, confirming the
numbers, and the owner's decision on his line.
"""
from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.communications.tests_sandbox import png
from apps.customers.models import CustomerProfile
from apps.jobs.models import Service
from apps.partners.models import Partner, PartnerRep
from apps.partners.services import apply as applying
from apps.partners.services import ids, review

CODE = 'apps.storefront.services.accounts.secrets.randbelow'
SHOP = '+233244550912'
REP = '+233201112233'


def photo(name='shop.png'):
    return SimpleUploadedFile(name, png(), content_type='image/png')


def send_code(phone):
    with patch(CODE, return_value=123456):
        applying.send_code(phone)


def form(**changes):
    data = {
        'invite': 'TESTSHOP', 'name': 'Kobby Prints', 'kind': 'PRINT_SHOP', 'region': 'Greater Accra',
        'area': 'Madina', 'gps_address': 'ga-402-1187', 'landmark': 'the Zongo junction',
        'monthly_volume': '6-20', 'accept_terms': 'true', 'rep_title': 'Mr', 'rep_first_name': 'Kobby',
        'rep_last_name': 'Asante', 'rep_role': 'OWNER', 'primary_phone': '0244550912',
        'primary_code': '123456', 'rep_phone': '020 111 2233', 'rep_code': '123456',
        'messages_consent': 'true', 'password': 'Madina-Prints-26',
    }
    data.update(changes)
    return data


@override_settings(PARTNER_SIGNUPS_OPEN=False, PARTNER_INVITE_CODES=['TESTSHOP'])
class Base(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.banner = Service.objects.create(name='Flexy Banner', code='PT-FLX', category='PRODUCTION',
                                            unit='PER_SQFT', is_active=True, online=True)
        cls.sticker = Service.objects.create(name='SAV Sticker', code='PT-SAV', category='PRODUCTION',
                                             unit='PER_SQFT', is_active=True, online=True)

    def setUp(self):
        cache.clear()

    def apply(self, **changes):
        send_code(SHOP)
        send_code(REP)
        with patch('apps.partners.services.review.put_to_owner'):
            with self.captureOnCommitCallbacks(execute=True):
                return applying.submit(form(services=f'{self.banner.pk},{self.sticker.pk}', **changes),
                                       photo(), photo('logo.png'))


class IdTests(TestCase):

    def test_known_towns_and_anywhere_else(self):
        self.assertEqual(ids.area_code('Madina'), 'MAD')
        self.assertEqual(ids.area_code('  east   LEGON '), 'ELG')
        self.assertEqual(ids.area_code('Abokobi'), 'ABO')

    def test_a_code_is_area_then_four_clear_characters(self):
        code = ids.new_code('Kasoa')
        self.assertRegex(code, r'^KAS-[A-HJ-NP-Z2-9]{4}$')


class ApplyTests(Base):

    def test_closed_without_an_invite(self):
        with self.assertRaises(applying.Refused) as refused:
            applying.submit(form(invite=''), photo(), photo())
        self.assertEqual(refused.exception.field, 'invite')

    @override_settings(PARTNER_SIGNUPS_OPEN=True)
    def test_open_to_all_once_switched_on(self):
        self.assertTrue(applying.open_to(''))

    def test_an_application_with_both_numbers_confirmed(self):
        partner = self.apply()
        self.assertEqual(partner.status, Partner.Status.APPLIED)
        self.assertIsNone(partner.code)                       # the ID comes at approval
        self.assertEqual(partner.gps_address, 'GA-402-1187')
        self.assertEqual(partner.primary_phone, SHOP)
        self.assertEqual(set(partner.services.all()), {self.banner, self.sticker})
        rep = partner.reps.get()
        self.assertEqual((rep.first_name, rep.role, rep.lead.phone), ('Kobby', 'OWNER', REP))
        self.assertRegex(partner.shop_photo.name, r'^partners/\d{4}/\d{2}/shop[^/]*\.png$')

    def test_a_wrong_code_takes_nothing(self):
        send_code(SHOP)
        send_code(REP)
        with self.assertRaises(applying.Refused) as refused:
            applying.submit(form(services=str(self.banner.pk), rep_code='000000'), photo(), photo())
        self.assertEqual(refused.exception.field, 'rep_code')
        self.assertFalse(Partner.objects.exists())

    def test_only_services_from_our_catalogue(self):
        with self.assertRaises(applying.Refused) as refused:
            applying.submit(form(services='999999'), photo(), photo())
        self.assertEqual(refused.exception.field, 'services')

    def test_the_same_shop_twice_is_refused(self):
        self.apply()
        send_code(SHOP)
        with self.assertRaises(applying.Refused):
            applying.submit(form(services=str(self.banner.pk)), photo(), photo())
        with self.assertRaises(applying.Refused) as by_name:
            applying.submit(form(services=str(self.banner.pk), primary_phone='0277000111',
                                 rep_phone='0277000111'), photo(), photo())
        self.assertEqual(by_name.exception.field, 'name')

    def test_the_registration_number_is_never_required(self):
        self.assertEqual(self.apply(registration_number='').registration_number, '')


@override_settings(OCTOS_OWNER_PHONE='0556244194')
class ReviewTests(Base):

    def test_the_card_goes_to_the_owner_with_the_shop_front_and_three_buttons(self):
        partner = self.apply()
        with patch('apps.communications.services.owner_line.tell') as tell:
            review.put_to_owner(partner.pk)
        kwargs = tell.call_args.kwargs
        self.assertEqual([b['title'] for b in kwargs['buttons']], ['Approve', 'Ask for more', 'Decline'])
        self.assertTrue(kwargs['card'].startswith(b'\x89PNG'))
        body = tell.call_args.args[1]
        self.assertIn('Kobby Prints', body)
        self.assertIn('New to us', body)

    def test_approve_opens_the_account_with_an_id_and_a_welcome(self):
        partner = self.apply()
        with patch('apps.communications.services.owner_line.tell'), \
                patch('apps.partners.services.review.say') as say, \
                self.captureOnCommitCallbacks(execute=True):
            review.tap(f'partner:approve:{partner.pk}')
        partner.refresh_from_db()
        self.assertEqual(partner.status, Partner.Status.APPROVED)
        self.assertRegex(partner.code, r'^MAD-')
        self.assertEqual(partner.customer.customer_type, 'BUSINESS')
        self.assertEqual(partner.customer.company_name, 'Kobby Prints')
        self.assertEqual(say.call_args.args[0], REP)
        self.assertIn(partner.shown_code, say.call_args.args[1])
        self.assertIn('10% off', say.call_args.args[1])

    def test_a_shop_number_already_a_person_gets_its_own_business_record(self):
        owner = CustomerProfile.objects.create(first_name='Kobby', phone=SHOP, customer_type='INDIVIDUAL')
        partner = self.apply()
        with patch('apps.communications.services.owner_line.tell'), patch('apps.partners.services.review.say'):
            review.approve(partner)
        partner.refresh_from_db()
        self.assertNotEqual(partner.customer_id, owner.pk)
        self.assertEqual(partner.customer.phone, f'TP-{partner.code}')

    def test_ask_for_more_sends_his_next_message_word_for_word(self):
        from apps.communications.models import OwnerMessage
        from apps.communications.services import owner_line
        partner = self.apply()
        with patch('apps.communications.services.owner_line.tell'):
            review.tap(f'partner:ask:{partner.pk}')
        said = OwnerMessage.objects.create(direction=OwnerMessage.IN, status=OwnerMessage.RECEIVED,
                                           body='Send a photo of the inside of your shop')
        with patch('apps.communications.services.owner_line.tell'), \
                patch('apps.partners.services.review.say') as say:
            owner_line.answer(said.pk)
        partner.refresh_from_db()
        self.assertEqual(partner.status, Partner.Status.ASKED)
        self.assertEqual(partner.asked_for, 'Send a photo of the inside of your shop')
        self.assertIn('Send a photo of the inside of your shop', say.call_args.args[1])

    def test_decline_is_kind_and_final(self):
        partner = self.apply()
        with patch('apps.communications.services.owner_line.tell'), \
                patch('apps.partners.services.review.say') as say:
            review.tap(f'partner:decline:{partner.pk}')
            review.tap(f'partner:approve:{partner.pk}')         # too late: already decided
        partner.refresh_from_db()
        self.assertEqual(partner.status, Partner.Status.DECLINED)
        self.assertIn('apply again', say.call_args.args[1])

    def test_unanswered_for_fourteen_days_closes(self):
        partner = self.apply()
        Partner.objects.filter(pk=partner.pk).update(status=Partner.Status.ASKED,
                                                     asked_at=timezone.now() - timedelta(days=15))
        self.assertEqual(review.close_stale(), 1)
        partner.refresh_from_db()
        self.assertEqual(partner.status, Partner.Status.CLOSED)


class ApiTests(Base):

    def test_open_lists_only_what_we_make_online(self):
        r = APIClient().get('/api/v1/partners/open/', {'invite': 'testshop'})
        self.assertTrue(r.data['open'])
        self.assertIn('Print shop', [k['name'] for k in r.data['kinds']])

    def test_apply_and_then_sign_in_to_see_the_status(self):
        from apps.storefront.services import accounts
        client = APIClient()
        with patch(CODE, return_value=123456):
            self.assertEqual(client.post('/api/v1/partners/code/', {'phone': '0244550912', 'invite': 'TESTSHOP'}).status_code, 200)
            client.post('/api/v1/partners/code/', {'phone': '0201112233', 'invite': 'TESTSHOP'})
        data = form(services=str(self.banner.pk))
        data.update(shop_photo=photo(), logo=photo('logo.png'))
        with patch('apps.partners.services.review.put_to_owner'):
            r = client.post('/api/v1/partners/apply/', data, format='multipart')
        self.assertEqual(r.status_code, 201, r.data)
        with patch(CODE, return_value=654321):
            accounts.send_code(REP)
        lead, token = accounts.verify_code(REP, '654321')
        me = client.get('/api/v1/partners/me/', HTTP_AUTHORIZATION=f'App {token}')
        self.assertEqual(me.status_code, 200)
        self.assertEqual((me.data['name'], me.data['status']), ('Kobby Prints', 'APPLIED'))

    def test_a_number_with_no_partner_account(self):
        from apps.storefront.services import accounts
        from apps.storefront.models import Lead
        Lead.objects.create(phone='+233209998877', first_name='Ama')
        with patch(CODE, return_value=111111):
            accounts.send_code('0209998877')
        _, token = accounts.verify_code('0209998877', '111111')
        self.assertEqual(APIClient().get('/api/v1/partners/me/', HTTP_AUTHORIZATION=f'App {token}').status_code, 404)
        self.assertFalse(PartnerRep.objects.exists())


class AccessTests(Base):
    """Registering sets a password; reps log in with their number and it (24 Nov 2026)."""

    def test_registering_logs_them_in_and_keeps_only_a_hash(self):
        client = APIClient()
        with patch(CODE, return_value=123456):
            client.post('/api/v1/partners/code/', {'phone': '0244550912', 'invite': 'TESTSHOP'})
            client.post('/api/v1/partners/code/', {'phone': '0201112233', 'invite': 'TESTSHOP'})
        data = form(services=str(self.banner.pk))
        data.update(shop_photo=photo(), logo=photo('logo.png'))
        with patch('apps.partners.services.review.put_to_owner'):
            r = client.post('/api/v1/partners/apply/', data, format='multipart')
        self.assertEqual(r.status_code, 201, r.data)
        rep = PartnerRep.objects.get()
        self.assertNotIn('Madina-Prints-26', rep.password)
        me = client.get('/api/v1/partners/me/', HTTP_AUTHORIZATION=f"App {r.data['token']}")
        self.assertEqual(me.data['status'], 'APPLIED')

    def test_a_weak_password_is_refused_before_any_code_is_used(self):
        send_code(SHOP)
        with self.assertRaises(applying.Refused) as refused:
            applying.submit(form(services=str(self.banner.pk), password='1234'), photo(), photo())
        self.assertEqual(refused.exception.field, 'password')

    def test_log_in_with_number_and_password(self):
        self.apply()
        client = APIClient()
        bad = client.post('/api/v1/partners/login/', {'phone': '020 111 2233', 'password': 'wrong-one-1'})
        self.assertEqual(bad.status_code, 400)
        good = client.post('/api/v1/partners/login/', {'phone': '020 111 2233', 'password': 'Madina-Prints-26'})
        self.assertEqual(good.status_code, 200)
        me = client.get('/api/v1/partners/me/', HTTP_AUTHORIZATION=f"App {good.data['token']}")
        self.assertEqual(me.data['name'], 'Kobby Prints')

    def test_five_wrong_passwords_lock_the_number(self):
        from apps.partners.services import access
        self.apply()
        for _ in range(access.MAX_TRIES):
            with self.assertRaises(access.Refused):
                access.login(REP, 'not-the-password')
        with self.assertRaises(access.Refused) as locked:
            access.login(REP, 'Madina-Prints-26')
        self.assertIn('15 minutes', str(locked.exception))

    def test_forgotten_password_by_code(self):
        from apps.partners.services import access
        self.apply()
        with patch(CODE, return_value=777777):
            self.assertEqual(APIClient().post('/api/v1/partners/password/code/', {'phone': REP}).status_code, 200)
        r = APIClient().post('/api/v1/partners/password/reset/',
                             {'phone': REP, 'code': '777777', 'password': 'Brand-New-Pass-9'})
        self.assertEqual(r.status_code, 200, r.data)
        rep, _ = access.login(REP, 'Brand-New-Pass-9')
        self.assertEqual(rep.first_name, 'Kobby')

    def test_a_reset_code_says_nothing_about_strangers(self):
        with patch('apps.storefront.services.accounts.send_code') as sent:
            r = APIClient().post('/api/v1/partners/password/code/', {'phone': '0209998877'})
        self.assertEqual(r.status_code, 200)
        sent.assert_not_called()

    def test_sign_out_ends_the_session(self):
        from apps.partners.services import access
        self.apply()
        _, token = access.login(REP, 'Madina-Prints-26')
        client = APIClient()
        client.post('/api/v1/partners/signout/', HTTP_AUTHORIZATION=f'App {token}')
        self.assertEqual(client.get('/api/v1/partners/me/', HTTP_AUTHORIZATION=f'App {token}').status_code, 401)
