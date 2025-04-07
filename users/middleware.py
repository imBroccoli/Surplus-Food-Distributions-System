class UserIPMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if request.user.is_authenticated:
            ip = self.get_client_ip(request)
            if hasattr(request.user, "admin_profile"):
                request.user.admin_profile.last_login_ip = ip
                request.user.admin_profile.save(update_fields=["last_login_ip"])

        return response

    def get_client_ip(self, request):
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            ip = x_forwarded_for.split(",")[0]
        else:
            ip = request.META.get("REMOTE_ADDR")
        return ip
