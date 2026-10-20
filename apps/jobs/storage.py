"""
Where catalogue photos live: a public R2 bucket.

Service photos are brand material, meant to be seen by anyone: the staff
portal, the website, the app. So they are kept apart from customers'
artwork, which stays in the private bucket behind a view that checks
who is asking. Here, every photo has a plain public address that any
browser can load without logging in.

Set by R2_PUBLIC_BUCKET and R2_PUBLIC_URL (the bucket's r2.dev address,
or a custom domain later). Without them, as in tests and local work,
photos fall back to the ordinary storage.
"""

from urllib.parse import urlparse

from decouple import config
from django.core.files.storage import default_storage


def catalogue_storage():
    bucket = config('R2_PUBLIC_BUCKET', default='')
    public_url = config('R2_PUBLIC_URL', default='')
    if not (bucket and public_url):
        return default_storage

    from storages.backends.s3 import S3Storage
    return S3Storage(
        bucket_name=bucket,
        endpoint_url=config('R2_ENDPOINT_URL'),
        access_key=config('R2_ACCESS_KEY_ID'),
        secret_key=config('R2_SECRET_ACCESS_KEY'),
        region_name='auto',
        location='services',
        # Public addresses: no signatures that expire, no login.
        custom_domain=urlparse(public_url).netloc,
        url_protocol='https:',
        querystring_auth=False,
        default_acl=None,
        file_overwrite=False,
    )