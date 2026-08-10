# AI Job Hunting Copilot — Phases 1–3

Harvests live job postings from three sources — Adzuna, USAJobs, and RemoteOK — normalizes them
to one schema, and stores them in Lakebase (Databricks-managed Postgres).

Phase 1 provides ingestion and Lakebase storage. Phase 2 adds chunked, hosted GTE embeddings and
configurable top-K pgvector retrieval. Phase 3 adds profiles, resume upload, bookmarks, and a
persistent application pipeline. See [`CAPSTONE_PLAN.md`](CAPSTONE_PLAN.md) for the remaining
waterfall roadmap — a scheduled sync job (Phase 4), an MCP server + a
Databricks Agent Bricks agent (Phase 5), and the differentiating features carried over from a prior
personal project (Phase 6).

---

## What's here

```
job-hunting-copilot/
├── app.py                Flask API + web UI
├── job_client.py         Adzuna / USAJobs / RemoteOK clients and normalizer
├── ingestion.py           Upsert logic (job_postings)
├── embedding_model.py     Hosted Databricks GTE client (1024 dimensions)
├── job_embeddings.py      Chunking, incremental embedding, pgvector top-K search
├── workflow_service.py    Reusable profile/application operations for UI + future MCP
├── lakebase.py            Lakebase connection helper (pg8000)
├── secrets_helper.py      Generic Databricks-secret resolution (env var, else secret)
├── config.py               Table names, harvest defaults
├── setup_secrets.py        Stores Lakebase URL + API credentials as Databricks secrets
├── app.yaml                 Databricks App configuration
├── requirements.txt
├── sql/
│   ├── 01_create_users.sql
│   ├── 02_create_profiles.sql
│   ├── 03_create_skills.sql
│   ├── 04_create_job_postings.sql
│   ├── 05_create_skill_joins.sql
│   ├── 06_create_applications.sql
│   ├── 07_create_saved_jobs.sql
│   ├── 08_create_interview_notes.sql
│   ├── 09_create_contacts.sql
│   ├── 10_verify_schema.sql
│   ├── 11_enable_pgvector.sql
│   ├── 12_create_job_posting_embeddings.sql
│   ├── 13_add_profile_resume_embedding.sql
│   ├── 14_verify_phase2_schema.sql
│   ├── 15_verify_phase2_pipeline.sql
│   ├── 16_verify_phase3_workflow.sql
│   └── README.md
├── notebooks/
│   └── ingest_job_embeddings.ipynb
├── templates/
│   └── index.html          Web UI (sync + browse)
├── CAPSTONE_PLAN.md         Full project roadmap, Phases 1-8
└── .env.example
```

See [`PHASE3_UPDATE.md`](PHASE3_UPDATE.md) for the dashboard smoke test.

---

## Why these three sources

**Adzuna** — broad private-sector coverage across many countries, free `app_id`/`app_key` pair, no
approval wait. **USAJobs** — official U.S. federal postings, structured and reliable, but needs a
registered email that doubles as an API header. **RemoteOK** — no key at all, but its public feed is
genuinely noisy (test posts, dead listings, non-job spam mixed with real postings); `job_client.py`
applies a minimal hygiene filter (drop empty/placeholder entries) at harvest time — full scam/quality
detection is a deliberately separate, LLM-backed tool added in a later phase, not conflated with
basic data hygiene here.

## Schema

Ten tables total: the 8 named in the brief, plus `profile_skills` and `job_posting_skills` — the two
many-to-many joins that make the `skills` table's relationships queryable without re-parsing text.
Full column-by-column rationale is in [`sql/README.md`](sql/README.md), including why `saved_jobs`
and `applications.stage = 'saved'` are deliberately both present and not redundant.

Phase 2 stores posting chunks in `job_posting_embeddings.embedding VECTOR(1024)` and adds a single
`profiles.resume_embedding VECTOR(1024)`. The HNSW index and query both use cosine semantics.

---

## Setup

### 1. Get API credentials

- **Adzuna**: register at [developer.adzuna.com](https://developer.adzuna.com) → note your
  `app_id` and `app_key`.
- **USAJobs**: register at [developer.usajobs.gov](https://developer.usajobs.gov) → note your API
  key and the email you registered with (both are required together).
- **RemoteOK**: nothing to do — no key needed.

You can run with just one or two of these configured; a source with no credentials is simply
skipped, not treated as an error.

### 2. Add the repository as a Databricks Git folder

**Workspace → Create → Git folder**, paste the repository URL.

### 3. Store secrets

```bash
python setup_secrets.py
```

Prompts for the Lakebase URL, then Adzuna and USAJobs credentials (leave any blank to skip that
source). Everything is stored base64-encoded under the `database` secret scope, matching the
convention used elsewhere in this course. Grant your deployed App's service principal read access
too:

```bash
databricks secrets put-acl database <app-service-principal> READ
```

### 4. Create the Lakebase schema

Run the scripts in `sql/`, **in order** (`01` through `13`; `10`, `14`, `15`, and `16` are inspection-only), against your
Lakebase database — via the Databricks SQL editor, `psql`, or any Postgres client. See
[`sql/README.md`](sql/README.md) for the full run order and rationale.

### 5. Deploy the Databricks App

**Compute → Apps → Create app**, point it at the Git folder. Databricks reads `app.yaml` for the
start command and environment, and `requirements.txt` for dependencies.

Before deploying Phase 2, run `notebooks/ingest_job_embeddings.ipynb` and confirm the 1024-dimension
probe succeeds. The notebook user and deployed App service principal need **CAN QUERY** on the GTE
embedding endpoint. This repository defaults to `databricks-gte-large-en`, matching the Day 2
bootcamp flow. If your workspace exposes `system.ai.gte-large-en`, change only
`DATABRICKS_EMBEDDING_MODEL` in `app.yaml`; both produce 1024-dimensional vectors.

### 6. Sync some postings

From the web UI, or directly:

```bash
curl -X POST https://<app-url>/jobs/sync \
  -H 'Content-Type: application/json' \
  -d '{"queries": [{"keyword": "data engineer", "location": "Austin, TX"}], "limit_per_source": 25}'
```

### 7. Try the CDF spike (5 minutes, worth doing now)

In the Lakebase UI, attempt **Lakebase CDF → Start** on `applications` (already has
`REPLICA IDENTITY FULL` set from `06_create_applications.sql`). See §6 of
[`CAPSTONE_PLAN.md`](CAPSTONE_PLAN.md) for why this is worth checking now rather than in Phase 7,
and what to do either way.

---

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | Web UI |
| `GET` | `/healthz` | Liveness, Lakebase reachability, table presence, which sources are configured |
| `GET` | `/jobs/stats` | Row counts and coverage by source |
| `POST` | `/jobs/sync` | Harvest postings for a list of search queries |
| `GET` | `/jobs` | Browse synced postings, with `source` / `remote_only` filters |
| `GET` | `/jobs/embeddings/status` | Posting/chunk embedding coverage |
| `POST` | `/jobs/embed` | Embed new or content-changed postings |
| `POST` | `/jobs/search` | Natural-language top-K semantic retrieval |
| `POST` | `/api/users/session` | Select or create a development workspace identity |
| `GET/POST` | `/api/profiles` | List or create resume/search profiles |
| `POST` | `/api/profiles/<id>/resume` | Upload UTF-8 `.txt`/`.md` resume text |
| `POST` | `/api/saved-jobs` | Bookmark a posting |
| `POST` | `/api/applications` | Add a posting to the formal pipeline |
| `PATCH` | `/api/applications/<id>/stage` | Move an application between stages |
| `GET` | `/api/pipeline` | Read the user's Lakebase-backed board |
| `POST` | `/api/applications/<id>/notes` | Add interview/follow-up notes |
| `POST` | `/api/contacts` | Add a recruiter or hiring contact |

### Sync

```bash
curl -X POST https://<app-url>/jobs/sync \
  -H 'Content-Type: application/json' \
  -d '{
        "queries": [
          {"keyword": "backend engineer", "location": "remote"},
          {"keyword": "data engineer"}
        ],
        "limit_per_source": 25
      }'
```

```json
{
  "synced": 61,
  "by_source": {"adzuna": 24, "usajobs": 11, "remoteok": 26},
  "queries": [...],
  "errors": []
}
```

`queries` can also be a flat list of strings (`["data engineer", "ML engineer"]`) if you don't need
per-query locations. Omit `queries` entirely to use the defaults from `app.yaml`.

### Embed and search

The recommended batch flow is the notebook. For a small App smoke test:

```bash
curl -X POST https://<app-url>/jobs/embed \
  -H 'Content-Type: application/json' \
  -d '{"limit": 100, "batch_size": 8}'
```

Then search with filters applied before vector ranking:

```bash
curl -X POST https://<app-url>/jobs/search \
  -H 'Content-Type: application/json' \
  -d '{
        "query": "senior data engineer with Databricks, Python, SQL, and AWS",
        "top_k": 5,
        "sources": ["adzuna", "usajobs", "remoteok"],
        "remote_only": false
      }'
```

Each posting can have several chunks, but `/jobs/search` returns distinct jobs using only each
posting's best-matching chunk. Re-running embedding skips unchanged `content_hash` + model pairs.

## Databricks Phase 2 run order

1. Pull the updated Git folder.
2. Keep existing SQL `01–10` and run `11`, `12`, `13`, then inspection script `14`.
3. Open and run `notebooks/ingest_job_embeddings.ipynb`.
4. Run `sql/15_verify_phase2_pipeline.sql`.
5. Grant the App service principal **CAN QUERY** on the configured GTE endpoint.
6. Redeploy the existing App.
7. Test **Embed pending** and semantic **Top K** in the UI.

## Databricks Phase 3 run order

1. Pull this update into the existing Databricks Git folder.
2. No new DDL is required; the workflow uses the Phase 1 tables already created.
3. Redeploy the existing App from the same workspace folder.
4. Choose a workspace identity, create a profile, and upload a UTF-8 `.txt` or `.md` resume.
5. Search for a job, bookmark it, track it, change its stage, and add a note.
6. Refresh the page to confirm persistence, then run `sql/16_verify_phase3_workflow.sql`.

---

## Running locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # fill in LAKEBASE_URL + whichever API credentials you have
export $(grep -v '^#' .env | xargs)
python app.py             # http://localhost:8000
```
