# Copyright 2026 Stefano Savanelli
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models
from odoo.exceptions import UserError
from odoo.tools import html2plaintext

from odoo.addons.ai_tool.tools import aitool

MAX_RECORDS = 10
MAX_TEXT_LENGTH = 20000
# Report types rendered from an HTML template, which can be turned into text.
AI_REPORT_TYPES = ("qweb-pdf", "qweb-html")


class IrActionsReport(models.Model):
    _inherit = "ir.actions.report"

    ai_allowed = fields.Boolean(
        string="Available to AI",
        help="Let AI agents read this report through the ai_tool_report tools. "
        "A report shows what its template prints, including fields forbidden "
        "to AI: allow only the reports whose content may be disclosed to the "
        "agents.",
    )

    def _ai_allowed_reports(self, model=None):
        """Return the reports allowed to AI that the caller may print."""
        domain = [("ai_allowed", "=", True), ("report_type", "in", AI_REPORT_TYPES)]
        if model:
            domain.append(("model", "=", model))
        user_groups = self.env.user.all_group_ids
        return self.search(domain, order="model, name").filtered(
            lambda report: not report.group_ids or report.group_ids & user_groups
        )

    @aitool(
        input_schema={"model": {"type": "string"}},
        output_schema={
            "reports": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "report": {"type": "string"},
                        "name": {"type": "string"},
                        "model": {"type": "string"},
                    },
                },
            },
        },
    )
    def _ai_list_reports(self, model=None):
        """List the reports the caller may read through render_report, for
        ``model`` or for every model."""
        return {
            "reports": [
                {"report": report.report_name, "name": report.name, "model": report.model}
                for report in self._ai_allowed_reports(model)
            ]
        }

    @aitool(
        input_schema={
            "report": {"type": "string"},
            "ids": {
                "type": "array",
                "items": {"type": "integer"},
                "minItems": 1,
                "maxItems": MAX_RECORDS,
            },
        },
        required_inputs=["report", "ids"],
        output_schema={
            "text": {"type": "string"},
            "truncated": {"type": "boolean"},
            "pdf_url": {"type": "string"},
        },
    )
    def _ai_render_report(self, report, ids):
        """Render ``report`` for the records ``ids`` and return its text, as
        printed, with the URL of its PDF.

        Only reports allowed to AI and available to the caller's groups can be
        rendered, for records the caller may read: the rendering runs with the
        caller's rights. The text is cut after ``MAX_TEXT_LENGTH`` characters,
        ``truncated`` telling so. The PDF URL opens in a browser where the user
        is logged in to Odoo.
        """
        report_record = self._ai_allowed_reports().filtered(
            lambda rec: rec.report_name == report
        )[:1]
        if not report_record:
            raise UserError(
                self.env._(
                    "Report '%(report)s' does not exist or is not available to AI. "
                    "list_reports lists the available ones.",
                    report=report,
                )
            )
        if not ids or len(ids) > MAX_RECORDS:
            raise UserError(
                self.env._(
                    "Give between 1 and %(max)s record IDs.", max=MAX_RECORDS
                )
            )
        target = self.env["ir.model"]._ai_target(report_record.model)
        records = target.browse(ids).exists()
        if len(records) != len(set(ids)):
            raise UserError(self.env._("Some of the records do not exist."))
        records.check_access("read")
        html, _report_type = self._render_qweb_html(report_record, records.ids)
        text = html2plaintext(html.decode() if isinstance(html, bytes) else html)
        return {
            "text": text[:MAX_TEXT_LENGTH],
            "truncated": len(text) > MAX_TEXT_LENGTH,
            "pdf_url": "{}/report/pdf/{}/{}".format(
                self.get_base_url(),
                report_record.report_name,
                ",".join(str(record_id) for record_id in records.ids),
            ),
        }
