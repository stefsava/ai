# Copyright 2026 Stefano Savanelli
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, new_test_user

from odoo.addons.ai_tool_read.models.ir_model import MAX_GROUP_LIMIT


class TestAiToolReadGroup(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        IrModelFields = cls.env["ir.model.fields"]
        # Start from a known state: only res.partner.email is forbidden.
        IrModelFields.search([("ai_no_read", "=", True)]).ai_no_read = False
        IrModelFields.search(
            [("model", "=", "res.partner"), ("name", "=", "email")], limit=1
        ).ai_no_read = True
        cls.company = cls.env["res.partner"].create(
            {"name": "Count Co", "is_company": True}
        )
        cls.contacts = cls.env["res.partner"].create(
            [
                {"name": f"Contact {i}", "parent_id": cls.company.id, "color": i}
                for i in range(3)
            ]
        )
        cls.user = new_test_user(cls.env, login="ai_counter", groups="base.group_user")

    def _tool(self, name):
        return self.env.ref(f"ai_tool_read.{name}_tool").with_user(self.user)

    def _read_group(self, **kwargs):
        return (
            self.env["ir.model"]
            .with_user(self.user)
            ._ai_read_group("res.partner", **kwargs)
        )

    def test_tool_definitions(self):
        for name in ("search_count", "read_group"):
            definition = self._tool(name)._get_tool_definition()
            self.assertEqual(definition["inputSchema"]["required"], ["model"])

    def test_search_count(self):
        res = self._tool("search_count")._execute_tool(
            model="res.partner", domain=[("parent_id", "=", self.company.id)]
        )
        self.assertEqual(res, {"count": 3})

    def test_search_read_total_count(self):
        res = self._tool("search_read")._execute_tool(
            model="res.partner",
            domain=[("parent_id", "=", self.company.id)],
            fields=["name"],
            limit=2,
        )
        self.assertEqual(len(res["records"]), 2)
        self.assertTrue(res["has_more"])
        self.assertEqual(res["total_count"], 3)

    def test_search_count_unreadable_model(self):
        with self.assertRaises(UserError):
            self._tool("search_count")._execute_tool(model="ir.cron")

    def test_read_group(self):
        res = self._tool("read_group")._execute_tool(
            model="res.partner",
            domain=[("id", "in", (self.company | self.contacts).ids)],
            groupby=["parent_id"],
            aggregates=["__count", "color:sum"],
            order="parent_id",
        )
        self.assertEqual(
            res["groups"],
            [
                {"parent_id": self.company.id, "__count": 3, "color:sum": 3},
                {"parent_id": False, "__count": 1, "color:sum": 0},
            ],
        )
        self.assertFalse(res["has_more"])

    def test_read_group_totals(self):
        # Without groupby, one group sums up all the records.
        res = self._read_group(domain=[("id", "in", self.contacts.ids)])
        self.assertEqual(res["groups"], [{"__count": 3}])

    def test_read_group_date_granularity(self):
        res = self._read_group(
            domain=[("id", "in", self.contacts.ids)], groupby=["create_date:year"]
        )
        self.assertEqual(len(res["groups"]), 1)
        self.assertIsInstance(res["groups"][0]["create_date:year"], str)

    def test_read_group_paging(self):
        domain = [("id", "in", self.contacts.ids)]
        res = self._read_group(domain=domain, groupby=["name"], order="name", limit=2)
        self.assertEqual(
            [g["name"] for g in res["groups"]], ["Contact 0", "Contact 1"]
        )
        self.assertTrue(res["has_more"])
        res = self._read_group(
            domain=domain, groupby=["name"], order="name", limit=2, offset=2
        )
        self.assertEqual([g["name"] for g in res["groups"]], ["Contact 2"])
        self.assertFalse(res["has_more"])
        # An out-of-range limit falls back to the cap.
        res = self._read_group(domain=domain, groupby=["name"], limit=-1)
        self.assertEqual(len(res["groups"]), 3)
        self.assertLessEqual(len(res["groups"]), MAX_GROUP_LIMIT)

    def test_read_group_forbidden_field(self):
        # A forbidden field, or one exposing its value, would show its values
        # in the group keys or the aggregates.
        for kwargs in (
            {"groupby": ["email"]},
            {"groupby": ["email_normalized"]},
            {"aggregates": ["email:max"]},
            {"aggregates": ["__count"], "groupby": ["name"], "order": "email:max"},
        ):
            with self.subTest(**kwargs), self.assertRaises(UserError):
                self._read_group(**kwargs)

    def test_read_group_refused_specs(self):
        for kwargs in (
            {"groupby": ["not_a_field"]},
            {"groupby": ["contact_address"]},  # not stored
            {"aggregates": ["id:array_agg"]},
            {"aggregates": ["parent_id:recordset"]},
            {"aggregates": ["color"]},
            {"groupby": ["create_date:fortnight"]},
        ):
            with self.subTest(**kwargs), self.assertRaises(UserError):
                self._read_group(**kwargs)
