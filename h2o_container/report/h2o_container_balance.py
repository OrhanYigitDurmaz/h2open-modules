from odoo import fields, models
from odoo.tools.sql import SQL, drop_view_if_exists


class H2oContainerBalance(models.Model):
    _name = 'h2o.container.balance'
    _description = 'Bottle Balance'
    _auto = False
    _order = 'qty desc, partner_id'

    partner_id = fields.Many2one('res.partner', string="Customer", readonly=True)
    product_id = fields.Many2one('product.product', string="Container", readonly=True)
    qty = fields.Integer(string="Bottles Held", readonly=True)
    qty_out = fields.Integer(string="Bottles Out", readonly=True)
    qty_in = fields.Integer(string="Bottles In", readonly=True)
    deposit_amount = fields.Monetary(string="Deposit Held", readonly=True)
    currency_id = fields.Many2one('res.currency', readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    zone_id = fields.Many2one('h2o.zone', string="Delivery Zone", readonly=True)
    customer_type = fields.Selection(
        selection=lambda self: self.env['res.partner']._fields['h2o_customer_type'].selection,
        string="Customer Type", readonly=True,
    )
    last_date = fields.Datetime(string="Last Movement", readonly=True)

    def init(self):
        drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(SQL("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT MIN(move.id) AS id,
                       move.partner_id,
                       move.product_id,
                       move.company_id,
                       company.currency_id,
                       partner.h2o_zone_id AS zone_id,
                       partner.h2o_customer_type AS customer_type,
                       SUM(move.qty_out - move.qty_in) AS qty,
                       SUM(move.qty_out) AS qty_out,
                       SUM(move.qty_in) AS qty_in,
                       SUM(move.deposit_amount) AS deposit_amount,
                       MAX(move.date) AS last_date
                  FROM h2o_container_move move
                  JOIN res_company company ON company.id = move.company_id
                  JOIN res_partner partner ON partner.id = move.partner_id
                 WHERE move.state = 'done'
              GROUP BY move.partner_id, move.product_id, move.company_id, company.currency_id,
                       partner.h2o_zone_id, partner.h2o_customer_type
            )
        """, SQL.identifier(self._table)))
