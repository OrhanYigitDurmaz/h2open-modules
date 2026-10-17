from odoo import api, fields, models
from odoo.exceptions import UserError


class H2oCashHandover(models.Model):
    _name = 'h2o.cash.handover'
    _description = 'Driver Cash Handover'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'
    _check_company_auto = True

    name = fields.Char(string="Reference", required=True, readonly=True, copy=False, default='/')
    trip_id = fields.Many2one(
        'h2o.trip', string="Trip", required=True, readonly=True, index=True, ondelete='restrict',
        check_company=True,
    )
    driver_id = fields.Many2one(related='trip_id.driver_id', store=True, index=True, string="Driver")
    company_id = fields.Many2one(related='trip_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='trip_id.currency_id')
    date = fields.Date(required=True, default=fields.Date.context_today, tracking=True)
    expected = fields.Monetary(
        related='trip_id.cash_expected', store=True,
        help="Cash collected on the delivered stops of the trip.",
    )
    counted = fields.Monetary(tracking=True, help="Cash counted when the driver handed it in.")
    difference = fields.Monetary(
        compute='_compute_difference', store=True,
        help="Counted minus expected: negative when cash is missing.",
    )
    state = fields.Selection(
        [('draft', "To Count"), ('approved', "Approved")],
        required=True, default='draft', readonly=True, copy=False, index=True, tracking=True,
    )
    approved_by = fields.Many2one('res.users', readonly=True, copy=False)
    note = fields.Text()

    _trip_uniq = models.Constraint('UNIQUE(trip_id)', "A trip has only one cash handover.")

    @api.depends('expected', 'counted')
    def _compute_difference(self):
        for handover in self:
            handover.difference = handover.counted - handover.expected

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('h2o.cash.handover') or '/'
        return super().create(vals_list)

    def action_approve(self):
        """The cash is counted: record it as handed in on the trip."""
        self.check_access('write')
        if any(handover.state != 'draft' for handover in self):
            raise UserError(self.env._("Only handovers to count can be approved."))
        for handover in self:
            # accountants only read trips
            handover.trip_id.sudo().cash_handed_in = handover.counted
        self.write({'state': 'approved', 'approved_by': self.env.uid})
        return True

    def action_draft(self):
        """Reopen an approved handover to count it again."""
        self.check_access('write')
        self.trip_id.sudo().cash_handed_in = 0.0
        self.write({'state': 'draft', 'approved_by': False})
        return True
