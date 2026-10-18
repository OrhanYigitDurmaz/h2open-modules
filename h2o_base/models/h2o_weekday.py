from odoo import api, fields, models


class H2oWeekday(models.Model):
    _name = 'h2o.weekday'
    _description = 'Weekday'
    _order = 'code'

    name = fields.Char(required=True, translate=True)
    code = fields.Integer(
        required=True,
        help="Python weekday number: 0 is Monday, 6 is Sunday.",
    )

    _code_unique = models.Constraint('UNIQUE(code)', 'Each weekday can only exist once.')
    _code_range = models.Constraint('CHECK(code >= 0 AND code <= 6)', 'Weekday code must be between 0 and 6.')

    @api.model
    def _h2o_from_date(self, date):
        """Return the weekday record of a date."""
        return self.search([('code', '=', date.weekday())], limit=1)
