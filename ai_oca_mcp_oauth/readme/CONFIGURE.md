- Open the MCP server in `Settings > Technical > AI > MCP Server` and check **OAuth**.
- Give the users who may connect AI clients the access right **AI Clients:
  Connect AI Clients with OAuth** (`Settings > Users & Companies > Users`,
  section **Productivity**).
- Make sure the `web.base.url` system parameter is the URL clients use to reach
  Odoo (set `web.base.url.freeze` to `True` behind a reverse proxy). The
  server's **URL** must match the URL entered in the client exactly.

Optional system parameters:

- `ai_oca_mcp_oauth.redirect_uris`: the redirect URIs clients may use,
  separated by spaces or new lines. For `localhost` and `127.0.0.1` the port is
  ignored. A URI ending with `/*` allows any single path segment in place of
  the `*`. By default, Claude, Claude Code and ChatGPT are allowed:
  `https://claude.ai/api/mcp/auth_callback http://localhost/callback http://127.0.0.1/callback https://chatgpt.com/connector_platform_oauth_redirect https://chatgpt.com/connector/oauth/*`
- `ai_oca_mcp_oauth.token_lifetime_days`: how many days an issued key is valid
  (default `30`). When it expires, the client asks the user to connect again.
