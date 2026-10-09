#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
if ! command -v node >/dev/null; then .venv/bin/python scripts/bootstrap_node.py; fi
export PATH="$PWD/.tools/node/bin:$PATH"
npm --prefix frontend ci
npm --prefix integrations/acgo ci --ignore-scripts
npm --prefix frontend run build
.venv/bin/python -m playwright install chromium
echo 'Setup complete. Run: bash scripts/start.sh'
