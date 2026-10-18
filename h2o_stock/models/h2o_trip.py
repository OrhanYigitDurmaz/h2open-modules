from collections import defaultdict

from odoo import Command, api, fields, models
from odoo.exceptions import UserError

# Transfers made when a trip closes.
H2O_CLOSE_ROLES = ('delivery', 'empties', 'return')


class H2oTrip(models.Model):
    _inherit = 'h2o.trip'

    h2o_warehouse_id = fields.Many2one(
        'stock.warehouse', string="Depot", check_company=True,
        compute='_compute_h2o_warehouse_id', store=True, readonly=False, precompute=True,
        help="Warehouse the trip loads out from and returns to: the route's depot.",
    )
    h2o_load_line_ids = fields.One2many('h2o.trip.load.line', 'trip_id', string="Load")
    h2o_picking_ids = fields.One2many(
        'stock.picking', 'h2o_trip_id', string="Transfers", groups='stock.group_stock_user',
    )
    h2o_picking_count = fields.Integer(
        string="Transfers Count", compute='_compute_h2o_picking_count', groups='stock.group_stock_user',
    )

    @api.depends('route_id', 'vehicle_id')
    def _compute_h2o_warehouse_id(self):
        for trip in self:
            if trip.state not in ('planned', False) and trip.h2o_warehouse_id:
                continue
            trip.h2o_warehouse_id = (
                trip.route_id.h2o_warehouse_id
                or trip.vehicle_id.h2o_warehouse_id
                or self.env['stock.warehouse']._h2o_default_for(trip.company_id or self.env.company)
            )

    @api.depends('h2o_picking_ids')
    def _compute_h2o_picking_count(self):
        for trip in self:
            trip.h2o_picking_count = len(trip.h2o_picking_ids)

    # ------------------------------------------------------------------
    # Load lines
    # ------------------------------------------------------------------

    def _h2o_stop_quantities(self, qty_field, states=('pending', 'delivered')):
        """Storable products on the stops in ``states``: ``{product: qty}`` in
        the product's unit, for ``qty_field`` (``qty_planned`` or ``qty_delivered``)."""
        self.ensure_one()
        result = defaultdict(float)
        for line in self.stop_ids.filtered(lambda s: s.state in states).line_ids:
            if line.product_id.is_storable:
                result[line.product_id] += line.product_uom_id._compute_quantity(line[qty_field], line.product_id.uom_id)
        return result

    def _h2o_empties_collected(self):
        """Empty bottles taken back on the delivered stops: ``{container: qty}``."""
        self.ensure_one()
        result = defaultdict(int)
        for stop in self.stop_ids.filtered(lambda s: s.state == 'delivered' and s.empties_collected):
            result[stop.empties_product_id] += stop.empties_collected
        return result

    def _h2o_sync_load_lines(self):
        """Add a load line for every storable product of the stops and every
        container collected as empties; the quantities follow the stops."""
        vals_list = []
        for trip in self:
            products = trip.stop_ids.line_ids.product_id | trip.stop_ids.filtered(
                lambda s: s.state == 'delivered' and s.empties_collected).empties_product_id
            missing = products.filtered('is_storable') - trip.h2o_load_line_ids.product_id
            vals_list += [{'trip_id': trip.id, 'product_id': product.id} for product in missing]
        return self.env['h2o.trip.load.line'].create(vals_list)

    # ------------------------------------------------------------------
    # Actions and hooks
    # ------------------------------------------------------------------

    def action_load(self):
        # Settle the load lines while the trips are still planned: until then
        # the quantities loaded follow the quantities planned.
        planned = self.sudo().filtered(lambda t: t.state == 'planned')
        planned._h2o_sync_load_lines()
        planned.h2o_load_line_ids.flush_recordset(['qty_planned', 'qty_loaded'])
        return super().action_load()

    def action_cancel(self):
        loaded = self.filtered(lambda t: t.state in ('loaded', 'on_road'))
        res = super().action_cancel()
        # Nothing was delivered: everything loaded goes back to the depot.
        for trip in loaded.sudo():
            if not trip._h2o_is_loaded():
                continue
            for line in trip.h2o_load_line_ids:
                line.qty_returned = line.qty_loaded
            trip._h2o_create_picking('return', {line.product_id: line.qty_returned for line in trip.h2o_load_line_ids})
        return res

    def action_reset_planned(self):
        res = super().action_reset_planned()
        self.sudo().h2o_load_line_ids.qty_returned = 0.0
        return res

    def action_view_pickings(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('stock.action_picking_tree_all')
        action['domain'] = [('h2o_trip_id', '=', self.id)]
        action['context'] = {'create': False}
        return action

    def _h2o_on_loaded(self):
        """Move the load from the depot to the vehicle."""
        super()._h2o_on_loaded()
        for trip in self.sudo():
            if trip._h2o_is_loaded():
                continue
            trip._h2o_sync_load_lines()
            lines = trip.h2o_load_line_ids
            lines.filtered(lambda l: not l.qty_planned and not l.qty_loaded).unlink()
            trip.load_qty = sum(
                int(round(line.qty_loaded)) for line in trip.h2o_load_line_ids
                if line.product_id.h2o_product_kind == 'water_returnable'
            )
            trip._h2o_create_picking('load', {line.product_id: line.qty_loaded for line in trip.h2o_load_line_ids})

    def _h2o_on_closed(self):
        """Move the deliveries to the customers, the empties onto the vehicle
        and everything left on the vehicle back to the depot."""
        super()._h2o_on_closed()
        for trip in self.sudo():
            if trip._h2o_current_pickings().filtered(lambda p: p.h2o_trip_role in H2O_CLOSE_ROLES):
                continue
            trip._h2o_sync_load_lines()
            lines = trip.h2o_load_line_ids
            for line in lines:
                line.qty_returned = max(0.0, line.qty_loaded - line.qty_delivered + line.qty_collected)
            trip._h2o_create_picking('delivery', {line.product_id: line.qty_delivered for line in lines})
            trip._h2o_create_picking('empties', {line.product_id: line.qty_collected for line in lines})
            trip._h2o_create_picking('return', {line.product_id: line.qty_returned for line in lines})

    # ------------------------------------------------------------------
    # Transfers
    # ------------------------------------------------------------------

    def _h2o_is_loaded(self):
        """Whether the trip's goods are on the vehicle: loaded out and not yet
        delivered or returned."""
        self.ensure_one()
        roles = set(self._h2o_current_pickings().mapped('h2o_trip_role'))
        return 'load' in roles and not roles & set(H2O_CLOSE_ROLES)

    def _h2o_current_pickings(self):
        """Transfers of the trip's current run: from its last load-out on
        (a cancelled trip planned again is loaded again)."""
        self.ensure_one()
        pickings = self.sudo().h2o_picking_ids.filtered(lambda p: p.state != 'cancel')
        last_load = pickings.filtered(lambda p: p.h2o_trip_role == 'load').sorted('id')[-1:]
        return pickings.filtered(lambda p: p.id >= last_load.id) if last_load else pickings

    def _h2o_picking_route(self, role):
        """Operation type, source and destination locations of a trip transfer."""
        self.ensure_one()
        warehouse = self.h2o_warehouse_id
        if not warehouse:
            raise UserError(self.env._("Set a depot warehouse on trip %s.", self.name))
        vehicle = self.vehicle_id._h2o_stock_location() if self.vehicle_id else self.env['stock.location']
        if not vehicle:
            raise UserError(self.env._("Vehicle of trip %s has no stock location; is it a delivery vehicle?", self.name))
        customers = (
            warehouse.out_type_id.default_location_dest_id
            or self.env.ref('stock.stock_location_customers')
        )
        return {
            'load': (warehouse.int_type_id, warehouse.lot_stock_id, vehicle),
            'delivery': (warehouse.out_type_id, vehicle, customers),
            'empties': (warehouse.in_type_id, customers, vehicle),
            'return': (warehouse.int_type_id, vehicle, warehouse.lot_stock_id),
        }[role]

    def _h2o_create_picking(self, role, quantities):
        """Create and validate the trip transfer ``role`` for ``{product: qty}``
        (product unit); nothing is created when every quantity is zero."""
        self.ensure_one()
        quantities = {
            product: qty for product, qty in quantities.items()
            if product.uom_id.compare(qty, 0.0) > 0
        }
        if not quantities:
            return self.env['stock.picking']
        picking_type, source, destination = self._h2o_picking_route(role)
        picking = self.env['stock.picking'].with_company(self.company_id).create({
            'picking_type_id': picking_type.id,
            'location_id': source.id,
            'location_dest_id': destination.id,
            'origin': self.name,
            'h2o_trip_id': self.id,
            'h2o_trip_role': role,
            'move_ids': [
                Command.create({
                    'product_id': product.id,
                    'product_uom_qty': qty,
                    'uom_id': product.uom_id.id,
                    'location_id': source.id,
                    'location_dest_id': destination.id,
                })
                for product, qty in sorted(quantities.items(), key=lambda item: item[0].id)
            ],
        })
        picking._h2o_validate()
        return picking
