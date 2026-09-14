#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; BASE="${HERMES_SI_BASE:-/opt/hermes-self-improvement}"; STAMP="$(date '+%Y%m%d-%H%M%S')"
[[ "$(uname -s)" == Darwin ]] || { echo 'ERROR: this installer targets macOS.' >&2; exit 1; }
[[ -f "$BASE/prompts/self_improvement.md" ]] || { echo "ERROR: existing master prompt not found: $BASE/prompts/self_improvement.md" >&2; echo 'The installer intentionally does not replace your master prompt.' >&2; exit 1; }
sudo mkdir -p "$BASE/scripts" "$BASE/config" "$BASE/backups" "$BASE/reports" "$BASE/logs" "$BASE/state" "$BASE/experiments/worktrees" "$BASE/experiments/promotion"
install_one(){ local src="$1" dst="$2" mode="$3"; [[ -f "$src" ]] || { echo "ERROR: missing bundle file $src" >&2; exit 1; }; [[ -f "$dst" ]] && sudo cp "$dst" "$BASE/backups/$(basename "$dst").$STAMP"; sudo cp "$src" "$dst"; sudo chown "$(id -un):$(id -gn)" "$dst"; chmod "$mode" "$dst"; }
install_one "$REPO_ROOT/self-improvement/run_daily_improvement.sh" "$BASE/scripts/run_daily_improvement.sh" 0755
install_one "$REPO_ROOT/self-improvement/hermes-worktree-context.md" "$BASE/config/self_improvement_context.md" 0644
install_one "$REPO_ROOT/scripts/baseline_validate.py" "$BASE/scripts/baseline_validate.py" 0755
install_one "$REPO_ROOT/scripts/agent_phase_guard.py" "$BASE/scripts/agent_phase_guard.py" 0755
install_one "$REPO_ROOT/scripts/triage_plan.py" "$BASE/scripts/triage_plan.py" 0755
install_one "$REPO_ROOT/scripts/triage_output.py" "$BASE/scripts/triage_output.py" 0755
install_one "$REPO_ROOT/scripts/triage_infer.py" "$BASE/scripts/triage_infer.py" 0755
install_one "$REPO_ROOT/scripts/fresh_probe.py" "$BASE/scripts/fresh_probe.py" 0755
install_one "$REPO_ROOT/scripts/ollama_model_check.py" "$BASE/scripts/ollama_model_check.py" 0755
install_one "$REPO_ROOT/scripts/run_with_deadline.py" "$BASE/scripts/run_with_deadline.py" 0755
install_one "$REPO_ROOT/scripts/candidate_gate.py" "$BASE/scripts/candidate_gate.py" 0755
install_one "$REPO_ROOT/scripts/cleanup_worktrees.py" "$BASE/scripts/cleanup_worktrees.py" 0755
install_one "$REPO_ROOT/scripts/set_promotion_mode.sh" "$BASE/scripts/set_promotion_mode.sh" 0755
install_one "$REPO_ROOT/scripts/controller_status.sh" "$BASE/scripts/controller_status.sh" 0755
install_one "$REPO_ROOT/scripts/preflight_macos.sh" "$BASE/scripts/preflight_macos.sh" 0755
if [[ ! -f "$BASE/config/promotion_policy.env" ]]; then sudo cp "$REPO_ROOT/self-improvement/promotion_policy.env" "$BASE/config/promotion_policy.env"; sudo chown "$(id -un):$(id -gn)" "$BASE/config/promotion_policy.env"; chmod 0644 "$BASE/config/promotion_policy.env"; POLICY_ACTION='installed defaults'; else sudo cp "$BASE/config/promotion_policy.env" "$BASE/backups/promotion_policy.env.$STAMP"; POLICY_ACTION='preserved existing policy (backup created)'; fi
# Safe carried-forward policy migration: only update exact prior controller defaults and
# add missing reasoning keys. Never alter AUTO_PROMOTE_MODE or unrelated user policy.
"$HOME/.hermes/hermes-agent/venv/bin/python" - "$BASE/config/promotion_policy.env" <<'PY_POLICY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); lines=p.read_text().splitlines(); out=[]; seen=set(); changed=[]
for line in lines:
    if line == 'DISCOVERY_MODEL=qwen3:8b': line='DISCOVERY_MODEL=qwen3.5:4b-mlx'; changed.append('model qwen3:8b->qwen3.5:4b-mlx')
    if line == 'DISCOVERY_RUNTIME_SECONDS=120': line='DISCOVERY_RUNTIME_SECONDS=150'; changed.append('runtime 120->150')
    elif line == 'DISCOVERY_TURNS=6': line='DISCOVERY_TURNS=4'; changed.append('turns 6->4')
    if '=' in line and not line.lstrip().startswith('#'): seen.add(line.split('=',1)[0])
    out.append(line)
if 'DISCOVERY_REASONING' not in seen: out.append('DISCOVERY_REASONING=minimal'); changed.append('added discovery reasoning')
if 'IMPLEMENTATION_REASONING' not in seen: out.append('IMPLEMENTATION_REASONING=medium'); changed.append('added implementation reasoning')
if 'FRESH_PROBE_TIMEOUT_SECONDS' not in seen: out.append('FRESH_PROBE_TIMEOUT_SECONDS=45'); changed.append('added fresh probe timeout')
if 'FRESH_PROBE_MAX_ATTEMPTS' not in seen: out.append('FRESH_PROBE_MAX_ATTEMPTS=3'); changed.append('added fresh probe max attempts')
p.write_text('\n'.join(out)+'\n')
print('Policy migration: '+(', '.join(changed) if changed else 'no triage-default changes needed'))
PY_POLICY
zsh -n "$BASE/scripts/run_daily_improvement.sh"
"$HOME/.hermes/hermes-agent/venv/bin/python" -m py_compile "$BASE/scripts/baseline_validate.py" "$BASE/scripts/agent_phase_guard.py" "$BASE/scripts/triage_plan.py" "$BASE/scripts/triage_output.py" "$BASE/scripts/triage_infer.py" "$BASE/scripts/fresh_probe.py" "$BASE/scripts/ollama_model_check.py" "$BASE/scripts/run_with_deadline.py" "$BASE/scripts/candidate_gate.py" "$BASE/scripts/cleanup_worktrees.py"
echo 'Installed self-improvement controller v3.19:'
for f in run_daily_improvement.sh baseline_validate.py agent_phase_guard.py triage_plan.py triage_output.py triage_infer.py fresh_probe.py ollama_model_check.py run_with_deadline.py candidate_gate.py cleanup_worktrees.py set_promotion_mode.sh controller_status.sh preflight_macos.sh; do echo "  $BASE/scripts/$f"; done
echo "  $BASE/config/self_improvement_context.md"; echo "Policy: $POLICY_ACTION"; echo "Backups: $BASE/backups/*.$STAMP"; echo; echo 'Automatic promotion remains OFF unless promotion_policy.env says otherwise.'; echo "Next: $BASE/scripts/run_daily_improvement.sh"
