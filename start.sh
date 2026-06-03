#!/bin/bash
python manage.py migrate --noinput
daphne -b 0.0.0.0 -p 8000 config.asgi:application