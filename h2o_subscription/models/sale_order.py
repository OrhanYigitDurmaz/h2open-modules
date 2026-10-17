from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    h2o_subscription_id = fields.Many2one(
        'h2o.subscription', string="Subscription", readonly=True, copy=False, index='btree_not_null',
        help="Water subscription that created this order.",
    )
