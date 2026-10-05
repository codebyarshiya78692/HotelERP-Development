from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


User = get_user_model()


class AccountsTests(TestCase):

    def test_login_page_loads(self):
        response = self.client.get(
            reverse("accounts:login")
        )

        self.assertEqual(response.status_code, 200)

    def test_user_can_login(self):
        User.objects.create_user(
            username="testuser",
            password="TestPassword123",
        )

        response = self.client.post(
            reverse("accounts:login"),
            {
                "username": "testuser",
                "password": "TestPassword123",
            },
        )

        self.assertEqual(response.status_code, 302)

    def test_invalid_login_is_rejected(self):
        User.objects.create_user(
            username="testuser",
            password="TestPassword123",
        )

        response = self.client.post(
            reverse("accounts:login"),
            {
                "username": "testuser",
                "password": "WrongPassword",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)

class RoleAndIsolationTests(TestCase):

    def setUp(self):
        from django.contrib.auth.models import Group
        from orders.models import DiningSession, Order
        from restaurant.models import DiningTable

        self.Group = Group
        self.DiningSession = DiningSession
        self.Order = Order
        self.DiningTable = DiningTable

        self.customer_a = User.objects.create_user(
            username="customer_a",
            password="CustomerA@12345",
        )
        self.customer_b = User.objects.create_user(
            username="customer_b",
            password="CustomerB@12345",
        )
        self.chef = User.objects.create_user(
            username="test_chef",
            password="Chef@12345",
        )
        self.waiter = User.objects.create_user(
            username="test_waiter",
            password="Waiter@12345",
        )
        self.admin = User.objects.create_superuser(
            username="test_admin",
            password="Admin@12345",
            email="admin@test.example",
        )

        chef_group, _ = Group.objects.get_or_create(name="Chef")
        waiter_group, _ = Group.objects.get_or_create(name="Waiter")
        self.chef.groups.add(chef_group)
        self.waiter.groups.add(waiter_group)

    def test_customer_login_routes_to_customer_dashboard(self):
        response = self.client.post(
            reverse("accounts:login"),
            {
                "username": "customer_a",
                "password": "CustomerA@12345",
            },
        )
        self.assertRedirects(
            response,
            reverse("accounts:dashboard"),
        )

    def test_chef_login_routes_to_kitchen(self):
        response = self.client.post(
            reverse("accounts:login"),
            {
                "username": "test_chef",
                "password": "Chef@12345",
            },
        )
        self.assertRedirects(
            response,
            reverse("kitchen:dashboard"),
        )

    def test_waiter_login_routes_to_waiter_dashboard(self):
        response = self.client.post(
            reverse("accounts:login"),
            {
                "username": "test_waiter",
                "password": "Waiter@12345",
            },
        )
        self.assertRedirects(
            response,
            reverse("accounts:waiter_dashboard"),
        )

    def test_admin_login_routes_to_admin(self):
        response = self.client.post(
            reverse("accounts:login"),
            {
                "username": "test_admin",
                "password": "Admin@12345",
            },
        )
        self.assertRedirects(
            response,
            "/admin/",
            fetch_redirect_response=False,
        )

    def test_customer_cannot_view_another_customers_order(self):
        table = self.DiningTable.objects.create(
            table_number=991,
            capacity=4,
            status="available",
        )
        session_a = self.DiningSession.objects.create(
            table=table,
            customer_name=self.customer_a.username,
            status="active",
        )
        order_a = self.Order.objects.create(
            session=session_a,
            status="new",
        )

        self.client.force_login(self.customer_b)

        response = self.client.get(
            reverse(
                "accounts:order_detail",
                kwargs={"order_id": order_a.id},
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_customer_dashboard_only_queries_own_orders(self):
        table = self.DiningTable.objects.create(
            table_number=992,
            capacity=4,
            status="available",
        )
        session_a = self.DiningSession.objects.create(
            table=table,
            customer_name=self.customer_a.username,
            status="active",
        )
        self.Order.objects.create(
            session=session_a,
            status="new",
        )

        self.client.force_login(self.customer_b)
        response = self.client.get(reverse("accounts:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["recent_orders"].filter(
                session__customer_name=self.customer_b.username
            ).count(),
            0,
        )

