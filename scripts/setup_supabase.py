# scripts/setup_supabase.py
"""
One-off provisioning script — run this once per environment (local, staging,
prod) after setting APP_SUPABASE_URL / APP_SUPABASE_SERVICE_ROLE_KEY /
APP_SUPABASE_BUCKET. Do NOT call this from the app's lifespan — see the note
in main.py.

Run from the `server/` directory:
    python -m scripts.setup_supabase
"""
import sys
from pathlib import Path

# Must happen BEFORE any `app.*` import — this is what makes `app` importable
# when running from scripts/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_app_config
from app.services.storage import ensure_bucket_exists

cfg = get_app_config()
print("Provider:", cfg.storage_config.provider)
print("Supabase URL:", repr(cfg.storage_config.supabase.url))
print("Service key present:", bool(cfg.storage_config.supabase.service_role_key))
print("Bucket:", cfg.storage_config.supabase.bucket_name)

if __name__ == "__main__":
    ensure_bucket_exists()
    print("Done.")