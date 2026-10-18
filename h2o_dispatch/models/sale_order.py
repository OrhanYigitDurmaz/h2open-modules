from odoo import api, fields, models
from odoo.exceptions import AccessError, LockError, UserError


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

    def _h2o_is_open(self):
        """Whether the order waits for a driver: confirmed, to deliver, on no trip yet."""
        self.ensure_one()
        order = self.sudo()
        return order.state == 'sale' and order.h2o_is_delivery and order.h2o_delivery_state == 'to_plan'

    def _h2o_claim(self):
        """The current user, a driver, takes the order to deliver it today.

        The order becomes a stop at the end of the driver's trip of the day
        (see ``h2o.trip._h2o_trip_for_driver``) and is ``planned``. The order
        row is locked first, so of two drivers taking it at the same time only
        one gets it; the other gets a ``UserError``.

        :return: the new stop (``h2o.stop``)
        """
        self.ensure_one()
        driver = self.env.user
        if not driver.has_group('h2o_base.group_h2o_driver'):
            raise AccessError(self.env._("Only drivers can take orders."))
        # sudo: drivers have no rights on orders; they only take open ones.
        order = self.sudo()
        try:
            order.lock_for_update()
        except LockError:
            raise UserError(self.env._("Another driver is taking order %s right now.", order.name)) from None
        order.invalidate_recordset(['state', 'h2o_delivery_state'])
        if not order._h2o_is_open():
            raise UserError(self.env._("Order %s was already taken.", order.name))
        trip = self.env['h2o.trip'].sudo()._h2o_trip_for_driver(driver, driver._h2o_today(), order.company_id)
        stop = self.env['h2o.stop'].sudo().create({
            'trip_id': trip.id,
            'order_id': order.id,
            'sequence': max(trip.stop_ids.mapped('sequence'), default=0) + 10,
            'claimed': True,
        })
        return stop.sudo(self.env.su)

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
