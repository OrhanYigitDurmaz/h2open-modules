from odoo import api, fields, models


class H2oTripLoadLine(models.Model):
    _name = 'h2o.trip.load.line'
    _description = 'Trip Load Line'
    _order = 'trip_id, product_id'
    _check_company_auto = True

    trip_id = fields.Many2one('h2o.trip', string="Trip", required=True, index=True, ondelete='cascade')
    company_id = fields.Many2one(related='trip_id.company_id', store=True, index=True)
    state = fields.Selection(related='trip_id.state', string="Trip Status")
    product_id = fields.Many2one(
        'product.product', string="Product", required=True, check_company=True,
        domain="[('is_storable', '=', True)]",
    )
    product_uom_id = fields.Many2one(related='product_id.uom_id', string="Unit")
    qty_planned = fields.Float(
        string="Planned", digits='Product Unit', compute='_compute_qty_planned', store=True,
        help="Quantity to deliver on the trip's pending and delivered stops.",
    )
    qty_loaded = fields.Float(
        string="Loaded", digits='Product Unit', compute='_compute_qty_loaded', store=True, readonly=False,
        help="Quantity loaded on the vehicle. Follows the planned quantity until the trip is loaded.",
    )
    qty_delivered = fields.Float(
        string="Delivered", digits='Product Unit', compute='_compute_qty_delivered', store=True,
        help="Quantity delivered on the trip's stops.",
    )
    qty_collected = fields.Float(
        string="Collected", digits='Product Unit', compute='_compute_qty_collected', store=True,
        help="Empty bottles taken back from the customers.",
    )
    qty_returned = fields.Float(
        string="Returned", digits='Product Unit', readonly=True,
        help="Quantity brought back to the depot, computed when the trip closes: "
             "loaded - delivered + collected.",
    )

    _trip_product_uniq = models.Constraint(
        'UNIQUE(trip_id, product_id)', 'A product can only be once on the load of a trip.',
    )

    @api.depends('product_id', 'trip_id.stop_ids.state', 'trip_id.stop_ids.line_ids.qty_planned',
                 'trip_id.stop_ids.line_ids.product_id')
    def _compute_qty_planned(self):
        for trip, lines in self.grouped('trip_id').items():
            quantities = trip._h2o_stop_quantities('qty_planned')
            for line in lines:
                line.qty_planned = quantities.get(line.product_id, 0.0)

    @api.depends('qty_planned')
    def _compute_qty_loaded(self):
        for line in self:
            if line.trip_id.state in ('planned', False):
                line.qty_loaded = line.qty_planned

    @api.depends('product_id', 'trip_id.stop_ids.state', 'trip_id.stop_ids.line_ids.qty_delivered')
    def _compute_qty_delivered(self):
        for trip, lines in self.grouped('trip_id').items():
            quantities = trip._h2o_stop_quantities('qty_delivered', ('delivered',))
            for line in lines:
                line.qty_delivered = quantities.get(line.product_id, 0.0)

    @api.depends('product_id', 'trip_id.stop_ids.state', 'trip_id.stop_ids.empties_collected',
                 'trip_id.stop_ids.empties_product_id')
    def _compute_qty_collected(self):
        for trip, lines in self.grouped('trip_id').items():
            quantities = trip._h2o_empties_collected()
            for line in lines:
                line.qty_collected = quantities.get(line.product_id, 0)
