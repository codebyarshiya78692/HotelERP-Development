from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from restaurant.views import (
    add_to_cart,
    cart,
    home,
    menu,
    order_confirmation,
    order_tracking,
    place_order,
    start_dining,
    table_selection,
    update_cart,
)

from restaurant.service_views import (
    create_service_request,
    service_requests,
    staff_service_requests,
    staff_service_request_detail,
    accept_service_request,
    complete_service_request,
)

# ============================================================
# DJANGO ADMIN ACCESS
# Only real administrators/superusers may enter Django Admin.
# Chef and Waiter accounts remain operational staff.
# ============================================================

def admin_superuser_only(request):
    return (
        request.user.is_authenticated
        and request.user.is_active
        and request.user.is_superuser
    )


admin.site.has_permission = admin_superuser_only

urlpatterns = [

    # ============================================================
    # MAIN WEBSITE
    # ============================================================

    path(
        "",
        home,
        name="home",
    ),


    # ============================================================
    # ADMIN
    # ============================================================

    path(
        "admin/",
        admin.site.urls,
    ),


    # ============================================================
    # RESTAURANT TABLE MANAGEMENT
    # ============================================================

    path(
        "restaurant/",
        include("restaurant.urls"),
    ),


    # ============================================================
    # ACCOUNTS / LOGIN / STAFF
    # ============================================================

    path(
        "accounts/",
        include("accounts.urls"),
    ),


    # ============================================================
    # CUSTOMER TABLE / DINING FLOW
    # ============================================================

    path(
        "tables/",
        table_selection,
        name="table_selection",
    ),

    path(
        "dining/start/<int:table_id>/",
        start_dining,
        name="start_dining",
    ),

    path(
        "menu/<int:table_id>/",
        menu,
        name="menu",
    ),


    # ============================================================
    # CUSTOMER CART
    # ============================================================

    path(
        "cart/",
        cart,
        name="cart",
    ),

    path(
        "cart/add/<int:item_id>/",
        add_to_cart,
        name="add_to_cart",
    ),

    path(
        "cart/update/<int:item_id>/",
        update_cart,
        name="update_cart",
    ),


    # ============================================================
    # CUSTOMER ORDERS
    # ============================================================

    path(
        "order/place/",
        place_order,
        name="place_order",
    ),

    path(
        "order/<int:order_id>/confirmation/",
        order_confirmation,
        name="order_confirmation",
    ),

    path(
        "order/<int:order_id>/track/",
        order_tracking,
        name="order_tracking",
    ),


    # ============================================================
    # CUSTOMER SERVICE REQUESTS
    # ============================================================

    path(
        "service-requests/",
        service_requests,
        name="service_requests",
    ),

    path(
        "service-requests/create/",
        create_service_request,
        name="create_service_request",
    ),


    # ============================================================
    # STAFF SERVICE REQUESTS
    # ============================================================

    path(
        "service-requests/staff/",
        staff_service_requests,
        name="staff_service_requests",
    ),

    path(
        "service-requests/staff/<int:request_id>/",
        staff_service_request_detail,
        name="staff_service_request_detail",
    ),

    path(
        "service-requests/staff/<int:request_id>/accept/",
        accept_service_request,
        name="staff_service_request_accept",
    ),

    path(
        "service-requests/staff/<int:request_id>/complete/",
        complete_service_request,
        name="staff_service_request_complete",
    ),


    # ============================================================
    # KITCHEN
    # ============================================================

    path(
        "kitchen/",
        include("kitchen.urls"),
    ),


    # ============================================================
    # BILLING
    # ============================================================

    path(
        "billing/",
        include("billing.urls"),
    ),


    # ============================================================
    # REPORTS
    # ============================================================

    path(
        "reports/",
        include("reports.urls"),
    ),


    # ============================================================
    # INVENTORY
    # ============================================================

    path(
        "inventory/",
        include("inventory.urls"),
    ),


    # ============================================================
    # FEEDBACK
    # ============================================================

    path(
        "feedback/",
        include("feedback.urls"),
    ),
]


# ================================================================
# MEDIA FILES
# ================================================================

urlpatterns += static(
    settings.MEDIA_URL,
    document_root=settings.MEDIA_ROOT,
)