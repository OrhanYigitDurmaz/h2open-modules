from odoo import Command
from odoo.tests import TransactionCase


class H2oOrderCase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.company.partner_id.tz = 'Europe/Istanbul'
        cls.env.company.h2o_order_cutoff_hour = 16.0
        cls.mon = cls.env.ref('h2o_base.weekday_mon')
        cls.thu = cls.env.ref('h2o_base.weekday_thu')
        cls.zone = cls.env['h2o.zone'].create({
            'name': 'Order Zone', 'zip_codes': '39001',
            'weekday_ids': [Command.set([cls.mon.id, cls.thu.id])],
        })
        cls.water = cls.env.ref('h2o_container.product_water_19l')
        cls.water_5l = cls.env.ref('h2o_container.product_water_5l')
        cls.bottle = cls.env.ref('h2o_container.product_bottle_19l')
        cls.deposit = cls.env.ref('h2o_container.product_deposit_19l')
        cls.customer = cls.env['res.partner'].create({
            'name': 'Order Home', 'h2o_customer_type': 'home', 'zip': '39001',
        })

    def _order(self, lines, **vals):
        return self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [Command.create({'product_id': product.id, 'product_uom_qty': qty}) for product, qty in lines],
            **vals,
        })

    def _deposit_qty(self, order):
        lines = order.order_line.filtered(lambda line: line.product_id == self.deposit)
        return sum(lines.mapped('product_uom_qty')), len(lines)
