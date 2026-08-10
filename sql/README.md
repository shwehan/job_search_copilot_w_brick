# Lakebase schema — Phases 1–3

Run these against your Lakebase Postgres database, **in order**, before running anything else.
Any Postgres client works: the Databricks SQL editor pointed at the Lakebase instance, `psql`, or
a notebook cell using `lakebase.connection_parts()`.

| File | Creates |
| --- | --- |
| `01_create_users.sql` | `users` |
| `02_create_profiles.sql` | `profiles` |
| `03_create_skills.sql` | `skills` |
| `04_create_job_postings.sql` | `job_postings` |
| `05_create_skill_joins.sql` | `profile_skills`, `job_posting_skills` |
| `06_create_applications.sql` | `applications` |
| `07_create_saved_jobs.sql` | `saved_jobs` |
| `08_create_interview_notes.sql` | `interview_notes` |
| `09_create_contacts.sql` | `contacts` |
| `10_verify_schema.sql` | (inspection only) |
| `11_enable_pgvector.sql` | pgvector extension |
| `12_create_job_posting_embeddings.sql` | `job_posting_embeddings` (chunked, `VECTOR(1024)`, HNSW index) |
| `13_add_profile_resume_embedding.sql` | Adds `resume_embedding`/`resume_content_hash`/`resume_embedded_at` to `profiles` |
| `14_verify_phase2_schema.sql` | (inspection only) |
| `15_verify_phase2_pipeline.sql` | Verifies embedded rows, model coverage, changed postings, and cosine index |
| `16_verify_phase3_workflow.sql` | Inspects workflow counts, stage totals, relationships, and recent activity |

Order matters: `04` must run before `05` (skill joins reference `job_postings`), and `02`/`04` must
run before `06` (`applications` references both `profiles` and `job_postings`). `04` must also run
before `12` (`job_posting_embeddings` references `job_postings`), and `02` before `13` (it alters
`profiles`). Phase 3 needs no new tables: it activates the workflow tables created in SQL `01–09`.
SQL `16` is inspection-only and safe to rerun after dashboard testing.

## Why 10 tables, not 8

The brief names 8 tables. `skills` many-to-many relationships (what a profile already has, what a
posting requires) need two join tables — `profile_skills` and `job_posting_skills` — to be queryable
without re-parsing text on every request. They're part of `skills`' design, not separate features.

## `saved_jobs` vs `applications.stage = 'saved'`

These look redundant at first glance and aren't. `saved_jobs` is a lightweight bookmark — one click
while scanning search results, no commitment. `applications` is the formal pipeline with a fixed
stage machine (`saved → applied → interviewing → rejected/offer`); its own `'saved'` stage means
"I've deliberately decided to track this one," a heavier single-item action. A posting can live in
`saved_jobs` forever without ever entering `applications` at all.

## Phase 2 vector design

SQL `11–13` add pgvector, chunk-level `VECTOR(1024)` job embeddings, a cosine HNSW index, and a
single profile-resume vector. `content_hash` is copied to each chunk, allowing the notebook to skip
unchanged postings and atomically replace only the chunks for changed postings.

## CDF: confirmed unavailable on Free Edition

`applications` has `REPLICA IDENTITY FULL` set in `06_create_applications.sql` — that part worked
as intended. Attempting Lakebase CDF against it confirmed the limitation predicted in the capstone
plan: Free Edition's only catalog (`workspace`) uses Databricks-managed default storage, which
Lakebase CDF explicitly rejects as a destination. See the main `README.md`'s "Known limitations"
section for the exact error and what replaces it (a scheduled Job writing periodic snapshots
instead of streaming). The `REPLICA IDENTITY FULL` line stays in the DDL regardless — harmless, and
correct if this project ever runs on a tier where CDF is available.
