import logging
import re
import threading
import time
from urllib.parse import parse_qs, unquote, urlsplit

import requests

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

# Changing one of these may move the partner to another zone.
H2O_ZONE_TRIGGER_FIELDS = ('zip', 'city', 'street2', 'state_id', 'parent_id', 'h2o_customer_type')

NOMINATIM_URL = 'https://nominatim.openstreetmap.org/search'
# Nominatim's usage policy: at most one request per second, from the whole server.
NOMINATIM_INTERVAL = 1.0
_nominatim_lock = threading.Lock()
_nominatim_last = [0.0]
# Hosts a shared Google Maps link may redirect through. Only these are fetched.
MAPS_LINK_HOSTS = re.compile(r'^(maps\.app\.goo\.gl|goo\.gl|(www\.|maps\.)?google\.com(\.tr)?)$')
MAX_REDIRECTS = 5

_NUM = r'(-?\d{1,3}(?:\.\d+)?)'
# A bare pair needs decimals, so two plain numbers (a door and a floor) are not taken for one.
_DEC = r'(-?\d{1,3}\.\d+)'
# Most exact first: a place pin (!3d…!4d…) beats the map center (@lat,lng).
_LOCATION_PATTERNS = [
    re.compile(r'!3d' + _NUM + r'!4d' + _NUM),
    re.compile(r'@' + _NUM + ',' + _NUM),
    re.compile(r'^geo:' + _NUM + ',' + _NUM),
    re.compile(r'^\s*' + _DEC + r'\s*[,;\s]\s*' + _DEC + r'\s*$'),
]
_LOCATION_PARAMS = ('q', 'query', 'll', 'destination', 'daddr', 'center')


def _point(lat, lng):
    lat, lng = float(lat), float(lng)
    if -90 <= lat <= 90 and -180 <= lng <= 180 and (lat or lng):
        return [lat, lng]
    return None


def h2o_parse_location(text):
    """[latitude, longitude] from a pasted location: "41.03, 28.98", a
    ``geo:`` URI or a long Google Maps link. None when there is none."""
    text = unquote((text or '').strip())
    for pattern in _LOCATION_PATTERNS:
        match = pattern.search(text)
        if match:
            point = _point(*match.groups())
            if point:
                return point
    if text.startswith(('http://', 'https://')):
        for name, values in parse_qs(urlsplit(text).query).items():
            if name in _LOCATION_PARAMS:
                match = _LOCATION_PATTERNS[-1].match(values[0])
                point = match and _point(*match.groups())
                if point:
                    return point
    return None


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
    h2o_has_location = fields.Boolean(
        string="Has Location", compute='_compute_h2o_has_location', store=True,
        help="Whether the exact coordinates of the address are set.",
    )
    h2o_payment_mode = fields.Selection(
        [('cash', "Cash"), ('card', "Card"), ('account', "Monthly Account")],
        string="Payment Mode", default='cash', tracking=True,
        help="Cash and card customers pay on delivery; account customers get a monthly invoice.",
    )

    @api.depends('partner_latitude', 'partner_longitude')
    def _compute_h2o_has_location(self):
        for partner in self:
            partner.h2o_has_location = bool(partner.partner_latitude or partner.partner_longitude)

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

    # ------------------------------------------------------------------
    # Location picker (customer form map)
    # ------------------------------------------------------------------

    @api.model
    def h2o_locate(self, text):
        """What the location box of the customer form found for ``text``:
        ``{'point': [lat, lng]}`` for a pasted location or Google Maps link,
        else ``{'results': [{'name', 'lat', 'lng'}]}`` from an address search."""
        if not self.env.user._is_internal():
            raise AccessError(self.env._("Only employees can look up locations."))
        text = (text or '').strip()[:500]
        if not text:
            return {'results': []}
        point = h2o_parse_location(text)
        if not point and text.startswith(('http://', 'https://')):
            point = h2o_parse_location(self._h2o_follow_maps_link(text))
        if point:
            return {'point': point}
        return {'results': self._h2o_nominatim_search(text)}

    @api.model
    def _h2o_follow_maps_link(self, url):
        """The URL a short Google Maps link (maps.app.goo.gl/…) redirects to:
        followed until it holds a location or leaves Google's hosts."""
        for _hop in range(MAX_REDIRECTS + 1):
            parts = urlsplit(url)
            if h2o_parse_location(url) or parts.scheme != 'https' \
                    or not MAPS_LINK_HOSTS.match(parts.hostname or ''):
                return url
            try:
                response = requests.get(url, allow_redirects=False, timeout=10)
            except requests.RequestException as e:
                _logger.info("Could not open the maps link %s: %s", url, e)
                raise UserError(self.env._("Could not open this link. Check the connection and try again.")) from None
            location = response.headers.get('Location')
            if not response.is_redirect or not location:
                return url
            url = requests.compat.urljoin(url, location)
        return url

    @api.model
    def _h2o_nominatim_search(self, query):
        """Up to 5 places matching ``query`` in Türkiye, from OpenStreetMap."""
        with _nominatim_lock:
            wait = _nominatim_last[0] + NOMINATIM_INTERVAL - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            try:
                response = requests.get(NOMINATIM_URL, timeout=10, params={
                    'q': query, 'format': 'jsonv2', 'countrycodes': 'tr', 'limit': 5,
                    'accept-language': self.env.lang and self.env.lang[:2] or 'tr',
                }, headers={
                    # Nominatim requires an identifying user agent.
                    'User-Agent': 'H2Open Odoo (%s)' % self.env['ir.config_parameter'].sudo().get_str('web.base.url'),
                })
                response.raise_for_status()
                places = response.json()
            except (requests.RequestException, ValueError) as e:
                _logger.info("OpenStreetMap search failed for %r: %s", query, e)
                raise UserError(self.env._("The address search is not available right now. Place the pin by hand.")) from None
            finally:
                _nominatim_last[0] = time.monotonic()
        return [{'name': place.get('display_name', ''), 'lat': float(place['lat']), 'lng': float(place['lon'])}
                for place in places if place.get('lat') and place.get('lon')]
