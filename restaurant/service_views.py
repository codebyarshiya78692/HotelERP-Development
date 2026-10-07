from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from orders.models import DiningSession, ServiceRequest


# ============================================================
# CUSTOMER SESSION
# ============================================================

def _get_customer_session(request):

    session_id = request.session.get(
        "dining_session_id"
    )

    if not session_id:
        return None

    return (
        DiningSession.objects
        .select_related(
            "table"
        )
        .filter(
            id=session_id,
            status="active",
        )
        .first()
    )


# ============================================================
# STAFF ROLE
# ============================================================

def _staff_role(request):

    user = request.user

    if not user.is_authenticated:
        return "anonymous"

    if user.is_superuser:
        return "admin"

    if user.groups.filter(
        name__iexact="Chef"
    ).exists():

        return "chef"

    if user.groups.filter(
        name__iexact="Waiter"
    ).exists():

        return "waiter"

    return "staff"


# ============================================================
# STAFF ACCESS
# ============================================================

def _staff_only(request):

    return (
        request.user.is_authenticated
        and request.user.is_staff
    )


def _allowed_request_types(request):

    role = _staff_role(
        request
    )

    # --------------------------------------------------------
    # ADMIN
    # --------------------------------------------------------

    if role == "admin":

        return [
            "water",
            "cutlery",
            "assistance",
            "bill",
            "other",
        ]

    # --------------------------------------------------------
    # CHEF / KITCHEN
    #
    # Customer assistance/custom requirements go directly
    # to the kitchen.
    # --------------------------------------------------------

    if role == "chef":

        return [
            "assistance",
            "other",
        ]

    # --------------------------------------------------------
    # WAITER
    #
    # Physical table-service requirements go to Waiter.
    # --------------------------------------------------------

    if role == "waiter":

        return [
            "water",
            "cutlery",
            "bill",
        ]

    return []


# ============================================================
# ACCESS DENIED
# ============================================================

def _staff_access_denied(request):

    return render(
        request,
        "restaurant/access_denied.html",
        status=403,
    )


# ============================================================
# CUSTOMER SERVICE REQUEST PAGE
# ============================================================

def service_requests(request):

    # Staff must use the dedicated staff service page.
    if (
        request.user.is_authenticated
        and request.user.is_staff
    ):
        return staff_service_requests(request)

    dining_session = _get_customer_session(request)

    if dining_session is None:
        messages.error(
            request,
            "Please select a table before requesting service.",
        )

        return redirect("table_selection")

    requests = (
        ServiceRequest.objects
        .filter(
            session=dining_session,
        )
        .select_related(
            "session",
            "session__table",
            "assigned_waiter",
        )
        .order_by("-requested_at")
    )

    return render(
        request,
        "orders/service_requests.html",
        {
            "session": dining_session,
            "table": dining_session.table,
            "service_requests": requests,
            "active_count": requests.exclude(
                status="completed"
            ).count(),
        },
    )
# ============================================================
# CREATE CUSTOMER SERVICE REQUEST
# ============================================================

def create_service_request(request):

    if request.method != "POST":

        return redirect(
            "service_requests"
        )

    dining_session = _get_customer_session(
        request
    )

    if dining_session is None:

        messages.error(
            request,
            "Your dining session is no longer active.",
        )

        return redirect(
            "table_selection"
        )

    request_type = request.POST.get(
        "request_type",
        "",
    ).strip()

    message = request.POST.get(
        "message",
        "",
    ).strip()

    valid_request_types = {
        choice[0]
        for choice in ServiceRequest.REQUEST_TYPES
    }

    if request_type not in valid_request_types:

        messages.error(
            request,
            "Please select a valid service request.",
        )

        return redirect(
            "service_requests"
        )

    # --------------------------------------------------------
    # PREVENT DUPLICATE ACTIVE REQUESTS
    # --------------------------------------------------------

    existing_request = (
        ServiceRequest.objects
        .filter(
            session=dining_session,
            request_type=request_type,
            status__in=[
                "requested",
                "accepted",
            ],
        )
        .first()
    )

    if existing_request:

        messages.info(
            request,
            "You already have an active request of this type.",
        )

        return redirect(
            "service_requests"
        )

    ServiceRequest.objects.create(
        session=dining_session,
        request_type=request_type,
        message=message,
        status="requested",
    )

    # --------------------------------------------------------
    # ROUTING MESSAGE
    # --------------------------------------------------------

    if request_type in [
        "water",
        "cutlery",
        "bill",
    ]:

        messages.success(
            request,
            "Your request has been sent to the waiter.",
        )

    elif request_type in [
        "assistance",
        "other",
    ]:

        messages.success(
            request,
            "Your request has been sent to the kitchen.",
        )

    else:

        messages.success(
            request,
            "Your service request has been sent to staff.",
        )

    return redirect(
        "service_requests"
    )


# ============================================================
# STAFF SERVICE REQUEST DASHBOARD
# ============================================================

@login_required
def staff_service_requests(request):

    if not _staff_only(
        request
    ):

        return _staff_access_denied(
            request
        )

    allowed_types = _allowed_request_types(
        request
    )

    if not allowed_types:

        return _staff_access_denied(
            request
        )

    service_request_list = (
        ServiceRequest.objects
        .filter(
            request_type__in=allowed_types,
        )
        .select_related(
            "session",
            "session__table",
            "assigned_waiter",
        )
        .order_by(
            "-requested_at",
        )
    )

    requested_requests = (
        service_request_list
        .filter(
            status="requested",
        )
    )

    accepted_requests = (
        service_request_list
        .filter(
            status="accepted",
        )
    )

    completed_requests = (
        service_request_list
        .filter(
            status="completed",
        )
    )

    return render(
        request,
        "restaurant/service_requests_staff.html",
        {
            "service_requests": service_request_list,
            "requested_requests": requested_requests,
            "accepted_requests": accepted_requests,
            "completed_requests": completed_requests,
            "requested_count": requested_requests.count(),
            "accepted_count": accepted_requests.count(),
            "completed_count": completed_requests.count(),
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

    if not _staff_only(
        request
    ):

        return _staff_access_denied(
            request
        )

    if request.method != "POST":

        return redirect(
            "staff_service_requests"
        )

    allowed_types = _allowed_request_types(
        request
    )

    if not allowed_types:

        return _staff_access_denied(
            request
        )

    service_request = get_object_or_404(
        ServiceRequest.objects
        .select_for_update()
        .select_related(
            "session",
            "session__table",
        ),
        id=request_id,
        request_type__in=allowed_types,
    )

    if service_request.status != "requested":

        messages.info(
            request,
            "This service request is no longer waiting for acceptance.",
        )

        return redirect(
            "staff_service_requests"
        )

    # --------------------------------------------------------
    # WAITER REQUEST
    # --------------------------------------------------------

    if (
        _staff_role(request) == "waiter"
        and service_request.assigned_waiter_id
        is not None
    ):

        messages.warning(
            request,
            "This request has already been taken by another waiter.",
        )

        return redirect(
            "staff_service_requests"
        )

    service_request.status = "accepted"

    # --------------------------------------------------------
    # ASSIGN WAITER
    # --------------------------------------------------------

    if _staff_role(request) == "waiter":

        service_request.assigned_waiter = (
            request.user
        )

        service_request.save(
            update_fields=[
                "status",
                "assigned_waiter",
            ],
        )

    else:

        service_request.save(
            update_fields=[
                "status",
            ],
        )

    messages.success(
        request,
        (
            f"Request for Table "
            f"{service_request.session.table.table_number} "
            "has been accepted."
        ),
    )

    return redirect(
        "staff_service_requests"
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

    if not _staff_only(
        request
    ):

        return _staff_access_denied(
            request
        )

    if request.method != "POST":

        return redirect(
            "staff_service_requests"
        )

    allowed_types = _allowed_request_types(
        request
    )

    if not allowed_types:

        return _staff_access_denied(
            request
        )

    filters = {
        "id": request_id,
        "request_type__in": allowed_types,
    }

    # A waiter can complete only a request assigned
    # to that waiter.
    if _staff_role(request) == "waiter":

        filters[
            "assigned_waiter"
        ] = request.user

    service_request = get_object_or_404(
        ServiceRequest.objects
        .select_for_update()
        .select_related(
            "session",
            "session__table",
        ),
        **filters,
    )

    if service_request.status != "accepted":

        messages.info(
            request,
            "Only accepted service requests can be completed.",
        )

        return redirect(
            "staff_service_requests"
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
            f"Request for Table "
            f"{service_request.session.table.table_number} "
            "has been completed."
        ),
    )

    return redirect(
        "staff_service_requests"
    )


# ============================================================
# SERVICE REQUEST DETAIL
# ============================================================

@login_required
def staff_service_request_detail(
    request,
    request_id,
):

    if not _staff_only(
        request
    ):

        return _staff_access_denied(
            request
        )

    allowed_types = _allowed_request_types(
        request
    )

    if not allowed_types:

        return _staff_access_denied(
            request
        )

    service_request = get_object_or_404(
        ServiceRequest.objects
        .select_related(
            "session",
            "session__table",
            "assigned_waiter",
        ),
        id=request_id,
        request_type__in=allowed_types,
    )

    return render(
        request,
        "restaurant/service_request_detail.html",
        {
            "service_request": service_request,
        },
    )