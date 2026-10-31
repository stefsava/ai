# Copyright 2026 Stefano Savanelli
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, new_test_user

from odoo.addons.ai_tool_report.models.ir_actions_report import MAX_TEXT_LENGTH


class TestAiToolReport(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.ui.view"].create(
            {
                "name": "ai_tool_report.test_partner_card",
                "key": "ai_tool_report.test_partner_card",
                "type": "qweb",
                "arch": """
                    <t t-name="ai_tool_report.test_partner_card">
                        <t t-foreach="docs" t-as="doc">
                            <p>Partner card: <span t-out="doc.name"/></p>
                        </t>
                    </t>
                """,
            }
        )
        cls.report = cls.env["ir.actions.report"].create(
            {
                "name": "Partner card",
                "model": "res.partner",
                "report_type": "qweb-html",
                "report_name": "ai_tool_report.test_partner_card",
                "ai_allowed": True,
            }
        )
        cls.partner = cls.env["res.partner"].create({"name": "Report Partner"})
        cls.user = new_test_user(cls.env, login="ai_report", groups="base.group_user")

    def _tool(self, name):
        return self.env.ref(f"ai_tool_report.{name}_tool").with_user(self.user)

    def _render(self, **kwargs):
        return self._tool("render_report")._execute_tool(
            **{"report": self.report.report_name, "ids": [self.partner.id], **kwargs}
        )

    def test_list_reports(self):
        reports = self._tool("list_reports")._execute_tool(model="res.partner")
        self.assertEqual(
            reports["reports"],
            [
                {
                    "report": "ai_tool_report.test_partner_card",
                    "name": "Partner card",
                    "model": "res.partner",
                }
            ],
        )
        self.report.ai_allowed = False
        reports = self._tool("list_reports")._execute_tool(model="res.partner")
        self.assertEqual(reports["reports"], [])

    def test_render_report(self):
        res = self._render()
        self.assertIn("Partner card: Report Partner", res["text"])
        self.assertFalse(res["truncated"])
        self.assertTrue(
            res["pdf_url"].endswith(
                f"/report/pdf/ai_tool_report.test_partner_card/{self.partner.id}"
            )
        )

    def test_render_truncated(self):
        self.partner.name = "x" * (MAX_TEXT_LENGTH + 10)
        res = self._render()
        self.assertEqual(len(res["text"]), MAX_TEXT_LENGTH)
        self.assertTrue(res["truncated"])

    def test_report_not_allowed(self):
        self.report.ai_allowed = False
        with self.assertRaises(UserError):
            self._render()

    def test_report_restricted_to_group(self):
        self.report.group_ids = self.env.ref("base.group_system")
        self.assertEqual(
            self._tool("list_reports")._execute_tool(model="res.partner")["reports"],
            [],
        )
        with self.assertRaises(UserError):
            self._render()

    def test_record_checks(self):
        for ids in ([], list(range(1, 12)), [self.partner.id, 999999999]):
            with self.subTest(ids=ids), self.assertRaises(UserError):
                self._render(ids=ids)

    def test_record_access(self):
        # A record the caller cannot read is not rendered, even though the
        # report is allowed.
        self.env["ir.rule"].create(
            {
                "name": "Hide the report partner",
                "model_id": self.env.ref("base.model_res_partner").id,
                "domain_force": f"[('id', '!=', {self.partner.id})]",
                "groups": [(4, self.env.ref("base.group_user").id)],
            }
        )
        with self.assertRaises(AccessError):
            self._render()
