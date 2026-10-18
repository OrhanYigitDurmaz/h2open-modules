from odoo import api, fields, models

# Changing one of these may move the partner to another zone.
H2O_ZONE_TRIGGER_FIELDS = ('zip', 'city', 'street2', 'state_id', 'parent_id', 'h2o_customer_type')


class ResPartner(models.Model):
    _inherit = 'res.partner'

    h2o_customer_type = fields.Selection(
        [('home', "Home"), ('office', "Office"), ('reseller', "Reseller")],
        string="Water Customer Type", index=True, tracking=True,
        help="Empty when the contact is not a water delivery customer.",
    )
    h2o_zone_id = fields.Many2one(
        'h2o.zone', string="Delivery Zone", index=True, tracking=True,
        help="Filled automatically from the address when empty.",
    )
    h2o_weekday_ids = fields.Many2many(
        'h2o.weekday', 'h2o_partner_weekday_rel', 'partner_id', 'weekday_id',
        string="Preferred Delivery Days",
        help="Leave empty to use the delivery days of the zone.",
    )
    h2o_delivery_notes = fields.Text(
        string="Delivery Notes",
        help="Shown to the driver: door code, where to leave the bottles, ...",
    )
    h2o_floor = fields.Integer(string="Floor")
    h2o_has_elevator = fields.Boolean(string="Elevator")
    h2o_payment_mode = fields.Selection(
        [('cash', "Cash"), ('card', "Card"), ('account', "Monthly Account")],
        string="Payment Mode", default='cash', tracking=True,
        help="Cash and card customers pay on delivery; account customers get a monthly invoice.",
    )

    @api.onchange(*H2O_ZONE_TRIGGER_FIELDS)
    def _onchange_h2o_zone_address(self):
        if not self.h2o_zone_id and self._h2o_is_water_partner():
            self.h2o_zone_id = self.env['h2o.zone']._h2o_match_partner(self)

    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        partners.filtered(lambda p: not p.h2o_zone_id)._h2o_assign_zone()
        return partners

    def write(self, vals):
        res = super().write(vals)
        if 'h2o_zone_id' not in vals and any(fname in vals for fname in H2O_ZONE_TRIGGER_FIELDS):
            self.filtered(lambda p: not p.h2o_zone_id)._h2o_assign_zone()
        return res

    def _h2o_is_water_partner(self):
        """Whether the partner (or its company) is a water delivery customer."""
        self.ensure_one()
        return bool(self.h2o_customer_type or self.parent_id.commercial_partner_id.h2o_customer_type)

    def _h2o_assign_zone(self):
        """Set the zone of water customers from their address, when one matches."""
        Zone = self.env['h2o.zone'].sudo()
        for partner in self:
            if partner._h2o_is_water_partner():
                zone = Zone._h2o_match_partner(partner)
                if zone:
                    partner.h2o_zone_id = zone.id

    def _h2o_delivery_weekdays(self):
        """Delivery days of the partner: its own preferred days, else those of
        its company, else the days of its delivery zone."""
        self.ensure_one()
        commercial = self.commercial_partner_id
        zone = self.h2o_zone_id or commercial.h2o_zone_id
        return self.h2o_weekday_ids or commercial.h2o_weekday_ids or zone.weekday_ids
