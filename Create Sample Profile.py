# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# DBTITLE 1,Install required dependencies
# MAGIC %pip install pg8000>=1.31.2 --quiet
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

# DBTITLE 1,Import dependencies and connect to Lakebase
import sys
sys.path.append('/Workspace/Users/lanshanoar@gmail.com/job_search_copilot_w_brick')

# Force reload of lakebase module to get latest changes
import importlib
if 'lakebase' in sys.modules:
    import lakebase
    importlib.reload(lakebase)
else:
    import lakebase

import uuid
from datetime import datetime

# Test connection
print("Testing Lakebase connection...")
health = lakebase.ping()
print(f"Connected to {health['host']} - {health['database']}")
print(f"Server: {health['server_version']}")

# COMMAND ----------

# DBTITLE 1,Create or find a sample user
# Check if users table exists
if not lakebase.table_exists('users'):
    print("❌ Users table not found. Please run the SQL setup scripts in sql/ directory first.")
else:
    print("✓ Users table exists")
    
    # Check for existing users
    sample_email = "demo.user@example.com"
    existing_users = lakebase.run_query("SELECT * FROM users WHERE email = %s", (sample_email,))
    
    if existing_users:
        user_id = existing_users[0]['id']
        print(f"\n✓ Found existing user: {existing_users[0]['email']}")
        print(f"  User ID: {user_id}")
    else:
        # Create a sample user with run_write (which commits)
        user_id = str(uuid.uuid4())
        
        insert_sql = """
            INSERT INTO users (id, email, display_name, created_at)
            VALUES (%s, %s, %s, %s)
        """
        
        lakebase.run_write(
            insert_sql,
            (user_id, sample_email, "Demo User", datetime.utcnow())
        )
        print(f"\n✓ Created sample user: {sample_email}")
        print(f"  User ID: {user_id}")

# COMMAND ----------

# DBTITLE 1,Create a sample profile with job preferences
# Check if profiles table exists
if not lakebase.table_exists('profiles'):
    print("❌ Profiles table not found. Please run the SQL setup scripts first.")
else:
    print("\n✓ Profiles table exists")
    
    # Delete existing profiles for this user to start fresh
    lakebase.run_write("DELETE FROM profiles WHERE user_id = %s", (user_id,))
    
    # Sample profile: looking for data/ML engineer roles, remote-friendly, $120k+
    target_roles = ['data engineer', 'machine learning engineer', 'ml engineer', 'software engineer']
    locations_preferred = ['San Francisco', 'Austin', 'Seattle', 'Remote']
    deal_breakers = ['no visa sponsorship', 'unpaid']
    
    sample_resume = """
    Experienced Data Engineer with 5+ years building scalable data pipelines.
    
    Skills:
    - Python, SQL, PySpark, Apache Spark
    - Data warehousing (Snowflake, Databricks, BigQuery)
    - ETL/ELT pipeline development
    - Machine learning deployment and MLOps
    - Cloud platforms (AWS, Azure, GCP)
    
    Looking for remote or hybrid opportunities in data engineering and ML engineering.
    """
    
    # Generate profile ID
    profile_id = str(uuid.uuid4())
    
    # Create a sample profile with run_write (which commits)
    profile_sql = """
        INSERT INTO profiles (
            id, user_id, label, target_roles, seniority, 
            salary_min, salary_currency, remote_preference,
            locations_preferred, deal_breakers,
            resume_text, is_default, created_at, updated_at
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
    """
    
    lakebase.run_write(
        profile_sql,
        (
            profile_id,
            user_id,
            'default',  # label
            target_roles,  # target_roles (PostgreSQL array)
            'mid-senior',  # seniority
            120000,  # salary_min
            'USD',  # salary_currency
            'remote_only',  # remote_preference: 'remote_only', 'hybrid', 'onsite', 'any'
            locations_preferred,  # locations_preferred
            deal_breakers,  # deal_breakers
            sample_resume,  # resume_text
            True,  # is_default
            datetime.utcnow(),
            datetime.utcnow()
        )
    )
    print(f"\n✓ Created sample profile:")
    print(f"  Profile ID: {profile_id}")
    print(f"  Target roles: {', '.join(target_roles)}")
    print(f"  Remote preference: remote_only")
    print(f"  Minimum salary: $120,000 USD")
    print(f"  Preferred locations: {', '.join(locations_preferred)}")

# COMMAND ----------

# DBTITLE 1,Verify the profile was created
# Query the profile back to verify
profile_check = lakebase.run_query("""
    SELECT p.*, u.email, u.display_name
    FROM profiles p
    JOIN users u ON p.user_id = u.id
    WHERE p.user_id = %s
""", (user_id,))

if profile_check:
    print("\n" + "="*60)
    print("PROFILE CREATED SUCCESSFULLY!")
    print("="*60)
    p = profile_check[0]
    print(f"\nUser: {p['display_name']} ({p['email']})")
    print(f"Label: {p['label']}")
    print(f"Target Roles: {p['target_roles']}")
    print(f"Seniority: {p['seniority']}")
    print(f"Minimum Salary: ${p['salary_min']:,.0f} {p['salary_currency']}")
    print(f"Remote Preference: {p['remote_preference']}")
    print(f"Preferred Locations: {p['locations_preferred']}")
    print(f"Is Default: {p['is_default']}")
    print("\n" + "="*60)
    print("\nNow you can:")
    print("1. Deploy the updated app code")
    print("2. Open the app and check 'Relevant jobs only'")
    print("3. The app will filter jobs based on this profile!")
    print("="*60)
else:
    print("❌ Profile verification failed")

# COMMAND ----------

