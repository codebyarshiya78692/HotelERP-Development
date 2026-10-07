from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)
from django.utils import timezone

from inventory.services import (
    deduct_inventory_for_order,
)

from orders.models import Order


# ============================================================
# STAFF ACCESS
# ============================================================

def _is_chef(request):
    """
    Only users belonging to the Chef group may access
    the kitchen.
    """

    if not request.user.is_authenticated:
        return False

    return request.user.groups.filter(
        name="Chef"
    ).exists()


def _staff_only(request):
    """
    Compatibility wrapper used by the kitchen views.
    """

    return _is_chef(
        request
    )


def _deny_kitchen_access(request):
    """
    Display a clear message and return the user to the
    public site.
    """

    messages.error(
        request,
        "Kitchen access is restricted to Chef staff.",
    )

    return redirect(
        "home"
    )


# ============================================================
# KITCHEN DASHBOARD
# ============================================================

@login_required
def kitchen_dashboard(request):
    """
    Main Chef kitchen dashboard.

    NEW orders are visible to all Chefs.

    Once a Chef accepts an order, that order is assigned
    to that Chef and moves into their personal workflow.
    """

    if not _staff_only(request):

        return _deny_kitchen_access(
            request
        )

    # --------------------------------------------------------
    # NEW ORDERS
    # --------------------------------------------------------
    #
    # All Chefs can see new orders.
    #
    # Once accepted, assigned_chef is set and the order
    # disappears from the unassigned queue.
    # --------------------------------------------------------

    new_orders = (
        Order.objects
        .filter(
            status="new",
            assigned_chef__isnull=True,
        )
        .select_related(
            "session",
            "session__table",
        )
        .prefetch_related(
            "items",
        )
        .order_by(
            "created_at",
        )
    )

    # --------------------------------------------------------
    # THIS CHEF'S ACCEPTED ORDERS
    # --------------------------------------------------------

    accepted_orders = (
        Order.objects
        .filter(
            status="accepted",
            assigned_chef=request.user,
        )
        .select_related(
            "session",
            "session__table",
        )
        .prefetch_related(
            "items",
        )
        .order_by(
            "accepted_at",
            "created_at",
        )
    )

    # --------------------------------------------------------
    # THIS CHEF'S PREPARING ORDERS
    # --------------------------------------------------------

    preparing_orders = (
        Order.objects
        .filter(
            status="preparing",
            assigned_chef=request.user,
        )
        .select_related(
            "session",
            "session__table",
        )
        .prefetch_related(
            "items",
        )
        .order_by(
            "preparing_at",
            "created_at",
        )
    )

    # --------------------------------------------------------
    # RECENTLY READY ORDERS
    # --------------------------------------------------------

    ready_orders = (
        Order.objects
        .filter(
            status="ready",
            assigned_chef=request.user,
        )
        .select_related(
            "session",
            "session__table",
        )
        .prefetch_related(
            "items",
        )
        .order_by(
            "-ready_at",
        )[:20]
    )

    context = {
        "new_orders": new_orders,
        "accepted_orders": accepted_orders,
        "preparing_orders": preparing_orders,
        "ready_orders": ready_orders,
    }

    return render(
        request,
        "kitchen/dashboard.html",
        context,
    )


# ============================================================
# ACCEPT ORDER
# ============================================================

@login_required
@transaction.atomic
def accept_order(request, order_id):
    """
    Allow a Chef to claim one NEW order.

    select_for_update() prevents two Chefs from accepting
    the same order at the same time.
    """

    if not _staff_only(request):

        return _deny_kitchen_access(
            request
        )

    if request.method != "POST":

        return redirect(
            "kitchen:dashboard"
        )

    order = get_object_or_404(
        Order.objects
        .select_for_update()
        .select_related(
            "session",
            "session__table",
        )
        .prefetch_related(
            "items",
        ),
        id=order_id,
    )

    if order.status != "new":

        messages.warning(
            request,
            (
                "This order is no longer available "
                "for acceptance."
            ),
        )

        return redirect(
            "kitchen:dashboard"
        )

    if order.assigned_chef_id is not None:

        messages.warning(
            request,
            (
                "This order has already been "
                "accepted by another Chef."
            ),
        )

        return redirect(
            "kitchen:dashboard"
        )

    order.assigned_chef = request.user
    order.status = "accepted"
    order.accepted_at = timezone.now()

    order.save(
        update_fields=[
            "assigned_chef",
            "status",
            "accepted_at",
            "updated_at",
        ],
    )

    messages.success(
        request,
        (
            f"Order #{order.id} has been "
            "assigned to you."
        ),
    )

    return redirect(
        "kitchen:dashboard"
    )


# ============================================================
# START PREPARING
# ============================================================

@login_required
@transaction.atomic
def start_preparing(request, order_id):
    """
    Start preparing an order owned by this Chef.

    IMPORTANT:

    Inventory is NOT deducted here.

    Stock is deducted only when the Chef marks the
    order READY.
    """

    if not _staff_only(request):

        return _deny_kitchen_access(
            request
        )

    if request.method != "POST":

        return redirect(
            "kitchen:dashboard"
        )

    order = get_object_or_404(
        Order.objects
        .select_for_update()
        .select_related(
            "session",
            "session__table",
        )
        .prefetch_related(
            "items",
        ),
        id=order_id,
        assigned_chef=request.user,
    )

    if order.status != "accepted":

        messages.warning(
            request,
            (
                "Only orders accepted by you can "
                "be started."
            ),
        )

        return redirect(
            "kitchen:dashboard"
        )

    order.status = "preparing"
    order.preparing_at = timezone.now()

    order.save(
        update_fields=[
            "status",
            "preparing_at",
            "updated_at",
        ],
    )

    messages.success(
        request,
        (
            f"Order #{order.id} is now being prepared. "
            "Inventory will be deducted when the "
            "order is marked READY."
        ),
    )

    return redirect(
        "kitchen:dashboard"
    )


# ============================================================
# MARK ORDER READY
# ============================================================

@login_required
@transaction.atomic
def mark_ready(request, order_id):
    """
    Chef marks their own preparing order as READY.

    THIS is the point where inventory is deducted.

    Flow:

        Preparing
            ↓
        Chef clicks READY
            ↓
        Calculate recipe quantities
            ↓
        Check stock
            ↓
        Deduct inventory
            ↓
        Create StockMovement
            ↓
        Check reorder level
            ↓
        Mark order READY
    """

    if not _staff_only(request):

        return _deny_kitchen_access(
            request
        )

    if request.method != "POST":

        return redirect(
            "kitchen:dashboard"
        )

    order = get_object_or_404(
        Order.objects
        .select_for_update()
        .select_related(
            "session",
            "session__table",
            "assigned_chef",
        )
        .prefetch_related(
            "items",
        ),
        id=order_id,
        assigned_chef=request.user,
    )

    if order.status != "preparing":

        messages.warning(
            request,
            (
                "Only your orders currently being "
                "prepared can be marked ready."
            ),
        )

        return redirect(
            "kitchen:dashboard"
        )

    # ========================================================
    # DEDUCT INVENTORY
    # ========================================================

    inventory_result = (
        deduct_inventory_for_order(
            order
        )
    )

    # --------------------------------------------------------
    # INSUFFICIENT STOCK
    # --------------------------------------------------------
    #
    # If there isn't enough stock, the order remains
    # PREPARING and therefore the Chef can try again
    # after Admin restocks the ingredient.
    # --------------------------------------------------------

    if not inventory_result["success"]:

        messages.error(
            request,
            inventory_result["message"],
        )

        return redirect(
            "kitchen:dashboard"
        )

    # ========================================================
    # MARK ORDER READY
    # ========================================================

    order.status = "ready"
    order.ready_at = timezone.now()

    order.save(
        update_fields=[
            "status",
            "ready_at",
            "updated_at",
        ],
    )

    # ========================================================
    # LOW STOCK ALERT
    # ========================================================

    low_stock = inventory_result.get(
        "low_stock",
        [],
    )

    if low_stock:

        low_stock_messages = []

        for item in low_stock:

            low_stock_messages.append(
                (
                    f"{item['ingredient']} "
                    f"({item['current_stock']} "
                    f"{item['unit']} remaining; "
                    f"reorder level "
                    f"{item['reorder_level']} "
                    f"{item['unit']})"
                )
            )

        messages.warning(
            request,
            (
                f"Order #{order.id} is READY. "
                "LOW STOCK: "
                + "; ".join(
                    low_stock_messages
                )
                + ". Please restock."
            ),
        )

    else:

        messages.success(
            request,
            (
                f"Order #{order.id} is READY. "
                "Inventory has been updated."
            ),
        )

    return redirect(
        "kitchen:dashboard"
    )


# ============================================================
# CUSTOMER SERVICE REQUESTS
# ============================================================

@login_required
def service_requests_dashboard(request):
    """
    Compatibility service-request dashboard.

    Service requests are operationally handled by Waiters.
    This endpoint is retained because the existing kitchen
    URL configuration and service-request template reference
    these view names.

    Chef accounts are not allowed to manage service requests.
    Waiter accounts may access the dashboard.
    """

    if not request.user.is_authenticated:

        return redirect(
            "accounts:login"
        )

    is_waiter = request.user.groups.filter(
        name__iexact="Waiter"
    ).exists()

    if not is_waiter:

        messages.error(
            request,
            (
                "Service requests are restricted "
                "to Waiter staff."
            ),
        )

        return redirect(
            "home"
        )

    from orders.models import ServiceRequest

    active_requests = (
        ServiceRequest.objects
        .filter(
            status__in=[
                "requested",
                "accepted",
            ],
            request_type__in=[
                "water",
                "cutlery",
                "bill",
            ],
        )
        .select_related(
            "session",
            "session__table",
        )
        .order_by(
            "status",
            "requested_at",
        )
    )

    completed_requests = (
        ServiceRequest.objects
        .filter(
            status="completed",
            request_type__in=[
                "water",
                "cutlery",
                "bill",
            ],
        )
        .select_related(
            "session",
            "session__table",
        )
        .order_by(
            "-completed_at",
        )[:20]
    )

    requested_count = (
        ServiceRequest.objects
        .filter(
            status="requested",
            request_type__in=[
                "water",
                "cutlery",
                "bill",
            ],
        )
        .count()
    )

    accepted_count = (
        ServiceRequest.objects
        .filter(
            status="accepted",
            request_type__in=[
                "water",
                "cutlery",
                "bill",
            ],
        )
        .count()
    )

    completed_count = (
        ServiceRequest.objects
        .filter(
            status="completed",
            request_type__in=[
                "water",
                "cutlery",
                "bill",
            ],
        )
        .count()
    )

    return render(
        request,
        "kitchen/service_requests.html",
        {
            "active_requests": active_requests,
            "completed_requests": completed_requests,
            "requested_count": requested_count,
            "accepted_count": accepted_count,
            "completed_count": completed_count,
        },
    )


# ============================================================
# ACCEPT SERVICE REQUEST
# ============================================================

@login_required
@transaction.atomic
def accept_service_request(
    request,
    request_id,
):
    """
    Allow one Waiter to claim a customer service request.

    Only water, cutlery and bill requests belong to the
    Waiter workflow.

    select_for_update() prevents two Waiters from accepting
    the same request simultaneously.
    """

    if not request.user.is_authenticated:

        return redirect(
            "accounts:login"
        )

    is_waiter = request.user.groups.filter(
        name__iexact="Waiter"
    ).exists()

    if not is_waiter:

        messages.error(
            request,
            (
                "Only Waiter staff can "
                "accept service requests."
            ),
        )

        return redirect(
            "home"
        )

    if request.method != "POST":

        return redirect(
            "kitchen:service_requests"
        )

    from orders.models import ServiceRequest

    service_request = get_object_or_404(
        ServiceRequest.objects
        .select_for_update()
        .select_related(
            "session",
            "session__table",
        ),
        id=request_id,
        request_type__in=[
            "water",
            "cutlery",
            "bill",
        ],
    )

    if service_request.status != "requested":

        messages.warning(
            request,
            (
                "This service request has already "
                "been accepted or completed."
            ),
        )

        return redirect(
            "kitchen:service_requests"
        )

    service_request.status = "accepted"
    service_request.assigned_waiter = request.user

    service_request.save(
        update_fields=[
            "status",
            "assigned_waiter",
        ],
    )

    messages.success(
        request,
        (
            f"Service request for Table "
            f"{service_request.session.table.table_number} "
            "has been assigned to you."
        ),
    )

    return redirect(
        "kitchen:service_requests"
    )


# ============================================================
# COMPLETE SERVICE REQUEST
# ============================================================

@login_required
@transaction.atomic
def complete_service_request(
    request,
    request_id,
):
    """
    Mark an accepted Waiter service request as completed.
    """

    if not request.user.is_authenticated:

        return redirect(
            "accounts:login"
        )

    is_waiter = request.user.groups.filter(
        name__iexact="Waiter"
    ).exists()

    if not is_waiter:

        messages.error(
            request,
            (
                "Only Waiter staff can "
                "complete service requests."
            ),
        )

        return redirect(
            "home"
        )

    if request.method != "POST":

        return redirect(
            "kitchen:service_requests"
        )

    from orders.models import ServiceRequest

    service_request = get_object_or_404(
        ServiceRequest.objects
        .select_for_update()
        .select_related(
            "session",
            "session__table",
        ),
        id=request_id,
        request_type__in=[
            "water",
            "cutlery",
            "bill",
        ],
    )

    if service_request.status != "accepted":

        messages.warning(
            request,
            (
                "Only an accepted service request "
                "can be completed."
            ),
        )

        return redirect(
            "kitchen:service_requests"
        )

    service_request.status = "completed"
    service_request.completed_at = timezone.now()

    service_request.save(
        update_fields=[
            "status",
            "completed_at",
        ],
    )

    messages.success(
        request,
        (
            f"Service request for Table "
            f"{service_request.session.table.table_number} "
            "has been completed."
        ),
    )

    return redirect(
        "kitchen:service_requests"
    )