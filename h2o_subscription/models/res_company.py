from odoo import fields, models
from odoo.addons.h2o_order.models.res_partner import H2O_DEFAULT_TZ


class ResCompany(models.Model):
    _inherit = 'res.company'

    h2o_subscription_lead_days = fields.Integer(
        string="Subscription Lead Days", default=1,
        help="Subscription orders are created this many days before their delivery date.",
    )

    def _h2o_today(self):
        """Today's date in the company time zone, as used for delivery dates."""
        self.ensure_one()
        tz = self.partner_id.tz or self.env.user.tz or H2O_DEFAULT_TZ
        return fields.Date.context_today(self.with_context(tz=tz))
