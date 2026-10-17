from odoo import Command

from odoo.addons.h2o_order.tests.common import H2oOrderCase


class H2oSubscriptionCase(H2oOrderCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.company.h2o_subscription_lead_days = 1

    def _subscription(self, lines=None, **vals):
        lines = lines or [(self.water, 2)]
        return self.env['h2o.subscription'].create({
            'partner_id': self.customer.id,
            'weekday_id': self.mon.id,
            'line_ids': [Command.create({'product_id': product.id, 'qty': qty}) for product, qty in lines],
            **vals,
        })
