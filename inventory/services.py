from decimal import Decimal

from django.db import transaction

from .models import (
    Ingredient,
    MenuIngredient,
    StockMovement,
)


# ============================================================
# ORDER INVENTORY DEDUCTION
# ============================================================

@transaction.atomic
def deduct_inventory_for_order(order):
    """
    Deduct inventory for an order using the actual
    MenuIngredient recipe mappings.

    Inventory is deducted ONLY when the kitchen marks
    the order READY.

    Example:

        Chicken Biryani
            -> Chicken Breast
            -> 0.500 kg per dish

        Customer orders 2 Chicken Biryanis

            0.500 x 2
            = 1.000 kg

        Chicken Breast stock:

            15.000 kg
            - 1.000 kg
            = 14.000 kg

    The function:

        1. Reads every item in the order.
        2. Finds its MenuIngredient recipe rows.
        3. Multiplies recipe quantity by ordered quantity.
        4. Locks the ingredients.
        5. Checks stock before making changes.
        6. Deducts the required stock.
        7. Creates StockMovement records.
        8. Checks the existing reorder_level.
        9. Returns low-stock information.
       10. Prevents the same order from being deducted twice.

    No hard-coded food names or recipe quantities are used.
    """

    # ========================================================
    # PREVENT DUPLICATE INVENTORY DEDUCTION
    # ========================================================
    #
    # Each successful inventory deduction creates a usage
    # StockMovement with:
    #
    #     reference = "Order #<id>"
    #
    # If this order has already created a usage movement,
    # inventory has already been deducted for it.
    #
    # This protects against the same READY action being
    # processed twice.
    # ========================================================

    order_reference = f"Order #{order.id}"

    already_deducted = (
        StockMovement.objects
        .filter(
            movement_type="usage",
            reference=order_reference,
        )
        .exists()
    )

    if already_deducted:

        return {
            "success": True,
            "message": (
                f"Inventory for Order #{order.id} "
                "has already been deducted."
            ),
            "used": [],
            "low_stock": [],
        }

    required = {}

    # ========================================================
    # COLLECT INGREDIENT REQUIREMENTS
    # ========================================================

    order_items = (
        order.items
        .select_related("menu_item")
        .all()
    )

    for order_item in order_items:

        menu_item_id = order_item.menu_item_id

        order_quantity = Decimal(
            str(
                order_item.quantity
            )
        )

        recipe_rows = (
            MenuIngredient.objects
            .filter(
                menu_item_id=menu_item_id,
            )
            .select_related(
                "ingredient",
            )
        )

        for recipe_row in recipe_rows:

            ingredient = recipe_row.ingredient

            if not ingredient.is_active:
                continue

            recipe_quantity = Decimal(
                str(
                    recipe_row.quantity_required
                )
            )

            if recipe_quantity <= 0:
                continue

            required_quantity = (
                recipe_quantity
                * order_quantity
            )

            ingredient_id = ingredient.id

            if ingredient_id not in required:

                required[ingredient_id] = {
                    "ingredient": ingredient,
                    "quantity": Decimal("0.000"),
                }

            required[
                ingredient_id
            ]["quantity"] += required_quantity

    # ========================================================
    # NO RECIPE CONFIGURED
    # ========================================================

    if not required:

        return {
            "success": True,
            "message": (
                "No recipe-linked inventory items "
                "are configured for this order."
            ),
            "used": [],
            "low_stock": [],
        }

    # ========================================================
    # LOCK INGREDIENTS AND CHECK STOCK
    # ========================================================

    locked_ingredients = {}

    for ingredient_id, data in required.items():

        ingredient = (
            Ingredient.objects
            .select_for_update()
            .filter(
                id=ingredient_id,
                is_active=True,
            )
            .first()
        )

        if ingredient is None:
            continue

        required_quantity = data[
            "quantity"
        ]

        locked_ingredients[
            ingredient_id
        ] = ingredient

        # ----------------------------------------------------
        # DO NOT ALLOW NEGATIVE INVENTORY
        # ----------------------------------------------------

        if (
            ingredient.current_stock
            < required_quantity
        ):

            return {
                "success": False,
                "message": (
                    f"Not enough "
                    f"{ingredient.name}. "
                    f"Required: "
                    f"{required_quantity} "
                    f"{ingredient.unit}. "
                    f"Available: "
                    f"{ingredient.current_stock} "
                    f"{ingredient.unit}."
                ),
                "used": [],
                "low_stock": [],
            }

    # ========================================================
    # DEDUCT STOCK
    # ========================================================

    used = []

    low_stock = []

    for ingredient_id, data in required.items():

        ingredient = locked_ingredients.get(
            ingredient_id
        )

        if ingredient is None:
            continue

        required_quantity = data[
            "quantity"
        ]

        # ----------------------------------------------------
        # DEDUCT
        # ----------------------------------------------------

        ingredient.current_stock -= (
            required_quantity
        )

        ingredient.save(
            update_fields=[
                "current_stock",
                "updated_at",
            ]
        )

        # ----------------------------------------------------
        # RECORD STOCK MOVEMENT
        # ----------------------------------------------------

        StockMovement.objects.create(
            ingredient=ingredient,
            movement_type="usage",
            quantity=required_quantity,
            unit_cost=ingredient.cost_per_unit,
            reference=order_reference,
            notes=(
                "Automatic inventory deduction "
                "when Chef marked the order READY."
            ),
        )

        used.append(
            {
                "ingredient": ingredient.name,
                "quantity": required_quantity,
                "unit": ingredient.unit,
            }
        )

        # ----------------------------------------------------
        # LOW STOCK CHECK
        # ----------------------------------------------------
        #
        # The existing reorder_level is used.
        #
        # Example:
        #
        # Current stock = 5 kg
        # Reorder level = 5 kg
        #
        # 5 <= 5
        #
        # Therefore LOW STOCK.
        #
        # The alert remains active while stock is at or
        # below reorder_level.
        #
        # Once Admin adds stock:
        #
        # 5 + 10 = 15 kg
        #
        # 15 > 5
        #
        # Low-stock condition is gone.
        # ----------------------------------------------------

        if (
            ingredient.current_stock
            <= ingredient.reorder_level
        ):

            low_stock.append(
                {
                    "ingredient": ingredient.name,
                    "current_stock": (
                        ingredient.current_stock
                    ),
                    "reorder_level": (
                        ingredient.reorder_level
                    ),
                    "unit": ingredient.unit,
                }
            )

    # ========================================================
    # RESULT MESSAGE
    # ========================================================

    if low_stock:

        low_stock_names = ", ".join(
            item["ingredient"]
            for item in low_stock
        )

        message = (
            "Inventory updated successfully. "
            f"Low stock: {low_stock_names}."
        )

    else:

        message = (
            "Inventory updated successfully."
        )

    return {
        "success": True,
        "message": message,
        "used": used,
        "low_stock": low_stock,
    }