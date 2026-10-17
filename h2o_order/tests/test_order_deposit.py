from odoo.tests import new_test_user, tagged
from odoo.exceptions import AccessError

from .common import H2oOrderCase


@tagged('post_install', '-at_install')
class TestOrderDeposit(H2oOrderCase):

    def test_returnable_qty(self):
        order = self._order([(self.water, 3), (self.water_5l, 4)])
        self.assertEqual(order._h2o_returnable_qty_by_container(), {self.bottle: 3})

    def test_deposit_lines_follow_empties(self):
        order = self._order([(self.water, 3), (self.water_5l, 2)], h2o_empties_expected=1)
        order.action_h2o_update_deposit_lines()
        self.assertEqual(self._deposit_qty(order), (2, 1))
        deposit_line = order.order_line.filtered(lambda line: line.product_id == self.deposit)
        self.assertEqual(deposit_line.price_unit, 250.0)

        order.h2o_empties_expected = 0
        order.action_h2o_update_deposit_lines()
        self.assertEqual(self._deposit_qty(order), (3, 1))

        order.h2o_empties_expected = 5
        order.action_h2o_update_deposit_lines()
        self.assertEqual(self._deposit_qty(order), (0, 0))

    def test_deposit_added_on_confirm(self):
        order = self._order([(self.water, 4)], h2o_empties_expected=2)
        order.action_confirm()
        self.assertEqual(order.state, 'sale')
        self.assertEqual(self._deposit_qty(order), (2, 1))
        # on a confirmed order the line is zeroed rather than removed
        order.h2o_empties_expected = 4
        order.action_h2o_update_deposit_lines()
        self.assertEqual(self._deposit_qty(order), (0, 1))

    def test_packaged_water_no_deposit(self):
        order = self._order([(self.water_5l, 10)])
        order.action_confirm()
        self.assertTrue(order.h2o_is_delivery)
        self.assertEqual(self._deposit_qty(order), (0, 0))

    def test_cancel_sets_delivery_state(self):
        order = self._order([(self.water, 1)], h2o_empties_expected=1)
        order.action_confirm()
        order._action_cancel()
        self.assertEqual(order.h2o_delivery_state, 'cancelled')
        order.action_draft()
        self.assertEqual(order.h2o_delivery_state, 'to_plan')

    def test_access(self):
        dispatcher = new_test_user(self.env, login='h2o_ord_dispatcher', groups='h2o_base.group_h2o_dispatcher')
        driver = new_test_user(self.env, login='h2o_ord_driver', groups='h2o_base.group_h2o_driver')
        order = self._order([(self.water, 2)]).with_user(dispatcher)
        order.write({'h2o_empties_expected': 1})
        order.action_confirm()
        self.assertEqual(self._deposit_qty(order), (1, 1))
        with self.assertRaises(AccessError):
            self.env['sale.order'].with_user(driver).create({'partner_id': self.customer.id})
