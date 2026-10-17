from werkzeug.exceptions import BadRequest

from odoo import http
from odoo.http import request

from odoo.addons.h2o_base.controllers.api import API_PREFIX, h2o_route


class H2oPushController(http.Controller):

    @h2o_route(f'{API_PREFIX}/push/register')
    def h2o_push_register(self, token=None, platform='android', app='driver', device_name=None, **kw):
        Device = request.env['h2o.push.device']
        if not token:
            raise BadRequest("token is required")
        if platform not in dict(Device._fields['platform'].selection):
            raise BadRequest("platform must be android or ios")
        if app not in dict(Device._fields['app'].selection):
            raise BadRequest("app must be driver or customer")
        device = Device._h2o_register(token, platform, app, device_name)
        return {'id': device.id}

    @h2o_route(f'{API_PREFIX}/push/unregister')
    def h2o_push_unregister(self, token=None, **kw):
        if not token:
            raise BadRequest("token is required")
        devices = request.env['h2o.push.device'].search([('token', '=', token), ('user_id', '=', request.env.uid)])
        devices.action_archive()
        return {'ok': True}
