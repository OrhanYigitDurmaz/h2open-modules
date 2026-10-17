from dateutil.relativedelta import relativedelta

from odoo import fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    h2o_stop_id = fields.Many2one(
        'h2o.stop', string="Delivery Stop", readonly=True, copy=False, index='btree_not_null',
        help="Delivery this invoice was created for.",
    )
    h2o_statement_month = fields.Date(
        string="Statement Month", readonly=True, copy=False, index='btree_not_null',
        help="First day of the month of a monthly statement invoice.",
    )

    def _cron_h2o_monthly_invoices(self):
        """Create the statements of the previous month for every company."""
        for company in self.env['res.company'].search([]):
            Order = self.env['sale.order'].with_company(company)
            month = fields.Date.context_today(Order).replace(day=1) - relativedelta(months=1)
            Order._h2o_create_monthly_statements(month)
