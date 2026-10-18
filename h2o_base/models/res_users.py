from datetime import timedelta

from odoo import fields, models

H2O_APP_SCOPE = 'h2o_app'


class ResUsers(models.Model):
    _inherit = 'res.users'

    def _h2o_app_roles(self):
        """Return the H2Open roles of the user, most powerful first."""
        self.ensure_one()
        roles = []
        for role, xmlid in (
            ('manager', 'h2o_base.group_h2o_manager'),
            ('dispatcher', 'h2o_base.group_h2o_dispatcher'),
            ('accountant', 'h2o_base.group_h2o_accountant'),
            ('driver', 'h2o_base.group_h2o_driver'),
        ):
            if self.has_group(xmlid):
                roles.append(role)
        return roles

    def _h2o_issue_app_token(self, device_name):
        """Create a scoped API key for a mobile app login and return it.

        The key only works on H2Open app routes (scope ``h2o_app``), not on
        Odoo's generic JSON-RPC, and expires after the company setting.
        """
        self.ensure_one()
        days = self.company_id.h2o_app_token_days or 30
        expiration = fields.Datetime.now() + timedelta(days=days)
        name = "H2Open app: %s" % (device_name or "unknown device")
        return self.env['res.users.apikeys'].with_user(self).sudo()._generate(H2O_APP_SCOPE, name, expiration)

    def _h2o_app_profile(self):
        """Public profile returned to the mobile apps."""
        self.ensure_one()
        return {
            'id': self.id,
            'name': self.name,
            'login': self.login,
            'lang': self.lang,
            'tz': self.tz,
            'company': {'id': self.company_id.id, 'name': self.company_id.name},
            'roles': self._h2o_app_roles(),
        }
