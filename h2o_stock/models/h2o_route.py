from odoo import fields, models


class H2oRoute(models.Model):
    _inherit = 'h2o.route'

    h2o_warehouse_id = fields.Many2one(
        'stock.warehouse', string="Depot", check_company=True,
        default=lambda self: self.env['stock.warehouse']._h2o_default_for(self.env.company),
        help="Warehouse the route's trips load out from and return to.",
    )
