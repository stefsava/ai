# Copyright 2026 Stefano Savanelli
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "AI Tool - Report",
    "summary": "Let an AI agent read the reports an administrator allows",
    "version": "19.0.1.0.0",
    "website": "https://github.com/OCA/ai",
    "license": "AGPL-3",
    "author": "Stefano Savanelli,Odoo Community Association (OCA)",
    "depends": [
        "ai_tool_read",
    ],
    "data": [
        "views/ir_actions_report_views.xml",
        "data/ai_tools.xml",
    ],
}
