#!/usr/bin/env bash
# Extract a paper PDF to structured Docling JSON.
# Usage: ./extract.sh /path/to/paper.pdf [extra args...]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
if [[ ! -d "$ROOT/.venv" ]]; then
  echo "Run setup first: cd docling && python3 -m venv .venv && source .venv/bin/activate && pip install -e ."
  exit 1
fi
source "$ROOT/.venv/bin/activate"
exec python -m paper_extract "$@"
