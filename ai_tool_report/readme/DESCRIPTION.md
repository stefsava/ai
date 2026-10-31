Adds two `ai_tool` tools that let an AI agent read printable reports
(invoices, quotations, delivery slips...) as their recipients see them:

- **list_reports**: lists the reports the agent may read, optionally for one
  model.
- **render_report**: renders a report for up to 10 records and returns the
  printed document as plain text, with a link to its PDF that the user can open
  in a browser where they are logged in to Odoo.

Reports are opt-in: a report is available only once an administrator ticks
**Available to AI** on it (`Settings > Technical > Reports`). A report shows
whatever its template prints, fields forbidden to AI by `ai_tool_read`
included, so allow only the reports whose content may be disclosed to the
agents.

The tools run with the calling user's own access rights: a report restricted
to groups is only available to their members, and only records the user may
read are rendered.
