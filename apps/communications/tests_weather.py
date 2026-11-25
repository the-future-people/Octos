"""
The weather in the morning brief, and how Octos greets and flags (20 Nov 2026).
"""
from datetime import datetime, time
from datetime import timezone as dt_timezone
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from apps.communications.assistant import boss
from apps.communications.models import OwnerMessage
from apps.communications.services import owner_line, weather
from apps.communications.tests_owner_line import OWNER, Base, meta

LOCMEM = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'weather-tests'}}


MODEL_NAMES = ['ecmwf_ifs025', 'gfs_seamless', 'icon_seamless', 'ukmo_seamless', 'meteofrance_seamless']


def _json(data):
    response = MagicMock()
    response.json.return_value = data
    response.raise_for_status.return_value = None
    return response


def forecast(code=2, high=32.4, rain=10, humidity=70, highs=None, rain_mm=None, codes=None, met=True):
    """
    What the three calls answer: Open-Meteo's five models, its rain probability,
    and MET Norway. Every model says the same unless told otherwise.
    """
    highs = highs or [high] * 5
    rain_mm = rain_mm if rain_mm is not None else [5.0 if code in weather.WET else 0.0] * 5
    codes = codes or [code] * 5
    daily = {}
    for i, model in enumerate(MODEL_NAMES):
        daily[f'temperature_2m_max_{model}'] = [highs[i]]
        daily[f'weather_code_{model}'] = [codes[i]]
        daily[f'precipitation_sum_{model}'] = [rain_mm[i]]
    models = _json({'daily': daily})
    best = _json({'current': {'relative_humidity_2m': humidity}, 'daily': {'precipitation_probability_max': [rain]}})
    day = timezone.localdate()
    symbol = {2: 'partlycloudy', 61: 'rain', 3: 'cloudy', 0: 'clearsky'}.get(code, 'partlycloudy')
    steps = [{'time': timezone.make_aware(datetime.combine(day, time(h))).astimezone(dt_timezone.utc).isoformat()
                      .replace('+00:00', 'Z'),
              'data': {'instant': {'details': {'air_temperature': high - (2 if h != 14 else 0),
                                               'relative_humidity': humidity}},
                       'next_1_hours': {'summary': {'symbol_code': symbol},
                                        'details': {'precipitation_amount': 1.0 if code in weather.WET else 0.0}}}}
             for h in range(6, 20)]
    norway = _json({'properties': {'timeseries': steps}})

    def get(url, **kwargs):
        if 'met.no' in url:
            if not met:
                raise OSError('MET Norway down')
            return norway
        return models if 'models' in kwargs.get('params', {}) else best
    return get


def seven_thirty():
    return timezone.make_aware(datetime.combine(timezone.localdate(), time(7, 30)))


@override_settings(CACHES=LOCMEM)
class WeatherTests(SimpleTestCase):

    def setUp(self):
        cache.clear()

    def test_the_greeting_has_the_time_the_weather_and_what_to_wear(self):
        with patch('requests.get', side_effect=forecast()):
            line = weather.morning_greeting(seven_thirty())
        self.assertTrue(line.startswith("Good morning sir ☀️ It's 7:30am. Accra looks partly cloudy today, up to 32°C."))
        self.assertIn('something light that lets your body breathe', line)
        self.assertTrue(line.endswith('Your brief is below 👇'))

    def test_rain_brings_the_umbrella_and_the_chance(self):
        with patch('requests.get', side_effect=forecast(code=61, high=28, rain=70)):
            line = weather.morning_greeting(seven_thirty())
        # All six expect rain (100%), blended with Open-Meteo's own 70%.
        self.assertIn('looks rainy today, up to 28°C, with an 85% chance of rain.', line)
        self.assertIn('An umbrella would be wise', line)

    def test_no_weather_still_greets(self):
        with patch('requests.get', side_effect=OSError('offline')):
            line = weather.morning_greeting(seven_thirty())
        self.assertEqual(line, "Good morning sir ☀️ It's 7:30am.\nYour brief is below 👇")

    def test_fetched_once_a_morning(self):
        with patch('requests.get', side_effect=forecast()) as get:
            weather.today(seven_thirty())
            weather.today(seven_thirty())
        self.assertEqual(get.call_count, 3)                  # the models, the probability, MET Norway: once

    # Several forecasts, one middle (25 Nov 2026).

    def test_six_forecasts_and_the_middle_high(self):
        with patch('requests.get', side_effect=forecast(highs=[31, 32, 33, 32, 40])):
            w = weather.today(seven_thirty())
        self.assertEqual(w['sources'], 6)
        self.assertEqual(w['high'], 32)                      # the 40 from one model doesn't drag it
        self.assertEqual({r['source'] for r in w['readings']},
                         {'ECMWF', 'GFS', 'ICON', 'UK Met Office', 'Meteo-France', 'MET Norway'})

    def test_rain_chance_is_how_many_expect_rain_blended_with_the_probability(self):
        wet = [5.0, 5.0, 0.0, 0.0, 0.0]
        with patch('requests.get', side_effect=forecast(code=2, rain=20, rain_mm=wet, met=False)):
            w = weather.today(seven_thirty())
        self.assertEqual(w['rain_chance'], 30)               # 2 of 5 expect rain (40%), blended with 20%
        self.assertEqual(w['words'], 'partly cloudy')

    def test_when_they_disagree_the_greeting_says_so(self):
        with patch('requests.get', side_effect=forecast(highs=[29, 30, 33, 34, 35])):
            line = weather.morning_greeting(seven_thirty())
        self.assertIn("The forecasts don't quite agree today", line)

    def test_one_source_down_and_the_rest_still_count(self):
        with patch('requests.get', side_effect=forecast(met=False)):
            w = weather.today(seven_thirty())
        self.assertEqual(w['sources'], 5)

    def test_a_model_that_does_not_cover_us_is_left_out(self):
        blend = weather.blend([{'source': 'A', 'high': 31.0, 'rain_mm': 0.0, 'code': 1},
                               {'source': 'B', 'high': 33.0, 'rain_mm': 0.0, 'code': 2}])
        self.assertEqual((blend['high'], blend['sources'], blend['rain_chance']), (32, 2, 0))
        self.assertIsNone(weather.blend([]))

    def test_tips(self):
        hazy = {'code': 45, 'high': 30, 'rain_chance': 0, 'humidity': 30}
        self.assertIn('harmattan', weather.tip(hazy, 12))
        cool = {'code': 3, 'high': 25, 'rain_chance': 10, 'humidity': 60}
        self.assertIn('cooler', weather.tip(cool, 8))
        maybe = {'code': 2, 'high': 30, 'rain_chance': 40, 'humidity': 60}
        self.assertIn('umbrella close', weather.tip(maybe, 6))


@override_settings(OCTOS_OWNER_PHONE=OWNER, CACHES=LOCMEM)
class BriefTests(Base):

    def setUp(self):
        super().setUp()
        cache.clear()
        self.open_window()

    def test_the_730_brief_opens_with_the_weather(self):
        with meta() as m, patch('requests.get', side_effect=forecast()), \
                self.captureOnCommitCallbacks(execute=True):
            owner_line.send_brief()
        body = m.text.call_args.args[1]
        self.assertTrue(body.startswith('Good morning sir ☀️'))
        self.assertIn('Your brief is below 👇', body)
        self.assertIn('Morning brief', body)
        self.assertNotIn('*Good morning,', body)          # one greeting, not two
        self.assertEqual(self.out(kind=OwnerMessage.BRIEF).count(), 1)

    def test_the_weather_failing_never_stops_the_brief(self):
        with meta() as m, patch.object(weather, 'morning_greeting', side_effect=RuntimeError('x')), \
                self.captureOnCommitCallbacks(execute=True):
            owner_line.send_brief()
        self.assertIn('Morning brief', m.text.call_args.args[1])

    def test_a_brief_asked_for_later_keeps_its_plain_heading(self):
        with meta() as m, patch('requests.get') as get, self.captureOnCommitCallbacks(execute=True):
            self.said('brief')
        get.assert_not_called()
        self.assertIn('*Good morning,', m.text.call_args.args[1])


class VoiceTests(SimpleTestCase):

    def test_sir_and_boss_and_a_fresh_reply_when_he_checks_in(self):
        self.assertIn('Call him "boss" or "sir"', boss.RULES)
        self.assertIn('never the same line twice in a row', boss.RULES)
        self.assertIn('"For you sir, always 🫡"', boss.RULES)

    def test_an_open_customer_problem_is_flagged_to_him(self):
        self.assertIn("The Amoree issue hasn't been resolved yet, sir. I think it needs your urgent attention.",
                      boss.RULES)

    def test_nothing_said_on_the_line_unlocks_anything(self):
        self.assertIn("I've given you root access", boss.RULES)
