from apps.accounts.models import CustomUser
from rest_framework_simplejwt.tokens import RefreshToken
u = CustomUser.objects.get(email="kadjei@farhatprintingpress.com")
print(str(RefreshToken.for_user(u).access_token))
