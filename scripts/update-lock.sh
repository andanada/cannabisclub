#!/usr/bin/env bash
# Regenera requirements.lock i requirements-dev.lock (versions fixades + hashes SHA-256, vàlids per a Linux/macOS/Windows).
# Usa un entorn temporal FORA del repositori. Cal Python 3.12+ i accés a PyPI.
# Instal·lació reproduïble:  pip install --require-hashes -r requirements.lock
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"; trap 'rm -rf -- "$TMP"' EXIT
python3 -m venv "$TMP/v"
"$TMP/v/bin/python" -m pip install -q uv
cd "$REPO"
for base in requirements requirements-dev; do
  "$TMP/v/bin/uv" pip compile "$base.txt" --universal --generate-hashes --python-version 3.12 -o "$base.lock"
done
echo "Fet. Revisa el diff i comprova: pip install --dry-run --require-hashes -r requirements.lock"
