from datetime import date
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import freeze_time, new_test_user, tagged

from odoo.addons.h2o_subscription.models.h2o_subscription import H2oSubscription

from .common import H2oSubscriptionCase


@tagged('post_install', '-at_install')
@freeze_time('2026-10-17 08:00')  # Saturday 11:00 in Istanbul
class TestSubscriptionOrders(H2oSubscriptionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dispatcher = new_test_user(cls.env, login='h2o_sub_dispatcher', groups='h2o_base.group_h2o_dispatcher')
        cls.accountant = new_test_user(cls.env, login='h2o_sub_accountant', groups='h2o_base.group_h2o_accountant')
        cls.manager = new_test_user(cls.env, login='h2o_sub_manager', groups='h2o_base.group_h2o_manager')

    def _active(self, next_date=date(2026, 10, 19), **vals):
        subscription = self._subscription(next_date=next_date, **vals)
        subscription.action_activate()
        return subscription

    def _cron(self):
        self.env['h2o.subscription']._cron_h2o_generate_orders()

    def test_cron_lead_days_and_idempotency(self):
        subscription = self._active()
        self._cron()  # lead 1 day: Sunday at most
        self.assertFalse(subscription.order_ids)
        self.assertEqual(subscription.next_date, date(2026, 10, 19))

        self.env.company.h2o_subscription_lead_days = 2
        self._cron()
        self.assertEqual(len(subscription.order_ids), 1)
        self.assertEqual(subscription.order_ids.h2o_delivery_date, date(2026, 10, 19))
        self.assertEqual(subscription.next_date, date(2026, 10, 26))

        self._cron()  # running again changes nothing
        self.assertEqual(subscription.order_count, 1)

        subscription.next_date = date(2026, 10, 19)  # back to a date that already has its order
        self._cron()
        self.assertEqual(subscription.order_count, 1)
        self.assertEqual(subscription.next_date, date(2026, 10, 26))

        self.env.company.h2o_subscription_lead_days = 10  # two deliveries within reach
        self._cron()
        self.assertEqual(
            sorted(subscription.order_ids.mapped('h2o_delivery_date')),
            [date(2026, 10, 19), date(2026, 10, 26)],
        )
        self.assertEqual(subscription.next_date, date(2026, 11, 2))

    def test_only_active_subscriptions(self):
        self.env.company.h2o_subscription_lead_days = 7
        active = self._active()
        paused = self._active()
        paused.action_pause()
        closed = self._active()
        closed.action_close()
        draft = self._subscription(next_date=date(2026, 10, 19))
        self._cron()
        self.assertEqual(active.order_count, 1)
        for subscription in paused | closed | draft:
            self.assertFalse(subscription.order_ids, subscription.state)
            self.assertEqual(subscription.next_date, date(2026, 10, 19))

    def test_order_content(self):
        pricelist = self.env['product.pricelist'].create({
            'name': 'Subscription Prices',
            'item_ids': [Command.create({
                'applied_on': '1_product', 'product_tmpl_id': self.water.product_tmpl_id.id,
                'compute_price': 'fixed', 'fixed_price': 95.0,
            })],
        })
        self.customer.property_product_pricelist = pricelist
        address = self.env['res.partner'].create({
            'name': 'Office floor 3', 'parent_id': self.customer.id, 'type': 'delivery', 'zip': '39001',
        })
        pack = self.env.ref('h2o_container.uom_pack_4')
        subscription = self._subscription(
            lines=[(self.water, 3)], time_window='afternoon', note='Ring twice', frequency='monthly',
            next_date=date(2026, 10, 19),
        )
        subscription.line_ids = [Command.create({'product_id': self.water_5l.id, 'qty': 2, 'product_uom_id': pack.id})]
        self.assertEqual(subscription.address_id, address)
        self.assertEqual(subscription.empties_expected, 3)
        subscription.empties_expected = 1
        subscription.action_activate()

        action = subscription.with_user(self.dispatcher).action_h2o_generate_now()
        order = self.env['sale.order'].browse(action['res_id'])
        self.assertEqual(order.state, 'sale')
        self.assertEqual(order.h2o_channel, 'subscription')
        self.assertEqual(order.h2o_subscription_id, subscription)
        self.assertEqual(order.origin, subscription.name)
        self.assertEqual(order.partner_shipping_id, address)
        self.assertEqual(order.h2o_zone_id, self.zone)
        self.assertEqual(order.h2o_delivery_date, date(2026, 10, 19))
        self.assertEqual(order.h2o_time_window, 'afternoon')
        self.assertEqual(order.h2o_empties_expected, 1)
        self.assertEqual(order.h2o_delivery_state, 'to_plan')
        self.assertIn('Ring twice', str(order.note))
        self.assertEqual(order.pricelist_id, pricelist)
        water_line = order.order_line.filtered(lambda line: line.product_id == self.water)
        self.assertEqual(water_line.price_unit, 95.0)
        pack_line = order.order_line.filtered(lambda line: line.product_id == self.water_5l)
        self.assertEqual((pack_line.product_uom_qty, pack_line.product_uom_id), (2, pack))
        self.assertEqual(self._deposit_qty(order), (2, 1))
        # monthly: the 3rd Monday of October gives the 3rd Monday of November
        self.assertEqual(subscription.next_date, date(2026, 11, 16))
        self.assertEqual(subscription.order_count, 1)
        self.assertEqual(self.env['sale.order'].search(subscription.action_view_orders()['domain']), order)

    def test_failing_subscription_skipped(self):
        failing = self._active()
        working = self._active()
        original = H2oSubscription._h2o_prepare_order_values

        def prepare(subscription, delivery_date):
            if subscription == failing:
                raise UserError("No water today")  # pylint: disable=translation-required
            return original(subscription, delivery_date)

        with patch.object(H2oSubscription, '_h2o_prepare_order_values', autospec=True, side_effect=prepare), \
                self.assertLogs('odoo.addons.h2o_subscription.models.h2o_subscription', 'WARNING') as logs:
            orders = (failing | working)._h2o_generate_due_orders(date(2026, 10, 19))
        self.assertIn(failing.name, logs.output[0])
        self.assertEqual(orders, working.order_ids)
        self.assertFalse(failing.order_ids)
        self.assertEqual(failing.next_date, date(2026, 10, 19))
        self.assertEqual(working.next_date, date(2026, 10, 26))

    def test_access_rights(self):
        subscription = self._subscription()
        as_dispatcher = subscription.with_user(self.dispatcher)
        as_dispatcher.time_window = 'evening'
        as_dispatcher.action_activate()
        self.assertEqual(subscription.state, 'active')
        self.env['h2o.subscription'].with_user(self.dispatcher).create({
            'partner_id': self.customer.id, 'weekday_id': self.thu.id,
        })

        as_accountant = subscription.with_user(self.accountant)
        self.assertEqual(as_accountant.line_ids.product_id, self.water)
        with self.assertRaises(AccessError):
            as_accountant.time_window = 'morning'
        with self.assertRaises(AccessError):
            as_accountant.action_pause()

        with self.assertRaises(UserError):
            subscription.with_user(self.manager).unlink()  # still running
        as_dispatcher.action_close()
        with self.assertRaises(AccessError):
            as_dispatcher.unlink()
        subscription.with_user(self.manager).unlink()
        self.assertFalse(subscription.exists())
