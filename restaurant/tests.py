from django.test import TestCase

# Create your tests here.

class RestaurantSecurityTests(TestCase):

    def setUp(self):
        from django.contrib.auth import get_user_model
        from restaurant.models import DiningTable
        User = get_user_model()
        self.customer = User.objects.create_user(
            username="restaurant_customer",
            password="Customer@12345",
        )
        self.table = DiningTable.objects.create(
            table_number=993,
            capacity=4,
            status="available",
        )

    def test_start_dining_requires_login(self):
        response = self.client.get(
            reverse("start_dining", kwargs={"table_id": self.table.id})
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_start_dining_binds_session_to_customer(self):
        self.client.force_login(self.customer)
        response = self.client.get(
            reverse("start_dining", kwargs={"table_id": self.table.id})
        )
        self.assertEqual(response.status_code, 302)

        from orders.models import DiningSession
        session = DiningSession.objects.get(table=self.table)
        self.assertEqual(session.customer_name, self.customer.username)
        self.table.refresh_from_db()
        self.assertEqual(self.table.status, "order_in_progress")

