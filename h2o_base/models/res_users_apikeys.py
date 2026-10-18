from odoo import models

from .h2o_app_session import H2O_APP_SCOPE


class ResUsersApikeys(models.Model):
    _inherit = 'res.users.apikeys'

    def _check_credentials(self, *, scope, key):
        uid = super()._check_credentials(scope=scope, key=key)
        if uid and scope == H2O_APP_SCOPE:
            self.env['h2o.app.session']._h2o_touch(uid, key)
        return uid
