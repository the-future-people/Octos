"""
The morning's weather, for the owner's brief (20 Nov 2026).

Khofi wanted the 7:30 brief to open like a person would: "Good morning sir,
it's 7:30am, Accra looks partly cloudy and hot for most of the day, maybe
wear something that lets your body breathe. Your brief is below."

The forecast comes from Open-Meteo (free, no key), once a day, cached. If it
can't be reached, the greeting goes without the weather: the brief never
waits on it and never fails because of it.
"""
import logging

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

URL = 'https://api.open-meteo.com/v1/forecast'
TIMEOUT = 5
CACHE_SECONDS = 3 * 60 * 60

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


def place():
    return getattr(settings, 'OCTOS_WEATHER_PLACE', 'Accra')


def today(now=None):
    """
    {'words', 'high', 'rain_chance', 'humidity', 'code'} for today, or None
    when the forecast can't be had. Cached for a few hours.
    """
    now = now or timezone.now()
    key = f'weather:{place()}:{timezone.localdate(now):%Y-%m-%d}'
    cached = cache.get(key)
    if cached is not None:
        return cached or None
    try:
        import requests
        r = requests.get(URL, timeout=TIMEOUT, params={
            'latitude': getattr(settings, 'OCTOS_WEATHER_LAT', 5.6037),
            'longitude': getattr(settings, 'OCTOS_WEATHER_LON', -0.1870),
            'current': 'temperature_2m,relative_humidity_2m,weather_code',
            'daily': 'weather_code,temperature_2m_max,precipitation_probability_max',
            'timezone': 'Africa/Accra', 'forecast_days': 1,
        })
        r.raise_for_status()
        data = r.json()
        daily, current = data['daily'], data.get('current', {})
        code = int(daily['weather_code'][0])
        result = {
            'code': code,
            'words': WORDS.get(code, 'mixed'),
            'high': round(float(daily['temperature_2m_max'][0])),
            'rain_chance': int(daily.get('precipitation_probability_max', [0])[0] or 0),
            'humidity': int(current.get('relative_humidity_2m') or 0),
        }
    except Exception:
        logger.warning('The weather could not be fetched for the brief', exc_info=True)
        cache.set(key, {}, 20 * 60)        # don't hammer it; try again in a while
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
    rain = f", with a {w['rain_chance']}% chance of rain" if w['rain_chance'] >= 30 else ''
    return (f"{opening} {place()} looks {w['words']} today, up to {w['high']}°C{rain}. "
            f"{tip(w, timezone.localtime(now).month)}\n\nYour brief is below 👇")
