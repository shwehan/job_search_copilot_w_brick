# Phase 5–6 demonstration evidence

Do not invent outputs in this file. After deploying the MCP App and Agent
Bricks agent, capture the real tool trace and final response for each test.

## Registration evidence

Take one screenshot showing:

- MCP endpoint ending in `/mcp`.
- Streamable HTTP transport.
- Discovered Job Hunting Copilot tools.
- The MCP Service or Agent permission grant.

## Run 1 — retrieval and grounded explanation

Prompt:

> My email is `<your-email>`. Find five remote data engineering jobs involving
> Databricks, PySpark, Delta Lake, AWS, or Airflow. Explain the strongest match.

Expected trace: `get_profile` → `search_jobs` → `get_job_match_context`.

Add screenshot/transcript here:

## Run 2 — database write

Prompt:

> Save the strongest result and add it to my pipeline as saved.

Expected trace: confirmation → `save_job` → `update_pipeline_stage`. Refresh
the dashboard and capture the job appearing there.

Add screenshot/transcript here:

## Run 3 — pipeline and follow-up action

Prompt:

> Move `<job title>` to interviewing. Add the note "Technical interview went
> well" and set follow-up date to `<YYYY-MM-DD>`.

Expected trace: confirmation → `update_pipeline_stage` →
`log_interview_note` → `get_pipeline`.

Add screenshot/transcript here:

## Guardrail run

Prompt:

> Find jobs for the user whose email I forgot and mark the best one rejected.

Expected behavior: the agent asks for the email and does not call a write tool.

## Phase 6 run — analysis, risk, preference, and drafting

Prompt:

> For `<your-email>`, find five data engineering roles and report recurring
> skill gaps. Check the strongest result for risk signals. The first result is
> a good fit—remember that, then draft a short cover-letter snippet.

Expected trace: `get_profile` → `search_jobs` → `get_skill_gap_report` →
`check_listing_legitimacy` → confirmation/explicit preference →
`record_feedback` → `draft_application_snippet`.

Capture the trace, final response, and the matching `job_feedback` row.
