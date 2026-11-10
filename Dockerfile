FROM python:3.13-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Customers' Word files become PDFs (7 Nov 2026): LibreOffice Writer with no
# screen, and fonts metric-compatible with Calibri, Cambria, Times and Arial,
# so pages break where Word breaks them and the page count stays true.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer-nogui \
    fonts-crosextra-carlito \
    fonts-crosextra-caladea \
    fonts-liberation \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

EXPOSE 8000
# collectstatic at start-up (not build): Railway's variables are only certain to exist at runtime.
# Without it staticfiles/ is empty and WhiteNoise serves nothing — the template portals load unstyled.
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py collectstatic --noinput && daphne -b 0.0.0.0 -p ${PORT:-8000} config.asgi:application"]