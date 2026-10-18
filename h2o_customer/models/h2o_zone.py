import re

from odoo import api, fields, models

# Fold Turkish letters to ASCII so "Kadıköy", "KADIKÖY" and "Kadikoy" all match.
_TR_FOLD = str.maketrans({
    'ı': 'i', 'İ': 'i', 'I': 'i', 'ğ': 'g', 'Ğ': 'g', 'ü': 'u', 'Ü': 'u',
    'ş': 's', 'Ş': 's', 'ö': 'o', 'Ö': 'o', 'ç': 'c', 'Ç': 'c', 'â': 'a', 'Â': 'a',
    'î': 'i', 'Î': 'i', 'û': 'u', 'Û': 'u',
})


def _h2o_normalize(text):
    """Lower-case, Turkish-folded, single-spaced version of ``text``."""
    return ' '.join((text or '').translate(_TR_FOLD).lower().split())


def _h2o_split(text):
    """Normalized non-empty items of a comma-separated list."""
    return [item for item in (_h2o_normalize(part) for part in (text or '').split(',')) if item]


class H2oZone(models.Model):
    _name = 'h2o.zone'
    _description = 'Delivery Zone'
    _order = 'sequence, name'
    _check_company_auto = True

    name = fields.Char(required=True, translate=True)
    code = fields.Char()
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    country_id = fields.Many2one('res.country', default=lambda self: self.env.ref('base.tr', raise_if_not_found=False))
    state_id = fields.Many2one(
        'res.country.state', string="Province (İl)",
        domain="[('country_id', '=?', country_id)]",
    )
    district_names = fields.Char(
        string="Districts / Neighbourhoods",
        help="Comma-separated ilçe or mahalle names. A customer whose city or second address line "
             "contains one of them belongs to this zone.",
    )
    zip_codes = fields.Char(
        string="Postal Codes",
        help="Comma-separated postal codes. They are checked before the district names.",
    )
    weekday_ids = fields.Many2many('h2o.weekday', string="Delivery Days")
    partner_ids = fields.One2many('res.partner', 'h2o_zone_id', string="Customers")
    partner_count = fields.Integer(compute='_compute_partner_count', string="Customer Count")
    color = fields.Integer()
    note = fields.Text()

    _code_company_unique = models.Constraint(
        'UNIQUE(code, company_id)', 'The zone code must be unique per company.',
    )

    @api.depends('partner_ids')
    def _compute_partner_count(self):
        counts = dict(self.env['res.partner']._read_group(
            [('h2o_zone_id', 'in', self.ids)], ['h2o_zone_id'], ['__count'],
        ))
        for zone in self:
            zone.partner_count = counts.get(zone, 0)

    @api.model
    def _h2o_match_partner(self, partner):
        """Return the zone of ``partner``'s address, or an empty recordset.

        Postal codes are checked first, then the district names against the
        partner's second street line (mahalle), then its city (ilçe). A zone with a province only
        matches partners in that province (or without one). When called on a
        recordset, only those zones are candidates; otherwise every active
        zone of the partner's company.
        """
        zones = self
        if not zones:
            company = partner.company_id or self.env.company
            zones = self.search([('company_id', '=', company.id)])
        if partner.state_id:
            zones = zones.filtered(lambda z: not z.state_id or z.state_id == partner.state_id)

        zip_code = _h2o_normalize(partner.zip)
        if zip_code:
            for zone in zones:
                if zip_code in _h2o_split(zone.zip_codes):
                    return zone

        # street2 usually holds the mahalle, more precise than the ilçe in city
        for text in (_h2o_normalize(partner.street2), _h2o_normalize(partner.city)):
            if not text:
                continue
            for zone in zones:
                for district in _h2o_split(zone.district_names):
                    if re.search(r'(?<!\w)%s(?!\w)' % re.escape(district), text):
                        return zone
        return self.browse()

    def action_view_partners(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('h2o_customer.h2o_customer_action')
        action['domain'] = [('h2o_zone_id', '=', self.id)]
        action['context'] = {'default_h2o_zone_id': self.id}
        return action

    def action_h2o_assign_partners(self):
        """Assign this zone to the water customers without a zone that match it."""
        partners = self.env['res.partner'].search([
            ('h2o_zone_id', '=', False),
            ('commercial_partner_id.h2o_customer_type', '!=', False),
        ])
        for partner in partners:
            zone = self._h2o_match_partner(partner)
            if zone:
                partner.h2o_zone_id = zone
        return True
