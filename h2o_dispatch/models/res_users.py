from odoo import fields, models

from odoo.addons.h2o_order.models.res_partner import H2O_DEFAULT_TZ


class ResUsers(models.Model):
    _inherit = 'res.users'

    def _h2o_today(self):
        """Today in the user's time zone (else their company's, else Türkiye's):
        the day of the trip a driver works on now."""
        self.ensure_one()
        tz = self.tz or self.company_id.partner_id.tz or H2O_DEFAULT_TZ
        return fields.Date.context_today(self.with_context(tz=tz))
