"""Shared JSON API for the H2Open mobile apps.

Apps sign in once with ``POST /h2o/api/v1/login`` and get an API key scoped to
``h2o_app``. Every other app route is declared with :func:`h2o_route`, which
requires that key as ``Authorization: Bearer <token>``. Bodies and responses
are plain JSON (Odoo's ``json2`` route type); errors come back as JSON with
an HTTP error status.
"""
import logging

from werkzeug.exceptions import Unauthorized

from odoo import http
from odoo.exceptions import AccessDenied
from odoo.http import request
from odoo.tools import SQL

from odoo.addons.h2o_base.models.res_users import H2O_APP_SCOPE

_logger = logging.getLogger(__name__)

API_PREFIX = '/h2o/api/v1'


def h2o_route(path, methods=('POST',), **kwargs):
    """Declare an authenticated H2Open app route (bearer token, JSON in and out)."""
    return http.route(
        path,
        type='json2',
        auth='bearer',
        bearer_scope=H2O_APP_SCOPE,
        methods=list(methods),
        csrf=False,
        save_session=False,
        **kwargs,
    )


class H2oApiController(http.Controller):

    @http.route(f'{API_PREFIX}/login', type='json2', auth='public', methods=['POST'],
                csrf=False, save_session=False)
    def h2o_login(self, login=None, password=None, device_name=None, **kw):
        if not login or not password:
            raise Unauthorized("login and password are required")
        credential = {'type': 'password', 'login': login, 'password': password}
        try:
            auth_info = request.env['res.users'].sudo()._login(credential, user_agent_env={'interactive': True})
        except AccessDenied:
            raise Unauthorized("Wrong login or password")
        user = request.env['res.users'].sudo().browse(auth_info['uid'])
        if not user._h2o_app_roles():
            raise Unauthorized("This user has no H2Open role")
        token = user._h2o_issue_app_token(device_name)
        return {'token': token, 'user': user._h2o_app_profile()}

    @h2o_route(f'{API_PREFIX}/logout')
    def h2o_logout(self, **kw):
        # Only the key used for this request is removed; other devices stay signed in.
        # The bearer check already validated the token, so its 8-char index identifies it.
        token = request.httprequest.headers.get('Authorization', '').split(' ', 1)[-1].strip()
        request.env.cr.execute(SQL(
            "DELETE FROM res_users_apikeys WHERE user_id = %s AND scope = %s AND index = %s",
            request.env.uid, H2O_APP_SCOPE, token[:8],
        ))
        request.env.transaction.invalidate_ormcache()
        return {'ok': True}

    @h2o_route(f'{API_PREFIX}/me', methods=('GET', 'POST'))
    def h2o_me(self, **kw):
        return request.env.user._h2o_app_profile()
