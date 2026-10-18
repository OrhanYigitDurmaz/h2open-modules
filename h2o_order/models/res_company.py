from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    h2o_pricelist_home_id = fields.Many2one(
        'product.pricelist', string="Home Customers Pricelist", check_company=True,
    )
    h2o_pricelist_office_id = fields.Many2one(
        'product.pricelist', string="Office Customers Pricelist", check_company=True,
    )
    h2o_pricelist_reseller_id = fields.Many2one(
        'product.pricelist', string="Resellers Pricelist", check_company=True,
    )

    def _h2o_pricelist_for_type(self, customer_type):
        """Pricelist configured for a water customer type, or an empty recordset."""
        self.ensure_one()
        field = {
            'home': 'h2o_pricelist_home_id',
            'office': 'h2o_pricelist_office_id',
            'reseller': 'h2o_pricelist_reseller_id',
        }.get(customer_type)
        return self[field] if field else self.env['product.pricelist']
