import json
import os
import re
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
# Reserved interface; disabled in the first release at the user's request.
ADMISSIONS_ENABLED = False
load_dotenv(ROOT / ".env")
DATA = Path(os.getenv("FEEDBACK_DATA_DIR", str(ROOT / "data/private"))).expanduser().resolve()
DATA.mkdir(parents=True, exist_ok=True)
os.chmod(DATA, 0o700)
SETTINGS = DATA / "settings.json"

def settings() -> dict:
    saved = json.loads(SETTINGS.read_text()) if SETTINGS.exists() else {}
    file_key = ""
    secret_file = ROOT / "deepseek"
    if secret_file.is_file():
        match = re.search(r"sk-[A-Za-z0-9_-]{12,}", secret_file.read_text(encoding="utf-8").strip())
        file_key = match.group(0) if match else ""
    return {
        "api_key": saved["api_key"] if "api_key" in saved else os.getenv("DEEPSEEK_API_KEY", "") or file_key,
        "base_url": saved.get("base_url") or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        "model": saved.get("model") or os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
        "timeout": int(os.getenv("DEEPSEEK_TIMEOUT", "120")),
        "max_calls": int(os.getenv("DEEPSEEK_MAX_CALLS", "48")),
        "analysis_concurrency": max(1, min(8, int(saved.get("analysis_concurrency", os.getenv("DEEPSEEK_CONCURRENCY", "4"))))),
    }

def save_settings(values: dict) -> None:
    # Preference changes must not copy the root secret to a second file.
    current = json.loads(SETTINGS.read_text()) if SETTINGS.exists() else {}
    current.update({k: v for k, v in values.items() if v is not None})
    temporary = SETTINGS.with_suffix(".tmp")
    temporary.write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(SETTINGS)
