"""
The morning's weather, for the owner's brief (20 Nov 2026).

Khofi wanted the 7:30 brief to open like a person would: "Good morning sir,
it's 7:30am, Accra looks partly cloudy and hot for most of the day, maybe
wear something that lets your body breathe. Your brief is below."

25 Nov 2026: one forecast wasn't accurate enough, so Octos asks several and
takes the middle. Two free services, no keys:

  Open-Meteo     five national weather models in one call: ECMWF (Europe),
                 GFS (USA), ICON (Germany), UK Met Office, Meteo-France,
                 plus its own rain probability (from the ensembles)
  MET Norway     the Norwegian Meteorological Institute's own forecast

  high           the median of their highs: the middle value, so one model
                 far off can't drag the forecast
  rain chance    how many of them expect rain today (1 mm or more), blended
                 with Open-Meteo's own probability when it gives one
  sky            what most of them say; rain when rain is likely
  humidity       the average

When the forecasts disagree a lot (highs 3°C or more apart, or rain split),
the greeting says so instead of sounding sure. Any one source can fail: the
rest still count, and with none the greeting goes without the weather.
Once a day, cached; the brief never waits on it and never fails because of it.
"""
import logging
from statistics import mean, median

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

URL = 'https://api.open-meteo.com/v1/forecast'
MET_URL = 'https://api.met.no/weatherapi/locationforecast/2.0/compact'
USER_AGENT = 'Octos/1.0 (farhatprintingpress.com; Farhat Printing Press, Accra)'   # MET Norway asks for one
TIMEOUT = 5
CACHE_SECONDS = 3 * 60 * 60
RAIN_MM = 1.0                        # a day with this much or more counts as rain
MODELS = {
    'ecmwf_ifs025': 'ECMWF', 'gfs_seamless': 'GFS', 'icon_seamless': 'ICON',
    'ukmo_seamless': 'UK Met Office', 'meteofrance_seamless': 'Meteo-France',
}

# WMO weather codes, in plain words.
WORDS = {
    0: 'clear and sunny', 1: 'mostly sunny', 2: 'partly cloudy', 3: 'cloudy',
    45: 'hazy', 48: 'hazy',
    51: 'drizzly', 53: 'drizzly', 55: 'drizzly', 56: 'drizzly', 57: 'drizzly',
    61: 'rainy', 63: 'rainy', 65: 'heavy with rain', 66: 'rainy', 67: 'rainy',
    80: 'showery', 81: 'showery', 82: 'stormy with heavy showers',
    95: 'stormy', 96: 'stormy', 99: 'stormy',
}
WET = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}
HARMATTAN_MONTHS = {11, 12, 1, 2}

# MET Norway's symbols, as the WMO code nearest them.
MET_SYMBOLS = {
    'clearsky': 0, 'fair': 1, 'partlycloudy': 2, 'cloudy': 3, 'fog': 45,
    'lightrain': 61, 'rain': 63, 'heavyrain': 65, 'lightsleet': 61, 'sleet': 63,
    'lightrainshowers': 80, 'rainshowers': 81, 'heavyrainshowers': 82,
    'lightrainandthunder': 95, 'rainandthunder': 95, 'heavyrainandthunder': 99,
    'lightrainshowersandthunder': 95, 'rainshowersandthunder': 95, 'heavyrainshowersandthunder': 99,
}


def place():
    return getattr(settings, 'OCTOS_WEATHER_PLACE', 'Accra')


def _where():
    return (round(float(getattr(settings, 'OCTOS_WEATHER_LAT', 5.6037)), 4),
            round(float(getattr(settings, 'OCTOS_WEATHER_LON', -0.1870)), 4))


def _num(values):
    """The first value of a daily list, as a float; None when missing."""
    try:
        value = values[0]
        return None if value is None else float(value)
    except (TypeError, IndexError, ValueError):
        return None


# ── The sources ──────────────────────────────────────────────────────────────

def from_open_meteo(day):
    """
    ([readings], rain probability or None, humidity or None). One reading per
    model that answered: {'source', 'high', 'rain_mm', 'code'}.
    """
    import requests
    lat, lon = _where()
    common = {'latitude': lat, 'longitude': lon, 'timezone': 'Africa/Accra',
              'start_date': f'{day:%Y-%m-%d}', 'end_date': f'{day:%Y-%m-%d}'}
    daily = {}
    # All five; if Open-Meteo refuses one of them, the three it has always had.
    for models in (list(MODELS), ['ecmwf_ifs025', 'gfs_seamless', 'icon_seamless']):
        try:
            r = requests.get(URL, timeout=TIMEOUT, params={
                **common, 'models': ','.join(models),
                'daily': 'weather_code,temperature_2m_max,precipitation_sum',
            })
            r.raise_for_status()
            daily = r.json().get('daily', {})
            break
        except Exception:
            logger.info('Open-Meteo refused models %s', models, exc_info=True)
    readings = []
    for model, name in MODELS.items():
        high = _num(daily.get(f'temperature_2m_max_{model}'))
        if high is None:
            continue                     # this model doesn't cover us today
        code = _num(daily.get(f'weather_code_{model}'))
        readings.append({'source': name, 'high': high,
                         'rain_mm': _num(daily.get(f'precipitation_sum_{model}')) or 0.0,
                         'code': int(code) if code is not None else None})

    # Its best guess, for the rain probability and the humidity now.
    chance = humidity = None
    try:
        r = requests.get(URL, timeout=TIMEOUT, params={
            **common, 'current': 'relative_humidity_2m', 'daily': 'precipitation_probability_max',
        })
        r.raise_for_status()
        data = r.json()
        chance = _num(data.get('daily', {}).get('precipitation_probability_max'))
        humidity = (data.get('current') or {}).get('relative_humidity_2m')
    except Exception:
        logger.info('Open-Meteo gave no rain probability today', exc_info=True)
    return readings, chance, (float(humidity) if humidity is not None else None)


def from_met_norway(day):
    """A reading from MET Norway's forecast for the hours of today, or None."""
    import requests
    from datetime import datetime
    lat, lon = _where()
    r = requests.get(MET_URL, timeout=TIMEOUT, headers={'User-Agent': USER_AGENT},
                     params={'lat': lat, 'lon': lon})
    r.raise_for_status()
    highs, rain, symbols, humid = [], 0.0, [], []
    for step in r.json().get('properties', {}).get('timeseries', []):
        when = timezone.localtime(datetime.fromisoformat(step['time'].replace('Z', '+00:00')))
        if when.date() != day:
            continue
        data = step.get('data', {})
        details = data.get('instant', {}).get('details', {})
        if details.get('air_temperature') is not None:
            highs.append(float(details['air_temperature']))
        if details.get('relative_humidity') is not None:
            humid.append(float(details['relative_humidity']))
        hour = data.get('next_1_hours') or {}
        rain += float((hour.get('details') or {}).get('precipitation_amount') or 0)
        symbol = (hour.get('summary') or {}).get('symbol_code') or ''
        if symbol and 6 <= when.hour <= 18:
            symbols.append(symbol.split('_')[0])
    if not highs:
        return None
    codes = [MET_SYMBOLS[s] for s in symbols if s in MET_SYMBOLS]
    code = max(set(codes), key=codes.count) if codes else None
    return {'source': 'MET Norway', 'high': max(highs), 'rain_mm': round(rain, 1), 'code': code,
            'humidity': round(mean(humid)) if humid else None}


# ── The middle of them ───────────────────────────────────────────────────────

def _sky(code):
    """A family of weather, so 'mostly sunny' and 'clear' agree."""
    if code is None:
        return None
    if code in (0, 1):
        return 'sunny'
    if code == 2:
        return 'partly'
    if code == 3:
        return 'cloudy'
    if code in (45, 48):
        return 'hazy'
    if code in (95, 96, 99, 82):
        return 'storm'
    if code in WET:
        return 'rain'
    return None


SKY_CODE = {'sunny': 1, 'partly': 2, 'cloudy': 3, 'hazy': 45, 'rain': 61, 'storm': 95}


def blend(readings, chance=None, humidity=None):
    """Several forecasts as one: the keys tip() and the greeting use, plus how sure it is."""
    if not readings:
        return None
    highs = [r['high'] for r in readings]
    wet = sum(1 for r in readings if (r['rain_mm'] or 0) >= RAIN_MM or (r['code'] in WET))
    agreed = round(100 * wet / len(readings))
    rain_chance = round((agreed + chance) / 2) if chance is not None else agreed

    skies = [_sky(r['code']) for r in readings if _sky(r['code'])]
    dry = [s for s in skies if s not in ('rain', 'storm')]
    if rain_chance >= 50:
        sky = 'storm' if skies.count('storm') > skies.count('rain') else 'rain'
    elif dry:
        sky = max(set(dry), key=dry.count)
    else:
        sky = 'partly'
    code = SKY_CODE[sky]

    humid = [h for h in [humidity] + [r.get('humidity') for r in readings] if h is not None]
    spread = max(highs) - min(highs)
    return {
        'code': code,
        'words': WORDS.get(code, 'mixed'),
        'high': round(median(highs)),
        'rain_chance': rain_chance,
        'humidity': round(mean(humid)) if humid else 0,
        'sources': len(readings),
        'unsure': spread >= 3 or 35 <= agreed <= 65 and len(readings) >= 3,
        'readings': readings,
    }


def today(now=None):
    """
    {'words', 'high', 'rain_chance', 'humidity', 'code', 'sources', 'unsure'}
    for today, from every source that answered, or None when none did.
    Cached for a few hours.
    """
    now = now or timezone.now()
    day = timezone.localdate(now)
    key = f'weather:{place()}:{day:%Y-%m-%d}'
    cached = cache.get(key)
    if cached is not None:
        return cached or None
    readings, chance, humidity = [], None, None
    try:
        readings, chance, humidity = from_open_meteo(day)
    except Exception:
        logger.warning('Open-Meteo could not be reached for the brief', exc_info=True)
    try:
        met = from_met_norway(day)
        if met:
            readings.append(met)
    except Exception:
        logger.warning('MET Norway could not be reached for the brief', exc_info=True)
    result = blend(readings, chance, humidity)
    if not result:
        cache.set(key, {}, 20 * 60)        # don't hammer them; try again in a while
        return None
    cache.set(key, result, CACHE_SECONDS)
    return result


def tip(w, month):
    """What to wear or carry, in a line, from today's weather."""
    if w['code'] in WET or w['rain_chance'] >= 60:
        return 'An umbrella would be wise today.'
    if w['rain_chance'] >= 30:
        return 'Maybe keep an umbrella close, just in case.'
    if w['code'] in (45, 48) and month in HARMATTAN_MONTHS:
        return "That's the harmattan haze: keep water close and some lip balm handy."
    if w['high'] >= 31 or (w['high'] >= 29 and w['humidity'] >= 75):
        return 'Maybe wear something light that lets your body breathe.'
    if w['high'] <= 26:
        return "A little cooler than usual, so something light with sleeves won't hurt."
    return 'A comfortable day for whatever you like to wear.'


def morning_greeting(now=None, title='sir'):
    """
    'Good morning sir ☀️ It's 7:30am. Accra looks partly cloudy today, up to
    32°C. Maybe wear something light that lets your body breathe.
    Your brief is below 👇'. Without the weather when it can't be had.
    """
    from apps.communications.assistant.boss_tools import clock
    now = now or timezone.now()
    opening = f"Good morning {title} ☀️ It's {clock(now)}."
    w = today(now)
    if not w:
        return f'{opening}\nYour brief is below 👇'
    n = w['rain_chance']
    rain = f", with {'an' if str(n).startswith('8') or n in (11, 18) else 'a'} {n}% chance of rain" if n >= 30 else ''
    # The forecasts disagree: say so, rather than sound sure (25 Nov 2026).
    unsure = " The forecasts don't quite agree today, so take it as a guide." if w.get('unsure') else ''
    return (f"{opening} {place()} looks {w['words']} today, up to {w['high']}°C{rain}.{unsure} "
            f"{tip(w, timezone.localtime(now).month)}\n\nYour brief is below 👇")
