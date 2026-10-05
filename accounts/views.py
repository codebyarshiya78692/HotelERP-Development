from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.urls import reverse
from django.utils import timezone


from orders.models import (
    DiningSession,
    Order,
    ServiceRequest,
)

from restaurant.models import (
    DiningTable,
    MenuCategory,
    MenuItem,
)


# ============================================================
# ROLE HELPERS
# ============================================================


def _is_chef(user):
    """
    Return True when the logged-in user belongs to the Chef group.
    """
    if not user or not user.is_authenticated:
        return False

    return user.groups.filter(name__iexact="Chef").exists()


def _is_waiter(user):
    """
    Return True when the logged-in user belongs to the Waiter group.
    """
    if not user or not user.is_authenticated:
        return False

    return user.groups.filter(name__iexact="Waiter").exists()


def _staff_role(user):
    """
    Determine the application role for the logged-in user.

    Priority:
        1. Superuser
        2. Chef group
        3. Waiter group
        4. Username containing chef
        5. Username containing waiter
        6. Other staff
        7. Customer
    """

    if not user or not user.is_authenticated:
        return "customer"

    if user.is_superuser:
        return "admin"

    if _is_chef(user):
        return "chef"

    if _is_waiter(user):
        return "waiter"

    username = (user.username or "").lower()

    if "chef" in username:
        return "chef"

    if "waiter" in username:
        return "waiter"



    return "customer"


# ============================================================
# LOGIN / LOGOUT
# ============================================================


def customer_login(request):
    """
    Unified login page.

    Customers, chefs and waiters all use the same login form.
    After successful customer login, return to the page that
    originally required authentication.
    """

    next_url = (
        request.POST.get("next")
        or request.GET.get("next")
    )

    if request.user.is_authenticated:
        role = _staff_role(request.user)

        if role == "chef":
            return redirect("kitchen:dashboard")

        if role == "waiter":
            return redirect("accounts:waiter_dashboard")

        if role == "admin":
            return redirect("/admin/")

        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={request.get_host()},
        ):
            return redirect(next_url)

        return redirect("accounts:dashboard")

    if request.method == "POST":

        username = request.POST.get(
            "username",
            ""
        ).strip()

        password = request.POST.get(
            "password",
            ""
        )

        if not username or not password:
            messages.error(
                request,
                "Please enter both username and password.",
            )

            return render(
                request,
                "accounts/login.html",
                {
                    "next": next_url,
                },
            )

        user = authenticate(
            request,
            username=username,
            password=password,
        )

        if user is None:
            messages.error(
                request,
                "Invalid username or password.",
            )

            return render(
                request,
                "accounts/login.html",
                {
                    "next": next_url,
                },
            )

        if not user.is_active:
            messages.error(
                request,
                "This account is inactive.",
            )

            return render(
                request,
                "accounts/login.html",
                {
                    "next": next_url,
                },
            )

        login(request, user)

        role = _staff_role(user)

        if role == "chef":
            return redirect("kitchen:dashboard")

        if role == "waiter":
            return redirect("accounts:waiter_dashboard")

        if role == "admin":
            return redirect("/admin/")

        # IMPORTANT:
        # Return the customer to the URL that originally
        # required login.
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={request.get_host()},
        ):
            return redirect(next_url)

        return redirect("accounts:dashboard")

    return render(
        request,
        "accounts/login.html",
        {
            "next": next_url,
        },
    )

@login_required
def customer_logout(request):
    """
    Log out the current user.
    """
    logout(request)

    messages.success(
        request,
        "You have been logged out successfully.",
    )

    return redirect("accounts:login")


# ============================================================
# CUSTOMER DASHBOARD
# ============================================================


@login_required
def dashboard(request):
    """
    Customer dashboard.

    Staff users are redirected to their appropriate dashboard.
    """

    role = _staff_role(request.user)

    if role == "chef":
        return redirect("kitchen:dashboard")

    if role == "waiter":
        return redirect("accounts:waiter_dashboard")

    if role == "admin":
        return redirect("/admin/")

    tables = (
        DiningTable.objects
        .filter(status="available")
        .order_by("table_number")
    )

    categories = (
        MenuCategory.objects
        .prefetch_related("items")
        .order_by("name")
    )

    menu_items = (
        MenuItem.objects
        .filter(is_available=True)
        .select_related("category")
        .order_by("category__name", "name")
    )

    active_session = (
        DiningSession.objects
        .filter(
            customer_name=request.user.username,
            status__in=["active", "occupied", "open"],
        )
        .select_related("table")
        .order_by("-started_at")
        .first()
    )

    customer_orders = (
        Order.objects
        .filter(session__customer_name=request.user.username)
        .select_related(
            "session",
            "session__table",
        )
        .prefetch_related("items")
        .order_by("-created_at")
    )

    recent_orders = customer_orders[:10]

    cart = request.session.get("cart", {})
    cart_count = sum(
        int(quantity)
        for quantity in cart.values()
        if str(quantity).isdigit()
    )

    context = {
        "tables": tables,
        "categories": categories,
        "menu_items": menu_items,
        "active_session": active_session,
        "recent_orders": recent_orders,
        "order_count": customer_orders.count(),
        "cart_count": cart_count,
    }

    return render(
        request,
        "accounts/dashboard.html",
        context,
    )


# ============================================================
# WAITER DASHBOARD
# ============================================================


@login_required
def waiter_dashboard(request):
    """
    Waiter dashboard.

    A waiter can see:
        - ready orders that nobody has claimed yet
        - ready orders claimed by the current waiter
        - waiter service requests that nobody has claimed yet
        - service requests claimed by the current waiter

    Orders claimed by another waiter are not shown.
    """

    if not _is_waiter(request.user):
        messages.error(
            request,
            "You are not authorized to access the waiter dashboard.",
        )
        return redirect("accounts:dashboard")

    waiter = request.user

    waiter_request_types = [
        "water",
        "cutlery",
        "bill",
    ]

    # --------------------------------------------------------
    # READY FOOD ORDERS
    # --------------------------------------------------------

    ready_orders = (
        Order.objects
        .filter(
            status="ready",
        )
        .filter(
            Q(assigned_waiter__isnull=True)
            | Q(assigned_waiter=waiter)
        )
        .select_related(
            "session",
            "session__table",
            "assigned_waiter",
        )
        .prefetch_related(
            "items",
        )
        .order_by(
            "ready_at",
        )
    )

    # --------------------------------------------------------
    # WAITER SERVICE REQUESTS
    # --------------------------------------------------------

    waiter_requests = (
        ServiceRequest.objects
        .filter(
            request_type__in=waiter_request_types,
            status__in=[
                "requested",
                "accepted",
            ],
        )
        .filter(
            Q(assigned_waiter__isnull=True)
            | Q(assigned_waiter=waiter)
        )
        .select_related(
            "session",
            "session__table",
            "assigned_waiter",
        )
        .order_by(
            "status",
            "requested_at",
        )
    )

    context = {
        "ready_orders": ready_orders,
        "waiter_requests": waiter_requests,
        "waiter": waiter,
    }

    return render(
        request,
        "accounts/waiter_dashboard.html",
        context,
    )
# ============================================================
# WAITER SERVICE REQUEST - ACCEPT
# ============================================================


@login_required
@transaction.atomic
def waiter_accept_request(request, request_id):
    """
    Accept a waiter service request.

    Only:
        Water
        Cutlery
        Bill

    are handled by waiters.

    A request can only be claimed once.
    """

    if not _is_waiter(request.user):
        messages.error(
            request,
            "You are not authorized to perform waiter actions.",
        )
        return redirect("accounts:dashboard")

    if request.method != "POST":
        messages.error(
            request,
            "Invalid request method.",
        )
        return redirect("accounts:waiter_dashboard")

    service_request = get_object_or_404(
        ServiceRequest.objects.select_for_update(),
        pk=request_id,
    )

    if service_request.request_type not in [
        "water",
        "cutlery",
        "bill",
    ]:
        messages.error(
            request,
            "This request is not assigned to the waiter team.",
        )
        return redirect("accounts:waiter_dashboard")

    if service_request.status != "requested":
        messages.warning(
            request,
            "This service request has already been taken.",
        )
        return redirect("accounts:waiter_dashboard")

    if service_request.assigned_waiter_id is not None:
        messages.warning(
            request,
            "This service request has already been assigned to another waiter.",
        )
        return redirect("accounts:waiter_dashboard")

    service_request.status = "accepted"
    service_request.assigned_waiter = request.user

    service_request.save(
        update_fields=[
            "status",
            "assigned_waiter",
        ]
    )

    messages.success(
        request,
        "Service request accepted successfully.",
    )

    return redirect("accounts:waiter_dashboard")


# ============================================================
# WAITER SERVICE REQUEST - COMPLETE
# ============================================================


@login_required
@transaction.atomic
def waiter_complete_request(request, request_id):
    """
    Complete a waiter service request.

    Only the waiter who claimed the request may complete it.
    """

    if not _is_waiter(request.user):
        messages.error(
            request,
            "You are not authorized to perform waiter actions.",
        )
        return redirect("accounts:dashboard")

    if request.method != "POST":
        messages.error(
            request,
            "Invalid request method.",
        )
        return redirect("accounts:waiter_dashboard")

    service_request = get_object_or_404(
        ServiceRequest.objects.select_for_update(),
        pk=request_id,
    )

    if service_request.assigned_waiter_id != request.user.id:
        messages.error(
            request,
            "This service request is assigned to another waiter.",
        )
        return redirect("accounts:waiter_dashboard")

    if service_request.status != "accepted":
        messages.warning(
            request,
            "This service request is not currently accepted.",
        )
        return redirect("accounts:waiter_dashboard")

    service_request.status = "completed"
    service_request.completed_at = timezone.now()

    service_request.save(
        update_fields=[
            "status",
            "completed_at",
        ]
    )

    messages.success(
        request,
        "Service request completed successfully.",
    )

    return redirect("accounts:waiter_dashboard")
# ============================================================
# WAITER FOOD ORDER - TAKE / CLAIM
# ============================================================


@login_required
@transaction.atomic
def waiter_take_order(request, order_id):
    """
    Claim a READY food order.

    Only one waiter can claim a particular order.

    READY
       ↓
    waiter2 clicks Take Order
       ↓
    assigned_waiter = waiter2
       ↓
    waiter2 can serve it
    other waiters cannot claim it
    """

    if not _is_waiter(request.user):
        messages.error(
            request,
            "You are not authorized to perform waiter actions.",
        )
        return redirect("accounts:dashboard")

    if request.method != "POST":
        messages.error(
            request,
            "Invalid request method.",
        )
        return redirect(
            "accounts:waiter_dashboard"
        )

    order = get_object_or_404(
        Order.objects.select_for_update(),
        pk=order_id,
    )

    if order.status != "ready":
        messages.warning(
            request,
            "Only ready orders can be taken by a waiter.",
        )
        return redirect(
            "accounts:waiter_dashboard"
        )

    if order.assigned_waiter_id is not None:

        if order.assigned_waiter_id == request.user.id:
            messages.info(
                request,
                "This order is already assigned to you.",
            )
        else:
            messages.warning(
                request,
                "This order has already been taken by another waiter.",
            )

        return redirect(
            "accounts:waiter_dashboard"
        )

    order.assigned_waiter = request.user

    order.save(
        update_fields=[
            "assigned_waiter",
            "updated_at",
        ]
    )

    messages.success(
        request,
        f"Order #{order.id} has been assigned to you.",
    )

    return redirect(
        "accounts:waiter_dashboard"
    )
# ============================================================
# WAITER FOOD ORDER - SERVE
# ============================================================


@login_required
@transaction.atomic
def waiter_serve_order(request, order_id):
    """
    Serve a READY food order.

    Only the waiter who claimed the order can serve it.
    """

    if not _is_waiter(request.user):
        messages.error(
            request,
            "You are not authorized to perform waiter actions.",
        )
        return redirect("accounts:dashboard")

    if request.method != "POST":
        messages.error(
            request,
            "Invalid request method.",
        )
        return redirect(
            "accounts:waiter_dashboard"
        )

    order = get_object_or_404(
        Order.objects.select_for_update(),
        pk=order_id,
    )

    if order.assigned_waiter_id != request.user.id:
        messages.error(
            request,
            "This order is assigned to another waiter.",
        )
        return redirect(
            "accounts:waiter_dashboard"
        )

    if order.status != "ready":
        messages.warning(
            request,
            "Only ready orders can be served.",
        )
        return redirect(
            "accounts:waiter_dashboard"
        )

    order.status = "served"
    order.served_at = timezone.now()
    order.updated_at = timezone.now()

    order.save(
        update_fields=[
            "status",
            "served_at",
            "updated_at",
        ]
    )

    messages.success(
        request,
        f"Order #{order.id} has been served successfully.",
    )

    return redirect(
        "accounts:waiter_dashboard"
    )
# ============================================================
# STAFF DASHBOARD
# ============================================================


@login_required
def staff_dashboard(request):
    """
    Basic staff dashboard.

    Chef and waiter users are redirected to their dedicated
    dashboards so they do not accidentally enter the generic
    staff dashboard.
    """

    role = _staff_role(request.user)

    if role == "chef":
        return redirect("kitchen:dashboard")

    if role == "waiter":
        return redirect("accounts:waiter_dashboard")

    if not request.user.is_staff:
        messages.error(
            request,
            "You are not authorized to access the staff dashboard.",
        )
        return redirect("accounts:dashboard")

    recent_orders = (
        Order.objects
        .select_related(
            "session",
            "session__table",
            "assigned_chef",
            "assigned_waiter",
        )
        .prefetch_related("items")
        .order_by("-created_at")[:20]
    )

    recent_requests = (
        ServiceRequest.objects
        .select_related(
            "session",
            "session__table",
            "assigned_waiter",
        )
        .order_by("-requested_at")[:20]
    )

    context = {
        "recent_orders": recent_orders,
        "recent_requests": recent_requests,
    }

    return render(
        request,
        "accounts/staff_dashboard.html",
        context,
    )


# ============================================================
# CUSTOMER SESSION HELPERS
# ============================================================


def _get_customer_active_session(user):
    """
    Return the customer's latest active dining session.
    """

    return (
        DiningSession.objects
        .filter(
            customer_name=user.username,
            status__in=[
                "active",
                "occupied",
                "open",
            ],
        )
        .select_related("table")
        .order_by("-started_at")
        .first()
    )


def _get_customer_order_queryset(user):
    """
    Return orders belonging to the logged-in customer.
    """

    return (
        Order.objects
        .filter(
            session__customer_name=user.username,
        )
        .select_related(
            "session",
            "session__table",
            "assigned_chef",
            "assigned_waiter",
        )
        .prefetch_related("items")
        .order_by("-created_at")
    )


# ============================================================
# CUSTOMER - TABLE / SESSION
# ============================================================


@login_required
def start_session(request, table_id):
    """
    Start a dining session for the selected table.
    """

    if request.method != "POST":
        messages.error(
            request,
            "Invalid request method.",
        )
        return redirect("accounts:dashboard")

    table = get_object_or_404(
        DiningTable,
        pk=table_id,
    )

    existing_session = _get_customer_active_session(
        request.user
    )

    if existing_session:
        messages.warning(
            request,
            "You already have an active dining session.",
        )
        return redirect("accounts:dashboard")

    if table.status != "available":
        messages.error(
            request,
            "This table is currently unavailable.",
        )
        return redirect("accounts:dashboard")

    session = DiningSession.objects.create(
        customer_name=request.user.username,
        table=table,
        status="active",
    )

    table.status = "order_in_progress"

    table.save(
        update_fields=[
            "status",
        ]
    )

    # Keep the selected dining session in the browser session so
    # the public menu, cart and order flow can identify the
    # customer's active table.
    request.session["dining_session_id"] = session.id
    request.session["table_id"] = table.id
    request.session["cart"] = {}
    request.session.modified = True

    messages.success(
        request,
        f"Table {table.table_number} has been selected.",
    )

    return redirect(
        "restaurant:menu_for_table",
        table_id=table.id,
    )


# ============================================================
# CUSTOMER - MENU
# ============================================================


@login_required
def menu(request, table_id=None):
    """
    Display the digital restaurant menu.
    """

    categories = (
        MenuCategory.objects
        .prefetch_related("items")
        .order_by("name")
    )

    menu_items = (
        MenuItem.objects
        .filter(is_available=True)
        .select_related("category")
        .order_by(
            "category__name",
            "name",
        )
    )

    context = {
        "categories": categories,
        "menu_items": menu_items,
    }

    return render(
        request,
        "restaurant/menu.html",
        context,
    )


# ============================================================
# CUSTOMER - ORDER LIST
# ============================================================


@login_required
def my_orders(request):
    """
    Display the logged-in customer's orders.
    """

    orders = _get_customer_order_queryset(
        request.user
    )

    context = {
        "orders": orders,
    }

    return render(
        request,
        "orders/my_orders.html",
        context,
    )


# ============================================================
# CUSTOMER - ORDER DETAIL
# ============================================================


@login_required
def order_detail(request, order_id):
    """
    Display one order belonging to the current customer.
    """

    order = get_object_or_404(
        _get_customer_order_queryset(
            request.user
        ),
        pk=order_id,
    )

    context = {
        "order": order,
    }

    return render(
        request,
        "orders/order_detail.html",
        context,
    )
# ============================================================
# CUSTOMER - SERVICE REQUEST
# ============================================================


@login_required
def create_service_request(request):
    """
    Create a service request from the customer side.

    Routing:
        water   -> waiter
        cutlery -> waiter
        bill    -> waiter
        assistance / other -> kitchen / chef
    """

    if request.method != "POST":
        messages.error(
            request,
            "Invalid request method.",
        )
        return redirect("accounts:dashboard")

    session = _get_customer_active_session(
        request.user
    )

    if not session:
        messages.error(
            request,
            "You need an active dining session before requesting assistance.",
        )
        return redirect("accounts:dashboard")

    request_type = (
        request.POST.get(
            "request_type",
            "",
        )
        .strip()
        .lower()
    )

    description = (
        request.POST.get(
            "description",
            "",
        )
        .strip()
    )

    allowed_types = {
        "water",
        "cutlery",
        "bill",
        "assistance",
        "other",
    }

    if request_type not in allowed_types:
        messages.error(
            request,
            "Invalid service request type.",
        )
        return redirect("accounts:dashboard")

    ServiceRequest.objects.create(
        session=session,
        request_type=request_type,
        message=description,
        status="requested",
    )

    if request_type in {
        "water",
        "cutlery",
        "bill",
    }:
        messages.success(
            request,
            "Your request has been sent to the waiter.",
        )
    else:
        messages.success(
            request,
            "Your request has been sent to the kitchen team.",
        )

    return redirect(
        "accounts:dashboard"
    )


# ============================================================
# CUSTOMER - CANCEL ORDER
# ============================================================


@login_required
@transaction.atomic
def cancel_order(request, order_id):
    """
    Cancel a customer's order when it is still cancellable.
    """

    if request.method != "POST":
        messages.error(
            request,
            "Invalid request method.",
        )
        return redirect("accounts:my_orders")

    order = get_object_or_404(
        Order.objects.select_for_update(),
        pk=order_id,
        session__customer_name=request.user.username,
    )

    cancellable_statuses = [
        "new",
        "accepted",
    ]

    if order.status not in cancellable_statuses:
        messages.error(
            request,
            "This order can no longer be cancelled.",
        )
        return redirect("accounts:my_orders")

    order.status = "cancelled"
    order.updated_at = timezone.now()

    order.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    messages.success(
        request,
        f"Order #{order.id} has been cancelled.",
    )

    return redirect(
        "accounts:my_orders"
    )


# ============================================================
# CUSTOMER - TABLE AVAILABILITY
# ============================================================


@login_required
def available_tables(request):
    """
    Show available dining tables.
    """

    tables = (
        DiningTable.objects
        .filter(status="available")
        .order_by("table_number")
    )

    context = {
        "tables": tables,
    }

    return render(
        request,
        "restaurant/table_selection.html",
        context,
    )


# ============================================================
# CUSTOMER - PROFILE
# ============================================================


@login_required
def profile(request):
    """
    Basic customer profile page.
    """

    return render(
        request,
        "accounts/profile.html",
        {
            "user": request.user,
        },
    )


# ============================================================
# LEGACY / COMPATIBILITY FUNCTIONS
# ============================================================


def chef_login(request):
    """
    Compatibility wrapper for older links.

    The application now uses the unified login page.
    """

    return customer_login(request)


def waiter_login(request):
    """
    Compatibility wrapper for older links.

    The application now uses the unified login page.
    """

    return customer_login(request)


# ============================================================
# STAFF ROLE REDIRECT
# ============================================================


@login_required
def role_dashboard(request):
    """
    Redirect the logged-in user to the correct dashboard.
    """

    role = _staff_role(request.user)

    if role == "chef":
        return redirect("kitchen:dashboard")

    if role == "waiter":
        return redirect("accounts:waiter_dashboard")

    if role == "admin":
        return redirect("/admin/")

    return redirect("accounts:dashboard")


# ============================================================
# HEALTH / STATUS
# ============================================================


@login_required
def system_status(request):
    """
    Simple authenticated system status page.
    """

    context = {
        "role": _staff_role(request.user),
        "username": request.user.username,
        "time": timezone.now(),
    }

    return render(
        request,
        "accounts/system_status.html",
        context,
    )


# ============================================================
# CUSTOMER ORDER TRACKING
# ============================================================


@login_required
def track_order(request, order_id):
    """
    Track an order belonging to the logged-in customer.
    """

    order = get_object_or_404(
        Order.objects
        .select_related(
            "session",
            "session__table",
            "assigned_chef",
            "assigned_waiter",
        )
        .prefetch_related("items"),
        pk=order_id,
        session__customer_name=request.user.username,
    )

    context = {
        "order": order,
    }

    return render(
        request,
        "orders/track_order.html",
        context,
    )


# ============================================================
# CUSTOMER SERVICE REQUEST LIST
# ============================================================


@login_required
def my_service_requests(request):
    """
    Display the current customer's service requests.
    """

    active_requests = (
        ServiceRequest.objects
        .filter(
            session__customer_name=request.user.username,
        )
        .select_related(
            "session",
            "session__table",
            "assigned_waiter",
        )
        .order_by("-requested_at")
    )

    context = {
        "service_requests": active_requests,
    }

    return render(
        request,
        "orders/service_requests.html",
        context,
    )


# ============================================================
# CUSTOMER ACTIVE SESSION
# ============================================================


@login_required
def active_session(request):
    """
    Display the customer's current dining session.
    """

    session = _get_customer_active_session(
        request.user
    )

    context = {
        "session": session,
    }

    return render(
        request,
        "orders/active_session.html",
        context,
    )


# ============================================================
# CUSTOMER CLOSE SESSION
# ============================================================


@login_required
@transaction.atomic
def close_session(request, session_id):
    """
    Close a customer's dining session after payment/completion.
    """

    if request.method != "POST":
        messages.error(
            request,
            "Invalid request method.",
        )
        return redirect("accounts:dashboard")

    session = get_object_or_404(
        DiningSession.objects.select_for_update(),
        pk=session_id,
        customer_name=request.user.username,
    )

    if session.status not in [
        "active",
        "occupied",
        "open",
    ]:
        messages.warning(
            request,
            "This dining session is already closed.",
        )
        return redirect("accounts:dashboard")

    session.status = "completed"

    session.save(
        update_fields=[
            "status",
        ]
    )

    if session.table:
        session.table.status = "available"

        session.table.save(
            update_fields=[
                "status",
            ]
        )

    messages.success(
        request,
        "Dining session closed successfully.",
    )

    return redirect(
        "accounts:dashboard"
    )
# ============================================================
# GENERIC STAFF ORDER VIEW
# ============================================================


@login_required
def staff_orders(request):
    """
    Staff order monitoring page.

    This page is intended for administrative/staff users.
    Chef and waiter users are redirected to their dedicated
    dashboards.
    """

    role = _staff_role(request.user)

    if role == "chef":
        return redirect("kitchen:dashboard")

    if role == "waiter":
        return redirect("accounts:waiter_dashboard")

    if not request.user.is_staff:
        messages.error(
            request,
            "You are not authorized to access staff orders.",
        )
        return redirect("accounts:dashboard")

    orders = (
        Order.objects
        .select_related(
            "session",
            "session__table",
            "assigned_chef",
            "assigned_waiter",
        )
        .prefetch_related("items")
        .order_by("-created_at")
    )

    context = {
        "orders": orders,
    }

    return render(
        request,
        "accounts/staff_orders.html",
        context,
    )


# ============================================================
# GENERIC STAFF SERVICE REQUEST VIEW
# ============================================================


@login_required
def staff_requests(request):
    """
    Staff monitoring page for service requests.
    """

    role = _staff_role(request.user)

    if role == "chef":
        return redirect("kitchen:dashboard")

    if role == "waiter":
        return redirect("accounts:waiter_dashboard")

    if not request.user.is_staff:
        messages.error(
            request,
            "You are not authorized to access service requests.",
        )
        return redirect("accounts:dashboard")

    service_requests = (
        ServiceRequest.objects
        .select_related(
            "session",
            "session__table",
            "assigned_waiter",
        )
        .order_by("-requested_at")
    )

    context = {
        "service_requests": service_requests,
    }

    return render(
        request,
        "accounts/staff_requests.html",
        context,
    )


# ============================================================
# CUSTOMER ORDER SUMMARY
# ============================================================


@login_required
def order_summary(request, order_id):
    """
    Display a customer's order summary.
    """

    order = get_object_or_404(
        Order.objects
        .select_related(
            "session",
            "session__table",
            "assigned_chef",
            "assigned_waiter",
        )
        .prefetch_related("items"),
        pk=order_id,
        session__customer_name=request.user.username,
    )

    context = {
        "order": order,
    }

    return render(
        request,
        "orders/order_summary.html",
        context,
    )


# ============================================================
# CUSTOMER FEEDBACK REDIRECT
# ============================================================


@login_required
def feedback_redirect(request, order_id):
    """
    Redirect the customer to the feedback page for an order.

    The actual feedback validation remains in the feedback app.
    """

    order = get_object_or_404(
        Order.objects
        .select_related(
            "session",
        ),
        pk=order_id,
        session__customer_name=request.user.username,
    )

    session_id = order.session_id

    return redirect(
        reverse(
            "feedback:session_feedback",
            kwargs={
                "session_id": session_id,
            },
        )
    )


# ============================================================
# DASHBOARD REDIRECTION
# ============================================================


@login_required
def home(request):
    """
    Application home/dashboard redirect.
    """

    role = _staff_role(request.user)

    if role == "chef":
        return redirect("kitchen:dashboard")

    if role == "waiter":
        return redirect("accounts:waiter_dashboard")

    if role == "admin":
        return redirect("/admin/")

    return redirect("accounts:dashboard")


# ============================================================
# END OF ACCOUNTS VIEWS
# ============================================================


    