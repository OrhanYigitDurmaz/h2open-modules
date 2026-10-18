from odoo import fields, models


class H2oTrip(models.Model):
    _inherit = 'h2o.trip'

    h2o_cash_handover_ids = fields.One2many('h2o.cash.handover', 'trip_id', string="Cash Handover")

    def _h2o_on_closed(self):
        """Open the cash handover of the trip for the accountant."""
        super()._h2o_on_closed()
        # closed by the driver, who cannot create handovers
        self.sudo()._h2o_create_cash_handovers()

    def _h2o_create_cash_handovers(self):
        trips = self.filtered(lambda t: not t.h2o_cash_handover_ids)
        return self.env['h2o.cash.handover'].create([{'trip_id': trip.id} for trip in trips])

    def action_h2o_view_cash_handover(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'h2o.cash.handover',
            'view_mode': 'form',
            'res_id': self.h2o_cash_handover_ids[:1].id,
        }
