from rest_framework.throttling import SimpleRateThrottle


class LoginRateThrottle(SimpleRateThrottle):
    """
    Throttles login attempts by IP address, not by user — since a
    failed login has no authenticated user to key off of.
    Rate defined in settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['login'].
    """
    scope = 'login'

    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        return self.cache_format % {'scope': self.scope, 'ident': ident}


class PinVerifyRateThrottle(SimpleRateThrottle):
    """
    Throttles PIN verification attempts (download PIN, Notes PIN) by
    the authenticated user — a brute-force attempt against your own
    account's PIN should be slow, even though you're logged in.
    """
    scope = 'pin_verify'

    def get_cache_key(self, request, view):
        if request.user and request.user.is_authenticated:
            ident = request.user.pk
        else:
            ident = self.get_ident(request)
        return self.cache_format % {'scope': self.scope, 'ident': ident}