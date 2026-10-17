from datetime import UTC, timedelta
from zoneinfo import ZoneInfo

from odoo import api, fields, models

H2O_DEFAULT_TZ = 'Europe/Istanbul'


class ResPartner(models.Model):
    _inherit = 'res.partner'

    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        partners.filtered('h2o_customer_type')._h2o_apply_type_pricelist()
        return partners

    def write(self, vals):
        res = super().write(vals)
        if vals.get('h2o_customer_type') and 'property_product_pricelist' not in vals:
            self._h2o_apply_type_pricelist()
        return res

    def _h2o_apply_type_pricelist(self):
        """Give each partner the pricelist of its customer type, when the
        company has one configured."""
        for partner in self:
            company = partner.company_id or self.env.company
            pricelist = company._h2o_pricelist_for_type(partner.h2o_customer_type)
            if pricelist:
                partner.with_company(company).property_product_pricelist = pricelist

    def _h2o_next_delivery_date(self, from_datetime=None):
        """Next date the partner can be delivered, from ``from_datetime``
        (UTC, default now).

        Today is allowed only before the company's order cut-off hour, in the
        company time zone. Then the first day on one of the partner's delivery
        weekdays is returned; any day when it has none.
        """
        self.ensure_one()
        company = self.company_id or self.env.company
        tz = ZoneInfo(company.partner_id.tz or self.env.user.tz or H2O_DEFAULT_TZ)
        local_now = (from_datetime or fields.Datetime.now()).replace(tzinfo=UTC).astimezone(tz)
        day = local_now.date()
        hour = local_now.hour + local_now.minute / 60.0
        if hour >= company.h2o_order_cutoff_hour:
            day += timedelta(days=1)
        codes = set(self._h2o_delivery_weekdays().mapped('code'))
        if codes:
            while day.weekday() not in codes:
                day += timedelta(days=1)
        return day
