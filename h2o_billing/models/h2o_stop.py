import logging

from odoo import fields, models
from odoo.exceptions import UserError
from odoo.sql_db import PG_CONCURRENCY_EXCEPTIONS_TO_RETRY
from odoo.tools import float_is_zero

_logger = logging.getLogger(__name__)


class H2oStop(models.Model):
    _inherit = 'h2o.stop'

    invoice_ids = fields.One2many(
        'account.move', 'h2o_stop_id', string="Invoices", groups='account.group_account_invoice',
    )

    def _h2o_on_delivered(self):
        """Invoice the deliveries of cash and card customers."""
        super()._h2o_on_delivered()
        for stop in self:
            if stop.sudo().order_id.partner_id.commercial_partner_id.h2o_payment_mode in ('cash', 'card'):
                stop._h2o_invoice_delivery()

    def _h2o_invoice_delivery(self):
        """Invoice the delivery and register the payment collected.

        Runs as the acting user, often a driver without accounting rights,
        so the work is done as superuser in the order's company. An error
        never undoes the delivery: it is logged and posted on the order, and
        the order can still be invoiced by hand."""
        self.ensure_one()
        order = self.sudo().order_id
        stop = self.sudo().with_company(order.company_id)
        try:
            with self.env.cr.savepoint():
                stop._h2o_create_delivery_invoice()
        except PG_CONCURRENCY_EXCEPTIONS_TO_RETRY:
            raise
        except Exception as error:  # the delivery must be kept whatever goes wrong
            _logger.warning("Could not invoice delivery %s of order %s", self.display_name, order.name, exc_info=True)
            order.message_post(body=self.env._(
                "The invoice of delivery %(stop)s could not be created, please invoice the order by hand: %(error)s",
                stop=self.display_name, error=error,
            ))

    def _h2o_create_delivery_invoice(self):
        """Create and post the invoice of the delivered quantities and
        reconcile it with the payment collected, if any. Returns the invoice."""
        self.ensure_one()
        invoice = self.order_id._h2o_create_delivered_invoice(
            h2o_stop_id=self.id,
            invoice_date=fields.Date.context_today(self, self.done_at),
        )
        if not invoice:
            return invoice
        invoice.action_post()
        if self.payment_method in ('cash', 'card') and not float_is_zero(
            self.payment_amount, precision_rounding=invoice.currency_id.rounding,
        ):
            self._h2o_register_payment(invoice)
        return invoice

    def _h2o_register_payment(self, invoice):
        """Register the amount collected on the cash or card journal and
        reconcile it with the invoice; an unpaid rest stays open."""
        self.ensure_one()
        journal = invoice.company_id._h2o_payment_journal(self.payment_method)
        if not journal:
            raise UserError(self.env._(
                "No journal for %(method)s payments in company %(company)s. Set one in the H2Open settings.",
                method=self._fields['payment_method'].convert_to_export(self.payment_method, self),
                company=invoice.company_id.name,
            ))
        return self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=invoice.ids,
            # always a journal entry, so the invoice is reconciled now
            force_payment_move=True,
        ).create({
            'journal_id': journal.id,
            'amount': self.payment_amount,
            'payment_date': invoice.invoice_date,
            'communication': ' - '.join(filter(None, (invoice.name, self.trip_id.name))),
            'payment_difference_handling': 'open',
        })._create_payments()
