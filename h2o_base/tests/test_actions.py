import ast

from odoo.tests import TransactionCase, tagged

# Names the web client can evaluate in an action's context or domain.
CLIENT_NAMES = {
    'uid', 'active_id', 'active_ids', 'active_model', 'allowed_company_ids',
    'context_today', 'current_date', 'datetime', 'relativedelta', 'time',
    'True', 'False', 'None',
}


@tagged('post_install', '-at_install')
class TestActions(TransactionCase):

    def test_window_action_context_and_domain_evaluate_in_client(self):
        """A ref() left in a text <field name="context"> is stored as-is and
        only fails when the user clicks the menu."""
        data = self.env['ir.model.data'].search([
            ('module', '=like', 'h2o_%'), ('model', '=', 'ir.actions.act_window'),
        ])
        for action in self.env['ir.actions.act_window'].browse(data.mapped('res_id')):
            for fname in ('context', 'domain'):
                expr = action[fname]
                if not expr:
                    continue
                with self.subTest(action=action.name, field=fname):
                    tree = ast.parse(expr, mode='eval')
                    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
                    self.assertFalse(names - CLIENT_NAMES, f'{fname} = {expr}')
