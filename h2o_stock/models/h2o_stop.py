from odoo import api, models


class H2oStopLine(models.Model):
    _inherit = 'h2o.stop.line'

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        # New products on a running trip get their load line (dispatchers see them before loading).
        lines.stop_id.trip_id.filtered(
            lambda t: t.state in ('planned', 'loaded', 'on_road')
        ).sudo()._h2o_sync_load_lines()
        return lines
