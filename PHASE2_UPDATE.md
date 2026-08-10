# Phase 2 Update — Exact File Changes

## Preserved byte-for-byte

All SQL migrations `01` through `14` are unchanged. Existing ingestion, Lakebase, secrets, and API-client behavior remains in the project.

## Added

- `embedding_model.py` — hosted GTE inference and 1024-dimension validation
- `job_embeddings.py` — sliding-window chunks, content-hash-aware embedding writes, HNSW candidate retrieval, and distinct Top-K jobs
- `notebooks/ingest_job_embeddings.ipynb` — Day 2-style notebook flow
- `sql/15_verify_phase2_pipeline.sql` — data/index verification after running the notebook
- `tests/test_job_embeddings.py` — chunking, model response, and parameterized search tests

## Modified

- `config.py` — embedding endpoint, dimension, chunk, and batch settings
- `app.py` — embedding status, embed, and semantic-search endpoints
- `app.yaml` — non-secret embedding configuration
- `templates/index.html` — embedding control, natural-language query, Top K, filters, and similarity scores
- `README.md` and `sql/README.md` — Phase 2 runbook

## Databricks order

1. Push these files and pull the Databricks Git folder.
2. If not already run, execute SQL `11`, `12`, and `13`; inspect with `14`.
3. Grant your notebook user **CAN QUERY** on `databricks-gte-large-en`.
4. Run `notebooks/ingest_job_embeddings.ipynb`.
5. Run `sql/15_verify_phase2_pipeline.sql`.
6. Grant the deployed App service principal **CAN QUERY** on the same endpoint.
7. Redeploy the existing App.
8. Test Top K values 3, 5, and 10 and confirm distinct, relevant jobs appear.

If your workspace names the endpoint `system.ai.gte-large-en`, update `DATABRICKS_EMBEDDING_MODEL` in `app.yaml` before steps 3–7. Do not change the vector dimension.
