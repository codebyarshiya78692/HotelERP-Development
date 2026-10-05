from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from restaurant.models import DiningTable, MenuItem

from .models import DiningSession, Order, OrderItem


def _cart_data(request):
    """
    Return the cart stored in the Django session.

    Cart format:

    {
        "1": 2,
        "5": 1,
        "9": 3,
    }

    where the key is the MenuItem ID and the value is quantity.
    """

    return request.session.get("cart", {})


def _save_cart(request, cart):
    """
    Save cart and explicitly mark the session as modified.
    """

    request.session["cart"] = cart
    request.session.modified = True


def _cart_items(request):
    """
    Convert session cart into database-backed menu items.
    """

    cart = _cart_data(request)

    if not cart:
        return []

    item_ids = []

    for item_id in cart.keys():
        try:
            item_ids.append(int(item_id))
        except (TypeError, ValueError):
            continue

    menu_items = (
        MenuItem.objects
        .filter(
            id__in=item_ids,
            is_available=True,
        )
        .select_related("category")
    )

    result = []

    for item in menu_items:
        quantity = int(cart.get(str(item.id), 0))

        if quantity <= 0:
            continue

        line_total = item.price * quantity

        result.append(
            {
                "item": item,
                "quantity": quantity,
                "line_total": line_total,
            }
        )

    return result


def _cart_total(cart_items):
    return sum(
        (entry["line_total"] for entry in cart_items),
        Decimal("0.00"),
    )


@login_required
def add_to_cart(request, item_id):
    """
    Add one MenuItem to the customer's cart.
    """

    if request.user.is_staff:
        return redirect("/admin/")

    if request.method != "POST":
        return redirect("restaurant:menu")

    item = get_object_or_404(
        MenuItem,
        id=item_id,
        is_available=True,
    )

    cart = _cart_data(request)

    current_quantity = int(
        cart.get(str(item.id), 0)
    )

    cart[str(item.id)] = current_quantity + 1

    _save_cart(request, cart)

    cart_count = sum(int(value) for value in cart.values())

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        from django.http import JsonResponse

        return JsonResponse({
            "success": True,
            "message": f"{item.name} was added to your cart.",
            "cart_count": cart_count,
            "quantity": cart[str(item.id)],
        })

    messages.success(
        request,
        f"{item.name} was added to your cart.",
    )

    return redirect(request.POST.get("next") or "restaurant:menu")


@login_required
def update_cart(request, item_id):
    """
    Update quantity of one cart item.
    """

    if request.user.is_staff:
        return redirect("/admin/")

    if request.method != "POST":
        return redirect("orders:cart")

    item = get_object_or_404(
        MenuItem,
        id=item_id,
    )

    cart = _cart_data(request)

    try:
        quantity = int(
            request.POST.get("quantity", 1)
        )
    except (TypeError, ValueError):
        quantity = 1

    if quantity <= 0:
        cart.pop(str(item.id), None)
    else:
        cart[str(item.id)] = quantity

    _save_cart(request, cart)

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        from django.http import JsonResponse

        cart_count = sum(int(value) for value in cart.values())
        return JsonResponse({
            "success": True,
            "quantity": cart.get(str(item.id), 0),
            "cart_count": cart_count,
            "removed": str(item.id) not in cart,
        })

    return redirect("orders:cart")


@login_required
def remove_from_cart(request, item_id):
    """
    Remove a cart item.
    """

    if request.user.is_staff:
        return redirect("/admin/")

    if request.method != "POST":
        return redirect("orders:cart")

    cart = _cart_data(request)

    cart.pop(str(item_id), None)

    _save_cart(request, cart)

    return redirect("orders:cart")


@login_required
def cart(request):
    """
    Display customer's current cart.
    """

    if request.user.is_staff:
        return redirect("/admin/")

    cart_items = _cart_items(request)

    available_tables = (
        DiningTable.objects
        .filter(status="available")
        .order_by("table_number")
    )

    return render(
        request,
        "orders/cart.html",
        {
            "cart_items": cart_items,
            "cart_total": _cart_total(cart_items),
            "available_tables": available_tables,
        },
    )


@login_required
@transaction.atomic
def place_order(request):
    """
    Create DiningSession + Order + OrderItems from the cart.
    """

    if request.user.is_staff:
        return redirect("/admin/")

    if request.method != "POST":
        return redirect("orders:cart")

    cart_items = _cart_items(request)

    if not cart_items:
        messages.error(
            request,
            "Your cart is empty.",
        )
        return redirect("restaurant:menu")

    table_id = request.POST.get("table_id")

    if not table_id:
        messages.error(
            request,
            "Please select a dining table.",
        )
        return redirect("orders:cart")

    table = get_object_or_404(
        DiningTable.objects.select_for_update(),
        id=table_id,
    )

    if table.status != "available":
        messages.error(
            request,
            "That table is no longer available. Please choose another table.",
        )
        return redirect("orders:cart")

    special_instructions = request.POST.get(
        "special_instructions",
        "",
    ).strip()

    # Create a dining session for this customer.
    dining_session = DiningSession.objects.create(
        table=table,
        customer_name=request.user.username,
        status="active",
    )

    # Create the actual order.
    order = Order.objects.create(
        session=dining_session,
        status="new",
        special_instructions=special_instructions,
    )

    # Create every order item.
    for entry in cart_items:
        item = entry["item"]
        quantity = entry["quantity"]

        OrderItem.objects.create(
            order=order,
            menu_item=item,
            item_name=item.name,
            unit_price=item.price,
            quantity=quantity,
        )

    # Mark the table as being used for an order.
    table.status = "order_in_progress"
    table.save(update_fields=["status"])

    # Empty customer's cart.
    request.session["cart"] = {}
    request.session.modified = True

    messages.success(
        request,
        f"Order #{order.id} has been placed successfully.",
    )

    return redirect(
        "orders:order_detail",
        order_id=order.id,
    )


@login_required
def my_orders(request):
    """
    Display all orders belonging to the logged-in customer.
    """

    if request.user.is_staff:
        return redirect("/admin/")

    orders = (
        Order.objects
        .filter(
            session__customer_name=request.user.username,
        )
        .select_related(
            "session",
            "session__table",
        )
        .prefetch_related("items")
        .order_by("-created_at")
    )

    return render(
        request,
        "orders/my_orders.html",
        {
            "orders": orders,
        },
    )


@login_required
def order_detail(request, order_id):
    """
    Display a customer's individual order and status.
    """

    if request.user.is_staff:
        return redirect("/admin/")

    order = get_object_or_404(
        Order.objects
        .select_related(
            "session",
            "session__table",
        )
        .prefetch_related("items"),
        id=order_id,
        session__customer_name=request.user.username,
    )

    status_steps = [
        ("new", "Order Placed"),
        ("accepted", "Confirmed"),
        ("preparing", "Preparing"),
        ("ready", "Ready"),
        ("served", "Served"),
        ("completed", "Completed"),
    ]

    status_order = [
        "new",
        "accepted",
        "preparing",
        "ready",
        "served",
        "completed",
    ]

    if order.status in status_order:
        current_index = status_order.index(order.status)
    else:
        current_index = -1

    steps = []

    for index, (code, label) in enumerate(status_steps):
        if order.status == "cancelled":
            state = "cancelled"
        elif index < current_index:
            state = "complete"
        elif index == current_index:
            state = "current"
        else:
            state = "pending"

        steps.append(
            {
                "code": code,
                "label": label,
                "state": state,
            }
        )

    return render(
        request,
        "orders/order_detail.html",
        {
            "order": order,
            "steps": steps,
        },
    )