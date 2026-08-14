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
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Custom user model
AUTH_USER_MODEL = 'accounts.CustomUser'

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
    },
}

# JWT Settings

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=8),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
}

# â”€â”€ ASGI & WebSocket â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
CELERY_BEAT_SCHEDULE = {
    'open-sheets-5am': {
        'task': 'apps.finance.tasks.open_sheets',
        'schedule': crontab(hour=5, minute=0),
    },
    'close-sheets-every-15min': {
        'task': 'apps.finance.tasks.close_sheets',
        'schedule': crontab(minute='*/15'),
    },
    'warn-sheets-every-5min': {
        'task': 'apps.finance.tasks.warn_sheets',
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
    'expire-quotes-nightly': {
        'task': 'apps.jobs.tasks.expire_quotes',
        'schedule': crontab(hour=2, minute=15),
    },
    'remind-open-quotes-daily': {
        'task': 'apps.jobs.tasks.remind_open_quotes',
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
}

# CORS
CORS_ALLOWED_ORIGINS = [
    'http://localhost:5173',
    'http://127.0.0.1:5173',
    'https://octos-web.vercel.app',
    'https://octos-production.up.railway.app',
]
