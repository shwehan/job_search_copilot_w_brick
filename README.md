# AI Job Hunting Copilot — Phase 1: Data Foundation

Harvests live job postings from three sources — Adzuna, USAJobs, and RemoteOK — normalizes them
to one schema, and stores them in Lakebase (Databricks-managed Postgres).

This is deliberately the *entire* scope of Phase 1: no embeddings, no semantic search, no agent
yet. See [`CAPSTONE_PLAN.md`](CAPSTONE_PLAN.md) for the full waterfall roadmap — vectorize/retrieve
(Phase 2), a human-facing dashboard (Phase 3), a scheduled sync job (Phase 4), an MCP server + a
Databricks Agent Bricks agent (Phase 5), and the differentiating features carried over from a prior
personal project (Phase 6).

---

## What's here

```
job-hunting-copilot/
├── app.py                Flask API + web UI
├── job_client.py         Adzuna / USAJobs / RemoteOK clients and normalizer
├── ingestion.py           Upsert logic (job_postings)
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
│   └── README.md
├── templates/
│   └── index.html          Web UI (sync + browse)
├── CAPSTONE_PLAN.md         Full project roadmap, Phases 1-8
└── .env.example
```

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

No vector columns yet — those are added in Phase 2, once the embedding model is chosen, rather than
guessing a dimension now.

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

Run the scripts in `sql/`, **in order** (`01` through `09`; `10` is inspection-only), against your
Lakebase database — via the Databricks SQL editor, `psql`, or any Postgres client. See
[`sql/README.md`](sql/README.md) for the full run order and rationale.

### 5. Deploy the Databricks App

**Compute → Apps → Create app**, point it at the Git folder. Databricks reads `app.yaml` for the
start command and environment, and `requirements.txt` for dependencies.

### 6. Sync some postings

From the web UI, or directly:

```bash
curl -X POST https://<app-url>/jobs/sync \
  -H 'Content-Type: application/json' \
  -d '{"queries": [{"keyword": "data engineer", "location": "Austin, TX"}], "limit_per_source": 25}'
```

### 7. CDF: confirmed unavailable on Free Edition — see below

`applications` has `REPLICA IDENTITY FULL` set (from `06_create_applications.sql`), so it was
eligible the moment we tried. Attempting **Lakebase CDF → Start** on it gets past table selection
cleanly, but fails at the destination-catalog step with:

> *"The selected catalog uses Databricks-managed Default Storage, which is not supported for
> Lakebase CDF. Please select a catalog backed by external storage."*

`workspace` is Free Edition's only available catalog, and it uses Databricks-managed default
storage — there's no alternative catalog to pick instead. Creating one backed by external storage
needs an S3/ADLS/GCS bucket, an IAM role, and a storage credential, which requires an actual cloud
account Free Edition doesn't provide. This is a structural limitation of the tier, not a
misconfiguration — confirmed directly via the Lakebase CDF UI rather than assumed from docs.

**What replaces it:** the scheduled Databricks Job (Phase 4) that re-syncs postings also writes a
periodic snapshot of `applications` — counts per pipeline stage, average days-in-stage — either to
a plain Lakebase summary table or a Delta table via a normal batch write. Same end-user-visible
result (a funnel view), on a polling interval instead of event-driven streaming.

---

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | Web UI |
| `GET` | `/healthz` | Liveness, Lakebase reachability, table presence, which sources are configured |
| `GET` | `/jobs/stats` | Row counts and coverage by source |
| `POST` | `/jobs/sync` | Harvest postings for a list of search queries |
| `GET` | `/jobs` | Browse synced postings, with `source` / `remote_only` filters |

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

---

## Known limitations

**Lakebase Change Data Feed is unavailable on Databricks Free Edition.** Confirmed directly, not
assumed — see step 7 above for the exact error and why there's no workaround within this tier.
Phase 4's scheduled Job produces the same pipeline-funnel visibility via periodic snapshots
instead of event-driven streaming.

**RemoteOK's public feed is noisy.** Test posts, dead listings, and non-job spam show up mixed
into real postings. `job_client.py` drops the obviously-empty cases at harvest time, but that's
basic hygiene, not scam detection — a real legitimacy check is a deliberately separate, LLM-backed
tool planned for a later phase, not conflated with data plumbing here.

**No user/profile management UI yet.** `users` and `profiles` exist in the schema and are
populated via direct SQL for now; a proper create/edit flow is Phase 3's job (the human-facing
dashboard), not Phase 1's.

## Running locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # fill in LAKEBASE_URL + whichever API credentials you have
export $(grep -v '^#' .env | xargs)
python app.py             # http://localhost:8000
```
