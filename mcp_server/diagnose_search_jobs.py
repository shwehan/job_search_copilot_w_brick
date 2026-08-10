#!/usr/bin/env python3
"""Diagnostic script for troubleshooting search_jobs and other MCP functions.

Run this script in your Databricks App environment to identify issues.
"""

import sys
import os
import traceback
from datetime import datetime

print("="*70)
print("JOB COPILOT MCP - DIAGNOSTIC REPORT")
print(f"Generated: {datetime.now().isoformat()}")
print("="*70)

# Step 1: Check environment
print("\n1. ENVIRONMENT CHECK")
print("-" * 70)
try:
    print(f"Python version: {sys.version}")
    print(f"Working directory: {os.getcwd()}")
    print(f"PYTHONPATH: {sys.path[:3]}")
    
    env_vars = [
        "DATABRICKS_EMBEDDING_MODEL",
        "DATABRICKS_CHAT_MODEL",
        "DATABRICKS_APP_PORT",
        "PORT"
    ]
    
    print("\nEnvironment variables:")
    for var in env_vars:
        value = os.getenv(var, "(not set)")
        print(f"  {var}: {value}")
    print("✓ Environment check complete")
except Exception as e:
    print(f"✗ Environment check failed: {e}")

# Step 2: Import dependencies
print("\n2. DEPENDENCY CHECK")
print("-" * 70)

dependencies = [
    ("config", "Configuration module"),
    ("lakebase", "Lakebase Postgres client"),
    ("embedding_client", "Embedding endpoint client"),
    ("model_client", "Chat model client"),
    ("job_adapter", "Job adapter logic"),
    ("job_copilot_mcp", "MCP server"),
    ("fastmcp", "FastMCP framework"),
    ("pg8000", "PostgreSQL driver")
]

import_errors = []

for module_name, description in dependencies:
    try:
        module = __import__(module_name)
        print(f"✓ {module_name}: {description}")
        
        # Print config values
        if module_name == "config":
            print(f"    EMBEDDING_MODEL: {getattr(module, 'EMBEDDING_MODEL', 'N/A')}")
            print(f"    EMBEDDING_DIMENSION: {getattr(module, 'EMBEDDING_DIMENSION', 'N/A')}")
            print(f"    MAX_TOP_K: {getattr(module, 'MAX_TOP_K', 'N/A')}")
            print(f"    CHAT_MODEL: {getattr(module, 'CHAT_MODEL', 'N/A')}")
            
    except ImportError as e:
        print(f"✗ {module_name}: FAILED - {str(e)}")
        import_errors.append((module_name, str(e)))
    except Exception as e:
        print(f"⚠ {module_name}: Import succeeded but error on access - {str(e)}")

if import_errors:
    print(f"\n⚠ {len(import_errors)} import error(s) detected")
else:
    print("\n✓ All dependencies imported successfully")

# Step 3: Test database connection
print("\n3. DATABASE CONNECTION CHECK")
print("-" * 70)

try:
    import lakebase
    
    # Test basic query
    test_query = "SELECT 1 AS test"
    result = lakebase.query(test_query)
    
    if result and result[0].get('test') == 1:
        print("✓ Lakebase connection works")
        
        # Check tables exist
        tables_to_check = [
            "users",
            "profiles",
            "job_postings",
            "job_posting_embeddings",
            "applications",
            "saved_jobs",
            "job_feedback",
            "interview_notes"
        ]
        
        print("\nChecking tables:")
        for table in tables_to_check:
            try:
                count_result = lakebase.query(
                    f"SELECT COUNT(*) as count FROM {table}"
                )
                count = count_result[0]['count'] if count_result else 0
                print(f"  ✓ {table}: {count} rows")
            except Exception as e:
                print(f"  ✗ {table}: Error - {str(e)[:50]}")
    else:
        print("✗ Lakebase query returned unexpected result")
        
except ImportError:
    print("✗ Cannot import lakebase - dependency missing")
except Exception as e:
    print(f"✗ Database connection failed: {e}")
    traceback.print_exc()

# Step 4: Test embedding endpoint
print("\n4. EMBEDDING ENDPOINT CHECK")
print("-" * 70)

try:
    import embedding_client
    import config
    
    print(f"Testing embedding endpoint: {config.EMBEDDING_MODEL}")
    
    test_text = "software engineer python backend"
    vector = embedding_client.embed_query(test_text)
    
    # Verify it's a valid pgvector string
    if vector.startswith('[') and vector.endswith(']'):
        vector_values = [float(x) for x in vector[1:-1].split(',')]
        dimension = len(vector_values)
        
        if dimension == config.EMBEDDING_DIMENSION:
            print(f"✓ Embedding endpoint works")
            print(f"  - Dimension: {dimension}")
            print(f"  - Sample values: {vector_values[:5]}")
        else:
            print(f"✗ Wrong dimension: got {dimension}, expected {config.EMBEDDING_DIMENSION}")
    else:
        print(f"✗ Invalid vector format: {vector[:50]}")
        
except ImportError:
    print("✗ Cannot import embedding_client - dependency missing")
except Exception as e:
    print(f"✗ Embedding endpoint failed: {e}")
    traceback.print_exc()

# Step 5: Test search_jobs with a real user
print("\n5. SEARCH_JOBS FUNCTION TEST")
print("-" * 70)

try:
    import job_adapter
    
    # First, check if any users exist
    import lakebase
    users = lakebase.query("SELECT email FROM users LIMIT 5")
    
    if not users:
        print("⚠ No users found in database")
        print("  Action: Create a user in the dashboard first")
    else:
        print(f"Found {len(users)} user(s):")
        for user in users:
            print(f"  - {user['email']}")
        
        test_email = users[0]['email']
        print(f"\nTesting search_jobs with: {test_email}")
        
        try:
            # Test get_profile_context first
            profile = job_adapter.get_profile_context(test_email)
            print(f"✓ Profile found: {profile['profile']['label']}")
            
            # Test search_jobs
            result = job_adapter.search_jobs(
                user_email=test_email,
                request="software engineer",
                top_k=3
            )
            
            print(f"✓ search_jobs executed successfully")
            print(f"  - Query: {result['query']}")
            print(f"  - Jobs found: {result['count']}")
            
            if result['count'] > 0:
                print("  - Sample job:")
                job = result['jobs'][0]
                print(f"      Title: {job['title']}")
                print(f"      Company: {job['company']}")
                print(f"      Similarity: {job.get('similarity', 'N/A')}")
            else:
                print("  ⚠ No jobs returned - job_postings table may be empty")
                
        except ValueError as e:
            if "no profile" in str(e).lower():
                print(f"⚠ User has no profile: {e}")
                print("  Action: Create a profile for this user in the dashboard")
            else:
                print(f"✗ Validation error: {e}")
        except Exception as e:
            print(f"✗ search_jobs failed: {e}")
            traceback.print_exc()
            
except ImportError:
    print("✗ Cannot import job_adapter - dependency missing")
except Exception as e:
    print(f"✗ Test failed: {e}")
    traceback.print_exc()

# Step 6: Test MCP server structure
print("\n6. MCP SERVER CHECK")
print("-" * 70)

try:
    import job_copilot_mcp
    
    # Check health endpoint
    health = job_copilot_mcp.health()
    if health.get('ok'):
        print("✓ MCP server health check passed")
    else:
        print("✗ MCP server health check failed")
    
    # Count registered tools
    if hasattr(job_copilot_mcp, 'mcp'):
        if hasattr(job_copilot_mcp.mcp, 'tools'):
            tool_count = len(job_copilot_mcp.mcp.tools)
            print(f"✓ {tool_count} MCP tools registered")
        else:
            print("⚠ Cannot count tools - mcp.tools not available")
    else:
        print("⚠ MCP instance not found")
        
except ImportError:
    print("✗ Cannot import job_copilot_mcp - dependency missing")
except Exception as e:
    print(f"✗ MCP server check failed: {e}")
    traceback.print_exc()

# Summary
print("\n" + "="*70)
print("DIAGNOSTIC SUMMARY")
print("="*70)

if import_errors:
    print("\n⚠ ISSUES DETECTED:")
    for module, error in import_errors:
        print(f"  - {module}: {error}")
    print("\nAction: Install missing dependencies")
else:
    print("\n✓ All critical checks passed")
    print("\nIf search_jobs still fails, check:")
    print("  1. User has a profile with target_roles")
    print("  2. job_postings table has data")
    print("  3. job_posting_embeddings table has data")
    print("  4. Embedding endpoint is accessible")
    print("  5. Application logs for detailed error messages")

print("\n" + "="*70)
print("END OF DIAGNOSTIC REPORT")
print("="*70)
