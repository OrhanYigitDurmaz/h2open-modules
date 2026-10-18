import re

from odoo import api, models
from odoo.tools import SQL

# Numbers shorter than this are internal extensions, never customers.
MIN_LOOKUP_DIGITS = 7


def h2o_normalize_phone(number):
    """Return a phone number in a form that can be compared.

    Turkish numbers become their 10 national digits whatever the way they are
    written: ``+90 532 123 45 67``, ``0090 532...``, ``0 (532) 123 45 67``
    and ``532 123 45 67`` all give ``5321234567``. Other international
    numbers keep their country code, without ``+`` or ``00``.
    """
    digits = re.sub(r'\D', '', number or '')
    if digits.startswith('00'):
        digits = digits[2:]
    elif digits.startswith('0'):
        return digits[1:]
    if digits.startswith('90') and len(digits) == 12:
        return digits[2:]
    return digits


class ResPartner(models.Model):
    _inherit = 'res.partner'

    @api.model
    def _h2o_find_by_phone(self, number):
        """Return the partner whose phone is ``number`` (any format), or an empty recordset.

        When several contacts share the number, the top-level one (company or
        main contact) wins over its addresses and employees.
        """
        normalized = h2o_normalize_phone(number)
        if len(normalized) < MIN_LOOKUP_DIGITS:
            return self.browse()
        # Phones are stored as typed: compare their trailing digits in SQL to
        # narrow down, then the full normalized number in Python.
        self.flush_model(['phone'])
        rows = self.env.execute_query(SQL(
            "SELECT id FROM res_partner WHERE right(regexp_replace(phone, '[^0-9]', '', 'g'), %s) = %s",
            MIN_LOOKUP_DIGITS, normalized[-MIN_LOOKUP_DIGITS:],
        ))
        partners = self.search([('id', 'in', [row[0] for row in rows])]).filtered(
            lambda partner: h2o_normalize_phone(partner.phone) == normalized)
        return partners.sorted(lambda partner: (bool(partner.parent_id), partner.id))[:1]
