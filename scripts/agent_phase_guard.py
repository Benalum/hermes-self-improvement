#!/usr/bin/env python3
"""Temporarily block controller-owned broad setup/tests during the LLM phase."""
from __future__ import annotations
import argparse, json, os, shutil, stat
from pathlib import Path

BLOCKED = ["scripts/run_tests.sh"]
STUB = """#!/bin/sh
echo 'BLOCKED_BY_SELF_IMPROVEMENT_CONTROLLER: broad baseline/regression tests are controller-owned during the agent phase. Select a candidate and use targeted tests; the controller restores this script before the independent candidate gate.' >&2
exit 86
"""

def _write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    os.chmod(path, 0o755)

def enter(worktree: Path, state: Path, token: str, uv_path: str|None=None) -> Path:
    root = state / "agent-guards" / token
    root.mkdir(parents=True, exist_ok=False)
    entries=[]
    for rel in BLOCKED:
        src=worktree/rel
        if not src.exists():
            continue
        backup=root/rel
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, backup)
        mode=stat.S_IMODE(src.stat().st_mode)
        src.write_text(STUB)
        os.chmod(src, mode | stat.S_IXUSR)
        entries.append({"rel":rel,"mode":mode})

    # Implementation-stage PATH shims: broad suites/setup are blocked, but a
    # specific candidate test file/node remains allowed.
    bindir=root/'bin'; bindir.mkdir()
    real_pytest = worktree/'.venv/bin/pytest'
    pytest_exec = str(real_pytest) if real_pytest.exists() else (shutil.which('pytest') or '')
    pytest_sh=f'''#!/bin/sh
set -eu
TARGETED=0
for ARG in "$@"; do
  case "$ARG" in
    *.py|*.py::*) TARGETED=1;;
  esac
done
if [ "$TARGETED" -ne 1 ]; then
  echo 'BLOCKED_BY_SELF_IMPROVEMENT_CONTROLLER: broad pytest is controller-owned during the agent phase. Target one or more specific test files/nodes (for example tests/test_x.py or tests/test_x.py::test_name); directory targets and -k-only scans are blocked.' >&2
  exit 86
fi
REAL={json.dumps(pytest_exec)}
if [ -z "$REAL" ]; then
  echo 'Targeted pytest requested but no pytest executable is available in the prepared worktree.' >&2
  exit 127
fi
exec "$REAL" "$@"
'''
    _write(bindir/'pytest', pytest_sh)

    real_uv = uv_path or shutil.which('uv') or ''
    uv_sh=f'''#!/bin/sh
set -eu
REAL={json.dumps(real_uv)}
if [ "${{1:-}}" = sync ]; then
  echo 'BLOCKED_BY_SELF_IMPROVEMENT_CONTROLLER: uv sync is controller-owned during the agent phase.' >&2
  exit 86
fi
if [ "${{1:-}}" = run ] && [ "${{2:-}}" = pytest ]; then
  TARGETED=0
  shift 2
  for ARG in "$@"; do
    case "$ARG" in *.py|*.py::*) TARGETED=1;; esac
  done
  if [ "$TARGETED" -ne 1 ]; then
    echo 'BLOCKED_BY_SELF_IMPROVEMENT_CONTROLLER: broad uv run pytest is controller-owned during the agent phase. Target one or more specific test files/nodes; directory targets and -k-only scans are blocked.' >&2
    exit 86
  fi
fi
if [ -z "$REAL" ]; then
  echo 'uv is unavailable to the agent phase.' >&2
  exit 127
fi
exec "$REAL" "$@"
'''
    _write(bindir/'uv', uv_sh)

    # Triage gets a stricter PATH than implementation. It is read-only and
    # should select a candidate rather than burn budget executing tests or
    # harvesting repository-wide TODOs.
    triage_bin=root/'triage-bin'; triage_bin.mkdir()
    _write(triage_bin/'pytest', """#!/bin/sh
echo 'BLOCKED_BY_SELF_IMPROVEMENT_CONTROLLER: pytest is disabled during read-only triage. Select a candidate from fresh code/current-state evidence and leave testing to implementation.' >&2
exit 86
""")
    triage_uv=f'''#!/bin/sh
set -eu
REAL={json.dumps(real_uv)}
if [ "${{1:-}}" = sync ] || {{ [ "${{1:-}}" = run ] && [ "${{2:-}}" = pytest ]; }}; then
  echo 'BLOCKED_BY_SELF_IMPROVEMENT_CONTROLLER: uv sync/pytest is disabled during read-only triage.' >&2
  exit 86
fi
if [ -z "$REAL" ]; then exit 127; fi
exec "$REAL" "$@"
'''
    _write(triage_bin/'uv', triage_uv)

    real_ls=shutil.which('ls') or '/bin/ls'
    ls_sh=f'''#!/bin/sh
set -eu
for ARG in "$@"; do
  case "$ARG" in
    -R|--recursive|tests|tests/) echo 'BLOCKED_BY_SELF_IMPROVEMENT_CONTROLLER: recursive or broad tests/ listing is disabled during triage.' >&2; exit 86;;
  esac
done
exec {json.dumps(real_ls)} "$@"
'''
    _write(triage_bin/'ls', ls_sh)

    real_grep=shutil.which('grep') or '/usr/bin/grep'
    grep_sh=f'''#!/bin/sh
set -eu
for ARG in "$@"; do
  case "$ARG" in
    *TODO*|*FIXME*) echo 'BLOCKED_BY_SELF_IMPROVEMENT_CONTROLLER: TODO/FIXME harvesting is disabled during triage.' >&2; exit 86;;
  esac
done
exec {json.dumps(real_grep)} "$@"
'''
    _write(triage_bin/'grep', grep_sh)

    real_find=shutil.which('find') or '/usr/bin/find'
    find_sh=f'''#!/bin/sh
set -eu
for ARG in "$@"; do
  case "$ARG" in tests|tests/) echo 'BLOCKED_BY_SELF_IMPROVEMENT_CONTROLLER: find over tests/ is disabled during triage.' >&2; exit 86;; esac
done
exec {json.dumps(real_find)} "$@"
'''
    _write(triage_bin/'find', find_sh)

    real_git=shutil.which('git') or '/usr/bin/git'
    git_sh=f'''#!/bin/sh
set -eu
CMD=""
SKIP=0
for ARG in "$@"; do
  if [ "$SKIP" -eq 1 ]; then SKIP=0; continue; fi
  case "$ARG" in
    -C|--git-dir|--work-tree) SKIP=1;;
    -*) ;;
    *) CMD="$ARG"; break;;
  esac
done
case "$CMD" in
  status|log|show|diff) echo 'BLOCKED_BY_SELF_IMPROVEMENT_CONTROLLER: generic git status/history/diff discovery is disabled during triage. Start from the controller fresh candidate probe; narrow git ls-files lookups remain allowed.' >&2; exit 86;;
esac
exec {json.dumps(real_git)} "$@"
'''
    _write(triage_bin/'git', git_sh)

    manifest=root/'manifest.json'
    manifest.write_text(json.dumps({"version":5,"worktree":str(worktree),"entries":entries,"bin":str(bindir),"triage_bin":str(triage_bin)},indent=2)+"\n")
    return manifest

def leave(manifest: Path) -> None:
    if not manifest.exists():
        return
    data=json.loads(manifest.read_text())
    worktree=Path(data["worktree"])
    root=manifest.parent
    for item in data.get("entries",[]):
        rel=item["rel"]
        backup=root/rel
        dst=worktree/rel
        if backup.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup,dst)
            os.chmod(dst,int(item["mode"]))
    shutil.rmtree(root,ignore_errors=True)

def main():
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest='cmd',required=True)
    a=sub.add_parser('enter'); a.add_argument('--worktree',required=True); a.add_argument('--state',required=True); a.add_argument('--token',required=True); a.add_argument('--uv')
    b=sub.add_parser('exit'); b.add_argument('--manifest',required=True)
    ns=ap.parse_args()
    if ns.cmd=='enter':
        print(enter(Path(ns.worktree).resolve(),Path(ns.state).resolve(),ns.token,ns.uv))
    else:
        leave(Path(ns.manifest).resolve())
    return 0
if __name__=='__main__': raise SystemExit(main())
