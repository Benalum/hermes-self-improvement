#!/bin/zsh
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"
BASE="${HERMES_SI_BASE:-/opt/hermes-self-improvement}"
HERMES_ROOT="${HERMES_ROOT:-$HOME/.hermes/hermes-agent}"
HERMES_PY="${HERMES_PY:-$HERMES_ROOT/venv/bin/python}"
PROMPT="$BASE/prompts/self_improvement.md"
CONTEXT_TEMPLATE="$BASE/config/self_improvement_context.md"
POLICY="$BASE/config/promotion_policy.env"
DEADLINE_RUNNER="$BASE/scripts/run_with_deadline.py"
CANDIDATE_GATE="$BASE/scripts/candidate_gate.py"
CLEANUP_TOOL="$BASE/scripts/cleanup_worktrees.py"
BASELINE_VALIDATOR="$BASE/scripts/baseline_validate.py"
AGENT_PHASE_GUARD="$BASE/scripts/agent_phase_guard.py"
TRIAGE_PLAN_TOOL="$BASE/scripts/triage_plan.py"
TRIAGE_OUTPUT_TOOL="$BASE/scripts/triage_output.py"
TRIAGE_INFER_TOOL="${TRIAGE_INFER_TOOL:-$BASE/scripts/triage_infer.py}"
FRESH_PROBE_TOOL="$BASE/scripts/fresh_probe.py"
REPORTS="$BASE/reports"; LOGS="$BASE/logs"; STATE="$BASE/state"; BACKUPS="$BASE/backups"
TIMESTAMP="$(date '+%Y-%m-%d_%H-%M-%S')"; REPORT="$REPORTS/self-improvement-$TIMESTAMP.md"; LOG="$LOGS/self-improvement-$TIMESTAMP.log"; LOCK="$STATE/self-improvement.lock"
WORKTREE=""; EPHEMERAL_CONTEXT=""; AGENT_GUARD_MANIFEST=""; AGENT_GUARD_BIN=""; WATCHDOG_PID=""; BASELINE_EVIDENCE=""; RED_BASELINE_RESEARCH="no"; TRIAGE_PLAN=""; TRIAGE_TRANSCRIPT=""; TRIAGE_PROMPT_FILE=""; FRESH_PROBE_JSON=""
mkdir -p "$REPORTS" "$LOGS" "$STATE" "$BACKUPS"
exec >> "$LOG" 2>&1
printf '%s\n' '================================================' 'HERMES AUTONOMOUS SELF-IMPROVEMENT' "Started: $(date)" '================================================'
cleanup(){
  if [[ -n "${WATCHDOG_PID:-}" ]] && kill -0 "$WATCHDOG_PID" 2>/dev/null; then
    kill -TERM "$WATCHDOG_PID" 2>/dev/null || true
    for _ in {1..50}; do kill -0 "$WATCHDOG_PID" 2>/dev/null || break; sleep 0.1; done
    kill -KILL "$WATCHDOG_PID" 2>/dev/null || true
    wait "$WATCHDOG_PID" 2>/dev/null || true
  fi
  WATCHDOG_PID=""
  if [[ -n "${AGENT_GUARD_MANIFEST:-}" && -f "$AGENT_GUARD_MANIFEST" ]]; then "$HERMES_PY" "$AGENT_PHASE_GUARD" exit --manifest "$AGENT_GUARD_MANIFEST" >/dev/null 2>&1 || true; fi
  [[ -n "${EPHEMERAL_CONTEXT:-}" && -f "$EPHEMERAL_CONTEXT" ]] && rm -f "$EPHEMERAL_CONTEXT"
  [[ -n "${TRIAGE_PLAN:-}" ]] && rm -f "$TRIAGE_PLAN" 2>/dev/null || true
  [[ -n "${TRIAGE_TRANSCRIPT:-}" ]] && rm -f "$TRIAGE_TRANSCRIPT" 2>/dev/null || true
  [[ -n "${TRIAGE_PROMPT_FILE:-}" ]] && rm -f "$TRIAGE_PROMPT_FILE" 2>/dev/null || true
  rm -f "$LOCK"
}
trap cleanup EXIT INT TERM HUP
if [[ -e "$LOCK" ]]; then OLD_PID="$(cat "$LOCK" 2>/dev/null || true)"; if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null; then echo "Another self-improvement process is already running. PID: $OLD_PID"; exit 0; fi; rm -f "$LOCK"; fi
# A terminal/session loss can kill the wrapper while leaving the deadline runner's
# detached Hermes process group alive. Never overlap a surviving autonomous chat.
ORPHAN_PIDS="$(ps -axo pid=,command= 2>/dev/null | awk '/hermes_cli\.main chat/ && /--source self-improvement/ {print $1}' | tr '\n' ' ' | sed 's/[[:space:]]*$//' || true)"
if [[ -n "$ORPHAN_PIDS" ]]; then
  echo "ERROR: existing Hermes self-improvement agent process(es) detected: $ORPHAN_PIDS"
  echo 'Refusing to start another autonomous run until the stale/active agent is resolved.'
  exit 75
fi
echo $$ > "$LOCK"
for f in "$PROMPT" "$CONTEXT_TEMPLATE" "$POLICY" "$DEADLINE_RUNNER" "$CANDIDATE_GATE" "$BASELINE_VALIDATOR" "$AGENT_PHASE_GUARD" "$TRIAGE_PLAN_TOOL" "$TRIAGE_OUTPUT_TOOL" "$TRIAGE_INFER_TOOL" "$FRESH_PROBE_TOOL"; do [[ -f "$f" ]] || { echo "ERROR: required file missing: $f"; exit 1; }; done
[[ -x "$HERMES_PY" ]] || { echo "ERROR: Hermes Python environment not found: $HERMES_PY"; exit 1; }
[[ -d "$HERMES_ROOT/.git" ]] || { echo "ERROR: Hermes repository not found: $HERMES_ROOT"; exit 1; }
# Policy values are defaults for scheduled runs. Explicit one-shot environment
# overrides (for example MAX_RUNTIME_SECONDS=1800 MAX_TURNS=25) must win.
ENV_MAX_RUNTIME_SECONDS="${MAX_RUNTIME_SECONDS-}"
ENV_MAX_TURNS="${MAX_TURNS-}"
ENV_DISCOVERY_MODEL="${DISCOVERY_MODEL-}"; ENV_IMPLEMENTATION_MODEL="${IMPLEMENTATION_MODEL-}"
ENV_DISCOVERY_RUNTIME_SECONDS="${DISCOVERY_RUNTIME_SECONDS-}"; ENV_DISCOVERY_TURNS="${DISCOVERY_TURNS-}"
ENV_DISCOVERY_REASONING="${DISCOVERY_REASONING-}"; ENV_IMPLEMENTATION_REASONING="${IMPLEMENTATION_REASONING-}"; ENV_FRESH_PROBE_TIMEOUT_SECONDS="${FRESH_PROBE_TIMEOUT_SECONDS-}"; ENV_FRESH_PROBE_MAX_ATTEMPTS="${FRESH_PROBE_MAX_ATTEMPTS-}"; ENV_TRIAGE_OLLAMA_URL="${TRIAGE_OLLAMA_URL-}"
set -a; source "$POLICY"; set +a
[[ -n "$ENV_MAX_RUNTIME_SECONDS" ]] && MAX_RUNTIME_SECONDS="$ENV_MAX_RUNTIME_SECONDS"
[[ -n "$ENV_MAX_TURNS" ]] && MAX_TURNS="$ENV_MAX_TURNS"
[[ -n "$ENV_DISCOVERY_MODEL" ]] && DISCOVERY_MODEL="$ENV_DISCOVERY_MODEL"
[[ -n "$ENV_IMPLEMENTATION_MODEL" ]] && IMPLEMENTATION_MODEL="$ENV_IMPLEMENTATION_MODEL"
[[ -n "$ENV_DISCOVERY_RUNTIME_SECONDS" ]] && DISCOVERY_RUNTIME_SECONDS="$ENV_DISCOVERY_RUNTIME_SECONDS"
[[ -n "$ENV_DISCOVERY_TURNS" ]] && DISCOVERY_TURNS="$ENV_DISCOVERY_TURNS"
[[ -n "$ENV_DISCOVERY_REASONING" ]] && DISCOVERY_REASONING="$ENV_DISCOVERY_REASONING"
[[ -n "$ENV_IMPLEMENTATION_REASONING" ]] && IMPLEMENTATION_REASONING="$ENV_IMPLEMENTATION_REASONING"
[[ -n "$ENV_FRESH_PROBE_TIMEOUT_SECONDS" ]] && FRESH_PROBE_TIMEOUT_SECONDS="$ENV_FRESH_PROBE_TIMEOUT_SECONDS"
[[ -n "$ENV_FRESH_PROBE_MAX_ATTEMPTS" ]] && FRESH_PROBE_MAX_ATTEMPTS="$ENV_FRESH_PROBE_MAX_ATTEMPTS"
[[ -n "$ENV_TRIAGE_OLLAMA_URL" ]] && TRIAGE_OLLAMA_URL="$ENV_TRIAGE_OLLAMA_URL"
MAX_RUNTIME_SECONDS="${MAX_RUNTIME_SECONDS:-5400}"; MAX_TURNS="${MAX_TURNS:-80}"
DISCOVERY_MODEL="${DISCOVERY_MODEL:-qwen3.5:4b-mlx}"; IMPLEMENTATION_MODEL="${IMPLEMENTATION_MODEL:-gemma4:31b-mlx}"
DISCOVERY_RUNTIME_SECONDS="${DISCOVERY_RUNTIME_SECONDS:-150}"; DISCOVERY_TURNS="${DISCOVERY_TURNS:-4}"
DISCOVERY_REASONING="${DISCOVERY_REASONING:-minimal}"; IMPLEMENTATION_REASONING="${IMPLEMENTATION_REASONING:-medium}"; FRESH_PROBE_TIMEOUT_SECONDS="${FRESH_PROBE_TIMEOUT_SECONDS:-45}"; FRESH_PROBE_MAX_ATTEMPTS="${FRESH_PROBE_MAX_ATTEMPTS:-3}"; TRIAGE_OLLAMA_URL="${TRIAGE_OLLAMA_URL:-http://127.0.0.1:11434/api/chat}"
if (( DISCOVERY_RUNTIME_SECONDS >= MAX_RUNTIME_SECONDS )); then DISCOVERY_RUNTIME_SECONDS=$(( MAX_RUNTIME_SECONDS / 5 )); (( DISCOVERY_RUNTIME_SECONDS < 1 )) && DISCOVERY_RUNTIME_SECONDS=1; fi
IMPLEMENTATION_RUNTIME_SECONDS=$(( MAX_RUNTIME_SECONDS - DISCOVERY_RUNTIME_SECONDS )); (( IMPLEMENTATION_RUNTIME_SECONDS < 1 )) && IMPLEMENTATION_RUNTIME_SECONDS=1
IMPLEMENTATION_TURNS="$MAX_TURNS"
BASELINE_VALIDATION_CACHE_SECONDS="${BASELINE_VALIDATION_CACHE_SECONDS:-86400}"; BASELINE_VALIDATION_TIMEOUT_SECONDS="${BASELINE_VALIDATION_TIMEOUT_SECONDS:-1800}"
cat > "$REPORT" <<EOF_REPORT
# Hermes Autonomous Self-Improvement Report

Started: $(date)

## Controller Policy

- Max agent runtime: \`${MAX_RUNTIME_SECONDS}s\`
- Max agent turns: \`${MAX_TURNS}\`
- Discovery model/budget: \`${DISCOVERY_MODEL}\` / \`${DISCOVERY_RUNTIME_SECONDS}s\` / \`direct Ollama structured inference (no tools)\`
- Implementation model/budget: \`${IMPLEMENTATION_MODEL}\` / \`${IMPLEMENTATION_RUNTIME_SECONDS}s\` / \`${IMPLEMENTATION_TURNS} turns\`
- Auto-promote mode: \`${AUTO_PROMOTE_MODE:-off}\`
- Fresh known-red probe timeout: \`${FRESH_PROBE_TIMEOUT_SECONDS}s\`
- Fresh known-red probe max attempts: \`${FRESH_PROBE_MAX_ATTEMPTS}\`

## System Baseline

\`\`\`
Hostname: $(hostname)
User: $(whoami)
Architecture: $(uname -m)
$(sw_vers 2>/dev/null || true)
\`\`\`

## Disk

\`\`\`
$(df -h /)
\`\`\`

## Hermes Repository

\`\`\`
EOF_REPORT
git -C "$HERMES_ROOT" status --short >> "$REPORT" 2>&1 || true; echo >> "$REPORT"; echo 'Current commit:' >> "$REPORT"; git -C "$HERMES_ROOT" rev-parse HEAD >> "$REPORT" 2>&1; echo '```' >> "$REPORT"
for section in 'Hermes Version' 'Hermes Update Check'; do echo >> "$REPORT"; echo "## $section" >> "$REPORT"; echo '```' >> "$REPORT"; if [[ "$section" == 'Hermes Version' ]]; then "$HERMES_PY" -m hermes_cli.main --version >> "$REPORT" 2>&1 || true; else "$HERMES_PY" -m hermes_cli.main update --check >> "$REPORT" 2>&1 || true; fi; echo '```' >> "$REPORT"; done
echo >> "$REPORT"; echo '## Installed Models' >> "$REPORT"; echo '```' >> "$REPORT"; ollama list >> "$REPORT" 2>&1 || true; echo '```' >> "$REPORT"
echo >> "$REPORT"; echo '## Hermes Skill Curator' >> "$REPORT"; echo '```' >> "$REPORT"; if "$HERMES_PY" -m hermes_cli.main --help 2>&1 | grep -q curator; then "$HERMES_PY" -m hermes_cli.main curator status >> "$REPORT" 2>&1 || true; echo >> "$REPORT"; echo 'Dry-run review:' >> "$REPORT"; "$HERMES_PY" -m hermes_cli.main curator run --dry-run >> "$REPORT" 2>&1 || true; else echo 'Curator is not available in this Hermes version.' >> "$REPORT"; fi; echo '```' >> "$REPORT"
BASELINE_COMMIT="$(git -C "$HERMES_ROOT" rev-parse HEAD)"; WORKTREE_PARENT="$BASE/experiments/worktrees"; WORKTREE="$WORKTREE_PARENT/$TIMESTAMP"; BRANCH="self-improvement/$TIMESTAMP"; mkdir -p "$WORKTREE_PARENT"
echo 'Creating isolated self-improvement worktree...'; git -C "$HERMES_ROOT" worktree add -b "$BRANCH" "$WORKTREE" "$BASELINE_COMMIT"
EPHEMERAL_CONTEXT="$WORKTREE/.hermes.md"; cp "$CONTEXT_TEMPLATE" "$EPHEMERAL_CONTEXT"
# Prepare/cache baseline evidence before the LLM starts so setup and broad baseline
# testing do not consume reasoning turns or the agent wall-clock budget.
set +e
BASELINE_ARGS=(--production "$HERMES_ROOT" --worktree "$WORKTREE" --baseline "$BASELINE_COMMIT" --python "$HERMES_PY" --state "$STATE" --timeout "$BASELINE_VALIDATION_TIMEOUT_SECONDS" --cache-seconds "$BASELINE_VALIDATION_CACHE_SECONDS")
[[ "${RUN_FULL_TESTS:-true}" == true ]] || BASELINE_ARGS+=(--skip-tests)
BASELINE_JSON="$("$HERMES_PY" "$BASELINE_VALIDATOR" "${BASELINE_ARGS[@]}" 2>>"$LOG")"
BASELINE_VALIDATOR_EXIT=$?
set -e
if [[ "$BASELINE_VALIDATOR_EXIT" -ne 0 || -z "$BASELINE_JSON" ]]; then BASELINE_JSON='{"cache":"error","baseline_health":"ATTENTION","tests":{"exit":null,"seconds":0},"dev_sync":{"exit":null,"seconds":0}}'; fi
BASELINE_SUMMARY="$(printf '%s' "$BASELINE_JSON" | "$HERMES_PY" -c 'import json,sys; d=json.load(sys.stdin); t=d.get("tests",{}); u=d.get("dev_sync",{}); f=d.get("test_failure_summary",{}); print("cache=%s health=%s env_ready=%s baseline_tests_exit=%s baseline_tests_seconds=%s failed_tests=%s failed_files=%s dev_sync_exit=%s dev_sync_mode=%s dependency_profile=%s uv_source=%s uv=%s generated_lock_removed=%s test_command=%s"%(d.get("cache"),d.get("baseline_health"),d.get("environment_ready"),t.get("exit"),t.get("seconds"),f.get("failed_test_count",0),len(f.get("failure_files",{})),u.get("exit"),u.get("mode"),d.get("dependency_profile") or u.get("profile"),u.get("source"),u.get("executable"),u.get("removed_generated_lock"),d.get("test_command")))' 2>/dev/null || echo 'baseline validation summary unavailable')"
BASELINE_EVIDENCE="$(printf '%s' "$BASELINE_JSON" | "$HERMES_PY" -c 'import json,sys; print(json.load(sys.stdin).get("cache_file") or "")' 2>/dev/null || true)"
echo >> "$REPORT"; echo '## Experiment Environment' >> "$REPORT"; echo >> "$REPORT"; echo "- Production repository: \`$HERMES_ROOT\`" >> "$REPORT"; echo "- Baseline commit: \`$BASELINE_COMMIT\`" >> "$REPORT"; echo "- Experiment branch: \`$BRANCH\`" >> "$REPORT"; echo "- Experiment worktree: \`$WORKTREE\`" >> "$REPORT"; echo "- Ephemeral context chars: \`$(wc -c < "$EPHEMERAL_CONTEXT" | tr -d ' ')\`" >> "$REPORT"
echo >> "$REPORT"; echo '## Controller Baseline Validation' >> "$REPORT"; echo >> "$REPORT"; echo "- Summary: \`$BASELINE_SUMMARY\`" >> "$REPORT"; echo "- Cache TTL: \`${BASELINE_VALIDATION_CACHE_SECONDS}s\`" >> "$REPORT"
BASELINE_ENV_READY="$(printf '%s' "$BASELINE_JSON" | "$HERMES_PY" -c 'import json,sys; print("yes" if json.load(sys.stdin).get("environment_ready", False) else "no")' 2>/dev/null || echo no)"
BASELINE_HEALTH="$(printf '%s' "$BASELINE_JSON" | "$HERMES_PY" -c 'import json,sys; print(json.load(sys.stdin).get("baseline_health", "ATTENTION"))' 2>/dev/null || echo ATTENTION)"
if [[ "$BASELINE_HEALTH" == KNOWN_RED && "${AUTO_PROMOTE_MODE:-off}" == off ]]; then RED_BASELINE_RESEARCH="yes"; fi
DAILY_TASK="# Hermes Self-Improvement Daily Run

Canonical master policy: $PROMPT

The master policy remains authoritative, but DO NOT dump or reread it wholesale during this run.
Critical safety, freshness, evidence, and execution rules are already in the worktree .hermes.md.
Consult only the specific policy section you need, using grep/sed/headings rather than catting the entire file.

# TODAY'S EXECUTION ENVIRONMENT
Production Hermes repository: $HERMES_ROOT
Production baseline commit: $BASELINE_COMMIT
Isolated development worktree: $WORKTREE
Experiment branch: $BRANCH
Wall-clock budget: ${MAX_RUNTIME_SECONDS}s
Turn budget: ${MAX_TURNS}
Controller baseline validation: $BASELINE_SUMMARY
Known-red research mode: $RED_BASELINE_RESEARCH

Perform ALL code modifications inside the experiment worktree. Never modify or deploy to production directly.
Before changing source, read only the relevant root/nested AGENTS.md sections for the files you will touch. Never cat/read the entire root AGENTS.md; use grep/sed/headings to load only applicable sections.

# EXECUTION DISCIPLINE
- Do not inspect this run's own report or log unless diagnosing a controller failure. They contain your own transcript and cause recursive work.
- Do not open previous self-improvement reports/logs during discovery. Only consult one if fresh current-run evidence first identifies a specific issue and the historical report is necessary to compare that exact issue.
- Spend no more than roughly 20% of the run on health/inventory/research. Use fresh current-state checks first.
- Baseline environment preparation and broad baseline tests were already handled by the controller. Do NOT run scripts/run_tests.sh, full pytest, uv sync, or another broad baseline suite before selecting a candidate.
- Before candidate selection, only run a narrow reproduction/smoke check that directly helps choose the candidate. Any pytest command must target a specific test file or node; directory-wide targets such as pytest tests/agent are prohibited. Do not use generic TODO/FIXME scans as a candidate source.
- Do not use the KNOWN_RED failure list as a candidate backlog. Those failures are comparison evidence only. Investigate a baseline-failing file only if fresh independent current-run evidence first identifies that exact issue as the best candidate.
- Do not recursively list the repository or broad test directories (for example ls -R or ls tests/) for discovery. Inspect only paths relevant to fresh evidence.
- By roughly 25% of the run, choose ONE highest-value candidate or explicitly choose NO PRODUCTION CHANGE TODAY.
- Spend the middle of the run implementing and testing that one candidate. Avoid broad inventory once a candidate is selected. Use targeted tests first; the independent candidate gate owns the broad non-integration regression suite.
- Reserve the final roughly 20% for benchmark/security review, a concise final report, and candidate-manifest creation if justified.
- Do not repeatedly list the same directories, reports, logs, or process state. Reuse evidence already collected in this run.
- Prefer a small fresh reproduction or focused benchmark over log archaeology.
- If time is becoming insufficient to test a candidate properly, stop changing code and conclude DEFER / NO PRODUCTION CHANGE TODAY.

Research, inspect, implement, test, benchmark, and report. NO PRODUCTION CHANGE TODAY is valid.

If and only if you have implemented a LOW-RISK candidate that has measurable evidence of improvement and does not require human authorization, create $WORKTREE/.hermes-si-candidate.json with exactly these fields:
{\"decision\":\"CANDIDATE_FOR_PRODUCTION\",\"summary\":\"short description\",\"risk\":\"low\",\"requires_human_authorization\":false,\"measurable_improvement\":true,\"evidence\":\"specific before/after evidence\"}
Do not create that file for research-only, uncertain, medium/high-risk, unverified, or no-change outcomes.
Do not wait for interactive human input."
echo >> "$REPORT"; echo '## Agent Run Discipline' >> "$REPORT"; echo >> "$REPORT"; echo "- Master policy injected wholesale: \`no\`" >> "$REPORT"; echo "- Daily task chars: \`$(printf %s "$DAILY_TASK" | wc -c | tr -d ' ')\`" >> "$REPORT"; echo "- Historical self-improvement reports during discovery: \`default 0; max 1 only after fresh issue-specific evidence\`" >> "$REPORT"
echo >> "$REPORT"; echo '## Autonomous Self-Improvement Agent' >> "$REPORT"; echo >> "$REPORT"
echo "- Known-red research mode: \`$RED_BASELINE_RESEARCH\`" >> "$REPORT"
if [[ "$BASELINE_HEALTH" != PASS ]]; then
  echo >> "$REPORT"; echo '## Baseline Failure Evidence' >> "$REPORT"; echo >> "$REPORT"; echo '```text' >> "$REPORT"
  printf '%s' "$BASELINE_JSON" | "$HERMES_PY" -c 'import json,sys; d=json.load(sys.stdin);
for name in ("dev_sync","cli_version","cli_help","tests"):
 x=d.get(name,{}) or {}; print(f"[{name}] exit={x.get(chr(101)+chr(120)+chr(105)+chr(116))} seconds={x.get(chr(115)+chr(101)+chr(99)+chr(111)+chr(110)+chr(100)+chr(115))}"); out=(x.get("output") or "").strip(); print(out[-4000:] if out else "(no output)"); print()' >> "$REPORT" 2>/dev/null || true
  echo '```' >> "$REPORT"
fi
if [[ "$BASELINE_ENV_READY" != yes ]]; then
  echo 'Controller refused to start the autonomous agent because the experiment environment was not prepared successfully.' >> "$REPORT"
  AGENT_EXIT=78
elif [[ "$BASELINE_HEALTH" != PASS && ! ( "$BASELINE_HEALTH" == KNOWN_RED && "${AUTO_PROMOTE_MODE:-off}" == off ) ]]; then
  echo 'Controller refused to start the autonomous agent because the unchanged Hermes baseline did not pass controller validation.' >> "$REPORT"
  AGENT_EXIT=79
else
  if [[ "$BASELINE_HEALTH" == KNOWN_RED ]]; then
    RED_BASELINE_RESEARCH="yes"
    echo 'Controller classified the exact baseline as KNOWN_RED. Research is allowed only because AUTO_PROMOTE_MODE=off; production promotion remains forbidden.' >> "$REPORT"
    DAILY_TASK="$DAILY_TASK

# KNOWN-RED BASELINE
The unchanged baseline has reproducible/parseable test failures. Treat them as baseline debt, not as evidence your candidate caused them and not as a candidate backlog. Do not investigate or rerun a baseline-failing test merely because it appears in the failure summary; fresh independent current-run evidence must first identify that exact issue as the best candidate. Production promotion is forbidden; the independent gate will compare the candidate suite against the saved baseline."
  fi

  # Convert one item of known-red debt into bounded fresh current-run evidence
  # before the LLM starts. This is controller-owned and rotates across a strict
  # allowlist of low-risk/core test files.
  FRESH_PROBE_JSON='{"status":"SKIPPED","reason":"baseline is not KNOWN_RED"}'
  if [[ "$BASELINE_HEALTH" == KNOWN_RED ]]; then
    TEST_PY_FOR_PROBE="$(printf '%s' "$BASELINE_JSON" | "$HERMES_PY" -c 'import json,sys; print(json.load(sys.stdin).get("test_python") or "")' 2>/dev/null || true)"
    [[ -x "$TEST_PY_FOR_PROBE" ]] || TEST_PY_FOR_PROBE="$WORKTREE/.venv/bin/python"
    [[ -x "$TEST_PY_FOR_PROBE" ]] || TEST_PY_FOR_PROBE="$HERMES_PY"
    set +e
    FRESH_PROBE_JSON="$("$HERMES_PY" "$FRESH_PROBE_TOOL" --baseline-json "$BASELINE_JSON" --worktree "$WORKTREE" --state "$STATE" --python "$TEST_PY_FOR_PROBE" --timeout "$FRESH_PROBE_TIMEOUT_SECONDS" --max-attempts "$FRESH_PROBE_MAX_ATTEMPTS" 2>>"$LOG")"
    FRESH_PROBE_EXIT=$?
    set -e
    if [[ "$FRESH_PROBE_EXIT" -ne 0 || -z "$FRESH_PROBE_JSON" ]]; then
      FRESH_PROBE_JSON='{"status":"ERROR","reason":"fresh probe controller failed"}'
    fi
    echo >> "$REPORT"; echo '## Controller Fresh Candidate Probe' >> "$REPORT"; echo >> "$REPORT"
    echo "- Total probe timeout: \`${FRESH_PROBE_TIMEOUT_SECONDS}s\`" >> "$REPORT"
    echo "- Max attempts: \`${FRESH_PROBE_MAX_ATTEMPTS}\`" >> "$REPORT"
    echo "- Result: \`$FRESH_PROBE_JSON\`" >> "$REPORT"
  fi

  cd "$STATE"

  # The report retains the complete bounded probe history, but the classifier sees
  # only the selected top-level candidate. This prevents earlier dependency-only
  # skips from contaminating root-cause classification of the current failure.
  TRIAGE_EVIDENCE_JSON="$(printf '%s' "$FRESH_PROBE_JSON" | "$HERMES_PY" -c 'import json,sys; d=json.load(sys.stdin); status=d.get("status"); keys=("status","target","baseline_failure_count","exit","seconds","output","rotation_index","rotation_total","context_packet","probe_budget_seconds","probe_elapsed_seconds"); out={k:d[k] for k in keys if k in d}; out=d if status=="NO_ACTIONABLE_FAILURE" else out; print(json.dumps(out,sort_keys=True,separators=(",",":")))')"

  # Stage 1: direct local structured inference. No Hermes agent and no tools exist
  # in this stage; the controller owns all evidence gathering and handoff persistence.
  TRIAGE_PLAN="$WORKTREE/.hermes-si-plan.json"
  TRIAGE_TRANSCRIPT="$STATE/triage-$TIMESTAMP.out"
  TRIAGE_PROMPT_FILE="$STATE/triage-$TIMESTAMP.prompt"
  rm -f "$TRIAGE_PLAN" "$TRIAGE_TRANSCRIPT" "$TRIAGE_PROMPT_FILE"
  TRIAGE_TASK="# Hermes Self-Improvement Candidate Triage

You are a read-only software triage classifier. You have NO tools and cannot inspect anything beyond the evidence below.

Baseline commit: $BASELINE_COMMIT
Worktree: $WORKTREE
Baseline validation: $BASELINE_SUMMARY
Known-red research mode: $RED_BASELINE_RESEARCH
Controller selected candidate evidence: $TRIAGE_EVIDENCE_JSON

Decide exactly one of IMPLEMENT or NO_CHANGE.

Rules:
- The controller fresh candidate probe is the ONLY baseline-failure evidence that is fresh today.
- If probe status is NO_ACTIONABLE_FAILURE, choose NO_CHANGE; the controller already exhausted its bounded safe probe allowance.
- Use the supplied context_packet first. It may contain the exact failing test, assertion-derived evidence_terms, and focused matching production source windows.
- Evaluate only this selected candidate evidence; earlier skipped probe attempts are intentionally excluded from classifier input.
- IMPLEMENT only when the fresh failure plus supplied production source support a specific LOW-RISK source change that Gemma can verify with the exact failing test/node.
- Do not propose changes to tests, dependencies/lockfiles, credentials, authentication/security policy, host/service configuration, gateway services, trading, payments, installers, or updaters.
- For IMPLEMENT, files must contain only the production source path(s) actually implicated by the packet, and targeted_tests must include the exact fresh failure node when available.
- If root cause is ambiguous, a necessary source definition is missing, or the safe fix cannot be justified from this packet alone, choose NO_CHANGE.
- For NO_CHANGE, files and targeted_tests must be empty arrays.
- risk must be low.

Return only the required structured JSON decision."
  printf '%s' "$TRIAGE_TASK" > "$TRIAGE_PROMPT_FILE"

  echo >> "$REPORT"; echo '## Discovery/Triage Classifier' >> "$REPORT"; echo >> "$REPORT"
  echo "- Model: \`$DISCOVERY_MODEL\`" >> "$REPORT"
  echo "- Budget: \`${DISCOVERY_RUNTIME_SECONDS}s\`" >> "$REPORT"
  echo '- Execution: `direct local Ollama /api/chat; JSON schema; no tools`' >> "$REPORT"
  echo '- Reasoning: `disabled (think=false)`' >> "$REPORT"
  set +e
  "$HERMES_PY" "$DEADLINE_RUNNER" "$DISCOVERY_RUNTIME_SECONDS" -- "$HERMES_PY" "$TRIAGE_INFER_TOOL" --model "$DISCOVERY_MODEL" --prompt-file "$TRIAGE_PROMPT_FILE" --endpoint "$TRIAGE_OLLAMA_URL" --timeout "$DISCOVERY_RUNTIME_SECONDS" > "$TRIAGE_TRANSCRIPT" 2>> "$LOG" &
  WATCHDOG_PID=$!
  wait "$WATCHDOG_PID"; TRIAGE_EXIT=$?; WATCHDOG_PID=""
  set -e
  [[ -f "$TRIAGE_TRANSCRIPT" ]] && { echo '```json' >> "$REPORT"; cat "$TRIAGE_TRANSCRIPT" >> "$REPORT"; echo '```' >> "$REPORT"; }
  echo >> "$REPORT"; echo "- Triage exit: \`$TRIAGE_EXIT\`" >> "$REPORT"

  if [[ "$TRIAGE_EXIT" -ne 0 ]]; then
    echo 'Direct structured triage did not complete successfully; implementation model was not started.' >> "$REPORT"
    AGENT_EXIT="$TRIAGE_EXIT"
  else
    AGENT_EXIT=0
    set +e
      MATERIALIZED_JSON="$("$HERMES_PY" "$TRIAGE_OUTPUT_TOOL" --transcript "$TRIAGE_TRANSCRIPT" --plan "$TRIAGE_PLAN" --worktree "$WORKTREE" 2>>"$LOG")"
    MATERIALIZE_EXIT=$?
    set -e
    if [[ "$MATERIALIZE_EXIT" -ne 0 || ! -f "$TRIAGE_PLAN" ]]; then
      echo 'Direct triage returned no controller-materializable structured decision; implementation model was not started.' >> "$REPORT"
      [[ -n "${MATERIALIZED_JSON:-}" ]] && echo "- Triage materializer: \`$MATERIALIZED_JSON\`" >> "$REPORT"
      AGENT_EXIT=76
    else
      TRIAGE_PLAN_SOURCE="$(printf '%s' "$MATERIALIZED_JSON" | "$HERMES_PY" -c 'import json,sys; print(json.load(sys.stdin).get("source","transcript"))' 2>/dev/null || echo transcript)"
      set +e
      PLAN_JSON="$("$HERMES_PY" "$TRIAGE_PLAN_TOOL" --plan "$TRIAGE_PLAN" --worktree "$WORKTREE" --evidence-json "$FRESH_PROBE_JSON" 2>>"$LOG")"
      PLAN_EXIT=$?
      set -e
      rm -f "$TRIAGE_PLAN"
        if [[ "$PLAN_EXIT" -ne 0 || -z "$PLAN_JSON" ]]; then
          echo 'Triage plan failed controller validation; implementation model was not started.' >> "$REPORT"
          AGENT_EXIT=76
        else
          PLAN_DECISION="$(printf '%s' "$PLAN_JSON" | "$HERMES_PY" -c 'import json,sys; print(json.load(sys.stdin)["decision"])')"
          echo "- Plan source: \`$TRIAGE_PLAN_SOURCE\`" >> "$REPORT"
          echo "- Validated plan: \`$PLAN_JSON\`" >> "$REPORT"
        if [[ "$PLAN_DECISION" == NO_CHANGE ]]; then
          echo 'Triage selected NO_CHANGE; implementation model was intentionally skipped.' >> "$REPORT"
          AGENT_EXIT=0
        else
          cd "$WORKTREE"
          UV_FOR_AGENT="$(printf '%s' "$BASELINE_JSON" | "$HERMES_PY" -c 'import json,sys; print(json.load(sys.stdin).get("dev_sync",{}).get("executable") or "")' 2>/dev/null || true)"
          GUARD_ARGS=(enter --worktree "$WORKTREE" --state "$STATE" --token "$TIMESTAMP")
          [[ -n "$UV_FOR_AGENT" ]] && GUARD_ARGS+=(--uv "$UV_FOR_AGENT")
          AGENT_GUARD_MANIFEST="$("$HERMES_PY" "$AGENT_PHASE_GUARD" "${GUARD_ARGS[@]}")"
          AGENT_GUARD_BIN="$(dirname "$AGENT_GUARD_MANIFEST")/bin"
          CHAT_HELP="$("$HERMES_PY" -m hermes_cli.main chat --help 2>&1 || true)"
          IMPLEMENTATION_TASK="# Hermes Self-Improvement Implementation Stage

Canonical master policy: $PROMPT
Critical safety/execution rules are already in the worktree .hermes.md.

Discovery is COMPLETE. Do not rediscover the repository and do not select a different candidate unless the handoff is demonstrably invalid. Never modify or deploy to the production repository directly.

Controller-validated candidate handoff:
$PLAN_JSON

Worktree: $WORKTREE
Baseline commit: $BASELINE_COMMIT
Known-red research mode: $RED_BASELINE_RESEARCH
Implementation budget: ${IMPLEMENTATION_RUNTIME_SECONDS}s / ${IMPLEMENTATION_TURNS} turns

Your job:
1. Read only the applicable AGENTS.md sections and the handoff-listed files plus direct dependencies necessary to understand them.
2. Confirm the handoff evidence quickly. If it is wrong or unsafe, make no change and conclude DEFER/NO PRODUCTION CHANGE TODAY.
3. Otherwise implement the smallest low-risk change that addresses the stated problem.
4. Run the handoff-listed specific test file/node first. You may add at most one directly related specific test file/node; no directory-wide pytest, no scripts/run_tests.sh, no uv sync.
5. Gather concise before/after evidence and do a focused security/regression review.
6. Do not perform broad discovery, TODO/FIXME scans, repository-wide grep, ls -R, broad test listing, or revisit the known-red failure list.
7. If and only if the candidate is low-risk, tested, and measurably improved, create $WORKTREE/.hermes-si-candidate.json with exactly:
{\"decision\":\"CANDIDATE_FOR_PRODUCTION\",\"summary\":\"short description\",\"risk\":\"low\",\"requires_human_authorization\":false,\"measurable_improvement\":true,\"evidence\":\"specific before/after evidence\"}
Otherwise create no candidate manifest."
          echo >> "$REPORT"; echo '## Implementation/Review Agent' >> "$REPORT"; echo >> "$REPORT"
          echo "- Model: \`$IMPLEMENTATION_MODEL\`" >> "$REPORT"; echo "- Budget: \`${IMPLEMENTATION_RUNTIME_SECONDS}s / ${IMPLEMENTATION_TURNS} turns\`" >> "$REPORT"; echo "- Reasoning: \`$IMPLEMENTATION_REASONING\`" >> "$REPORT"
          IMPL_ARGS=(chat --toolsets web,terminal,skills)
          IMPL_MODEL_OVERRIDE=env
          if echo "$CHAT_HELP" | grep -q -- '--model'; then IMPL_ARGS+=(--model "$IMPLEMENTATION_MODEL"); IMPL_MODEL_OVERRIDE=flag+env; fi
          if echo "$CHAT_HELP" | grep -q -- '--reasoning'; then IMPL_ARGS+=(--reasoning "$IMPLEMENTATION_REASONING"); fi
          if echo "$CHAT_HELP" | grep -q -- '--max-turns'; then IMPL_ARGS+=(--max-turns "$IMPLEMENTATION_TURNS"); fi
          if echo "$CHAT_HELP" | grep -q -- '--source'; then IMPL_ARGS+=(--source self-improvement); fi
          IMPL_ARGS+=(-q "$IMPLEMENTATION_TASK")
          echo "- Model override: \`$IMPL_MODEL_OVERRIDE\`" >> "$REPORT"
          set +e
          HERMES_INFERENCE_MODEL="$IMPLEMENTATION_MODEL" PATH="$AGENT_GUARD_BIN:$PATH" "$HERMES_PY" "$DEADLINE_RUNNER" "$IMPLEMENTATION_RUNTIME_SECONDS" -- "$HERMES_PY" -m hermes_cli.main "${IMPL_ARGS[@]}" >> "$REPORT" 2>> "$LOG" &
          WATCHDOG_PID=$!
          wait "$WATCHDOG_PID"; AGENT_EXIT=$?; WATCHDOG_PID=""
          set -e
        fi
      fi
    fi
  fi
  rm -f "$TRIAGE_PLAN" 2>/dev/null || true
  rm -f "$TRIAGE_TRANSCRIPT" "$TRIAGE_PROMPT_FILE" 2>/dev/null || true
  TRIAGE_TRANSCRIPT=""; TRIAGE_PROMPT_FILE=""
  if [[ -n "${AGENT_GUARD_MANIFEST:-}" && -f "$AGENT_GUARD_MANIFEST" ]]; then
    "$HERMES_PY" "$AGENT_PHASE_GUARD" exit --manifest "$AGENT_GUARD_MANIFEST" >> "$LOG" 2>&1 || true
    AGENT_GUARD_MANIFEST=""
  fi
fi
rm -f "$EPHEMERAL_CONTEXT"; EPHEMERAL_CONTEXT=''
echo >> "$REPORT"; echo '## Agent Exit Status' >> "$REPORT"; echo >> "$REPORT"; echo "Exit code: $AGENT_EXIT" >> "$REPORT"; [[ "$AGENT_EXIT" -eq 124 ]] && echo "A stage wall-clock watchdog terminated the active agent. Discovery budget=${DISCOVERY_RUNTIME_SECONDS}s; implementation budget=${IMPLEMENTATION_RUNTIME_SECONDS}s." >> "$REPORT"
if [[ "$AGENT_EXIT" -eq 0 ]]; then GATE_ARGS=(--production "$HERMES_ROOT" --worktree "$WORKTREE" --baseline "$BASELINE_COMMIT" --report "$REPORT" --policy "$POLICY" --python "$HERMES_PY" --base "$BASE"); [[ -n "$BASELINE_EVIDENCE" ]] && GATE_ARGS+=(--baseline-evidence "$BASELINE_EVIDENCE"); "$HERMES_PY" "$CANDIDATE_GATE" "${GATE_ARGS[@]}" >> "$LOG" 2>&1 || true; elif [[ "$AGENT_EXIT" -eq 78 ]]; then echo >> "$REPORT"; echo '## Candidate Gate' >> "$REPORT"; echo >> "$REPORT"; echo '- Decision: `SKIPPED_BASELINE_ENVIRONMENT`' >> "$REPORT"; echo '- Production modified: `no`' >> "$REPORT"; rm -f "$WORKTREE/.hermes-si-candidate.json"; elif [[ "$AGENT_EXIT" -eq 79 ]]; then echo >> "$REPORT"; echo '## Candidate Gate' >> "$REPORT"; echo >> "$REPORT"; echo '- Decision: `SKIPPED_BASELINE_FAILURE`' >> "$REPORT"; echo '- Production modified: `no`' >> "$REPORT"; rm -f "$WORKTREE/.hermes-si-candidate.json"; elif [[ "$AGENT_EXIT" -eq 76 ]]; then echo >> "$REPORT"; echo '## Candidate Gate' >> "$REPORT"; echo >> "$REPORT"; echo '- Decision: `SKIPPED_TRIAGE_FAILURE`' >> "$REPORT"; echo '- Production modified: `no`' >> "$REPORT"; rm -f "$WORKTREE/.hermes-si-candidate.json"; else echo >> "$REPORT"; echo '## Candidate Gate' >> "$REPORT"; echo >> "$REPORT"; echo '- Decision: `SKIPPED_AGENT_FAILURE`' >> "$REPORT"; echo '- Production modified: `no`' >> "$REPORT"; rm -f "$WORKTREE/.hermes-si-candidate.json"; fi
echo >> "$REPORT"; echo '## Experiment Git Status' >> "$REPORT"; echo '```' >> "$REPORT"; git -C "$WORKTREE" status --short >> "$REPORT" 2>&1 || true; echo >> "$REPORT"; git -C "$WORKTREE" log --oneline --decorate -10 >> "$REPORT" 2>&1 || true; echo '```' >> "$REPORT"
echo >> "$REPORT"; echo '## Experiment Diff Summary' >> "$REPORT"; echo '```' >> "$REPORT"; git -C "$WORKTREE" diff --stat "$BASELINE_COMMIT" >> "$REPORT" 2>&1 || true; echo '```' >> "$REPORT"
echo >> "$REPORT"; echo '## Completion' >> "$REPORT"; echo >> "$REPORT"; echo "Completed: $(date)" >> "$REPORT"; echo "Agent exit code: $AGENT_EXIT" >> "$REPORT"; echo >> "$REPORT"; echo '## Post-Run Processes' >> "$REPORT"; echo '```' >> "$REPORT"; ps aux | grep -Ei '[h]ermes|[o]llama' >> "$REPORT" 2>&1 || true; echo '```' >> "$REPORT"
[[ -f "$CLEANUP_TOOL" ]] && "$HERMES_PY" "$CLEANUP_TOOL" --production "$HERMES_ROOT" --worktrees "$WORKTREE_PARENT" --keep "${RETAIN_NO_CHANGE_WORKTREES:-3}" >> "$LOG" 2>&1 || true
printf '%s\n' '================================================' "Completed: $(date)" "Report: $REPORT" "Log: $LOG" '================================================'
exit "$AGENT_EXIT"
