from django.contrib import messages
from django.db import models

from .models import Ingredient


class LowStockLoginAlertMiddleware:
    """
    Shows a low-stock alert whenever a staff/admin user
    successfully logs into the Django admin.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Only check the Django admin login submission.
        if (
            request.path == "/admin/login/"
            and request.method == "POST"
            and response.status_code in (301, 302)
            and getattr(request.user, "is_authenticated", False)
            and request.user.is_staff
        ):
            low_stock = Ingredient.objects.filter(
                is_active=True,
                current_stock__lte=models.F("reorder_level"),
            )

            if low_stock.exists():
                ingredients = list(low_stock)

                if len(ingredients) == 1:
                    ingredient = ingredients[0]

                    messages.warning(
                        request,
                        (
                            f"⚠ LOW STOCK ALERT: {ingredient.name} is at "
                            f"{ingredient.current_stock} {ingredient.unit}. "
                            f"Reorder level: "
                            f"{ingredient.reorder_level} {ingredient.unit}. "
                            f"Please restock this ingredient."
                        ),
                    )
                else:
                    names = ", ".join(
                        ingredient.name for ingredient in ingredients
                    )

                    messages.warning(
                        request,
                        (
                            f"⚠ LOW STOCK ALERT: {len(ingredients)} "
                            f"ingredients need attention: {names}. "
                            f"Please restock them."
                        ),
                    )

        return response