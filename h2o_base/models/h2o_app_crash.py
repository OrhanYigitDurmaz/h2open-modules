from datetime import timedelta

from odoo import api, fields, models

# Crash reports older than this are deleted.
KEEP_CRASH_DAYS = 90
# Longest stack trace kept; the top of the trace is what matters.
MAX_TRACE_CHARS = 20000


class H2oAppCrash(models.Model):
    """A crash of a mobile app, sent by the app the next time it runs."""
    _name = 'h2o.app.crash'
    _description = 'App Crash Report'
    _order = 'occurred_at desc, id desc'
    _rec_name = 'exception'

    user_id = fields.Many2one('res.users', string="User", index=True, ondelete='cascade', readonly=True)
    app = fields.Char(string="App", readonly=True)
    app_version = fields.Char(string="App Version", readonly=True)
    device = fields.Char(string="Device", readonly=True)
    os_version = fields.Char(string="Android Version", readonly=True)
    occurred_at = fields.Datetime(string="Crashed At", readonly=True)
    exception = fields.Char(string="Exception", readonly=True, help="First line of the stack trace.")
    stack_trace = fields.Text(string="Stack Trace", readonly=True)

    @api.model
    def _h2o_report(self, user, reports):
        """Store crash reports sent by ``user``'s app; each report is a dict
        with ``stack_trace`` and optional ``app``, ``app_version``, ``device``,
        ``os_version`` and ``occurred_at`` (ISO 8601, UTC)."""
        vals_list = []
        for report in reports:
            trace = str(report.get('stack_trace') or '')[:MAX_TRACE_CHARS]
            if not trace.strip():
                continue
            try:
                occurred_at = fields.Datetime.to_datetime(str(report.get('occurred_at') or '')[:19].replace('T', ' '))
            except ValueError:
                occurred_at = None
            vals_list.append({
                'user_id': user.id,
                'app': str(report.get('app') or '')[:64],
                'app_version': str(report.get('app_version') or '')[:64],
                'device': str(report.get('device') or '')[:128],
                'os_version': str(report.get('os_version') or '')[:64],
                'occurred_at': occurred_at or fields.Datetime.now(),
                'exception': trace.strip().splitlines()[0][:256],
                'stack_trace': trace,
            })
        return self.sudo().create(vals_list)

    @api.autovacuum
    def _gc_h2o_app_crashes(self):
        limit = fields.Datetime.now() - timedelta(days=KEEP_CRASH_DAYS)
        self.sudo().search([('occurred_at', '<', limit)]).unlink()
