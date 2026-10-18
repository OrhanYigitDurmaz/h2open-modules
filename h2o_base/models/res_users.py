from odoo import fields, models



class ResUsers(models.Model):
    _inherit = 'res.users'

    h2o_app_session_ids = fields.One2many('h2o.app.session', 'user_id', string="App Devices",
                                          groups='h2o_base.group_h2o_manager')

    def write(self, vals):
        res = super().write(vals)
        if vals.get('active') is False or vals.get('password'):
            # A stolen phone is handled by archiving the user or resetting the password.
            self.env['h2o.app.session'].sudo().search([
                ('user_id', 'in', self.ids), ('state', '=', 'active'),
            ])._h2o_revoke('user')
        return res

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

    def _h2o_app_login(self, device_name):
        """Sign the user in on a new device; return the token dict for the app
        (see ``h2o.app.session._h2o_issue_tokens``)."""
        self.ensure_one()
        return self.env['h2o.app.session']._h2o_start(self, device_name)

    def _h2o_issue_app_token(self, device_name):
        """Sign the user in on a new device and return only the access token
        (bearer for the H2Open app routes). Handy in tests."""
        return self._h2o_app_login(device_name)['access_token']

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
