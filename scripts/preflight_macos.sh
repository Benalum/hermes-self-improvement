#!/usr/bin/env bash
set -euo pipefail
BASE="${HERMES_SI_BASE:-/opt/hermes-self-improvement}"
HERMES_ROOT="${HERMES_ROOT:-$HOME/.hermes/hermes-agent}"
HERMES_PY="${HERMES_PY:-$HERMES_ROOT/venv/bin/python}"
[[ "$(uname -s)" == Darwin ]] || { echo 'ERROR: macOS required' >&2; exit 1; }
echo '[1/9] controller files'
for f in "$BASE/scripts/run_daily_improvement.sh" "$BASE/scripts/baseline_validate.py" "$BASE/scripts/agent_phase_guard.py" "$BASE/scripts/triage_plan.py" "$BASE/scripts/triage_output.py" "$BASE/scripts/triage_infer.py" "$BASE/scripts/fresh_probe.py" "$BASE/scripts/ollama_model_check.py" "$BASE/scripts/run_with_deadline.py" "$BASE/scripts/candidate_gate.py" "$BASE/scripts/cleanup_worktrees.py" "$BASE/config/self_improvement_context.md" "$BASE/config/promotion_policy.env" "$BASE/prompts/self_improvement.md"; do [[ -f "$f" ]] || { echo "MISSING: $f"; exit 1; }; done
echo '[2/9] syntax'
zsh -n "$BASE/scripts/run_daily_improvement.sh"
"$HERMES_PY" -m py_compile "$BASE/scripts/baseline_validate.py" "$BASE/scripts/agent_phase_guard.py" "$BASE/scripts/triage_plan.py" "$BASE/scripts/triage_output.py" "$BASE/scripts/triage_infer.py" "$BASE/scripts/fresh_probe.py" "$BASE/scripts/ollama_model_check.py" "$BASE/scripts/run_with_deadline.py" "$BASE/scripts/candidate_gate.py" "$BASE/scripts/cleanup_worktrees.py"
echo '[3/9] Hermes CLI'
"$HERMES_PY" -m hermes_cli.main --version
CHAT_HELP="$("$HERMES_PY" -m hermes_cli.main chat --help 2>&1 || true)"
echo "$CHAT_HELP" | grep -q -- '--max-turns' && echo '  --max-turns supported' || echo '  --max-turns not advertised; wall-clock watchdog will still bound runs'
echo "$CHAT_HELP" | grep -q -- '--source' && echo '  --source supported' || echo '  --source not advertised; source tag will be omitted'
echo "$CHAT_HELP" | grep -q -- '--model' && echo '  --model supported (implementation model pinning)' || echo '  --model not advertised; HERMES_INFERENCE_MODEL fallback will be used'
echo "$CHAT_HELP" | grep -q -- '--reasoning' && echo '  --reasoning supported (implementation reasoning)' || echo '  --reasoning not advertised; configured global reasoning will apply'
echo '[4/9] uv baseline tool'
UV_PATH=""
for candidate in "$HERMES_ROOT/venv/bin/uv" "${UV_BIN:-}" "$(command -v uv 2>/dev/null || true)" "$HOME/.hermes/bin/uv" "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv" /opt/homebrew/bin/uv /usr/local/bin/uv; do
  [[ -n "$candidate" && -x "$candidate" ]] || continue
  UV_PATH="$candidate"
  break
done
if [[ -f "$HERMES_ROOT/pyproject.toml" && -z "$UV_PATH" ]]; then
  echo 'ERROR: uv not found for baseline environment preparation.' >&2
  echo "Checked Hermes venv, UV_BIN, PATH, ~/.hermes/bin, ~/.local/bin, ~/.cargo/bin, and Homebrew locations." >&2
  exit 1
fi
if [[ -n "$UV_PATH" ]]; then echo "  uv: $UV_PATH"; "$UV_PATH" --version; else echo '  uv not required (no pyproject.toml)'; fi

echo '[5/9] local triage + implementation models/context'
# Read installed policy so preflight validates the same models the scheduler will use.
DISCOVERY_MODEL="${DISCOVERY_MODEL:-$(awk -F= '$1=="DISCOVERY_MODEL" {print substr($0,index($0,"=")+1); exit}' "$BASE/config/promotion_policy.env")}"
IMPLEMENTATION_MODEL="${IMPLEMENTATION_MODEL:-$(awk -F= '$1=="IMPLEMENTATION_MODEL" {print substr($0,index($0,"=")+1); exit}' "$BASE/config/promotion_policy.env")}"
DISCOVERY_MODEL="${DISCOVERY_MODEL:-qwen3.5:4b-mlx}"
IMPLEMENTATION_MODEL="${IMPLEMENTATION_MODEL:-gemma4:31b-mlx}"
OLLAMA_MODELS="$(ollama list 2>/dev/null | awk 'NR>1 {print $1}' || true)"
for model in "$DISCOVERY_MODEL" "$IMPLEMENTATION_MODEL"; do
  if ! printf '%s\n' "$OLLAMA_MODELS" | grep -Fxq "$model"; then
    echo "ERROR: required local model not installed: $model" >&2
    if [[ "$model" == "$DISCOVERY_MODEL" ]]; then echo "Install it with: ollama pull $model" >&2; fi
    exit 1
  fi
  CHECK_OUT="$("$HERMES_PY" "$BASE/scripts/ollama_model_check.py" --model "$model" --minimum 64000 2>&1)" || { echo "$CHECK_OUT" >&2; exit 1; }
  CTX="$(printf '%s\n' "$CHECK_OUT" | tail -1 | awk '{print $2}')"
  echo "  model: $model (context=$CTX)"
done
echo '  triage execution: direct local Ollama structured inference (no Hermes tools)'
PROBE_MAX="$(awk -F= '$1=="FRESH_PROBE_MAX_ATTEMPTS" {print $2; exit}' "$BASE/config/promotion_policy.env")"
PROBE_MAX="${PROBE_MAX:-3}"
[[ "$PROBE_MAX" =~ ^[0-9]+$ ]] && (( PROBE_MAX >= 1 && PROBE_MAX <= 8 )) || { echo "ERROR: FRESH_PROBE_MAX_ATTEMPTS must be an integer from 1 to 8" >&2; exit 1; }
echo "  fresh probe max attempts: $PROBE_MAX"
echo '[6/9] existing self-improvement agent'
ORPHAN_PIDS="$(ps -axo pid=,command= 2>/dev/null | awk '/hermes_cli\.main chat/ && /--source self-improvement/ {print $1}' | tr '\n' ' ' | sed 's/[[:space:]]*$//' || true)"
if [[ -n "$ORPHAN_PIDS" ]]; then echo "ERROR: existing Hermes self-improvement agent process(es): $ORPHAN_PIDS" >&2; exit 1; else echo '  none found'; fi
echo '[7/9] production Git state' 
git -C "$HERMES_ROOT" log -1 --oneline
git -C "$HERMES_ROOT" status --short || true
echo '[8/9] promotion policy'
grep '^AUTO_PROMOTE_MODE=' "$BASE/config/promotion_policy.env" || true
if ! grep -q '^AUTO_PROMOTE_MODE=off$' "$BASE/config/promotion_policy.env"; then echo 'WARNING: automatic promotion is not OFF.'; fi
echo '[9/9] scheduler'
launchctl print "gui/$(id -u)/com.hermes.selfimprovement" >/dev/null 2>&1 && echo '  launchd job found' || echo '  launchd job not found (controller itself is still valid)'
echo 'PREFLIGHT PASS'
