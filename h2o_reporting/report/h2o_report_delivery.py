from odoo import fields, models
from odoo.tools.sql import SQL, drop_view_if_exists


class H2oReportDelivery(models.Model):
    """One row per stop, with its quantities and payment, for pivot and graph views."""
    _name = 'h2o.report.delivery'
    _description = 'Delivery Analysis'
    _auto = False
    _order = 'date desc, id desc'
    _rec_name = 'stop_id'

    stop_id = fields.Many2one('h2o.stop', string="Stop", readonly=True)
    date = fields.Date(readonly=True)
    trip_id = fields.Many2one('h2o.trip', string="Trip", readonly=True)
    route_id = fields.Many2one('h2o.route', string="Route", readonly=True)
    driver_id = fields.Many2one('res.users', string="Driver", readonly=True)
    vehicle_id = fields.Many2one('fleet.vehicle', string="Vehicle", readonly=True)
    zone_id = fields.Many2one('h2o.zone', string="Zone", readonly=True)
    partner_id = fields.Many2one('res.partner', string="Customer", readonly=True)
    customer_type = fields.Selection(
        selection=lambda self: self.env['res.partner']._fields['h2o_customer_type'].selection,
        string="Customer Type", readonly=True,
    )
    company_id = fields.Many2one('res.company', readonly=True)
    currency_id = fields.Many2one('res.currency', readonly=True)
    state = fields.Selection(
        selection=lambda self: self.env['h2o.stop']._fields['state'].selection,
        string="Status", readonly=True,
    )
    failure_reason = fields.Selection(
        selection=lambda self: self.env['h2o.stop']._fields['failure_reason'].selection,
        readonly=True,
    )
    payment_method = fields.Selection(
        selection=lambda self: self.env['h2o.stop']._fields['payment_method'].selection,
        readonly=True,
    )
    stop_count = fields.Integer(string="Stops", readonly=True)
    delivered_count = fields.Integer(string="Delivered Stops", readonly=True)
    success_rate = fields.Float(
        string="Success Rate (%)", aggregator='avg', readonly=True,
        help="Share of stops delivered; failed and skipped stops count as misses, pending stops are left out.",
    )
    bottle_qty = fields.Float(string="Bottles Delivered", readonly=True,
                              help="Returnable water bottles delivered.")
    packaged_qty = fields.Float(string="Packaged Units Delivered", readonly=True,
                                help="Non-returnable water delivered, in units of the order line.")
    empties_collected = fields.Integer(readonly=True)
    payment_amount = fields.Monetary(string="Collected", readonly=True)

    def init(self):
        drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(SQL("""
            CREATE OR REPLACE VIEW %s AS (
                WITH line_qty AS (
                    SELECT line.stop_id,
                           SUM(CASE WHEN tmpl.h2o_product_kind = 'water_returnable'
                                    THEN line.qty_delivered ELSE 0 END) AS bottle_qty,
                           SUM(CASE WHEN tmpl.h2o_product_kind = 'water_packaged'
                                    THEN line.qty_delivered ELSE 0 END) AS packaged_qty
                      FROM h2o_stop_line line
                      JOIN product_product product ON product.id = line.product_id
                      JOIN product_template tmpl ON tmpl.id = product.product_tmpl_id
                  GROUP BY line.stop_id
                )
                SELECT stop.id AS id,
                       stop.id AS stop_id,
                       trip.date,
                       trip.id AS trip_id,
                       trip.route_id,
                       trip.driver_id,
                       trip.vehicle_id,
                       address.h2o_zone_id AS zone_id,
                       stop.commercial_partner_id AS partner_id,
                       customer.h2o_customer_type AS customer_type,
                       trip.company_id,
                       company.currency_id,
                       stop.state,
                       stop.failure_reason,
                       stop.payment_method,
                       1 AS stop_count,
                       CASE WHEN stop.state = 'delivered' THEN 1 ELSE 0 END AS delivered_count,
                       CASE WHEN stop.state = 'delivered' THEN 100.0
                            WHEN stop.state IN ('failed', 'skipped') THEN 0.0
                       END AS success_rate,
                       COALESCE(line_qty.bottle_qty, 0) AS bottle_qty,
                       COALESCE(line_qty.packaged_qty, 0) AS packaged_qty,
                       CASE WHEN stop.state = 'delivered' THEN stop.empties_collected ELSE 0 END
                           AS empties_collected,
                       CASE WHEN stop.state = 'delivered' THEN stop.payment_amount ELSE 0 END
                           AS payment_amount
                  FROM h2o_stop stop
                  JOIN h2o_trip trip ON trip.id = stop.trip_id
                  JOIN res_company company ON company.id = trip.company_id
                  JOIN res_partner address ON address.id = stop.partner_id
                  LEFT JOIN res_partner customer ON customer.id = stop.commercial_partner_id
                  LEFT JOIN line_qty ON line_qty.stop_id = stop.id
                 WHERE trip.state != 'cancelled'
            )
        """, SQL.identifier(self._table)))
