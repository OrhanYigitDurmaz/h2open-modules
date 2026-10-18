from odoo import api, fields, models

# Seconds FCM keeps an open-order push for a phone that is offline.
H2O_ORDER_PUSH_TTL = 4 * 3600


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def action_confirm(self):
        res = super().action_confirm()
        # Subscription orders come in batches ahead of time: they are listed
        # in the app but do not ring every driver's phone.
        self.filtered(lambda o: o.h2o_channel != 'subscription' and o._h2o_is_open())._h2o_push_order_open()
        return res

    def _h2o_claim(self):
        stop = super()._h2o_claim()
        self._h2o_push_drivers({'type': 'order_claimed', 'order_id': self.id}, priority='normal')
        return stop

    def _h2o_drivers_to_notify(self):
        """Drivers told about the order: the driver of its zone's route, else
        every driver of its company. Never the user who caused the push."""
        self.ensure_one()
        order = self.sudo()
        route = order.h2o_zone_id.h2o_route_id
        drivers = route._h2o_driver() if route else self.env['res.users']
        if not drivers:
            drivers = self.env['res.users'].sudo().search([
                ('all_group_ids', 'in', self.env.ref('h2o_base.group_h2o_driver').ids),
                ('company_ids', 'in', order.company_id.ids),
                ('share', '=', False),
            ])
        return drivers - self.env.user

    def _h2o_push_drivers(self, data, priority='high'):
        Device = self.env['h2o.push.device']
        for order in self:
            Device._h2o_send(order._h2o_drivers_to_notify(), data, priority=priority,
                             ttl=H2O_ORDER_PUSH_TTL, app='driver')

    def _h2o_push_order_open(self):
        """Tell the drivers an order is waiting to be taken (shown as a
        notification by the app, which opens its Orders tab)."""
        for order in self:
            address = order.sudo().partner_shipping_id
            order._h2o_push_drivers({
                'type': 'order_open',
                'order_id': order.id,
                'order_name': order.sudo().name,
                'customer': address.commercial_partner_id.name or address.name,
                'address': ', '.join(filter(None, (address.street, address.street2, address.city))),
                'zone': order.sudo().h2o_zone_id.name or '',
                'delivery_date': fields.Date.to_string(order.sudo().h2o_delivery_date) or '',
            })

    @api.model
    def _h2o_open_orders_domain(self):
        return [
            ('state', '=', 'sale'),
            ('h2o_is_delivery', '=', True),
            ('h2o_delivery_state', '=', 'to_plan'),
            ('company_id', 'in', self.env.user.company_ids.ids),
        ]
