#!/usr/bin/env bash
set -euo pipefail
export PATH="$PATH:/c/Program Files/GitHub CLI"

REPO_NAME="hermes-railway-migrator"
DESCRIPTION="Migrate Hermes Agent sessions from a hosted Railway/dashboard instance into a local Hermes state.db"

if ! gh auth status >/dev/null 2>&1; then
  echo "GitHub CLI is not authenticated. Run: gh auth login"
  exit 1
fi

cd "$(dirname "$0")"

if ! git remote get-url origin >/dev/null 2>&1; then
  gh repo create "$REPO_NAME" --public --description "$DESCRIPTION" --source . --remote origin --push
else
  git push -u origin main
fi

gh repo edit "$REPO_NAME" --add-topic hermes-agent,migration,railway,sqlite,sessions || true

echo "Published: $(gh repo view "$REPO_NAME" --json url --jq .url)"
