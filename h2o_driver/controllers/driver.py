"""Driver app API: a driver's trips and stops, under /h2o/api/v1/driver/.

Every route checks the user is a driver and only looks up trips whose driver
is the user (dispatchers using the app see their own trips too). Records of
other drivers answer 404, wrong states 422 (``UserError``), bad input 400.

Open orders (confirmed, not on a trip yet) are listed to every driver of the
company; a driver takes one with ``orders/<id>/claim``, which answers 409 when
it was taken in the meantime.
"""
import base64
import binascii

from werkzeug.exceptions import BadRequest, Conflict, Forbidden, NotFound

from odoo import fields, http
from odoo.http import request

from odoo.addons.h2o_base.controllers.api import API_PREFIX, h2o_route

DRIVER_PREFIX = f'{API_PREFIX}/driver'


def _ref(record, name_field='display_name'):
    return {'id': record.id, 'name': record[name_field]} if record else None


def _datetime(value):
    return value and value.replace(microsecond=0).isoformat() + 'Z'


class H2oDriverController(http.Controller):

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    def _check_driver(self):
        if not request.env.user.has_group('h2o_base.group_h2o_driver'):
            raise Forbidden("Only drivers can use the driver app")

    def _get_trip(self, trip_id):
        self._check_driver()
        if not isinstance(trip_id, int):
            raise BadRequest("trip_id must be an integer")
        trip = request.env['h2o.trip'].search([('id', '=', trip_id), ('driver_id', '=', request.env.uid)])
        if not trip:
            raise NotFound("Trip not found")
        return trip

    def _get_stop(self, stop_id):
        self._check_driver()
        stop = request.env['h2o.stop'].search([('id', '=', stop_id), ('trip_id.driver_id', '=', request.env.uid)])
        if not stop:
            raise NotFound("Stop not found")
        return stop

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def _trip_summary(self, trip):
        return {
            'id': trip.id,
            'name': trip.name,
            'date': fields.Date.to_string(trip.date),
            'state': trip.state,
            'route': _ref(trip.route_id),
            'vehicle': trip.vehicle_id and {
                'id': trip.vehicle_id.id,
                'name': trip.vehicle_id.name,
                'license_plate': trip.vehicle_id.license_plate,
            } or None,
            'stop_count': trip.stop_count,
            'pending_count': trip.pending_count,
            'delivered_count': trip.delivered_count,
            'failed_count': trip.failed_count,
            'planned_bottle_qty': trip.planned_bottle_qty,
            'load_qty': trip.load_qty,
            'cash_expected': trip.cash_expected,
            'currency': trip.currency_id.name,
            'note': trip.note or '',
        }

    def _trip_detail(self, trip):
        return self._trip_summary(trip) | {'stops': [self._stop_data(stop) for stop in trip.stop_ids]}

    def _stop_data(self, stop):
        # Drivers have no rights on sales orders: read only what the app shows.
        order = stop.order_id.sudo()
        return {
            'id': stop.id,
            'trip_id': stop.trip_id.id,
            'sequence': stop.sequence,
            'state': stop.state,
            'order': order and {
                'id': order.id,
                'name': order.name,
                'note': order.h2o_delivery_notes or '',
                'empties_expected': order.h2o_empties_expected,
            } or None,
            'time_window': stop.time_window or 'any',
            'partner': self._partner_data(stop.partner_id),
            'zone': _ref(stop.zone_id),
            'lines': [{
                'id': line.id,
                'product_id': line.product_id.id,
                'product_name': line.product_id.display_name,
                'product_kind': line.product_id.h2o_product_kind or None,
                'uom': line.product_uom_id.name,
                'qty_planned': line.qty_planned,
                'qty_delivered': line.qty_delivered,
                'price_unit': line.sale_line_id.sudo().price_reduce_taxinc,
            } for line in stop.line_ids],
            'empties_product_id': stop.empties_product_id.id or None,
            'empties_expected': stop.empties_expected,
            'empties_collected': stop.empties_collected,
            'payment_mode': stop.commercial_partner_id.h2o_payment_mode or None,
            'payment_method': stop.payment_method,
            'amount_due': stop.amount_due,
            'payment_amount': stop.payment_amount,
            'currency': stop.currency_id.name,
            'failure_reason': stop.failure_reason or None,
            'failure_note': stop.failure_note or '',
            'note': stop.note or '',
            'done_at': _datetime(stop.done_at),
            'claimed': stop.claimed,
        }

    def _partner_data(self, partner):
        customer = partner.commercial_partner_id
        return {
            'id': partner.id,
            'name': partner.name,
            'customer_name': customer.name,
            'customer_type': customer.h2o_customer_type or None,
            'street': partner.street or '',
            'street2': partner.street2 or '',
            'city': partner.city or '',
            'zip': partner.zip or '',
            'state': partner.state_id.name or '',
            'phone': partner.phone or customer.phone or '',
            'floor': partner.h2o_floor,
            'has_elevator': partner.h2o_has_elevator,
            'delivery_notes': partner.h2o_delivery_notes or customer.h2o_delivery_notes or '',
            'latitude': partner.partner_latitude or None,
            'longitude': partner.partner_longitude or None,
            'bottle_balance': partner.h2o_bottle_balance,
        }

    def _order_data(self, order):
        """An open order as the Orders tab shows it. ``order`` is read with sudo."""
        route = order.h2o_zone_id.h2o_route_id
        return {
            'id': order.id,
            'name': order.name,
            'delivery_date': fields.Date.to_string(order.h2o_delivery_date) or None,
            'time_window': order.h2o_time_window or 'any',
            'zone': _ref(order.h2o_zone_id),
            'my_zone': bool(route) and route._h2o_driver() == request.env.user,
            'partner': self._partner_data(order.partner_shipping_id),
            'note': order.h2o_delivery_notes or '',
            'empties_expected': order.h2o_empties_expected,
            'payment_mode': order.partner_id.commercial_partner_id.h2o_payment_mode or None,
            'amount_total': order.amount_total,
            'currency': order.currency_id.name,
            'lines': [{
                'product_id': line.product_id.id,
                'product_name': line.product_id.display_name,
                'product_kind': line.product_id.h2o_product_kind or None,
                'uom': line.product_uom_id.name,
                'qty': line.product_uom_qty - line.qty_delivered,
            } for line in order.order_line
                if not line.display_type and line.product_id and line.product_uom_qty > line.qty_delivered],
        }

    # ------------------------------------------------------------------
    # Trips
    # ------------------------------------------------------------------

    @h2o_route(f'{DRIVER_PREFIX}/trips', methods=('GET',))
    def h2o_driver_trips(self, **kw):
        self._check_driver()
        # GET parameters come in the query string, not in the JSON body.
        day = request.httprequest.args.get('date') or kw.get('date')
        try:
            day = fields.Date.to_date(day) if day else request.env.user._h2o_today()
        except ValueError:
            raise BadRequest("date must be YYYY-MM-DD") from None
        trips = request.env['h2o.trip'].search([
            ('driver_id', '=', request.env.uid),
            ('date', '=', day),
            ('state', '!=', 'cancelled'),
        ], order='id')
        return [self._trip_summary(trip) for trip in trips]

    @h2o_route(f'{DRIVER_PREFIX}/trips/<int:trip_id>', methods=('GET',))
    def h2o_driver_trip(self, trip_id, **kw):
        return self._trip_detail(self._get_trip(trip_id))

    @h2o_route(f'{DRIVER_PREFIX}/trips/<int:trip_id>/start')
    def h2o_driver_trip_start(self, trip_id, **kw):
        trip = self._get_trip(trip_id)
        trip.action_start()
        return self._trip_detail(trip)

    @h2o_route(f'{DRIVER_PREFIX}/trips/<int:trip_id>/close')
    def h2o_driver_trip_close(self, trip_id, **kw):
        trip = self._get_trip(trip_id)
        trip.action_close()
        return self._trip_summary(trip)

    @h2o_route(f'{DRIVER_PREFIX}/position')
    def h2o_driver_position(self, latitude=None, longitude=None, trip_id=None, **kw):
        if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)) or not trip_id:
            raise BadRequest("latitude, longitude and trip_id are required")
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise BadRequest("latitude or longitude out of range")
        trip = self._get_trip(trip_id)
        trip._h2o_update_position(latitude, longitude)
        return {'ok': True}

    # ------------------------------------------------------------------
    # Stops
    # ------------------------------------------------------------------

    @h2o_route(f'{DRIVER_PREFIX}/stops/<int:stop_id>/deliver')
    def h2o_driver_stop_deliver(self, stop_id, lines=None, **kw):
        stop = self._get_stop(stop_id)
        vals = {key: kw[key] for key in (
            'empties_collected', 'payment_method', 'payment_amount', 'signature', 'photo',
            'latitude', 'longitude', 'note',
        ) if kw.get(key) is not None}
        if lines is not None:
            if not isinstance(lines, list) or not all(isinstance(line, dict) for line in lines):
                raise BadRequest("lines must be a list of {product_id, qty_delivered}")
            vals['lines'] = lines
        if 'payment_method' in vals and vals['payment_method'] not in dict(stop._fields['payment_method'].selection):
            raise BadRequest("unknown payment_method")
        for key in ('signature', 'photo'):
            if key in vals:
                try:
                    base64.b64decode(vals[key], validate=True)
                except (binascii.Error, TypeError, ValueError):
                    raise BadRequest(f"{key} must be base64") from None
        stop.action_deliver(vals)
        return self._stop_data(stop)

    @h2o_route(f'{DRIVER_PREFIX}/stops/<int:stop_id>/fail')
    def h2o_driver_stop_fail(self, stop_id, reason=None, note=None, **kw):
        stop = self._get_stop(stop_id)
        if reason not in dict(stop._fields['failure_reason'].selection):
            raise BadRequest("reason must be one of: %s" % ', '.join(dict(stop._fields['failure_reason'].selection)))
        stop.action_fail(reason, note)
        return self._stop_data(stop)

    @h2o_route(f'{DRIVER_PREFIX}/stops/<int:stop_id>/skip')
    def h2o_driver_stop_skip(self, stop_id, **kw):
        stop = self._get_stop(stop_id)
        stop.action_skip()
        return self._stop_data(stop)

    @h2o_route(f'{DRIVER_PREFIX}/stops/reorder')
    def h2o_driver_stops_reorder(self, trip_id=None, stop_ids=None, **kw):
        """Put the given pending stops of the trip in this order. They take
        the places they had among themselves; the other stops keep theirs."""
        if not trip_id or not isinstance(stop_ids, list) or not stop_ids \
                or not all(isinstance(stop_id, int) for stop_id in stop_ids):
            raise BadRequest("trip_id and stop_ids (list of ids) are required")
        trip = self._get_trip(trip_id)
        pending = trip.stop_ids.filtered(lambda s: s.state == 'pending')
        if len(set(stop_ids)) != len(stop_ids) or not set(stop_ids) <= set(pending.ids):
            raise BadRequest("stop_ids must be pending stops of the trip, each once")
        wanted = iter(request.env['h2o.stop'].browse(stop_ids))
        new_order = [next(wanted) if stop.id in stop_ids else stop for stop in trip.stop_ids]
        for sequence, stop in enumerate(new_order, start=1):
            if stop.sequence != sequence:
                # sudo: done stops may need a new number too; only the order changes
                stop.sudo().sequence = sequence
        trip.invalidate_recordset(['stop_ids'])
        return self._trip_detail(trip)

    # ------------------------------------------------------------------
    # Open orders
    # ------------------------------------------------------------------

    @h2o_route(f'{DRIVER_PREFIX}/orders', methods=('GET',))
    def h2o_driver_orders(self, **kw):
        """Orders waiting for a driver, by delivery date: the driver's own zones first."""
        self._check_driver()
        SaleOrder = request.env['sale.order']
        # sudo: drivers have no rights on sales orders; the domain keeps to the open ones.
        orders = SaleOrder.sudo().search(SaleOrder._h2o_open_orders_domain(), order='h2o_delivery_date, id', limit=200)
        data = [self._order_data(order) for order in orders]
        return sorted(data, key=lambda o: (o['delivery_date'] or '', not o['my_zone']))

    @h2o_route(f'{DRIVER_PREFIX}/orders/<int:order_id>/claim')
    def h2o_driver_order_claim(self, order_id, **kw):
        """Take an open order: it becomes a stop on the driver's trip of today."""
        self._check_driver()
        SaleOrder = request.env['sale.order']
        order = SaleOrder.sudo().search([('id', '=', order_id)] + SaleOrder._h2o_open_orders_domain()).sudo(False)
        if not order:
            if SaleOrder.sudo().search_count([('id', '=', order_id)]):
                raise Conflict("This order was already taken")
            raise NotFound("Order not found")
        stop = order._h2o_claim()
        return {'trip': self._trip_summary(stop.trip_id), 'stop': self._stop_data(stop)}

    @h2o_route(f'{DRIVER_PREFIX}/stops/<int:stop_id>/release')
    def h2o_driver_stop_release(self, stop_id, **kw):
        """Give back an order the driver took: it is open again for every driver."""
        stop = self._get_stop(stop_id)
        trip = stop.trip_id
        stop.action_release()
        return self._trip_summary(trip)
