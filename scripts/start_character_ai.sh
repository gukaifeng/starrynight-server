#!/bin/zsh
set -euo pipefail
cd "$(dirname "$0")/.."
exec .local/character-ai-venv/bin/python -m uvicorn services.character_ai.app:create_app --factory --host 127.0.0.1 --port 18766 --no-access-log --log-level warning
