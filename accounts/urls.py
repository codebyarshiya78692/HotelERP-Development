from django.contrib.auth import views as auth_views
from django.urls import path

from . import auth_views as account_auth_views
from . import views


app_name = "accounts"


urlpatterns = [

    # ========================================================
    # LOGIN / LOGOUT
    # ========================================================

    path(
        "login/",
        views.customer_login,
        name="login",
    ),

    path(
        "logout/",
        views.customer_logout,
        name="logout",
    ),


    # ========================================================
    # CUSTOMER SIGNUP
    # ========================================================

    path(
        "signup/",
        account_auth_views.signup,
        name="signup",
    ),


    # ========================================================
    # CUSTOMER DASHBOARD
    # ========================================================

    path(
        "dashboard/",
        views.dashboard,
        name="dashboard",
    ),


    # ========================================================
    # CUSTOMER ORDERS
    # ========================================================

    path(
        "orders/",
        views.my_orders,
        name="my_orders",
    ),

    path(
        "orders/<int:order_id>/",
        views.order_detail,
        name="order_detail",
    ),

    path(
        "orders/<int:order_id>/track/",
        views.track_order,
        name="track_order",
    ),

    path(
        "orders/<int:order_id>/cancel/",
        views.cancel_order,
        name="cancel_order",
    ),

    path(
        "orders/<int:order_id>/summary/",
        views.order_summary,
        name="order_summary",
    ),

    path(
        "orders/<int:order_id>/feedback/",
        views.feedback_redirect,
        name="feedback_redirect",
    ),


    # ========================================================
    # CUSTOMER DINING SESSION
    # ========================================================

    path(
        "session/start/<int:table_id>/",
        views.start_session,
        name="start_session",
    ),

    path(
        "session/<int:session_id>/close/",
        views.close_session,
        name="close_session",
    ),

    path(
        "active-session/",
        views.active_session,
        name="active_session",
    ),


    # ========================================================
    # CUSTOMER SERVICE REQUESTS
    # ========================================================

    path(
        "service-requests/",
        views.my_service_requests,
        name="my_service_requests",
    ),

    path(
        "service-requests/create/",
        views.create_service_request,
        name="create_service_request",
    ),


    # ========================================================
    # CUSTOMER TABLES / PROFILE
    # ========================================================

    path(
        "tables/",
        views.available_tables,
        name="available_tables",
    ),

    path(
        "profile/",
        views.profile,
        name="profile",
    ),


    # ========================================================
    # PASSWORD RESET
    # ========================================================

    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="registration/password_reset_form.html",
            email_template_name="registration/password_reset_email.html",
            subject_template_name="registration/password_reset_subject.txt",
            success_url="/accounts/password-reset/done/",
        ),
        name="password_reset",
    ),

    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="registration/password_reset_done.html",
        ),
        name="password_reset_done",
    ),

    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="registration/password_reset_confirm.html",
            success_url="/accounts/reset/done/",
        ),
        name="password_reset_confirm",
    ),

    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="registration/password_reset_complete.html",
        ),
        name="password_reset_complete",
    ),


    # ========================================================
    # CHANGE PASSWORD
    # ========================================================

    path(
        "change-password/",
        account_auth_views.CustomerPasswordChangeView.as_view(),
        name="change_password",
    ),


    # ========================================================
    # LEGACY ROLE LOGIN URLS
    # ========================================================

    path(
        "staff/login/",
        views.customer_login,
        name="staff_login",
    ),

    path(
        "chef/login/",
        views.chef_login,
        name="chef_login",
    ),

    path(
        "waiter/login/",
        views.waiter_login,
        name="waiter_login",
    ),


    # ========================================================
    # WAITER DASHBOARD
    # ========================================================

    path(
        "waiter/",
        views.waiter_dashboard,
        name="waiter_dashboard",
    ),

    path(
        "waiter/request/<int:request_id>/accept/",
        views.waiter_accept_request,
        name="waiter_accept_request",
    ),

    path(
        "waiter/request/<int:request_id>/complete/",
        views.waiter_complete_request,
        name="waiter_complete_request",
    ),

    path(
        "waiter/order/<int:order_id>/serve/",
        views.waiter_serve_order,
        name="waiter_serve_order",
    ),

    path(
        "waiter/order/<int:order_id>/take/",
        views.waiter_take_order,
        name="waiter_take_order",
    ),


    # ========================================================
    # STAFF DASHBOARD
    # ========================================================

    path(
        "staff/",
        views.staff_dashboard,
        name="staff_dashboard",
    ),

    path(
        "staff/orders/",
        views.staff_orders,
        name="staff_orders",
    ),

    path(
        "staff/requests/",
        views.staff_requests,
        name="staff_requests",
    ),

    path(
        "role-dashboard/",
        views.role_dashboard,
        name="role_dashboard",
    ),

    path(
        "system-status/",
        views.system_status,
        name="system_status",
    ),
]       