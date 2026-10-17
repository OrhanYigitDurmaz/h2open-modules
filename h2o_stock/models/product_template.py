from odoo import api, models

# Water product kinds kept in stock: full bottles, packaged water and the empty bottles.
H2O_STORABLE_KINDS = ('water_returnable', 'water_packaged', 'container')


def _h2o_default_storable(vals_list):
    """``is_storable`` has a default, so its compute does not run on create:
    new water and container products are made storable here."""
    for vals in vals_list:
        if (
            vals.get('h2o_product_kind') in H2O_STORABLE_KINDS
            and vals.get('type', 'consu') == 'consu'
            and 'is_storable' not in vals
        ):
            vals['is_storable'] = True
    return vals_list


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    @api.model_create_multi
    def create(self, vals_list):
        return super().create(_h2o_default_storable(vals_list))

    @api.depends('h2o_product_kind')
    def _compute_is_storable(self):
        super()._compute_is_storable()
        self.filtered(lambda t: t.h2o_product_kind in H2O_STORABLE_KINDS and t.type == 'consu').is_storable = True

    @api.model
    def _h2o_make_storable(self):
        """Make the existing water and container products storable (on install)."""
        self.with_context(active_test=False).search([
            ('h2o_product_kind', 'in', H2O_STORABLE_KINDS), ('type', '=', 'consu'), ('is_storable', '=', False),
        ]).is_storable = True


class ProductProduct(models.Model):
    _inherit = 'product.product'

    @api.model_create_multi
    def create(self, vals_list):
        return super().create(_h2o_default_storable(vals_list))
