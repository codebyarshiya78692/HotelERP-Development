from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import render
from django.utils import timezone

from orders.models import DiningSession, Order, OrderItem
from restaurant.models import DiningTable, MenuItem


def format_duration(value):
    """
    Convert a timedelta into a simple human-readable format.
    Example:
        125 seconds -> 2m 5s
        3725 seconds -> 1h 2m 5s
    """

    if value is None:
        return "—"

    total_seconds = int(value.total_seconds())

    if total_seconds < 0:
        return "—"

    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours:
        return f"{hours}h {minutes}m"

    if minutes:
        return f"{minutes}m {seconds}s"

    return f"{seconds}s"


def average_duration(durations):
    """
    Return the average timedelta from a list of timedeltas.
    """
    if not durations:
        return None

    total_seconds = sum(
        duration.total_seconds()
        for duration in durations
    )

    return timedelta(
        seconds=total_seconds / len(durations)
    )


@login_required
def dashboard(request):
    """
    Main IDDS reporting dashboard.

    Reports are calculated directly from operational data:
    DiningSession -> Order -> OrderItem.

    The Staff Performance Report is included at the bottom
    of this same Reports page.
    """

    if not request.user.is_authenticated or not request.user.is_superuser:
        return render(
            request,
            "reports/dashboard.html",
            {
                "access_denied": True,
            },
        )

    today = timezone.localdate()

    # =========================================================
    # REPORT PERIOD
    # =========================================================

    period = request.GET.get("period", "today")

    start_date = today
    end_date = today
    period_label = "Today"

    if period == "week":
        # Monday through today
        start_date = today - timedelta(days=today.weekday())
        period_label = "This Week"

    elif period == "month":
        start_date = today.replace(day=1)
        period_label = "This Month"

    elif period == "custom":
        custom_start = request.GET.get("start_date")
        custom_end = request.GET.get("end_date")

        if custom_start and custom_end:
            try:
                from datetime import date

                parsed_start = date.fromisoformat(custom_start)
                parsed_end = date.fromisoformat(custom_end)

                if parsed_start <= parsed_end:
                    start_date = parsed_start
                    end_date = parsed_end
                    period_label = (
                        f"{start_date.strftime('%d %b %Y')} "
                        f"— {end_date.strftime('%d %b %Y')}"
                    )
                else:
                    period = "today"
                    period_label = "Today"

            except ValueError:
                period = "today"
                period_label = "Today"

    # =========================================================
    # ORDERS
    # =========================================================

    orders = (
        Order.objects
        .exclude(status="cancelled")
        .select_related(
            "session",
            "session__table",
            "assigned_chef",
            "assigned_waiter",
        )
    )

    orders = orders.filter(
        created_at__date__gte=start_date,
        created_at__date__lte=end_date,
    )

    # =========================================================
    # ORDER ITEMS / REVENUE
    # =========================================================

    order_items = OrderItem.objects.filter(
        order__in=orders
    )

    item_revenue_expression = ExpressionWrapper(
        F("unit_price") * F("quantity"),
        output_field=DecimalField(
            max_digits=12,
            decimal_places=2,
        ),
    )

    total_revenue = order_items.aggregate(
        total=Coalesce(
            Sum(item_revenue_expression),
            Decimal("0.00"),
        )
    )["total"]

    total_orders = orders.count()

    completed_orders = orders.filter(
        status="completed"
    ).count()

    active_orders = orders.filter(
        status__in=[
            "new",
            "accepted",
            "preparing",
            "ready",
            "served",
        ]
    ).count()

    # =========================================================
    # CANCELLED ORDERS
    # =========================================================

    cancelled_count = (
        Order.objects
        .filter(status="cancelled")
        .filter(
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
        )
        .count()
    )

    # =========================================================
    # AVERAGE ORDER VALUE
    # =========================================================

    if total_orders:
        average_order_value = (
            total_revenue / total_orders
        )
    else:
        average_order_value = Decimal("0.00")

    # =========================================================
    # TOP SELLING MENU ITEMS
    # =========================================================

    top_items = (
        order_items
        .values(
            "menu_item_id",
            "item_name",
        )
        .annotate(
            quantity_sold=Coalesce(
                Sum("quantity"),
                0,
            ),
            revenue=Coalesce(
                Sum(item_revenue_expression),
                Decimal("0.00"),
            ),
        )
        .order_by(
            "-quantity_sold",
            "-revenue",
        )[:10]
    )

    # =========================================================
    # ORDER STATUS
    # =========================================================

    status_breakdown = (
        orders
        .values("status")
        .annotate(
            count=Count("id")
        )
        .order_by("-count")
    )

    # =========================================================
    # TABLE USAGE
    # =========================================================

    table_usage = (
        DiningSession.objects
        .filter(
            orders__in=orders
        )
        .values(
            "table__table_number"
        )
        .annotate(
            session_count=Count(
                "id",
                distinct=True,
            ),
            order_count=Count(
                "orders",
                distinct=True,
            ),
        )
        .order_by(
            "-order_count",
            "table__table_number",
        )[:10]
    )

    # =========================================================
    # DINING SESSIONS FOR SELECTED PERIOD
    # =========================================================

    period_sessions = DiningSession.objects.filter(
        started_at__date__gte=start_date,
        started_at__date__lte=end_date,
    )

    total_sessions = period_sessions.count()

    completed_sessions = period_sessions.filter(
        status="completed"
    ).count()

    # =========================================================
    # CURRENT ACTIVE SESSIONS
    # =========================================================

    active_sessions = DiningSession.objects.filter(
        status="active"
    ).count()

    # =========================================================
    # MENU STATISTICS
    # =========================================================

    total_menu_items = MenuItem.objects.count()

    available_menu_items = MenuItem.objects.filter(
        is_available=True
    ).count()

    unavailable_menu_items = MenuItem.objects.filter(
        is_available=False
    ).count()

    # =========================================================
    # TABLE STATISTICS
    # =========================================================

    total_tables = DiningTable.objects.count()

    available_tables = DiningTable.objects.filter(
        status="available"
    ).count()

    occupied_tables = DiningTable.objects.exclude(
        status="available"
    ).count()

    # =========================================================
    # STAFF PERFORMANCE REPORT
    # =========================================================

    # We use the same report period selected above.
    #
    # Timing fields already exist on Order:
    #
    # created_at     = order placed
    # accepted_at   = chef accepted order
    # preparing_at  = chef started preparing
    # ready_at      = food ready
    # served_at     = waiter served customer
    #
    # Therefore no database migration is required.

    staff_orders = list(
        orders.order_by("-created_at")
    )

    # ---------------------------------------------------------
    # CHEF PERFORMANCE
    # ---------------------------------------------------------

    chef_data = defaultdict(
        lambda: {
            "orders": 0,
            "order_to_start": [],
            "prep_times": [],
        }
    )

    # ---------------------------------------------------------
    # WAITER PERFORMANCE
    # ---------------------------------------------------------

    waiter_data = defaultdict(
        lambda: {
            "orders": 0,
            "service_times": [],
            "total_times": [],
        }
    )

    # ---------------------------------------------------------
    # DETAILED ORDER TIMING
    # ---------------------------------------------------------

    performance_orders = []

    for order in staff_orders:

        # =====================================================
        # CHEF
        # =====================================================

        chef = getattr(order, "assigned_chef", None)

        if chef:
            chef_name = (
                chef.get_full_name()
                or chef.username
            )

            chef_data[chef.id]["name"] = chef_name
            chef_data[chef.id]["orders"] += 1

            # Order placed -> chef started preparing
            if (
                order.created_at
                and order.preparing_at
            ):
                order_to_start = (
                    order.preparing_at
                    - order.created_at
                )

                if order_to_start.total_seconds() >= 0:
                    chef_data[chef.id][
                        "order_to_start"
                    ].append(order_to_start)

            # Chef preparation time
            if (
                order.preparing_at
                and order.ready_at
            ):
                prep_time = (
                    order.ready_at
                    - order.preparing_at
                )

                if prep_time.total_seconds() >= 0:
                    chef_data[chef.id][
                        "prep_times"
                    ].append(prep_time)

        # =====================================================
        # WAITER
        # =====================================================

        waiter = getattr(order, "assigned_waiter", None)

        if waiter:
            waiter_name = (
                waiter.get_full_name()
                or waiter.username
            )

            waiter_data[waiter.id]["name"] = waiter_name
            waiter_data[waiter.id]["orders"] += 1

            # Food ready -> waiter served customer
            if (
                order.ready_at
                and order.served_at
            ):
                service_time = (
                    order.served_at
                    - order.ready_at
                )

                if service_time.total_seconds() >= 0:
                    waiter_data[waiter.id][
                        "service_times"
                    ].append(service_time)

            # Order placed -> customer served
            if (
                order.created_at
                and order.served_at
            ):
                total_time = (
                    order.served_at
                    - order.created_at
                )

                if total_time.total_seconds() >= 0:
                    waiter_data[waiter.id][
                        "total_times"
                    ].append(total_time)

        # =====================================================
        # DETAILED ORDER TIMING ROW
        # =====================================================

        order_to_start = None
        prep_time = None
        ready_to_served = None
        total_time = None

        if (
            order.created_at
            and order.preparing_at
        ):
            value = (
                order.preparing_at
                - order.created_at
            )

            if value.total_seconds() >= 0:
                order_to_start = value

        if (
            order.preparing_at
            and order.ready_at
        ):
            value = (
                order.ready_at
                - order.preparing_at
            )

            if value.total_seconds() >= 0:
                prep_time = value

        if (
            order.ready_at
            and order.served_at
        ):
            value = (
                order.served_at
                - order.ready_at
            )

            if value.total_seconds() >= 0:
                ready_to_served = value

        if (
            order.created_at
            and order.served_at
        ):
            value = (
                order.served_at
                - order.created_at
            )

            if value.total_seconds() >= 0:
                total_time = value

        performance_orders.append(
            {
                "id": order.id,

                "status": order.status,

                "chef": (
                    (
                        order.assigned_chef.get_full_name()
                        or order.assigned_chef.username
                    )
                    if order.assigned_chef
                    else "Not assigned"
                ),

                "waiter": (
                    (
                        order.assigned_waiter.get_full_name()
                        or order.assigned_waiter.username
                    )
                    if order.assigned_waiter
                    else "Not assigned"
                ),

                "order_to_start": format_duration(
                    order_to_start
                ),

                "prep_time": format_duration(
                    prep_time
                ),

                "ready_to_served": format_duration(
                    ready_to_served
                ),

                "total_time": format_duration(
                    total_time
                ),
            }
        )

    # ---------------------------------------------------------
    # BUILD CHEF REPORT
    # ---------------------------------------------------------

    chef_performance = []

    User = get_user_model()

    chefs = User.objects.filter(
        id__in=(
            Order.objects
            .filter(
                created_at__date__gte=start_date,
                created_at__date__lte=end_date,
                assigned_chef__isnull=False,
            )
            .values_list(
                "assigned_chef_id",
                flat=True,
            )
            .distinct()
        )
    ).order_by(
        "first_name",
        "last_name",
        "username",
    )

    for chef in chefs:
        data = chef_data.get(
            chef.id,
            {
                "orders": 0,
                "order_to_start": [],
                "prep_times": [],
            },
        )

        chef_performance.append(
            {
                "name": (
                    chef.get_full_name()
                    or chef.username
                ),

                "orders": data["orders"],

                "avg_order_to_start": format_duration(
                    average_duration(
                        data["order_to_start"]
                    )
                ),

                "avg_prep_time": format_duration(
                    average_duration(
                        data["prep_times"]
                    )
                ),
            }
        )

    # ---------------------------------------------------------
    # BUILD WAITER REPORT
    # ---------------------------------------------------------

    waiter_performance = []

    waiters = User.objects.filter(
        id__in=(
            Order.objects
            .filter(
                created_at__date__gte=start_date,
                created_at__date__lte=end_date,
                assigned_waiter__isnull=False,
            )
            .values_list(
                "assigned_waiter_id",
                flat=True,
            )
            .distinct()
        )
    ).order_by(
        "first_name",
        "last_name",
        "username",
    )

    for waiter in waiters:
        data = waiter_data.get(
            waiter.id,
            {
                "orders": 0,
                "service_times": [],
                "total_times": [],
            },
        )

        waiter_performance.append(
            {
                "name": (
                    waiter.get_full_name()
                    or waiter.username
                ),

                "orders": data["orders"],

                "avg_service_time": format_duration(
                    average_duration(
                        data["service_times"]
                    )
                ),

                "avg_total_time": format_duration(
                    average_duration(
                        data["total_times"]
                    )
                ),
            }
        )

    # ---------------------------------------------------------
    # LIMIT DETAILED REPORT
    #
    # The summary contains all orders.
    # The detailed table shows the latest 50 orders so the
    # Reports page does not become unnecessarily huge.
    # ---------------------------------------------------------

    performance_orders = performance_orders[:50]

    # =========================================================
    # CONTEXT
    # =========================================================

    context = {
        "period": period,
        "period_label": period_label,

        "start_date": start_date,
        "end_date": end_date,
        "today": today,

        "total_revenue": total_revenue,
        "total_orders": total_orders,
        "completed_orders": completed_orders,
        "active_orders": active_orders,
        "cancelled_count": cancelled_count,
        "average_order_value": average_order_value,

        "top_items": top_items,
        "status_breakdown": status_breakdown,
        "table_usage": table_usage,

        "total_sessions": total_sessions,
        "completed_sessions": completed_sessions,
        "active_sessions": active_sessions,

        "total_menu_items": total_menu_items,
        "available_menu_items": available_menu_items,
        "unavailable_menu_items": unavailable_menu_items,

        "total_tables": total_tables,
        "available_tables": available_tables,
        "occupied_tables": occupied_tables,

        # =====================================================
        # STAFF PERFORMANCE
        # =====================================================

        "chef_performance": chef_performance,
        "waiter_performance": waiter_performance,
        "performance_orders": performance_orders,

        "access_denied": False,
    }

    return render(
        request,
        "reports/dashboard.html",
        context,
    )