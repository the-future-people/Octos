from rest_framework.permissions import BasePermission


class IsBusinessOwner(BasePermission):
    """The Eye is the owner's alone."""
    message = 'Only the business owner can open the Eye.'

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and getattr(user, 'is_business_owner', False))
