"""
One-time setup script: stores the Lakebase connection URL and the job-source
API credentials as Databricks secrets, all under the same scope. Run this
locally (with the Databricks CLI configured) or from a notebook -- never
commit the resulting secret values anywhere.

RemoteOK needs no key, so only Adzuna and USAJobs credentials are prompted
for here. Leave a prompt blank to skip that source -- the app runs fine with
just one or two sources configured; a missing source is simply omitted from
sync results rather than causing an error.

Usage:
    python setup_secrets.py
"""
from databricks.sdk import WorkspaceClient
from databricks.sdk.service import workspace
import base64
import getpass

w = WorkspaceClient()

# w.secrets.create_scope(scope="database")


def _put(key: str, prompt: str) -> None:
    value = getpass.getpass(prompt).strip()
    if not value:
        print(f"  skipped {key} (blank)")
        return
    w.secrets.put_secret(
        scope="database",
        key=key,
        string_value=base64.b64encode(value.encode("utf-8")).decode("ascii"),
    )
    print(f"  stored {key}")


print("Lakebase")
_put("lakebase-url", "Paste your Lakebase URL: ")

print("\nAdzuna (https://developer.adzuna.com) -- leave blank to skip")
_put("adzuna-app-id", "Paste your Adzuna app_id: ")
_put("adzuna-app-key", "Paste your Adzuna app_key: ")

print("\nUSAJobs (https://developer.usajobs.gov) -- leave blank to skip")
_put("usajobs-api-key", "Paste your USAJobs API key: ")
_put("usajobs-email", "Paste the email registered for that key: ")


w.secrets.put_acl(
    scope="database",
    principal="users",
    permission=workspace.AclPermission.READ,
)

print("\nGranted READ on the 'database' scope to the 'users' group.")
print("Remember to also grant your Databricks App's service principal READ")
print("on this scope, or the app cannot open a connection:")
print("  databricks secrets put-acl database <app-service-principal> READ")
