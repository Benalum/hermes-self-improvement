#!/usr/bin/env bash
set -euo pipefail
BASE="${HERMES_SI_BASE:-/opt/hermes-self-improvement}"; POLICY="$BASE/config/promotion_policy.env"; MODE="${1:-}"
case "$MODE" in off|skills_only|conservative) ;; *) echo "usage: $0 {off|skills_only|conservative}" >&2; exit 2;; esac
[[ -f "$POLICY" ]] || { echo "missing policy: $POLICY" >&2; exit 1; }
STAMP="$(date '+%Y%m%d-%H%M%S')"; cp "$POLICY" "$BASE/backups/promotion_policy.env.$STAMP"
python3 - "$POLICY" "$MODE" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); mode=sys.argv[2]; lines=p.read_text().splitlines(); out=[]; found=False
for line in lines:
    if line.startswith('AUTO_PROMOTE_MODE='): out.append('AUTO_PROMOTE_MODE='+mode); found=True
    else: out.append(line)
if not found: out.insert(0,'AUTO_PROMOTE_MODE='+mode)
p.write_text('\n'.join(out)+'\n')
PY
echo "AUTO_PROMOTE_MODE=$MODE"; echo "Backup: $BASE/backups/promotion_policy.env.$STAMP"
