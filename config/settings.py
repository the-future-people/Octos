from pathlib import Path
from datetime import timedelta
from celery.schedules import crontab


import os
from decouple import config as decouple_config
# Override decouple with actual OS env vars (for Docker)
class EnvConfig:
    def __call__(self, key, default=None, cast=None):
        val = os.environ.get(key)
        if val is not None:
            if cast:
                return cast(val)
            return val
        if cast is not None:
            return decouple_config(key, default=default, cast=cast)
        return decouple_config(key, default=default)
config = EnvConfig()

config = EnvConfig()

# Base directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Security
SECRET_KEY = config('SECRET_KEY')
DEBUG = config('DEBUG', cast=bool, default=True)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='127.0.0.1,localhost').split(',')

# Applications
DJANGO_APPS = [
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
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
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
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
        'apps.core.permissions.IsNotShadowUser',
    ],
}

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
}

# JWT Settings

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=8),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
}
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'


CELERY_BROKER_URL = 'redis://localhost:6379/0'
CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'
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
    'check-credit-due-daily': {
        'task': 'apps.finance.tasks.check_credit_due',
        'schedule': crontab(hour=7, minute=30),
    },
    'process-staff-activations-daily': {
        'task': 'apps.accounts.tasks.process_staff_activations',
        'schedule': crontab(hour=0, minute=1),  # 00:01 WAT daily
    },
}
