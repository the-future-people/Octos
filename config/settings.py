from pathlib import Path
from datetime import timedelta
from celery.schedules import crontab


import os
import os as _os
from decouple import config as decouple_config
# Override decouple with actual OS env vars (for Docker)
class EnvConfig:
    def __call__(self, key, default=None, cast=None):
        val = os.environ.get(key)
        if val is not None:
            if cast is bool:
                return val.strip().lower() in ('true', '1', 'yes', 'on')
            if cast:
                return cast(val)
            return val
        if cast is not None:
            return decouple_config(key, default=default, cast=cast)
        return decouple_config(key, default=default)


config = EnvConfig()

# Base directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Security
SECRET_KEY = config('SECRET_KEY')
DEBUG = config('DEBUG', cast=bool, default=False)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='127.0.0.1,localhost').split(',')

# Trust Railway's TLS termination — requests arrive as plain HTTP
# internally with this header set, so Django must be told to trust it
# in order for request.is_secure() and secure-cookie logic to work.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Applications
DJANGO_APPS = [
    'daphne',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

THIRD_PARTY_APPS = [
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'channels',
]

LOCAL_APPS = [
    'apps.core',
    'apps.organization',
    'apps.production',
    'apps.accounts',
    'apps.jobs',
    'apps.customers',
    'apps.communications',
    'apps.hr',
    'apps.finance',
    'apps.inventory',
    'apps.procurement',
    'apps.notifications',
    'apps.analytics',
    'apps.personal_notes',
    'apps.eye',
    'apps.spine',
    # The public-facing side. Imports from jobs, customers and finance;
    # nothing imports back, so the storefront stays separable from the
    # staff platform it sits in front of.
    'apps.storefront',
    'apps.partners',
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'apps.core.middleware.ShadowUserMiddleware',
]

ROOT_URLCONF = 'config.urls'
X_FRAME_OPTIONS = 'SAMEORIGIN'
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Database
_DATABASE_URL = os.environ.get('DATABASE_URL')
if _DATABASE_URL:
    import dj_database_url as _dj_db
    DATABASES = {'default': _dj_db.parse(_DATABASE_URL, conn_max_age=600)}
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': config('DB_NAME'),
            'USER': config('DB_USER'),
            'PASSWORD': config('DB_PASSWORD'),
            'HOST': config('DB_HOST', default='localhost'),
            'PORT': config('DB_PORT', default='5432'),
        }
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Accra'
USE_I18N = True
USE_TZ = True

# Static & Media
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static'] if (BASE_DIR / 'static').exists() else []
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.StaticFilesStorage'
# ── Media storage ────────────────────────────────────────────────
#
# Customer artwork. Two things drive this design:
#
# It must survive a deploy. MEDIA_ROOT defaulted to BASE_DIR / 'media',
# inside the code directory, so every deploy replaced it — files uploaded
# in the morning were gone by evening. It now points at a mounted volume in
# production, set by MEDIA_ROOT_PATH.
#
# It must not be publicly readable. A customer's artwork at a guessable URL
# is a real exposure, so nothing is served directly: every file goes
# through a view that checks who is asking. That is why MEDIA_URL points at
# an app route rather than a static path, and why it does not change when
# the backend moves to object storage.
MEDIA_URL = '/api/v1/jobs/files/'
MEDIA_ROOT = Path(config('MEDIA_ROOT_PATH', default=str(BASE_DIR / 'media')))

# Where uploaded files actually live.
#
# A Railway volume mounts to one service, and conversion runs in the
# worker — so artwork written by the web container was invisible to
# the process that needed to copy it onto a job. Every online order
# reached the floor without its file, and the only sign was a line in
# a log nobody was reading.
#
# Object storage has no such edge: every service sees the same bucket,
# and nothing is lost when a container is replaced.
#
# Local development keeps the filesystem, so a laptop needs no bucket
# and no keys. The switch is the presence of R2_BUCKET_NAME.
R2_BUCKET_NAME = config('R2_BUCKET_NAME', default='')

if R2_BUCKET_NAME:
    _media_storage = {
        'BACKEND': 'storages.backends.s3.S3Storage',
        'OPTIONS': {
            'bucket_name': R2_BUCKET_NAME,
            'endpoint_url': config('R2_ENDPOINT_URL'),
            'access_key': config('R2_ACCESS_KEY_ID'),
            'secret_key': config('R2_SECRET_ACCESS_KEY'),
            # R2 has one region and rejects the usual names.
            'region_name': 'auto',
            # Nothing is served straight from the bucket. Customer
            # artwork at a guessable URL is a real exposure, so every
            # file still goes through the view that checks who is
            # asking.
            'default_acl': None,
            'querystring_auth': False,
            'file_overwrite': False,
        },
    }
else:
    _media_storage = {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    }

STORAGES = {
    'default': _media_storage,
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.StaticFilesStorage',
    },
}

# Default primary key
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Custom user model
AUTH_USER_MODEL = 'accounts.CustomUser'
STOREFRONT_HOST = os.environ.get('STOREFRONT_HOST', 'print-octos.vercel.app')
# REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
        'apps.core.permissions.IsNotShadowUser',
    ),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_THROTTLE_CLASSES': (
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ),
    'DEFAULT_THROTTLE_RATES': {
        'anon': '20/min',
        'user': '120/min',
        'login': '5/min',
        'pin_verify': '5/min',
        # A customer specifying a banner reprices on every change —
        # width, height, quantity, each a request. Twenty a minute is
        # right for an API with no public face and would lock a real
        # customer out halfway through their own order.
        'storefront': '90/min',
        # Guessing a code is the one thing worth slowing down.
        'storefront_code': '6/min',
        # Harder than the rest of the storefront. Order numbers run in
        # sequence and a phone number is guessable, so this is the one
        # door where patience could pay off.
        'storefront_find': '10/hour',
    },
}

# JWT Settings

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=8),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
}
PAYSTACK_SECRET_KEY = os.environ.get('PAYSTACK_SECRET_KEY', 'test-secret')
PAYSTACK_PUBLIC_KEY = os.environ.get('PAYSTACK_PUBLIC_KEY', '')

# mNotify, for the texts a customer actually reads: their code, their
# receipt, and the one that says it is ready. Empty by default, and the
# sender logs instead of sending — so a developer machine never texts a
# real customer by accident.
MNOTIFY_API_KEY = os.environ.get('MNOTIFY_API_KEY', '')
MNOTIFY_SENDER_ID = os.environ.get('MNOTIFY_SENDER_ID', 'Farhat')

# WhatsApp Cloud API, for Farhat's one central number. Empty defaults on
# purpose: the webhook refuses every request while the app secret or the
# verify token is missing, rather than accepting messages it cannot check.
# (A default that means "do nothing" hid mNotify for weeks; one that means
# "accept anything" would be worse.)
WHATSAPP_ACCESS_TOKEN        = os.environ.get('WHATSAPP_ACCESS_TOKEN', '')
WHATSAPP_PHONE_NUMBER_ID     = os.environ.get('WHATSAPP_PHONE_NUMBER_ID', '')
WHATSAPP_BUSINESS_ACCOUNT_ID = os.environ.get('WHATSAPP_BUSINESS_ACCOUNT_ID', '')
WHATSAPP_APP_SECRET          = os.environ.get('WHATSAPP_APP_SECRET', '')
WHATSAPP_VERIFY_TOKEN        = os.environ.get('WHATSAPP_VERIFY_TOKEN', '')
# The owner's private WhatsApp line (18 Nov 2026): reports and urgent matters go
# to this number, and its messages are handled apart from customers'. Set on
# Railway, never in the code (the repository is public). Empty: no line.
OCTOS_OWNER_PHONE            = os.environ.get('OCTOS_OWNER_PHONE', '')

# Farhat Trade Partners (23 Nov 2026). Sign-ups stay closed until the machines
# have run 90 days: until PARTNER_SIGNUPS_OPEN is 'on', only a shop with one of
# the invite codes (comma-separated, set on Railway) can apply.
PARTNER_SIGNUPS_OPEN         = os.environ.get('PARTNER_SIGNUPS_OPEN', 'off').lower() == 'on'
# Where the partner portal lives: its own app on Farhat's domain.
PARTNERS_HOST                = os.environ.get('PARTNERS_HOST', 'partners.farhatprintingpress.com')
PARTNER_INVITE_CODES         = [c.strip().upper() for c in os.environ.get('PARTNER_INVITE_CODES', '').split(',') if c.strip()]

# Octos's assistant. Mode is the kill switch: 'off' (silent, the default),
# 'shadow' (writes its reply as an internal note, sends nothing) or 'live'.
# An unknown mode is treated as off. The model is a setting so the exams can
# compare models before one is switched on.
ANTHROPIC_API_KEY      = os.environ.get('ANTHROPIC_API_KEY', '')
OCTOS_ASSISTANT_MODE   = os.environ.get('OCTOS_ASSISTANT_MODE', 'off')
OCTOS_ASSISTANT_MODEL  = os.environ.get('OCTOS_ASSISTANT_MODEL', 'claude-sonnet-5-5')
# The owner's line talking back (19 Nov 2026): 'off' returns it to its
# shortcuts and menu. Its model defaults to the assistant's.
OCTOS_OWNER_BRAIN      = os.environ.get('OCTOS_OWNER_BRAIN', 'on')
# The weather in the morning brief (20 Nov 2026): Open-Meteo, no key needed.
OCTOS_WEATHER_PLACE    = os.environ.get('OCTOS_WEATHER_PLACE', 'Accra')
OCTOS_WEATHER_LAT      = float(os.environ.get('OCTOS_WEATHER_LAT', '5.6037'))
OCTOS_WEATHER_LON      = float(os.environ.get('OCTOS_WEATHER_LON', '-0.1870'))
OCTOS_OWNER_MODEL      = os.environ.get('OCTOS_OWNER_MODEL', '')
ASGI_APPLICATION = 'config.asgi.application'

_REDIS_URL = os.environ.get('REDIS_URL', 'redis://redis:6379/0')
CACHES = {
    'default': {
        'BACKEND'  : 'django.core.cache.backends.redis.RedisCache',
        'LOCATION' : _REDIS_URL,
        'TIMEOUT'  : 300,
        'KEY_PREFIX': 'octos',
        'OPTIONS'  : {
            'db': '1',
        },
    }
}
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            'hosts': [_REDIS_URL],
            'capacity': 1500,
            'expiry': 10,
        },
    },
}
CELERY_BROKER_URL = _os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = _os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')

# Railway's Redis drops idle connections. On 15 Oct 2026 the worker lost
# its connection at 02:48 and sat alive but deaf for six hours: no task
# ran, a paid order never became a job, and the hourly sweep that should
# have caught it never fired either. Railway saw nothing wrong because
# nothing crashed.
#
# These make a dropped connection get noticed and rebuilt: a health check
# on the connection every 25 seconds, TCP keepalive so the socket is not
# silently dropped, timeouts so a dead read fails instead of hanging, and
# reconnection that never gives up.
CELERY_BROKER_CONNECTION_RETRY = True
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_CONNECTION_MAX_RETRIES = None
CELERY_BROKER_TRANSPORT_OPTIONS = {
    'health_check_interval': 25,
    'socket_keepalive':      True,
    'socket_timeout':        30,
    'socket_connect_timeout': 30,
    'retry_on_timeout':      True,
}
CELERY_RESULT_BACKEND_TRANSPORT_OPTIONS = {
    'health_check_interval': 25,
    'socket_keepalive':      True,
    'retry_on_timeout':      True,
}
CELERY_REDIS_BACKEND_HEALTH_CHECK_INTERVAL = 25
# A task cut off by a lost connection is put back for another worker
# rather than left half-done.
CELERY_WORKER_CANCEL_LONG_RUNNING_TASKS_ON_CONNECTION_LOSS = True
CELERY_BEAT_SCHEDULE = {
    # The owner's line: morning brief and day close to his phone (18 Nov 2026).
    # The owner's "check back in a bit" and "remind me on Saturday" (19 Nov 2026).
    'owner-reminders': {
        'task': 'apps.communications.tasks.owner_reminders',
        'schedule': crontab(minute='*'),
    },
    'owner-brief': {
        'task': 'apps.communications.tasks.owner_brief',
        'schedule': crontab(hour=7, minute=30),
    },
    'owner-close': {
        'task': 'apps.communications.tasks.owner_close',
        'schedule': crontab(hour=21, minute=0),
    },
    # Pickup reminders and design-feedback nudges, mornings, shop days (13 Nov 2026).
    'customer-reminders': {
        'task': 'apps.jobs.tasks.send_customer_reminders',
        'schedule': crontab(hour=9, minute=0, day_of_week='mon-sat'),
    },
    # Front-desk work nobody has taken in 10 minutes: tell the BM (14 Nov 2026).
    'escalate-front-desk': {
        'task': 'apps.jobs.tasks.escalate_front_desk',
        'schedule': crontab(minute='*'),
    },
    # A break past 30 minutes tells the Branch Manager (16 Nov 2026).
    'alert-long-breaks': {
        'task': 'apps.analytics.tasks.alert_long_breaks',
        'schedule': crontab(minute='*/5'),
    },
    'open-sheets-5am': {
        'task': 'apps.finance.tasks.open_sheets',
        'schedule': crontab(hour=5, minute=0),
    },
        'check-promises-every-5min': {
        'task': 'apps.jobs.tasks.check_promises',
        'schedule': crontab(minute='*/5'),
    },
    
    'close-sheets-every-15min': {
        'task': 'apps.finance.tasks.close_sheets',
        'schedule': crontab(minute='*/15'),
    },
    'warn-sheets-every-5min': {
        'task': 'apps.finance.tasks.warn_sheets',
        'schedule': crontab(minute='*/5'),
    },
    # Attendants who miss their sign-off deadline are signed off by Octos
    # and the branch manager is told (13 Nov 2026).
    'attendant-signoff-every-5min': {
        'task': 'apps.finance.tasks.attendant_signoff',
        'schedule': crontab(minute='*/5'),
    },
    'suspend-overdue-daily': {
        'task': 'apps.finance.tasks.suspend_overdue',
        'schedule': crontab(hour=6, minute=0),
    },
    'expire-drafts-nightly': {
        'task': 'apps.jobs.tasks.expire_drafts',
        'schedule': crontab(hour=2, minute=0),
    },
    'expire-proformas-nightly': {
        'task': 'apps.jobs.tasks.expire_proformas',
        'schedule': crontab(hour=2, minute=15),
    },
    # End-of-day thank-you, from half an hour before each branch closes; late
    # customers three hours after they were served (14 and 24 Nov 2026).
    'thanks-before-closing': {
        'task': 'apps.storefront.tasks.send_thanks',
        'schedule': crontab(minute='*/5'),
    },
    # Customer files older than 14 days, unless kept (25 Nov 2026).
    'clean-customer-files': {
        'task': 'apps.communications.tasks.clean_customer_files',
        'schedule': crontab(hour=2, minute=41),
    },
    # Pays at the counter: the shelf at closing, cancelled a week on (24 Nov 2026).
    'tidy-counter-orders': {
        'task': 'apps.jobs.tasks.tidy_counter_orders',
        'schedule': crontab(minute='7,22,37,52'),
    },
    # One reminder for unpaid orders Octos took on WhatsApp (14 Nov 2026).
    'payment-reminders': {
        'task': 'apps.storefront.tasks.send_payment_reminders',
        'schedule': crontab(minute='*/10'),
    },
    'sweep-storefront-nightly': {
        'task': 'apps.storefront.tasks.sweep_storefront',
        'schedule': crontab(hour=2, minute=30),
    },
    # Trade partners: an application left unanswered after "Ask for more" closes at 14 days.
    'partners-close-stale': {
        'task': 'apps.partners.tasks.close_stale',
        'schedule': crontab(hour=6, minute=17),
    },
    'observe-station-timings-nightly': {
        'task': 'apps.production.tasks.observe_station_timings',
        'schedule': crontab(hour=3, minute=0),
    },
    'remind-open-proformas-daily': {
        'task': 'apps.jobs.tasks.remind_open_proformas',
        'schedule': crontab(hour=8, minute=30),
    },
    'check-credit-due-daily': {
        'task': 'apps.finance.tasks.check_credit_due',
        'schedule': crontab(hour=7, minute=30),
    },
        'recovery-float-check-daily': {
        'task': 'apps.finance.tasks.recovery_float_check',
        'schedule': crontab(hour=16, minute=0),
    },
    # Saturday at 8pm, after the branch has closed and the cashier has
    # signed off. Only ever prepares — submitting is the manager's.
    'prepare-weekly-filings-saturday': {
        'task': 'apps.finance.tasks.prepare_weekly_filings',
        'schedule': crontab(hour=20, minute=0, day_of_week=6),
    },
    'refresh-weather-cache': {
        'task': 'apps.analytics.tasks.weather.refresh_weather_cache',
        'schedule': crontab(minute='*/15'),
    },
    'process-staff-activations-daily': {
        'task': 'apps.accounts.tasks.process_staff_activations',
        'schedule': crontab(hour=0, minute=1),  # 00:01 WAT daily
    },
    'generate-shift-reminders-every-minute': {
        'task': 'apps.notifications.tasks.generate_shift_reminders',
        'schedule': crontab(minute='*'),
    },
    'generate-checkpoint-reminders-every-minute': {
        'task': 'apps.notifications.tasks.generate_checkpoint_reminders',
        'schedule': crontab(minute='*'),
    },
    'expire-wallet-credits-daily': {
        'task': 'apps.finance.tasks.expire_wallet_credits',
        'schedule': crontab(hour=1, minute=0),  # 01:00 WAT daily
    },
        'convert-stragglers-hourly': {
        'task': 'apps.storefront.tasks.convert_stragglers',
        'schedule': crontab(minute=20),
    },
    # Who answers WhatsApp: a customer waiting 30 minutes on a person gets
    # that person reminded; 10 minutes after an ignored reminder, Octos
    # takes the conversation back (communications/services/handover.py).
    'watch-handovers-every-minute': {
        'task': 'apps.communications.tasks.watch_handovers',
        'schedule': crontab(),
    },
    # A customer who sent a file from outside the shop and went quiet, with
    # no job made, goes to "Needs you" (communications/services/quiet_remote.py).
    'flag-quiet-remote-chats': {
        'task': 'apps.communications.tasks.flag_quiet_remote',
        'schedule': crontab(minute='*/5'),
    },
    # Visits quiet for over 2 hours are closed as NO_ACTION or ABANDONED,
    # backdated to when they went quiet (apps/spine/visits.py).
    'close-quiet-visits': {
        'task': 'apps.spine.tasks.close_quiet_visits',
        'schedule': crontab(minute='*/10'),
    },
}

# CORS
CORS_ALLOWED_ORIGINS = [
    # The staff portal
    'http://localhost:5173',
    'http://127.0.0.1:5173',
    'https://octos-web.vercel.app',
    'https://octos-production.up.railway.app',
    # Print Octos, the customer-facing storefront. Its own app on its
    # own port, so a change to one cannot break the other.
    'http://localhost:5180',
    'http://127.0.0.1:5180',
    'https://print-octos.vercel.app',
    # The public website (farhat-web): careers page reads vacancies and posts
    # applications. Local dev runs on 5174 because the staff portal holds 5173.
    # The real domain is listed ahead of the cutover so careers keeps working then.
    'http://localhost:5174',
    'http://127.0.0.1:5174',
    'https://farhat-web.vercel.app',
    'https://farhatprintingpress.com',
    'https://www.farhatprintingpress.com',
    # The trade-partner portal (24 Nov 2026): its own app on its own
    # subdomain. Local dev runs on 5185.
    'http://localhost:5185',
    'http://127.0.0.1:5185',
    'https://farhat-partners.vercel.app',
    'https://partners.farhatprintingpress.com',
    # The Print Octos app. Its pages are served from inside the phone,
    # under these addresses: Android's, then iPhone's.
    'https://localhost',
    'capacitor://localhost',
]

# Files and sending have their own fast lane (9 Nov 2026): fetching a customer's
# file and sending a message never wait behind Octos's replies or scheduled jobs.
# The worker runs 8 at once and listens to both: -Q celery,fast.
CELERY_TASK_ROUTES = {
    'apps.communications.tasks.fetch_whatsapp_media': {'queue': 'fast'},
    'apps.communications.tasks.fetch_shared_link': {'queue': 'fast'},
    'apps.communications.tasks.deliver_whatsapp': {'queue': 'fast'},
}
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

# The counter QR's own secret (11 Nov 2026): separate from SECRET_KEY so rotating
# that never invalidates printed QRs. Changing this means reprinting every QR.
COUNTER_QR_SECRET = os.environ.get('COUNTER_QR_SECRET', '')


# Customer files are deleted 14 days after they arrive, unless kept
# (communications/services/customer_files.py, 25 Nov 2026). Nothing is
# deleted before this date, so older files can be marked Keep first.
FILE_CLEANUP_STARTS = os.environ.get('FILE_CLEANUP_STARTS', '2026-11-28')
