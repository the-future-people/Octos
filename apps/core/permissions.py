from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsNotShadowUser(BasePermission):
    """
    Blocks write operations for users with employment_status=SHADOW.
    Shadow users may only perform safe (read-only) requests.
    """
    message = 'Your account has read-only shadow access until your start date.'

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        if not user or not user.is_authenticated:
            return True  # let auth handle this
        status = getattr(user, 'employment_status', None)
        return status != 'SHADOW'