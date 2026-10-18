from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    h2o_bottle_balance = fields.Integer(
        string="Bottles Held", compute='_compute_h2o_container_balances', compute_sudo=True,
        help="Returnable bottles the customer currently holds, from the bottle ledger.",
    )
    h2o_deposit_balance = fields.Monetary(
        string="Deposit Held", compute='_compute_h2o_container_balances', compute_sudo=True,
        currency_field='currency_id',
        help="Deposits charged minus deposits refunded, from the bottle ledger.",
    )
    h2o_container_move_count = fields.Integer(
        string="Ledger Entries", compute='_compute_h2o_container_balances', compute_sudo=True,
    )

    @api.depends('commercial_partner_id')
    def _compute_h2o_container_balances(self):
        commercials = self.commercial_partner_id
        data = {
            partner: (qty_out - qty_in, deposit, count)
            for partner, qty_out, qty_in, deposit, count in self.env['h2o.container.move']._read_group(
                [('partner_id', 'in', commercials.ids), ('state', '=', 'done')],
                ['partner_id'], ['qty_out:sum', 'qty_in:sum', 'deposit_amount:sum', '__count'],
            )
        }
        for partner in self:
            partner.h2o_bottle_balance, partner.h2o_deposit_balance, partner.h2o_container_move_count = \
                data.get(partner.commercial_partner_id, (0, 0.0, 0))

    def _h2o_bottle_balance_by_product(self):
        """Bottles held by the (commercial) partner per container: ``{product: qty}``.
        Containers with a zero balance are left out."""
        self.ensure_one()
        groups = self.env['h2o.container.move'].sudo()._read_group(
            [('partner_id', '=', self.commercial_partner_id.id), ('state', '=', 'done')],
            ['product_id'], ['qty_out:sum', 'qty_in:sum'],
        )
        Product = self.env['product.product']
        return {
            Product.browse(product.id): qty_out - qty_in
            for product, qty_out, qty_in in groups
            if qty_out != qty_in
        }

    def action_h2o_view_container_moves(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('h2o_container.h2o_container_move_action')
        action['domain'] = [('partner_id', '=', self.commercial_partner_id.id)]
        action['context'] = {
            'default_partner_id': self.commercial_partner_id.id,
            'search_default_done': 1,
        }
        return action
