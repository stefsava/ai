# Copyright 2026 Quartile (https://www.quartile.co)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).


def uninstall_hook(env):
    """Expire the keys from OAuth: without this module, nothing checks their
    users any more."""
    env["mcp.server.key"].sudo().search([("oauth_code_hash", "!=", False)]).expire_key()
