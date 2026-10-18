from odoo import models


class H2oAppSession(models.Model):
    _inherit = 'h2o.app.session'

    def _h2o_revoke(self, reason):
        active = self.filtered(lambda s: s.state == 'active')
        super()._h2o_revoke(reason)
        # A signed-out phone must not keep ringing for calls or showing trips.
        self.env['h2o.push.device'].sudo().search([('session_id', 'in', active.ids)]).active = False
