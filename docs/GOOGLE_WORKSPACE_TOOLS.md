# Google Workspace tools in the shared Harness catalog

Status: read-only integration implemented and the dedicated Pi account authorized on 2026-11-18. The current catalog exposes `search_mail`, `read_mail`, `search_drive`, and `read_drive_text` to Chat mode for any selected local or cloud model. Coding mode keeps its existing no-public-network boundary. The same MCP schemas and tool names are used for every Chat model; model-specific authentication is not involved.

The Harness owns the tool schemas and MCP adapter in `tools/google_workspace_mcp.py`. Gateway owns the typed `/dashboard/api/google/*` endpoints, account verification, token refresh, and private token file. The adapter connects only to Gateway loopback and receives bounded results. The model sees mail and Drive content marked `content_trust: untrusted`; it never receives OAuth credentials.

Search is bounded to 20 hits and individual text reads to 16,000 characters. Drive text reads support Google Docs and plain text, Markdown, CSV, and JSON files. Unsupported file types return a typed error. The current OAuth scopes are Gmail read-only and Drive read-only. Sending mail, creating drafts, editing Drive files, attachments, calendars, and inbound work commands are **not enabled**. Those require server-side recipient/resource policy, explicit operator approval, and durable idempotency receipts before any model gets write authority.

Deployment and OAuth instructions are in Gateway's `docs/CLOUD_CONNECTORS.md`. A disabled connector is omitted from both local model tool advertisement and cloud MCP configuration; adding a catalog entry alone does not grant access.
