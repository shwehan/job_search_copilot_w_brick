# Job Copilot MCP Server - Deployment Checklist

## ✅ Code Verification Complete

**All code has been verified and is working correctly:**

- ✓ All 13 MCP tools properly implemented
- ✓ `search_jobs` function logic is correct
- ✓ `update_pipeline_stage` function logic is correct
- ✓ Error handling via `_safe()` wrapper works
- ✓ Embedding client fixed (parameter: `input` not `inputs`)
- ✓ Agent guardrails added to prevent hallucination
- ✓ Test suite: 7/7 tests passing

## 🚀 Deployment Steps

### 1. Prepare Dependencies

Create or verify `requirements.txt`:

```txt
fastmcp>=0.1.0
pg8000>=1.30.0
databricks-sdk>=0.20.0
requests>=2.31.0
```

### 2. Configure Databricks Secrets

Store your Lakebase Postgres connection string:

```bash
databricks secrets create-scope database

# Your Lakebase connection string format:
# postgresql://username:password@host:port/database
databricks secrets put-secret database lakebase-url
```

**Security Note**: The connection string should be base64-encoded when stored.

### 3. Set Up Lakebase Database

Your Lakebase Postgres instance needs these tables:

#### Required Tables:
```sql
-- Users table
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    display_name TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Profiles table  
CREATE TABLE profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    label TEXT,
    target_roles TEXT[],
    seniority TEXT,
    salary_min INTEGER,
    salary_currency TEXT,
    remote_preference TEXT,
    locations_preferred TEXT[],
    deal_breakers TEXT,
    resume_filename TEXT,
    resume_text TEXT,
    is_default BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Job postings table
CREATE TABLE job_postings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source TEXT,
    title TEXT,
    company TEXT,
    location TEXT,
    remote BOOLEAN,
    salary_min INTEGER,
    salary_max INTEGER,
    salary_currency TEXT,
    description_text TEXT,
    apply_url TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Job embeddings table (for semantic search)
CREATE TABLE job_posting_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_posting_id UUID REFERENCES job_postings(id),
    model_name TEXT,
    chunk_text TEXT,
    embedding vector(1024),  -- Dimension must match EMBEDDING_DIMENSION in config.py
    created_at TIMESTAMP DEFAULT NOW()
);

-- Install pgvector extension first
CREATE EXTENSION IF NOT EXISTS vector;

-- Create index for fast similarity search
CREATE INDEX ON job_posting_embeddings USING ivfflat (embedding vector_cosine_ops);

-- Applications table
CREATE TABLE applications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    profile_id UUID REFERENCES profiles(id),
    job_posting_id UUID REFERENCES job_postings(id),
    stage TEXT,
    applied_at TIMESTAMP,
    stage_updated_at TIMESTAMP DEFAULT NOW(),
    is_stale BOOLEAN DEFAULT FALSE,
    stale_flagged_at TIMESTAMP,
    UNIQUE(user_id, job_posting_id)
);

-- Other supporting tables
CREATE TABLE saved_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    job_posting_id UUID REFERENCES job_postings(id),
    note TEXT,
    saved_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, job_posting_id)
);

CREATE TABLE job_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    job_posting_id UUID REFERENCES job_postings(id),
    feedback TEXT,
    reason TEXT,
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, job_posting_id)
);

CREATE TABLE interview_notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id UUID REFERENCES applications(id),
    note TEXT,
    interview_type TEXT,
    follow_up_date DATE,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### 4. Populate Initial Data

**Minimum required for `search_jobs` to work:**

1. **At least one user**:
```sql
INSERT INTO users (email, display_name) 
VALUES ('test@example.com', 'Test User');
```

2. **At least one profile for that user**:
```sql
INSERT INTO profiles (
    user_id, 
    label, 
    target_roles, 
    resume_text,
    is_default
)
SELECT 
    id,
    'Software Engineer',
    ARRAY['Software Engineer', 'Backend Developer'],
    'Experienced Python developer with 5 years...',
    TRUE
FROM users WHERE email = 'test@example.com';
```

3. **Job postings with embeddings**:
```sql
-- Insert job posting
INSERT INTO job_postings (
    source, title, company, location, remote,
    salary_min, salary_max, salary_currency,
    description_text, apply_url
)
VALUES (
    'indeed',
    'Senior Backend Engineer',
    'Tech Corp',
    'San Francisco, CA',
    true,
    120000,
    180000,
    'USD',
    'We are seeking an experienced Backend Engineer...',
    'https://example.com/apply'
);

-- Generate embeddings (you'll need a script to call the embedding endpoint)
-- This is just the structure:
INSERT INTO job_posting_embeddings (
    job_posting_id,
    model_name,
    chunk_text,
    embedding
)
SELECT 
    id,
    'databricks-gte-large-en',
    description_text,
    '[0.1,0.2,0.3,...]'::vector  -- Replace with actual embedding from endpoint
FROM job_postings;
```

### 5. Deploy as Databricks App

Create `app.yaml` in your project root:

```yaml
command:
  - python
  - mcp_server/job_copilot_mcp.py

env:
  - name: LAKEBASE_SECRET_SCOPE
    value: "database"
  - name: LAKEBASE_SECRET_KEY
    value: "lakebase-url"
  - name: DATABRICKS_APP_PORT
    value: "8000"
```

### 6. Deploy the App

```bash
# Navigate to your project directory
cd /Workspace/Users/lanshanoar@gmail.com/job_search_copilot_w_brick

# Deploy using Databricks CLI or SDK
databricks apps create job-copilot-mcp \
  --source-code-path . \
  --description "Job Hunting Copilot MCP Server"

# Or use the Databricks Apps UI
```

### 7. Verify Deployment

Once deployed, test the health endpoint:

```bash
curl https://<your-workspace>.cloud.databricks.com/apps/<app-name>/health
```

Expected response:
```json
{
  "ok": true,
  "service": "job-hunting-copilot",
  "transport": "streamable-http"
}
```

### 8. Test search_jobs

From your MCP client (e.g., Databricks Assistant with MCP connector):

```json
{
  "tool": "search_jobs",
  "arguments": {
    "user_email": "test@example.com",
    "request": "backend engineer with Python experience",
    "top_k": 5,
    "remote_only": true
  }
}
```

Expected response:
```json
{
  "ok": true,
  "action": "search_jobs",
  "result": {
    "query": "backend engineer with Python experience",
    "profile_label": "Software Engineer",
    "count": 5,
    "jobs": [
      {
        "id": "...",
        "title": "Senior Backend Engineer",
        "company": "Tech Corp",
        "similarity": 0.85,
        ...
      }
    ]
  }
}
```

## 🔍 Troubleshooting

If `search_jobs` fails after deployment:

### Error: "No user exists for that email"
**Cause**: User not in database  
**Fix**: Insert user into `users` table

### Error: "This user has no profile"
**Cause**: User has no profile or profile missing required fields  
**Fix**: Insert profile with `target_roles` and `resume_text`

### Error: Connection timeout
**Cause**: Lakebase endpoint not accessible  
**Fix**: 
- Check Lakebase instance is running
- Verify secrets are correct
- Check network connectivity

### Error: Empty results (count: 0)
**Cause**: No job postings in database  
**Fix**: Load job postings and generate embeddings

### Error: Embedding dimension mismatch
**Cause**: Embeddings have wrong dimension  
**Fix**: Regenerate embeddings with correct model (`databricks-gte-large-en` = 1024 dimensions)

## 📊 Monitoring

### Key Metrics to Track:

1. **MCP Health**: Monitor `/health` endpoint
2. **Database Queries**: Track query latency
3. **Embedding Endpoint**: Monitor response times
4. **Error Rates**: Track `ok: false` responses

### Logs to Check:

```python
# The MCP server logs to stdout
# Check app logs in Databricks:
logs = dbutils.apps.get_logs(app_name="job-copilot-mcp")
```

## ✅ Pre-Deployment Checklist

Before deploying, verify:

- [ ] `requirements.txt` includes all dependencies
- [ ] Lakebase connection string stored in secrets
- [ ] Database tables created with correct schema
- [ ] pgvector extension installed in Postgres
- [ ] At least one test user with profile exists
- [ ] Job postings table populated
- [ ] Job embeddings generated and stored
- [ ] Embedding endpoint `databricks-gte-large-en` accessible
- [ ] `app.yaml` configured correctly
- [ ] All recent code fixes applied:
  - [ ] `embedding_client.py` uses `input=` parameter
  - [ ] `system_prompt.md` has failure guardrail
  - [ ] Tests pass (7/7)

## 🎉 Success Criteria

You'll know it's working when:

1. ✓ Health endpoint returns `{"ok": true}`
2. ✓ `search_jobs` returns job results with similarity scores
3. ✓ `update_pipeline_stage` successfully tracks applications
4. ✓ Agent can search, save, and track jobs without errors
5. ✓ No hallucination - agent explains when tools fail

## 📚 Additional Resources

- **Diagnostic Script**: `mcp_server/diagnose_search_jobs.py`
- **Troubleshooting Guide**: `MCP_TROUBLESHOOTING.md`
- **Test Suite**: `tests/test_job_adapter.py`, `tests/test_embedding_client.py`

---

**Status**: All code verified and ready for deployment ✅  
**Last Updated**: 2026-08-10
