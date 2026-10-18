from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    h2o_push_fcm_project_id = fields.Char(
        string="FCM Project ID",
        config_parameter='h2o_push.fcm_project_id',
        groups='base.group_system',
    )
    h2o_push_fcm_service_account = fields.Char(
        string="FCM Service Account",
        config_parameter='h2o_push.fcm_service_account',
        groups='base.group_system',
        help="Content of the JSON key file of a Google service account allowed to send Firebase messages.",
    )
