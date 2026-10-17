from datetime import timedelta

from odoo import api, fields, models

LOG_RETENTION_DAYS = 30


class H2oPushLog(models.Model):
    _name = 'h2o.push.log'
    _description = 'Push Notification Log'
    _order = 'id desc'

    user_id = fields.Many2one('res.users', string="User", index=True, ondelete='cascade')
    device_id = fields.Many2one('h2o.push.device', string="Device", ondelete='set null')
    data = fields.Json(string="Data")
    state = fields.Selection([('sent', "Sent"), ('failed', "Failed")], required=True)
    error = fields.Text()

    @api.autovacuum
    def _gc_h2o_push_log(self):
        limit = fields.Datetime.now() - timedelta(days=LOG_RETENTION_DAYS)
        self.search([('create_date', '<', limit)]).unlink()
