#!/usr/bin/env bash
set -euo pipefail
BASE="${HERMES_SI_BASE:-/opt/hermes-self-improvement}"; HERMES_ROOT="${HERMES_ROOT:-$HOME/.hermes/hermes-agent}"
echo '== policy =='; cat "$BASE/config/promotion_policy.env" 2>/dev/null || true; echo; echo '== production =='; git -C "$HERMES_ROOT" status --short 2>/dev/null || true; git -C "$HERMES_ROOT" log -1 --oneline 2>/dev/null || true; echo; echo '== worktrees =='; git -C "$HERMES_ROOT" worktree list 2>/dev/null || true; echo; echo '== latest candidate-gate decision =='; LATEST="$(ls -t "$BASE"/reports/self-improvement-*.md 2>/dev/null | head -1 || true)"; if [[ -n "$LATEST" ]]; then echo "$LATEST"; awk '/^## Candidate Gate/{show=1;next}/^## /{if(show)exit}show' "$LATEST" | tail -40; else echo 'No reports found.'; fi
