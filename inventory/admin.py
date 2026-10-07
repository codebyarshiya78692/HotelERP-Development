from django.contrib import admin

from .models import Ingredient, MenuIngredient, StockMovement


@admin.register(Ingredient)
class IngredientAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "unit",
        "current_stock",
        "reorder_level",
        "stock_status",
        "is_active",
    )

    list_filter = (
        "unit",
        "is_active",
    )

    search_fields = (
        "name",
    )

    ordering = (
        "name",
    )

    @admin.display(
        description="Stock Status",
        boolean=False,
    )
    def stock_status(self, obj):
        if obj.is_low_stock:
            return "⚠ LOW STOCK"

        return "Healthy"


@admin.register(MenuIngredient)
class MenuIngredientAdmin(admin.ModelAdmin):
    list_display = (
        "menu_item_id",
        "ingredient",
        "quantity_required",
    )

    list_filter = (
        "ingredient",
    )

    search_fields = (
        "ingredient__name",
    )

    ordering = (
        "menu_item_id",
        "ingredient__name",
    )


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = (
        "ingredient",
        "movement_type",
        "quantity",
        "created_at",
    )

    list_filter = (
        "movement_type",
        "created_at",
    )

    search_fields = (
        "ingredient__name",
        "notes",
    )

    ordering = (
        "-created_at",
    )