from odoo import api, fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    h2o_stop_ids = fields.One2many('h2o.stop', 'order_id', string="Delivery Stops")
    h2o_trip_id = fields.Many2one(
        'h2o.trip', string="Delivery Trip", compute='_compute_h2o_trip_id', store=True, index='btree_not_null',
        help="Trip of the order's last delivery stop.",
    )

    @api.depends('h2o_stop_ids.trip_id')
    def _compute_h2o_trip_id(self):
        for order in self:
            order.h2o_trip_id = order.h2o_stop_ids.sorted('id')[-1:].trip_id

    def _h2o_release_planned(self):
        """Send planned orders without a pending stop back to planning.

        Runs as superuser: drivers fail and skip stops but have no rights on orders.
        """
        orders = self.sudo().filtered(
            lambda o: o.h2o_delivery_state == 'planned'
            and not o.h2o_stop_ids.filtered(lambda s: s.state == 'pending')
        )
        orders.h2o_delivery_state = 'to_plan'

    def _action_cancel(self):
        stops = self.h2o_stop_ids.filtered(lambda s: s.state == 'pending')
        res = super()._action_cancel()
        # Cancelled orders leave planned trips; trips already out skip them.
        stops.filtered(lambda s: s.trip_id.state == 'planned').unlink()
        stops.exists().sudo().write({'state': 'skipped', 'done_at': fields.Datetime.now()})
        return res

    def action_h2o_view_trip(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'h2o.trip',
            'res_id': self.h2o_trip_id.id,
            'view_mode': 'form',
        }
