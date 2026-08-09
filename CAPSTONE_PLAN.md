# AI Job Hunting Copilot — Capstone Plan

Status: **planning complete, no code written yet**. This document is the source of truth if the
chat that produced it gets cut off — hand it to a fresh conversation and say "here's my capstone
plan, let's start building Phase N."

---

## 0. What this project is

Users describe their skills, target roles, and preferences. An agent finds matching job openings
across three live APIs, explains why each is or isn't a good match, tracks the user's application
pipeline, drafts tailored application material, and proactively surfaces stale applications.

Built on Databricks: Lakebase (Postgres + pgvector) for storage and retrieval, a Databricks-hosted
embedding + chat model for context engineering, and a Databricks Agent Bricks agent talking to the
app over MCP — not just an LLM call wrapped in a Flask route.

## 1. Why this plan is structured the way it is

The single biggest lever for standing out is demonstrating **all three bootcamp days**, not just
Day 2's harvest→vectorize→retrieve pattern. Most submissions will likely stop there. This plan
makes Day 1 (Lakebase CRUD + secrets + Change Data Feed) and Day 3 (MCP server + Agent Bricks)
load-bearing, not decorative — plus reuses genuinely differentiated ideas from a prior personal
project (legitimacy/scam checking, skill-gap aggregation, a feedback loop that makes the agent
visibly improve within a session).

Built **waterfall**: each phase produces something demoable on its own, and later phases only add
to a working foundation. If time runs out at any phase, there's still a coherent submission.

## 2. Architecture (target end state)

```
                    ┌─────────────────────────────────────────┐
                    │         Databricks Agent Bricks           │
                    │   (the "copilot" — chat interface)         │
                    └───────────────┬─────────────────────────┘
                                     │ MCP tool calls (streamable HTTP)
                    ┌────────────────▼────────────────────────┐
                    │   job-agent-mcp (Databricks App #1)       │
                    │   FastMCP server: search_jobs,             │
                    │   save_job, update_pipeline_stage,         │
                    │   draft_application_snippet,               │
                    │   log_interview_note, check_stale_apps,    │
                    │   get_skill_gap_report,                    │
                    │   check_listing_legitimacy                 │
                    └───────┬───────────────────────┬───────────┘
                            │                        │
                 ┌──────────▼─────────┐   ┌──────────▼───────────┐
                 │   Lakebase (pg8000) │   │ Databricks Model      │
                 │   8 required tables │   │ Serving:               │
                 │   + pgvector cols   │   │ - gte-large-en (embed) │
                 └──────────┬──────────┘   │ - a chat FM (scoring,  │
                            │              │   tailoring, legit-    │
                 [CDF spike — see §6] ─┐   │   imacy checks)        │
                            │         │   └────────────────────────┘
                 ┌──────────▼──────────┐    │
                 │  Unity Catalog Delta │◄───┘ (only if spike passes)
                 │  history tables      │
                 └──────────┬──────────┘
                            │
                 ┌──────────▼──────────┐
                 │  Genie / AI-BI       │
                 │  dashboard           │
                 └──────────────────────┘

                    ┌─────────────────────────────────────────┐
                    │  job-agent-dashboard (Databricks App #2)  │
                    │  Human-facing Flask UI — mirrors the       │
                    │  MCP tools 1:1 as REST + pipeline board    │
                    └─────────────────────────────────────────┘

         Scheduled Databricks Job (serverless — same pattern as HW2)
         re-syncs Adzuna / USAJobs / RemoteOK, embeds new postings,
         refreshes stale-application flags
```

Two Databricks Apps sharing one Lakebase instance — same split as Day 3's Alpaca lab (an MCP
server the agent calls, and a dashboard a human uses). An action the agent takes shows up in the
dashboard instantly, and vice versa.

## 3. Lakebase schema (the 8 required tables)

| Table | Role |
|---|---|
| `users` | One row per person using the copilot |
| `profiles` | Target roles, skills, salary floor, seniority, deal-breakers, embedded resume/profile vector — what postings get matched against |
| `skills` | Normalized skill taxonomy, many-to-many with `profiles` and `job_postings` — powers gap analysis and match explanations without re-parsing text |
| `job_postings` | Normalized documents from all 3 sources: `narrative_text`, embedding, `content_hash` (re-embed only what changed, same trick as HW2), `source` |
| `applications` | Pipeline stage (`saved`/`applied`/`interviewing`/`rejected`/`offer`), `stage_updated_at` — powers stale-application detection and the CDF funnel |
| `saved_jobs` | Bookmarked postings not yet committed to a pipeline stage — matches the stated capability literally |
| `interview_notes` | Free text + follow-up date, FK to `applications` |
| `contacts` | Recruiter/hiring-manager info per application |

## 4. Environment workflow (confirmed, matches HW2's pattern)

1. Push code to GitHub.
2. In Databricks: **Workspace → Create → Git folder**, paste the repo URL.
3. Open the **SQL editor**, run everything in `sql/` in order to create the schema.
4. Run `setup_secrets.py` once (from a notebook cell or terminal) to store:
   - Lakebase connection URL (`database` / `lakebase-url`)
   - Adzuna `app_id` + `app_key`
   - USAJobs API key + registered email
   - (RemoteOK needs no key)
5. Deploy `job-agent-dashboard` and `job-agent-mcp` as two separate Databricks Apps, each pointed
   at its own subfolder of the same Git folder — mirrors Day 3's `mcp_server/` + `dashboard/` split.
6. Register the MCP server as an external MCP in AI Gateway, build the Agent Bricks agent on top.

Known constraint from HW2: **no psycopg2, no local sentence-transformers/torch** — Free Edition is
serverless-only and both reliably SIGABRT-crash the kernel. Use `pg8000` and a hosted embedding
endpoint (`databricks-gte-large-en`, 1024-dim) from day one, not as a later fix.

## 5. Waterfall build order

Each phase is independently demoable. Stop after any phase and there's still a coherent project.

### Phase 1 — Data foundation (fastest path to something real)
- Lakebase schema for all 8 tables (`sql/01`–`0N`)
- `job_client.py`: harvest from Adzuna, USAJobs, RemoteOK → normalize to one document schema →
  upsert into `job_postings` (dedupe by source + external ID)
- `POST /jobs/sync` — proves the harvest layer, same shape as HW2's `/weather/sync`
- **Checkpoint: CDF feasibility spike (see §6)** — do this now, while the stakes of finding out
  "no" are low, not after building features that assume "yes"

### Phase 2 — Vectorize + retrieve
- Embed `job_postings.narrative_text` and `profiles.resume_text` via `databricks-gte-large-en`
- `POST /jobs/search` — semantic search with pgvector `<=>`, filterable by salary/seniority/deal-breakers
  applied as a cheap SQL prefilter *before* any embedding/LLM call (cost control, straight from the
  prior project's design)
- Prove retrieval quality manually before building UI on top of it

### Phase 3 — Human-facing dashboard (Databricks App #1)
- Flask app: pipeline board (saved/applied/interviewing/rejected/offer), search UI, resume upload
- Every dashboard action is a thin wrapper over a function that will later become an MCP tool —
  write that function once, call it from both the dashboard route and the future MCP tool

### Phase 4 — Scheduled Job
- Serverless Databricks Job (no classic cluster — same constraint as HW2), re-syncs postings on a
  schedule, flags `applications` where `stage='applied'` and `stage_updated_at` is stale

### Phase 5 — Agent layer (Databricks App #2 + Agent Bricks)
- FastMCP server wrapping the Phase 1–4 functions as tools
- Register as external MCP, build the Agent Bricks agent, write a system prompt with real
  guardrails (e.g. "only reference postings returned by `search_jobs`; never fabricate a listing")
- This is the phase that makes Day 3 load-bearing rather than referenced

### Phase 6 — Differentiators (from the prior project, reused deliberately)
- `check_listing_legitimacy` — scam/red-flag detection + URL liveness check, run before a posting
  is surfaced as a strong match
- `get_skill_gap_report` — aggregate missing skills across scored postings into a ranked report
- `record_feedback` (good/bad/skip) — adjusts future ranking; the strongest "beyond standard"
  feature, since it makes the agent visibly learn within a session rather than being stateless
- `draft_application_snippet` — tailored cover-letter/resume-bullet generation per posting

### Phase 7 — Stretch: CDF → Unity Catalog → Genie/AI-BI (gated by §6's spike result)
- If the spike passed: enable CDF on `applications`, build a Genie space or AI/BI dashboard
  answering things like "average days from saved → applied," a real pipeline funnel
- If not: document the limitation explicitly in the README (see §6) — a clearly-reasoned
  "here's why not, here's what I'd do on a paid tier" is worth real credit too

### Phase 8 — Polish
- README + a second doc mirroring HW2's `README_WEATHER.md` structure (data source rationale,
  schema decisions, chunking/model choices, end-to-end run instructions, known limitations)
- Self-check against a rubric shape like HW2's (Harvest / Vectorize / Retrieve / Documentation,
  here extended with an Agent/Tool-use category) before submitting
- Record a short demo script: sync → search → explain match → save → agent chat → tailor snippet →
  stale-application nudge — so the flow is obvious to a grader with no live walkthrough

## 6. The CDF question — what to actually do

Databricks' own docs state CDF's destination Unity Catalog **cannot use default storage** — the
catalog needs its own cloud storage (S3/ADLS/GCS) attached via a storage credential + external
location, which requires an actual cloud account with IAM permissions. Free Edition workspaces are
fully Databricks-hosted with no bring-your-own-cloud-account path, which strongly suggests CDF's
destination-catalog requirement can't be satisfied there at all — independent of any workaround
inside Lakebase itself.

**Do this as a 15-minute spike at the end of Phase 1, not a Phase 7 surprise:**
1. In the Lakebase UI, try **Lakebase CDF → Start** on any table with `REPLICA IDENTITY FULL` set.
2. When it asks for a destination catalog, check whether Free Edition's default catalog is the
   only option, or whether "create a new catalog" is even reachable without cloud credentials.
3. If it's a dead end, that's the answer — stop there, don't spend more time on it.

**If it's blocked (likely outcome):** don't try to route around it with S3 directly — Free Edition
almost certainly doesn't give you a cloud account to attach either, so that's the same wall from a
different angle. Two honest alternatives instead:
- **Polling instead of streaming**: a scheduled Job (already being built in Phase 4 anyway) queries
  `applications` on an interval and writes a snapshot to a plain Lakebase summary table or a Delta
  table via a normal batch write — same end-user-visible result (a funnel view), just not
  event-driven CDF. This is a legitimate, explainable substitution, the same way pg8000-for-psycopg2
  was in HW2.
- **Document it as a known limitation** in the README, exactly like the "what I'd improve given
  more time" section HW2's rubric explicitly rewarded. A clear, correct explanation of *why*
  something doesn't work on Free Edition demonstrates the same understanding as building it.

Either path keeps Day 1's lesson visibly present in the project without gambling the whole
timeline on a feature that might be a dead end on this tier.

## 7. What's explicitly out of scope

Scraping Greenhouse/Lever/Ashby/LinkedIn — the prior project's own operations notes already flag
these as unreliable (empty slugs, LinkedIn blocking scrapers) and they sit in murkier ToS territory
than the three approved APIs. Not worth the risk for marginal coverage gain.

## 8. Immediate next step

Once this plan is confirmed, start Phase 1: Lakebase schema + the three-API harvest client. Ask
for the code as a zip, same delivery pattern as the HW2 weather project, so it can be pushed to
GitHub and connected in Databricks the same way.
