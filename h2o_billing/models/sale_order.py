from dateutil.relativedelta import relativedelta

from odoo import Command, api, fields, models
from odoo.tools import float_compare, format_date


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _h2o_lines_to_invoice(self):
        """Product lines delivered beyond what was already invoiced."""
        precision = self.env['decimal.precision'].precision_get('Product Unit')
        return self.order_line.filtered(
            lambda line: not line.display_type and line.product_id
            and float_compare(line.qty_delivered, line.qty_invoiced, precision_digits=precision) > 0
        )

    def _h2o_invoice_line_commands(self, sequence=0):
        """Invoice lines for the delivered, not yet invoiced quantities of the order."""
        self.ensure_one()
        commands = []
        for line in self._h2o_lines_to_invoice():
            sequence += 1
            commands.append(Command.create(line._prepare_invoice_line(
                quantity=line.qty_delivered - line.qty_invoiced, sequence=sequence,
            )))
        return commands

    def _h2o_create_delivered_invoice(self, **values):
        """Create a draft invoice for the delivered, not yet invoiced
        quantities of the order, whatever the products' invoicing policy.
        ``values`` complete the invoice values. Returns the invoice, or an
        empty recordset when there is nothing to invoice."""
        self.ensure_one()
        order = self.with_company(self.company_id)
        line_commands = order._h2o_invoice_line_commands()
        if not line_commands:
            return self.env['account.move']
        invoice_vals = order._prepare_invoice() | values
        invoice_vals['invoice_line_ids'] = line_commands
        return order.env['account.move'].create(invoice_vals)

    @api.model
    def _h2o_create_monthly_statements(self, month, partners=None):
        """Create and post one statement invoice per ``account`` customer of
        the current company for its orders delivered in ``month`` (any day of
        it) and not invoiced yet. ``partners`` limits the customers.
        Returns the invoices."""
        start = month.replace(day=1)
        end = start + relativedelta(months=1, days=-1)
        domain = [
            ('state', '=', 'delivered'),
            ('date', '>=', start),
            ('date', '<=', end),
            ('company_id', '=', self.env.company.id),
            ('order_id.partner_id.commercial_partner_id.h2o_payment_mode', '=', 'account'),
        ]
        if partners:
            domain.append(('order_id.partner_id.commercial_partner_id', 'in', partners.commercial_partner_id.ids))
        orders = self.env['h2o.stop'].search(domain).order_id.filtered(lambda o: o._h2o_lines_to_invoice())
        invoices = self.env['account.move']
        for customer_orders in orders.grouped(lambda o: o.partner_id.commercial_partner_id).values():
            invoices |= customer_orders._h2o_create_statement(start)
        invoices.action_post()
        return invoices

    def _h2o_create_statement(self, month):
        """One draft invoice for the delivered, not yet invoiced quantities
        of the orders (all of the same customer), a section per order."""
        customer = self.partner_id.commercial_partner_id
        customer.ensure_one()
        orders = self.sorted(lambda o: (o.h2o_delivery_date or o.date_order.date(), o.id))
        first = orders[0].with_company(orders[0].company_id)
        invoice_partner = orders.partner_invoice_id if len(orders.partner_invoice_id) == 1 else customer
        shipping_partner = orders.partner_shipping_id if len(orders.partner_shipping_id) == 1 else invoice_partner
        end = month + relativedelta(months=1, days=-1)
        invoice_vals = first._prepare_invoice() | {
            'partner_id': invoice_partner.id,
            'partner_shipping_id': shipping_partner.id,
            'invoice_date': min(end, fields.Date.context_today(first)),
            'invoice_origin': ', '.join(orders.mapped('name')),
            'ref': self.env._("Statement %s", format_date(self.env, month, date_format='MMMM y')),
            'payment_reference': False,
            'h2o_statement_month': month,
        }
        line_commands = []
        for order in orders:
            delivery_dates = order.h2o_stop_ids.filtered(lambda s: s.state == 'delivered').mapped('date')
            line_commands.append(Command.create({
                'display_type': 'line_section',
                'name': ' - '.join(filter(None, [
                    order.name, ', '.join(format_date(self.env, day) for day in sorted(set(delivery_dates))),
                ])),
                'sequence': len(line_commands) + 1,
            }))
            line_commands += order._h2o_invoice_line_commands(sequence=len(line_commands))
        invoice_vals['invoice_line_ids'] = line_commands
        return first.env['account.move'].create(invoice_vals)
