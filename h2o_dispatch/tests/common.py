from datetime import date

from odoo import Command
from odoo.tests import TransactionCase, new_test_user


class H2oDispatchCase(TransactionCase):
    """A route over one zone, a van, two drivers, a dispatcher and two customers."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.date = date(2030, 1, 7)  # a Monday
        cls.water = cls.env.ref('h2o_container.product_water_19l')
        cls.water_5l = cls.env.ref('h2o_container.product_water_5l')
        cls.bottle = cls.env.ref('h2o_container.product_bottle_19l')
        cls.deposit = cls.env.ref('h2o_container.product_deposit_19l')
        cls.driver_a = new_test_user(cls.env, login='h2o_dispatch_driver_a', groups='h2o_base.group_h2o_driver')
        cls.driver_b = new_test_user(cls.env, login='h2o_dispatch_driver_b', groups='h2o_base.group_h2o_driver')
        cls.dispatcher = new_test_user(cls.env, login='h2o_dispatch_dispatcher',
                                       groups='h2o_base.group_h2o_dispatcher')
        brand = cls.env['fleet.vehicle.model.brand'].create({'name': 'H2O Test Brand'})
        model = cls.env['fleet.vehicle.model'].create({'name': 'Van', 'brand_id': brand.id})
        cls.van = cls.env['fleet.vehicle'].create({
            'license_plate': '06 TST 01', 'model_id': model.id,
            'h2o_is_delivery_vehicle': True, 'h2o_capacity': 80, 'h2o_driver_user_id': cls.driver_a.id,
        })
        cls.van_b = cls.env['fleet.vehicle'].create({
            'license_plate': '06 TST 02', 'model_id': model.id, 'h2o_is_delivery_vehicle': True,
        })
        cls.route = cls.env['h2o.route'].create({
            'name': 'Test Route', 'vehicle_id': cls.van.id,
            'weekday_ids': [Command.set(cls.env.ref('h2o_base.weekday_mon').ids)],
        })
        # keep the demo routes out of the day's planning
        cls.env['h2o.route'].search([('id', '!=', cls.route.id)]).action_archive()
        cls.zone = cls.env['h2o.zone'].create({
            'name': 'Dispatch Zone', 'zip_codes': '06001', 'sequence': 1, 'h2o_route_id': cls.route.id,
        })
        cls.zone_2 = cls.env['h2o.zone'].create({
            'name': 'Dispatch Zone 2', 'zip_codes': '06002', 'sequence': 2, 'h2o_route_id': cls.route.id,
        })
        cls.cash_customer = cls.env['res.partner'].create({
            'name': 'Cash Customer', 'h2o_customer_type': 'home', 'zip': '06001',
            'partner_latitude': 39.92, 'partner_longitude': 32.85,
        })
        cls.account_customer = cls.env['res.partner'].create({
            'name': 'Account Customer', 'h2o_customer_type': 'office', 'zip': '06002',
            'h2o_payment_mode': 'account',
        })

    @classmethod
    def _order(cls, partner, lines, empties=0, delivery_date=None, confirm=True):
        order = cls.env['sale.order'].create({
            'partner_id': partner.id,
            'h2o_empties_expected': empties,
            'order_line': [Command.create({'product_id': p.id, 'product_uom_qty': qty}) for p, qty in lines],
        })
        order.h2o_delivery_date = delivery_date or cls.date
        if confirm:
            order.action_confirm()
        return order

    def _planned_trip(self):
        return self.env['h2o.trip']._h2o_plan_day(self.date, self.route)

    def _started_trip(self):
        trip = self._planned_trip()
        trip.action_start()
        return trip
