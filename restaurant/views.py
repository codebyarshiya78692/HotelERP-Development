
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from .models import DiningTable, MenuCategory, MenuItem
from orders.models import DiningSession, Order, OrderItem


# ============================================================
# HOME
# ============================================================

def home(request):
    return render(
        request,
        "restaurant/home.html",
    )


# ============================================================
# TABLE SELECTION
# ============================================================

def table_selection(request):
    tables = (
        DiningTable.objects
        .all()
        .order_by("table_number")
    )

    return render(
        request,
        "restaurant/table_selection.html",
        {
            "tables": tables,
        },
    )


# ============================================================
# START DINING SESSION
# ============================================================

@login_required
@transaction.atomic
def start_dining(request, table_id):
    """
    Start a dining session for the logged-in customer.

    Guests can SEE tables, but only logged-in customers
    can actually select a table.
    """

    table = get_object_or_404(
        DiningTable.objects.select_for_update(),
        id=table_id,
    )

    # Only available/completed tables can be selected.
    if table.status not in ["available", "completed"]:
        messages.error(
            request,
            f"Table {table.table_number} is currently unavailable.",
        )
        return redirect("table_selection")

    # If this customer already has an active session at
    # another table, don't silently create another one.
    existing_session = (
        DiningSession.objects
        .filter(
            customer_name=request.user.username,
            status="active",
        )
        .select_related("table")
        .first()
    )

    if existing_session:
        if existing_session.table_id == table.id:
            # Reuse the customer's own current session.
            request.session["dining_session_id"] = existing_session.id
            request.session["table_id"] = table.id
            request.session.setdefault("cart", {})
            request.session.modified = True

            return redirect(
                "menu_for_table",
                table_id=table.id,
            )

        messages.warning(
            request,
            (
                f"You already have an active dining session "
                f"at Table {existing_session.table.table_number}."
            ),
        )
        return redirect(
            "menu_for_table",
            table_id=existing_session.table.id,
        )

    # Create a session specifically for this customer.
    session = DiningSession.objects.create(
        table=table,
        customer_name=request.user.username,
        status="active",
    )

    table.status = "occupied"
    table.save(
        update_fields=["status"],
    )

    # Store the active dining session in the browser session.
    request.session["dining_session_id"] = session.id
    request.session["table_id"] = table.id
    request.session["cart"] = {}
    request.session.modified = True

    

    messages.success(
        request,
        f"Table {table.table_number} selected.",
    )

    return redirect(
        "menu_for_table",
        table_id=table.id,
    )


# ============================================================
# DIGITAL MENU
# ============================================================

def menu(request, table_id=None):
    """
    Public digital menu.

    Guests:
        - can browse the menu
        - cannot select a table
        - cannot add items to cart

    Logged-in customers:
        - can browse the menu
        - must have an active dining session before ordering
    """

    table = None
    dining_session = None

    # --------------------------------------------------------
    # TABLE INFORMATION
    # --------------------------------------------------------

    if table_id is not None:
        table = get_object_or_404(
            DiningTable,
            id=table_id,
        )

    # --------------------------------------------------------
    # CURRENT CUSTOMER SESSION
    # --------------------------------------------------------

    if request.user.is_authenticated:
        session_id = request.session.get(
            "dining_session_id"
        )

        saved_table_id = request.session.get(
            "table_id"
        )

        if session_id and saved_table_id:
            dining_session = (
                DiningSession.objects
                .filter(
                    id=session_id,
                    table_id=saved_table_id,
                    customer_name=request.user.username,
                    status="active",
                )
                .select_related("table")
                .first()
            )

            # If the saved session is valid and no table was
            # supplied in the URL, use the customer's table.
            if dining_session and table is None:
                table = dining_session.table

            # If the URL contains another table, don't pretend
            # the customer selected that table.
            if (
                dining_session
                and table is not None
                and table.id != dining_session.table_id
            ):
                dining_session = None

    # --------------------------------------------------------
    # MENU CATEGORIES
    # --------------------------------------------------------

    categories = (
        MenuCategory.objects
        .filter(
            items__is_available=True,
        )
        .prefetch_related("items")
        .distinct()
        .order_by("name")
    )

    # --------------------------------------------------------
    # MENU ITEMS
    # --------------------------------------------------------

    selected_category = request.GET.get(
        "category"
    )

    items = (
        MenuItem.objects
        .filter(
            is_available=True,
        )
        .select_related("category")
        .order_by("category__name", "name")
    )

    if selected_category:
        items = items.filter(
            category_id=selected_category
        )

    # --------------------------------------------------------
    # CART
    # --------------------------------------------------------

    if request.user.is_authenticated:
        cart = request.session.get(
            "cart",
            {}
        )
    else:
        cart = {}

    cart_count = 0

    for quantity in cart.values():
        try:
            cart_count += int(quantity)
        except (TypeError, ValueError):
            continue

    return render(
        request,
        "restaurant/menu.html",
        {
            "table": table,
            "session": dining_session,
            "categories": categories,
            "items": items,
            "selected_category": selected_category,
            "cart": cart,
            "cart_count": cart_count,
            "can_order": (
                request.user.is_authenticated
                and not request.user.is_staff
                and dining_session is not None
            ),
        },
    )


# ============================================================
# ADD ITEM TO CART
# ============================================================

@login_required
def add_to_cart(request, item_id):
    """
    Add a menu item to the current customer's cart.

    A customer must have an active dining session first.
    """

    if request.user.is_staff:
        return redirect("admin:index")

    if request.method != "POST":
        return redirect("menu")

    item = get_object_or_404(
        MenuItem,
        id=item_id,
        is_available=True,
    )

    session_id = request.session.get(
        "dining_session_id"
    )

    table_id = request.session.get(
        "table_id"
    )

    customer_session = None

    if session_id and table_id:
        customer_session = (
            DiningSession.objects
            .filter(
                id=session_id,
                table_id=table_id,
                customer_name=request.user.username,
                status="active",
            )
            .first()
        )

    # --------------------------------------------------------
    # NO ACTIVE TABLE
    # --------------------------------------------------------

    if customer_session is None:
        request.session.pop(
            "dining_session_id",
            None,
        )
        request.session.pop(
            "table_id",
            None,
        )

        messages.info(
            request,
            "Please select an available table before adding items.",
        )

        return redirect("table_selection")

    # --------------------------------------------------------
    # QUANTITY
    # --------------------------------------------------------

    try:
        quantity = int(
            request.POST.get(
                "quantity",
                1,
            )
        )
    except (TypeError, ValueError):
        quantity = 1

    quantity = max(
        1,
        min(quantity, 20),
    )

    # --------------------------------------------------------
    # CART
    # --------------------------------------------------------

    cart = request.session.get(
        "cart",
        {},
    )

    item_key = str(
        item.id
    )

    try:
        current_quantity = int(
            cart.get(
                item_key,
                0,
            )
        )
    except (TypeError, ValueError):
        current_quantity = 0

    new_quantity = min(
        current_quantity + quantity,
        20,
    )

    cart[item_key] = new_quantity

    request.session["cart"] = cart
    request.session.modified = True

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({
            "success": True,
            "message": f"{item.name} added to your cart.",
            "cart_count": sum(
                int(value)
                for value in cart.values()
            ),
            "quantity": cart[item_key],
        })


    messages.success(
        request,
        f"{item.name} added to your cart.",
    )

    return redirect(
        request.POST.get("next")
        or "cart"
    )


# ============================================================
# CART
# ============================================================

@login_required
def cart(request):
    """
    Display the current customer's cart.

    Invalid/stale dining sessions are cleared instead
    of causing a Django 404.
    """

    if request.user.is_staff:
        return redirect("admin:index")

    session_id = request.session.get(
        "dining_session_id"
    )

    table_id = request.session.get(
        "table_id"
    )

    if not session_id or not table_id:
        messages.info(
            request,
            "Please select a table before opening your cart.",
        )
        return redirect("table_selection")

    dining_session = (
        DiningSession.objects
        .filter(
            id=session_id,
            table_id=table_id,
            customer_name=request.user.username,
            status="active",
        )
        .select_related("table")
        .first()
    )

    # --------------------------------------------------------
    # STALE SESSION RECOVERY
    # --------------------------------------------------------

    if dining_session is None:
        request.session.pop(
            "dining_session_id",
            None,
        )
        request.session.pop(
            "table_id",
            None,
        )
        request.session["cart"] = {}
        request.session.modified = True

        messages.info(
            request,
            "Your previous dining session is no longer active. Please select a table.",
        )

        return redirect("table_selection")

    # --------------------------------------------------------
    # READ CART
    # --------------------------------------------------------

    cart_data = request.session.get(
        "cart",
        {},
    )

    item_ids = []

    for item_id in cart_data.keys():
        try:
            item_ids.append(
                int(item_id)
            )
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

    item_map = {
        str(item.id): item
        for item in menu_items
    }

    cart_items = []

    subtotal = Decimal("0.00")

    for item_id, quantity in cart_data.items():
        item = item_map.get(
            str(item_id)
        )

        if not item:
            continue

        try:
            quantity = int(quantity)
        except (TypeError, ValueError):
            continue

        quantity = max(
            1,
            min(quantity, 20),
        )

        item_total = (
            item.price * quantity
        )

        subtotal += item_total

        cart_items.append(
            {
                "item": item,
                "quantity": quantity,
                "total": item_total,
            }
        )

    return render(
        request,
        "restaurant/cart.html",
        {
            "session": dining_session,
            "table": dining_session.table,
            "cart_items": cart_items,
            "subtotal": subtotal,
        },
    )


# ============================================================
# UPDATE CART
# ============================================================

@login_required
def update_cart(request, item_id):
    if request.user.is_staff:
        return redirect("admin:index")

    if request.method != "POST":
        return redirect("cart")

    session_id = request.session.get(
        "dining_session_id"
    )

    table_id = request.session.get(
        "table_id"
    )

    valid_session = (
        session_id
        and table_id
        and DiningSession.objects.filter(
            id=session_id,
            table_id=table_id,
            customer_name=request.user.username,
            status="active",
        ).exists()
    )

    if not valid_session:
        messages.info(
            request,
            "Please select a table before updating your cart.",
        )
        return redirect("table_selection")

    cart = request.session.get(
        "cart",
        {}
    )

    item_key = str(
        item_id
    )

    if item_key not in cart:
        messages.warning(
            request,
            "That item is not in your cart.",
        )
        return redirect("cart")

    try:
        quantity = int(
            request.POST.get(
                "quantity",
                1,
            )
        )
    except (TypeError, ValueError):
        quantity = 1

    if quantity <= 0:
        cart.pop(
            item_key,
            None,
        )
    else:
        cart[item_key] = min(
            quantity,
            20,
        )

    request.session["cart"] = cart
    request.session.modified = True

    cart_count = sum(
        int(value)
        for value in cart.values()
    )

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({
            "success": True,
            "quantity": cart.get(item_key, 0),
            "cart_count": cart_count,
            "removed": item_key not in cart,
        })

    return redirect("cart")


# ============================================================
# PLACE ORDER
# ============================================================

@login_required
@transaction.atomic
def place_order(request):
    if request.user.is_staff:
        return redirect("admin:index")

    if request.method != "POST":
        return redirect("cart")

    session_id = request.session.get(
        "dining_session_id"
    )

    table_id = request.session.get(
        "table_id"
    )

    if not session_id or not table_id:
        messages.info(
            request,
            "Please select a table before placing your order.",
        )
        return redirect("table_selection")

    dining_session = (
        DiningSession.objects
        .select_for_update()
        .select_related("table")
        .filter(
            id=session_id,
            table_id=table_id,
            customer_name=request.user.username,
            status="active",
        )
        .first()
    )

    if dining_session is None:
        request.session.pop(
            "dining_session_id",
            None,
        )
        request.session.pop(
            "table_id",
            None,
        )
        request.session["cart"] = {}
        request.session.modified = True

        messages.info(
            request,
            "Your dining session is no longer active. Please select a table.",
        )

        return redirect("table_selection")

    cart_data = request.session.get(
        "cart",
        {}
    )

    if not cart_data:
        messages.error(
            request,
            "Your cart is empty.",
        )
        return redirect("cart")

    special_instructions = (
        request.POST
        .get(
            "special_instructions",
            "",
        )
        .strip()
    )

    item_ids = []

    for item_id in cart_data.keys():
        try:
            item_ids.append(
                int(item_id)
            )
        except (TypeError, ValueError):
            continue

    menu_items = (
        MenuItem.objects
        .filter(
            id__in=item_ids,
            is_available=True,
        )
    )

    item_map = {
        item.id: item
        for item in menu_items
    }

    valid_items = []

    for item_id, quantity in cart_data.items():
        try:
            numeric_item_id = int(item_id)
            quantity = int(quantity)
        except (TypeError, ValueError):
            continue

        menu_item = item_map.get(
            numeric_item_id
        )

        if not menu_item:
            continue

        quantity = max(
            1,
            min(quantity, 20),
        )

        valid_items.append(
            (
                menu_item,
                quantity,
            )
        )

    if not valid_items:
        messages.error(
            request,
            "None of the selected menu items are currently available.",
        )
        return redirect("cart")

    order = Order.objects.create(
        session=dining_session,
        status="new",
        special_instructions=special_instructions,
    )

    for menu_item, quantity in valid_items:
        OrderItem.objects.create(
            order=order,
            menu_item=menu_item,
            item_name=menu_item.name,
            unit_price=menu_item.price,
            quantity=quantity,
        )

    dining_session.table.status = "order_in_progress"

    dining_session.table.save(
        update_fields=["status"],
    )

    request.session["cart"] = {}
    request.session["last_order_id"] = order.id
    request.session.modified = True

    messages.success(
        request,
        f"Order #{order.id} has been placed successfully.",
    )

    return redirect(
        "order_confirmation",
        order_id=order.id,
    )


# ============================================================
# ORDER CONFIRMATION
# ============================================================

@login_required
def order_confirmation(request, order_id):
    if request.user.is_staff:
        return redirect("admin:index")

    session_id = request.session.get(
        "dining_session_id"
    )

    order = get_object_or_404(
        Order.objects
        .select_related("session__table")
        .prefetch_related("items"),
        id=order_id,
        session_id=session_id,
        session__customer_name=request.user.username,
    )

    return render(
        request,
        "restaurant/order_confirmation.html",
        {
            "order": order,
            "session": order.session,
        },
    )


# ============================================================
# ORDER TRACKING
# ============================================================

@login_required
def order_tracking(request, order_id):
    if request.user.is_staff:
        return redirect("admin:index")

    order = get_object_or_404(
        Order.objects
        .select_related("session__table")
        .prefetch_related("items"),
        id=order_id,
        session__customer_name=request.user.username,
    )

    status_steps = [
        (
            "new",
            "Order Received",
        ),
        (
            "accepted",
            "Accepted by Kitchen",
        ),
        (
            "preparing",
            "Preparing",
        ),
        (
            "ready",
            "Ready",
        ),
        (
            "served",
            "Served",
        ),
        (
            "completed",
            "Completed",
        ),
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
        current_index = status_order.index(
            order.status
        )
    else:
        current_index = 0

    return render(
        request,
        "restaurant/order_tracking.html",
        {
            "order": order,
            "status_steps": status_steps,
            "current_index": current_index,
        },
    )

