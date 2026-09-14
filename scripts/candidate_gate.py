#!/usr/bin/env python3
"""Conservative validation/promotion gate for Hermes self-improvement candidates."""
from __future__ import annotations
import argparse, json, os, re, shutil, statistics, subprocess, time
from pathlib import Path

BLOCKED_PATH_RE=re.compile(r"(^|/)(\.github/workflows|\.git)(/|$)",re.I)
SENSITIVE_COMPONENT_RE=re.compile(r"(auth|credential|secret|ssh|firewall|security|payment|trading|broker|wallet|launchd|systemd|installer|updater)",re.I)
BLOCKED_BASENAMES={"pyproject.toml","uv.lock","requirements.txt","requirements-dev.txt","package-lock.json","pnpm-lock.yaml","yarn.lock","Dockerfile","conftest.py","pytest.ini","tox.ini"}
SAFE_SKILLS_PREFIXES=("skills/","docs/","website/docs/")
MANIFEST_NAME=".hermes-si-candidate.json"

def run(cmd,cwd=None,timeout=None,env=None,check=False):
    cp=subprocess.run(cmd,cwd=cwd,timeout=timeout,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    if check and cp.returncode!=0: raise RuntimeError(f"command failed ({cp.returncode}): {' '.join(map(str,cmd))}\n{cp.stdout}")
    return cp

def git(repo,*args,**kw): return run(["git","-C",str(repo),*args],**kw)


def parse_test_failure_summary(output):
    output = output or ""
    files = {}
    for m in re.finditer(r"^\s+(tests/\S+?\.py)\s+\((\d+) tests? failed\)\s*$", output, re.M):
        files[m.group(1)] = int(m.group(2))
    no_run = []
    marker = re.search(r"^===\s+\d+ files where no tests ran .*?===\s*$", output, re.M)
    if marker:
        for line in output[marker.end():].splitlines():
            m = re.match(r"^\s+(tests/\S+?\.py)\s*$", line)
            if m: no_run.append(m.group(1))
            elif line.strip().startswith('==='): break
    return {"failure_files": dict(sorted(files.items())), "no_run_files": sorted(set(no_run)), "failed_test_count": sum(files.values())}


def load_baseline_evidence(path):
    if not path: return None
    try: return json.loads(Path(path).read_text())
    except Exception: return None


def compare_red_baseline(base_summary, cand_summary):
    reasons=[]
    bfiles=base_summary.get('failure_files') or {}; cfiles=cand_summary.get('failure_files') or {}
    if not bfiles:
        return ['known-red baseline has no parseable failure-file fingerprint']
    new_files=sorted(set(cfiles)-set(bfiles))
    if new_files: reasons.append('candidate introduces new failing test files: '+', '.join(new_files[:12]))
    worse=[]
    for f,n in cfiles.items():
        if f in bfiles and n>bfiles[f]: worse.append(f'{f} ({bfiles[f]} -> {n})')
    if worse: reasons.append('candidate increases failures in: '+', '.join(worse[:12]))
    bnr=set(base_summary.get('no_run_files') or []); cnr=set(cand_summary.get('no_run_files') or [])
    new_no_run=sorted(cnr-bnr)
    if new_no_run: reasons.append('candidate introduces files where no tests ran: '+', '.join(new_no_run[:12]))
    if cand_summary.get('failed_test_count',0)>base_summary.get('failed_test_count',0):
        reasons.append(f"candidate total failed-test count increased ({base_summary.get('failed_test_count',0)} -> {cand_summary.get('failed_test_count',0)})")
    return reasons

def load_policy(path):
    out={}
    for raw in Path(path).read_text().splitlines():
        line=raw.strip()
        if not line or line.startswith('#') or '=' not in line: continue
        k,v=line.split('=',1); out[k.strip()]=v.strip().strip('"').strip("'")
    return out

def pbool(p,k,d=False): return p.get(k,str(d)).lower() in {"1","true","yes","on"}
def pint(p,k,d):
    try:return int(p.get(k,d))
    except:return int(d)
def pfloat(p,k,d):
    try:return float(p.get(k,d))
    except:return float(d)

def status_paths(repo,baseline):
    names=set(git(repo,"diff","--no-renames","--name-only",baseline,"--").stdout.splitlines())
    names.update(x for x in git(repo,"ls-files","--others","--exclude-standard").stdout.splitlines() if x and x!=MANIFEST_NAME)
    return sorted(x for x in names if x)

def num_changed_lines(repo,baseline,paths):
    total=0
    for line in git(repo,"diff","--no-renames","--numstat",baseline,"--").stdout.splitlines():
        parts=line.split('\t',2)
        if len(parts)>=2 and parts[0].isdigit() and parts[1].isdigit(): total+=int(parts[0])+int(parts[1])
    tracked=set(git(repo,"diff","--no-renames","--name-only",baseline,"--").stdout.splitlines())
    for rel in paths:
        if rel not in tracked:
            p=Path(repo)/rel
            if p.is_file():
                try: total+=len(p.read_text(errors='ignore').splitlines())
                except OSError: pass
    return total

def baseline_has(repo,baseline,rel): return git(repo,"cat-file","-e",f"{baseline}:{rel}").returncode==0

def read_manifest(worktree):
    p=Path(worktree)/MANIFEST_NAME
    if not p.exists(): return None,None
    try:
        try:return json.loads(p.read_text()),None
        except Exception as e:return None,f"invalid candidate manifest JSON: {e}"
    finally:p.unlink(missing_ok=True)

def manifest_ok(m):
    if not isinstance(m,dict): return False,"candidate manifest missing or invalid"
    if m.get("decision")!="CANDIDATE_FOR_PRODUCTION": return False,"manifest does not request production candidacy"
    if str(m.get("risk","")).lower()!="low": return False,"candidate risk is not low"
    if bool(m.get("requires_human_authorization",True)): return False,"candidate requires human authorization"
    if not bool(m.get("measurable_improvement",False)): return False,"manifest lacks measurable improvement evidence"
    if not str(m.get("evidence","")).strip(): return False,"manifest evidence is empty"
    return True,"ok"

def path_policy(mode,worktree,baseline,paths):
    reasons=[]
    for rel in paths:
        base=Path(rel).name
        if base in BLOCKED_BASENAMES or BLOCKED_PATH_RE.search(rel) or any(SENSITIVE_COMPONENT_RE.search(part) for part in Path(rel).parts): reasons.append(f"blocked/high-risk path: {rel}")
        if rel.startswith("tests/") and baseline_has(worktree,baseline,rel): reasons.append(f"existing test modified (human review required): {rel}")
        p=Path(worktree)/rel
        if p.exists() and p.is_symlink(): reasons.append(f"symlink change not auto-promotable: {rel}")
        if p.exists() and p.is_file():
            try:
                if b"\0" in p.read_bytes()[:8192]: reasons.append(f"binary change not auto-promotable: {rel}")
            except OSError: reasons.append(f"unreadable candidate file: {rel}")
    if mode=="skills_only":
        bad=[p for p in paths if not p.startswith(SAFE_SKILLS_PREFIXES)]
        if bad: reasons.append("skills_only mode forbids: "+", ".join(bad[:8]))
    return reasons

def validate_syntax(worktree,paths,py,timeout):
    failures=[]
    for rel in paths:
        p=Path(worktree)/rel
        if not p.exists() or not p.is_file(): continue
        try:
            if p.suffix=='.py': cp=run([py,'-m','py_compile',str(p)],cwd=worktree,timeout=timeout)
            elif p.suffix in {'.sh','.bash'}: cp=run(['bash','-n',str(p)],cwd=worktree,timeout=timeout)
            elif p.suffix=='.zsh': cp=run(['zsh','-n',str(p)],cwd=worktree,timeout=timeout)
            elif p.suffix=='.json': json.loads(p.read_text()); continue
            else: continue
            if cp.returncode!=0: failures.append(f"syntax {rel}: {cp.stdout[-1200:]}")
        except Exception as e: failures.append(f"syntax {rel}: {e}")
    return failures

def repo_env(repo):
    env=os.environ.copy(); old=env.get('PYTHONPATH',''); env['PYTHONPATH']=str(repo)+(os.pathsep+old if old else ''); return env

def timed(cmd,cwd,timeout,runs=1,env=None):
    vals=[]
    for _ in range(runs):
        t=time.perf_counter(); cp=run(cmd,cwd=cwd,timeout=timeout,env=env); vals.append(time.perf_counter()-t)
        if cp.returncode!=0:return None,cp.stdout
    return statistics.median(vals),''

def append_report(report,lines):
    with Path(report).open('a') as f:
        f.write('\n\n## Candidate Gate\n\n'); [f.write(x.rstrip()+'\n') for x in lines]

def copy_candidate_state(src,dst,paths):
    src,dst=Path(src),Path(dst)
    for rel in paths:
        s,d=src/rel,dst/rel
        if s.exists():
            d.parent.mkdir(parents=True,exist_ok=True)
            if s.is_dir():
                if d.exists(): shutil.rmtree(d)
                shutil.copytree(s,d)
            else: shutil.copy2(s,d)
        else:
            if d.is_dir(): shutil.rmtree(d)
            elif d.exists() or d.is_symlink(): d.unlink()

def deterministic_health(production,py,timeout):
    failures=[]
    for cmd in ([py,'-m','hermes_cli.main','--version'],[py,'-m','hermes_cli.main','--help']):
        try:
            cp=run(cmd,cwd=production,timeout=timeout,env=repo_env(production))
            if cp.returncode!=0: failures.append(f"{' '.join(cmd)} => {cp.returncode}: {cp.stdout[-1000:]}")
        except subprocess.TimeoutExpired: failures.append(f"{' '.join(cmd)} => timed out after {timeout}s")
        except Exception as e: failures.append(f"{' '.join(cmd)} => {e}")
    return failures

def main():
    ap=argparse.ArgumentParser()
    for a in ['production','worktree','baseline','report','policy','python','base']: ap.add_argument('--'+a,required=True)
    ap.add_argument('--baseline-evidence')
    ns=ap.parse_args(); production=Path(ns.production).resolve(); worktree=Path(ns.worktree).resolve(); report=Path(ns.report)
    policy=load_policy(ns.policy); mode=policy.get('AUTO_PROMOTE_MODE','off'); timeout=pint(policy,'VALIDATION_TIMEOUT_SECONDS',1800); health_timeout=pint(policy,'HEALTH_TIMEOUT_SECONDS',180)
    baseline_evidence=load_baseline_evidence(ns.baseline_evidence); baseline_health=(baseline_evidence or {}).get('baseline_health','PASS')
    manifest,manifest_error=read_manifest(worktree); paths=status_paths(worktree,ns.baseline); lines=[f"- Auto-promote mode: `{mode}`",f"- Baseline health: `{baseline_health}`",f"- Changed files: `{len(paths)}`"]
    if not paths:
        lines += ["- Decision: `NO_CHANGE`","- Production modified: `no`"]; append_report(report,lines); print('CANDIDATE_GATE=NO_CHANGE'); return 0
    changed_lines=num_changed_lines(worktree,ns.baseline,paths); lines.append(f"- Changed lines (approx): `{changed_lines}`"); reasons=[]
    if mode not in {'off','skills_only','conservative'}: reasons.append(f"unknown AUTO_PROMOTE_MODE={mode!r}; failing closed")
    if baseline_health=='KNOWN_RED' and mode!='off': reasons.append('known-red baseline is research-only; promotion modes are forbidden')
    if manifest_error: reasons.append(manifest_error)
    if len(paths)>pint(policy,'MAX_CHANGED_FILES',20): reasons.append('too many changed files')
    if changed_lines>pint(policy,'MAX_CHANGED_LINES',800): reasons.append('change exceeds line budget')
    ok,why=manifest_ok(manifest)
    if not ok: reasons.append(why)
    reasons += path_policy(mode,worktree,ns.baseline,paths)
    dc=git(worktree,'diff','--check',ns.baseline,'--')
    if dc.returncode!=0: reasons.append('git diff --check failed: '+dc.stdout[-1000:])
    reasons += validate_syntax(worktree,paths,ns.python,timeout)
    if reasons:
        lines += ["- Decision: `REJECT_OR_REVIEW`","- Production modified: `no`","- Reasons:"]+[f"  - {r}" for r in reasons]; append_report(report,lines); print('CANDIDATE_GATE=REJECT_OR_REVIEW'); return 0

    for cmd in ([ns.python,'-m','hermes_cli.main','--version'],[ns.python,'-m','hermes_cli.main','--help']):
        try:
            cp=run(cmd,cwd=worktree,timeout=health_timeout,env=repo_env(worktree))
            if cp.returncode!=0: reasons.append(f"candidate CLI smoke failed: {' '.join(cmd)}: {cp.stdout[-1000:]}")
        except subprocess.TimeoutExpired: reasons.append(f"candidate CLI smoke timed out after {health_timeout}s: {' '.join(cmd)}")
        except Exception as e: reasons.append(f"candidate CLI smoke error: {e}")
    if pbool(policy,'RUN_FULL_TESTS',True):
        try:
            dev_python=worktree/'.venv/bin/python'
            test_python=str(dev_python) if dev_python.exists() else ns.python
            lines.append(f"- Candidate test Python: `{test_python}`")
            wrapper=worktree/'scripts/run_tests.sh'
            if wrapper.exists():
                test_cmd=['/bin/bash',str(wrapper)]
                lines.append('- Candidate test command: `scripts/run_tests.sh`')
            else:
                test_cmd=[test_python,'-m','pytest','-q','-m','not integration']
                lines.append('- Candidate test command: `pytest fallback (no wrapper present)`')
            cp=run(test_cmd,cwd=worktree,timeout=timeout,env=repo_env(worktree)); lines.append(f"- Candidate tests exit: `{cp.returncode}`")
            if baseline_health=='KNOWN_RED':
                base_summary=(baseline_evidence or {}).get('test_failure_summary') or {}
                cand_summary=parse_test_failure_summary(cp.stdout) if cp.returncode==1 else {"failure_files":{},"no_run_files":[],"failed_test_count":0}
                lines.append(f"- Baseline failed tests (summary): `{base_summary.get('failed_test_count',0)}`")
                lines.append(f"- Candidate failed tests (summary): `{cand_summary.get('failed_test_count',0)}`")
                if cp.returncode not in (0,1): reasons.append(f'candidate wrapper exited unexpectedly: {cp.returncode}')
                else: reasons += compare_red_baseline(base_summary,cand_summary)
            elif cp.returncode!=0:
                reasons.append('candidate CI-parity tests failed')
        except subprocess.TimeoutExpired: lines.append('- Candidate tests exit: `TIMEOUT`'); reasons.append(f'candidate CI-parity tests timed out after {timeout}s')
        except Exception as e: reasons.append(f'candidate test runner error: {e}')
    runs=pint(policy,'STARTUP_BENCH_RUNS',3)
    try:
        base_t,_=timed([ns.python,'-m','hermes_cli.main','--version'],production,health_timeout,runs,repo_env(production)); cand_t,_=timed([ns.python,'-m','hermes_cli.main','--version'],worktree,health_timeout,runs,repo_env(worktree))
    except subprocess.TimeoutExpired: base_t=cand_t=None; reasons.append('startup benchmark timed out')
    except Exception as e: base_t=cand_t=None; reasons.append(f'startup benchmark error: {e}')
    if base_t is None or cand_t is None:
        if not any(r.startswith('startup benchmark') for r in reasons): reasons.append('startup benchmark failed')
    else:
        pct=((cand_t-base_t)/max(base_t,1e-9))*100; lines += [f"- Baseline startup median: `{base_t:.4f}s`",f"- Candidate startup median: `{cand_t:.4f}s`",f"- Startup delta: `{pct:+.1f}%`"]
        if cand_t-base_t>pfloat(policy,'MAX_STARTUP_REGRESSION_ABS_SECONDS',0.25) and pct>pfloat(policy,'MAX_STARTUP_REGRESSION_PCT',25): reasons.append('startup performance regression exceeds policy')
    if reasons:
        lines += ["- Decision: `REJECT_OR_REVIEW`","- Production modified: `no`","- Reasons:"]+[f"  - {r}" for r in reasons]; append_report(report,lines); print('CANDIDATE_GATE=REJECT_OR_REVIEW'); return 0
    if mode=='off':
        if baseline_health=='KNOWN_RED':
            lines += ["- Decision: `VALIDATED_RESEARCH_ONLY_BASELINE_RED`","- Production modified: `no`","- Promotion eligibility: `blocked until baseline is green`"]; append_report(report,lines); print('CANDIDATE_GATE=VALIDATED_RESEARCH_ONLY_BASELINE_RED'); return 0
        lines += ["- Decision: `VALIDATED_AWAITING_ENABLEMENT`","- Production modified: `no`"]; append_report(report,lines); print('CANDIDATE_GATE=VALIDATED_AWAITING_ENABLEMENT'); return 0
    if git(production,'rev-parse','HEAD').stdout.strip()!=ns.baseline:
        lines += ["- Decision: `ABORT_BASELINE_MOVED`","- Production modified: `no`"]; append_report(report,lines); print('CANDIDATE_GATE=ABORT_BASELINE_MOVED'); return 0
    if git(production,'status','--porcelain').stdout.strip():
        lines += ["- Decision: `ABORT_PRODUCTION_DIRTY`","- Production modified: `no`"]; append_report(report,lines); print('CANDIDATE_GATE=ABORT_PRODUCTION_DIRTY'); return 0
    stamp=time.strftime('%Y-%m-%d_%H-%M-%S'); promo_parent=Path(ns.base)/'experiments'/'promotion'; promo_parent.mkdir(parents=True,exist_ok=True); promo=promo_parent/stamp; branch=f'auto-promote/{stamp}'; backup=f'backup/auto-promote-{stamp}'
    try:
        git(production,'worktree','add','-b',branch,str(promo),ns.baseline,check=True); copy_candidate_state(worktree,promo,paths); git(promo,'add','-A',check=True); git(promo,'commit','-m',f'self-improvement: auto-promote {stamp}',check=True); commit=git(promo,'rev-parse','HEAD',check=True).stdout.strip(); git(production,'branch',backup,ns.baseline,check=True); git(production,'merge','--ff-only',commit,check=True)
        health=deterministic_health(production,ns.python,health_timeout)
        if health:
            git(production,'reset','--hard',ns.baseline,check=True); lines += ["- Decision: `ROLLED_BACK`",f"- Backup branch: `{backup}`","- Production modified: `rolled back`","- Health failures:"]+[f"  - {h}" for h in health]; append_report(report,lines); print('CANDIDATE_GATE=ROLLED_BACK'); return 0
        lines += ["- Decision: `PROMOTED`",f"- Promoted commit: `{commit}`",f"- Rollback branch: `{backup}`","- Production modified: `yes`","- Live gateway/desktop restart: `not automatic`"]; append_report(report,lines); print('CANDIDATE_GATE=PROMOTED'); return 0
    except Exception as e:
        try:
            if git(production,'rev-parse','HEAD').stdout.strip()!=ns.baseline: git(production,'reset','--hard',ns.baseline)
        except Exception: pass
        lines += ["- Decision: `PROMOTION_ERROR`","- Production modified: `no/rolled back`",f"- Error: `{str(e).replace('`','')[:1500]}`"]; append_report(report,lines); print('CANDIDATE_GATE=PROMOTION_ERROR'); return 0
    finally:
        if promo.exists(): git(production,'worktree','remove','--force',str(promo))
        git(production,'branch','-D',branch)

if __name__=='__main__': raise SystemExit(main())
