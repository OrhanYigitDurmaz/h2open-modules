from odoo import fields, models


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    h2o_trip_id = fields.Many2one('h2o.trip', string="Trip", readonly=True, copy=False, index='btree_not_null')
    h2o_trip_role = fields.Selection(
        [
            ('load', "Load-out"),
            ('delivery', "Deliveries"),
            ('empties', "Empties Collected"),
            ('return', "Return to Depot"),
        ],
        string="Trip Transfer", readonly=True, copy=False,
    )

    def _h2o_validate(self):
        """Validate the transfers for their full demand, without wizards: no
        backorder, and a vehicle may go negative (it delivered more than
        what was recorded as loaded)."""
        self.action_confirm()
        for move in self.move_ids:
            move.quantity = move.product_uom_qty
        self.move_ids.picked = True
        self.with_context(skip_backorder=True, picking_ids_not_to_backorder=self.ids).button_validate()
