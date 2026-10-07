    from django.urls import path

    from . import views


    app_name = "orders"


    urlpatterns = [
        path(
            "cart/",
            views.cart,
            name="cart",
        ),

        path(
            "cart/add/<int:item_id>/",
            views.add_to_cart,
            name="add_to_cart",
        ),

        path(
            "cart/update/<int:item_id>/",
            views.update_cart,
            name="update_cart",
        ),

        path(
            "cart/remove/<int:item_id>/",
            views.remove_from_cart,
            name="remove_from_cart",
        ),

        path(
            "place/",
            views.place_order,
            name="place_order",
        ),

        path(
            "my-orders/",
            views.my_orders,
            name="my_orders",
        ),

        # Customer order details
        path(
            "my-orders/<int:order_id>/",
            views.order_detail,
            name="order_detail",
        ),

        # Customer order tracking
        path(
            "<int:order_id>/track/",
            views.order_detail,
            name="order_tracking",
        ),
    ]