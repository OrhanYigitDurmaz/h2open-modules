from datetime import date

from odoo import Command
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests import new_test_user


class H2oBillingCase(AccountTestInvoicingCommon):
    """A Turkish company (TRY, generic chart) with a delivery route, a driver,
    an accountant, and customers paying cash, by card and on account."""

    chart_template = 'generic_coa'
    country_code = 'TR'

    @classmethod
    def setup_independent_company(cls, **kwargs):
        cls.env.ref('base.TRY').active = True
        return super().setup_independent_company(**kwargs)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids += cls.env.ref('h2o_base.group_h2o_manager')
        cls.company = cls.env.company
        cls.date = date(2030, 1, 7)  # a Monday

        cls.deposit_account = cls.env['account.account'].create({
            'name': 'Bottle deposits', 'code': '329950', 'account_type': 'liability_current',
        })
        cls.cash_journal = cls.company_data['default_journal_cash']
        cls.card_journal = cls.company_data['default_journal_bank']
        cls.company.write({
            'h2o_deposit_account_id': cls.deposit_account.id,
            'h2o_cash_journal_id': cls.cash_journal.id,
            'h2o_card_journal_id': cls.card_journal.id,
        })

        cls.water = cls.env.ref('h2o_container.product_water_19l')
        cls.water.taxes_id |= cls.tax_sale_a
        cls.deposit = cls.env.ref('h2o_container.product_deposit_19l')

        cls.driver = new_test_user(cls.env, login='h2o_billing_driver', groups='h2o_base.group_h2o_driver')
        cls.driver_b = new_test_user(cls.env, login='h2o_billing_driver_b', groups='h2o_base.group_h2o_driver')
        cls.accountant = new_test_user(cls.env, login='h2o_billing_accountant',
                                       groups='h2o_base.group_h2o_accountant')
        brand = cls.env['fleet.vehicle.model.brand'].create({'name': 'H2O Billing Brand'})
        van = cls.env['fleet.vehicle'].create({
            'license_plate': '34 BIL 01', 'h2o_is_delivery_vehicle': True, 'h2o_driver_user_id': cls.driver.id,
            'model_id': cls.env['fleet.vehicle.model'].create({'name': 'Van', 'brand_id': brand.id}).id,
        })
        cls.route = cls.env['h2o.route'].create({
            'name': 'Billing Route', 'vehicle_id': van.id,
            'weekday_ids': [Command.set(cls.env.ref('h2o_base.weekday_mon').ids)],
        })
        cls.env['h2o.zone'].create({'name': 'Billing Zone', 'zip_codes': '34001', 'h2o_route_id': cls.route.id})

        def customer(name, mode):
            return cls.env['res.partner'].create({
                'name': name, 'h2o_customer_type': 'home', 'zip': '34001', 'h2o_payment_mode': mode,
            })
        cls.cash_customer = customer('Cash Customer', 'cash')
        cls.card_customer = customer('Card Customer', 'card')
        cls.account_customer = customer('Account Customer', 'account')

    @classmethod
    def _order(cls, partner, water_qty=2, empties=0, delivery_date=None):
        """A confirmed order of 19 L bottles: a deposit is charged for the
        bottles not matched by empties."""
        order = cls.env['sale.order'].create({
            'partner_id': partner.id,
            'h2o_empties_expected': empties,
            'order_line': [Command.create({'product_id': cls.water.id, 'product_uom_qty': water_qty})],
        })
        order.h2o_delivery_date = delivery_date or cls.date
        order.action_confirm()
        return order

    def _started_trip(self, day=None):
        trip = self.env['h2o.trip']._h2o_plan_day(day or self.date, self.route)
        trip.action_start()
        return trip

    def _deliver(self, trip, order, vals=None):
        """Deliver the order's stop as the driver."""
        stop = trip.stop_ids.filtered(lambda s: s.order_id == order)
        stop.with_user(self.driver).action_deliver(vals)
        return stop
