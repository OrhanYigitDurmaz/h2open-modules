from dateutil.relativedelta import relativedelta

from odoo import fields, models


class H2oStatementWizard(models.TransientModel):
    _name = 'h2o.statement.wizard'
    _description = 'Create Monthly Statements'

    def _default_month(self):
        return fields.Date.context_today(self).replace(day=1) - relativedelta(months=1)

    month = fields.Date(
        required=True, default=lambda self: self._default_month(),
        help="Any day of the month to invoice: orders delivered in that month are invoiced.",
    )
    partner_ids = fields.Many2many(
        'res.partner', string="Customers",
        domain="[('h2o_payment_mode', '=', 'account'), ('h2o_customer_type', '!=', False)]",
        help="Customers on account to invoice. Leave empty for all of them.",
    )

    def action_create_statements(self):
        self.ensure_one()
        month = self.month.replace(day=1)
        invoices = self.env['sale.order']._h2o_create_monthly_statements(month, self.partner_ids)
        if not invoices:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'info',
                    'message': self.env._("Nothing left to invoice for this month."),
                    'next': {'type': 'ir.actions.act_window_close'},
                },
            }
        action = self.env['ir.actions.act_window']._for_xml_id('h2o_billing.h2o_statement_action')
        action['domain'] = [('id', 'in', invoices.ids)]
        action['context'] = {'create': False}
        return action
