from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    h2o_product_kind = fields.Selection(
        [
            ('water_returnable', "Water in Returnable Bottle"),
            ('water_packaged', "Packaged Water"),
            ('container', "Returnable Container"),
            ('deposit', "Container Deposit"),
        ],
        string="Water Product Kind", index=True,
        help="Returnable water is delivered in a container tracked on the customer's bottle ledger; "
             "packaged water is a plain product. Containers are the empty bottles themselves, "
             "deposits the amount charged per container held by a customer.",
    )
    h2o_volume = fields.Float(string="Volume (L)", digits=(16, 2))
    h2o_container_product_id = fields.Many2one(
        'product.product', string="Container",
        domain="[('h2o_product_kind', '=', 'container')]",
        help="The returnable bottle this water comes in.",
    )
    h2o_deposit_product_id = fields.Many2one(
        'product.product', string="Deposit Product",
        domain="[('h2o_product_kind', '=', 'deposit')]",
        help="The deposit charged per container; its sales price is the deposit amount.",
    )

    @api.onchange('h2o_product_kind')
    def _onchange_h2o_product_kind(self):
        if self.h2o_product_kind == 'deposit':
            self.type = 'service'
        elif self.h2o_product_kind and self.type == 'service':
            self.type = 'consu'

    @api.constrains('h2o_product_kind', 'h2o_container_product_id', 'h2o_deposit_product_id')
    def _check_h2o_links(self):
        for template in self:
            if template.h2o_container_product_id and (
                template.h2o_product_kind != 'water_returnable'
                or template.h2o_container_product_id.h2o_product_kind != 'container'
            ):
                raise ValidationError(self.env._(
                    "Only returnable water can have a container, and it must be a container product (%s).",
                    template.display_name,
                ))
            if template.h2o_deposit_product_id and (
                template.h2o_product_kind != 'container'
                or template.h2o_deposit_product_id.h2o_product_kind != 'deposit'
            ):
                raise ValidationError(self.env._(
                    "Only containers can have a deposit product, and it must be a deposit product (%s).",
                    template.display_name,
                ))
