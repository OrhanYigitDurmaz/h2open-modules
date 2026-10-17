from datetime import date, datetime

from odoo.tests import tagged

from .common import H2oOrderCase


@tagged('post_install', '-at_install')
class TestDeliveryDate(H2oOrderCase):

    def test_next_delivery_date(self):
        self.assertEqual(self.customer.h2o_zone_id, self.zone)
        cases = [
            # (UTC now, expected) - Istanbul is UTC+3; 2026-10-19 is a Monday
            (datetime(2026, 10, 19, 10, 0), date(2026, 10, 19)),   # 13:00 Monday, before cut-off
            (datetime(2026, 10, 19, 13, 30), date(2026, 10, 22)),  # 16:30 Monday, after cut-off -> Thursday
            (datetime(2026, 10, 18, 22, 0), date(2026, 10, 19)),   # Monday 01:00 local
            (datetime(2026, 10, 20, 8, 0), date(2026, 10, 22)),    # Tuesday -> Thursday
            (datetime(2026, 10, 22, 14, 0), date(2026, 10, 26)),   # Thursday 17:00 -> next Monday
        ]
        for now, expected in cases:
            self.assertEqual(self.customer._h2o_next_delivery_date(now), expected, now)

    def test_own_days_and_no_days(self):
        self.customer.h2o_weekday_ids = self.env.ref('h2o_base.weekday_sat')
        self.assertEqual(self.customer._h2o_next_delivery_date(datetime(2026, 10, 19, 10, 0)), date(2026, 10, 24))
        partner = self.env['res.partner'].create({'name': 'No Zone', 'h2o_customer_type': 'home'})
        self.assertEqual(partner._h2o_next_delivery_date(datetime(2026, 10, 20, 10, 0)), date(2026, 10, 20))
        self.assertEqual(partner._h2o_next_delivery_date(datetime(2026, 10, 20, 15, 0)), date(2026, 10, 21))

    def test_order_defaults(self):
        order = self._order([(self.water, 1)])
        self.assertEqual(order.h2o_delivery_date, self.customer._h2o_next_delivery_date())
        self.assertEqual(order.h2o_zone_id, self.zone)
        self.assertEqual(order.h2o_channel, 'phone')
        self.assertEqual(order.h2o_delivery_state, 'to_plan')
        self.assertTrue(order.h2o_is_delivery)
        explicit = self._order([(self.water, 1)], h2o_delivery_date=date(2030, 1, 3))
        self.assertEqual(explicit.h2o_delivery_date, date(2030, 1, 3))
        service = self.env['product.product'].create({'name': 'Cleaning', 'type': 'service'})
        self.assertFalse(self._order([(service, 1)]).h2o_is_delivery)
