# Job Hunting Copilot MCP App

Deploy this folder as a separate Databricks App whose name starts with `mcp-`,
for example `mcp-job-hunting-copilot`. The Streamable HTTP endpoint is
`https://<app-url>/mcp`.

The App service principal needs:

- READ on secret scope `database`, key `lakebase-url`.
- CAN QUERY on the configured `databricks-gte-large-en` endpoint.
- CAN QUERY on the configured `databricks-claude-sonnet-4-5` chat endpoint
  (or the endpoint selected with `DATABRICKS_CHAT_MODEL`).
- Network access to the same Lakebase instance used by the dashboard.

The server exposes `health`, `get_profile`, `search_jobs`,
`get_job_match_context`, `save_job`, `update_pipeline_stage`,
`log_interview_note`, `get_pipeline`, `check_stale_applications`,
`record_feedback`, `check_listing_legitimacy`, `get_skill_gap_report`, and
`draft_application_snippet`.

This capstone uses an explicit `user_email` tool argument because Phase 3 has a
development identity selector rather than production authentication. The MCP
server validates that the email already exists; it never invents a default
user. A production version should map the governed caller identity to `users`
and enforce authorization server-side.
