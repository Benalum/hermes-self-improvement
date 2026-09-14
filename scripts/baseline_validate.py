#!/usr/bin/env python3
"""Prepare and cache baseline validation evidence outside the LLM turn budget."""
from __future__ import annotations
import argparse, hashlib, json, os, re, shutil, subprocess, time
try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # macOS system Python 3.9/3.10 compatibility
    tomllib = None
from pathlib import Path


def run(cmd, cwd=None, timeout=None, max_output=6000):
    started = time.perf_counter()
    try:
        cp = subprocess.run(cmd, cwd=cwd, timeout=timeout, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return {"exit": cp.returncode, "seconds": round(time.perf_counter()-started, 3),
                "output": cp.stdout[-max_output:]}
    except subprocess.TimeoutExpired as e:
        out = e.stdout or ""
        if isinstance(out, bytes): out = out.decode(errors="replace")
        return {"exit": 124, "seconds": round(time.perf_counter()-started, 3),
                "output": (out + f"\nTIMEOUT after {timeout}s")[-max_output:]}
    except Exception as e:
        return {"exit": 125, "seconds": round(time.perf_counter()-started, 3), "output": repr(e)}


def parse_test_failure_summary(output):
    """Extract a coarse but deterministic failure fingerprint from run_tests.sh."""
    output = output or ""
    files = {}
    for m in re.finditer(r"^\s+(tests/\S+?\.py)\s+\((\d+) tests? failed\)\s*$", output, re.M):
        files[m.group(1)] = int(m.group(2))
    nodeids = sorted(set(re.findall(r"^FAILED\s+(\S+)", output, re.M)))
    no_run = []
    marker = re.search(r"^===\s+\d+ files where no tests ran .*?===\s*$", output, re.M)
    if marker:
        tail = output[marker.end():]
        for line in tail.splitlines():
            m = re.match(r"^\s+(tests/\S+?\.py)\s*$", line)
            if m:
                no_run.append(m.group(1))
            elif line.strip().startswith('==='):
                break
    payload = {"failure_files": dict(sorted(files.items())), "no_run_files": sorted(set(no_run))}
    sig = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        **payload,
        "failed_test_count": sum(files.values()),
        "failed_nodeids_seen": nodeids,
        "signature": sig,
    }


def load_json(path):
    try: return json.loads(Path(path).read_text())
    except Exception: return None


def save_json(path, data):
    p=Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    tmp=p.with_suffix(p.suffix+".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True)+"\n")
    os.replace(tmp,p)


CACHE_SCHEMA=6

def detect_optional_extras(pyproject_path: Path):
    """Return optional dependency names needed by the controller.

    Prefer the stdlib TOML parser on Python 3.11+.  The controller test harness
    may run under Apple's older system Python, where tomllib is unavailable.
    In that case we only need to detect keys in [project.optional-dependencies],
    so use a conservative, read-only parser for that one table.
    """
    text=pyproject_path.read_text()
    if tomllib is not None:
        doc=tomllib.loads(text)
        optional=((doc.get('project') or {}).get('optional-dependencies') or {})
        return set(optional)

    in_optional=False
    found=set()
    table_re=re.compile(r'^\s*\[([^]]+)\]\s*(?:#.*)?$')
    key_re=re.compile(r'^\s*(?:"([^"]+)"|\'([^\']+)\'|([A-Za-z0-9_.-]+))\s*=')
    for raw in text.splitlines():
        line=raw.strip()
        if not line or line.startswith('#'):
            continue
        m=table_re.match(raw)
        if m:
            in_optional=(m.group(1).strip()=='project.optional-dependencies')
            continue
        if not in_optional:
            continue
        m=key_re.match(raw)
        if m:
            found.add(next(x for x in m.groups() if x is not None))
    return found

def find_uv(python_exe=None, production=None):
    """Find uv robustly in Hermes, interactive-shell, and scheduler environments."""
    candidates=[]
    override=os.environ.get("UV_BIN")
    if override:
        candidates.append((Path(override).expanduser(), "override"))
    if python_exe:
        try:
            py=Path(python_exe).expanduser().resolve()
        except Exception:
            py=Path(python_exe).expanduser()
        candidates.append((py.parent/"uv", "python-sibling"))
    if production:
        candidates.append((Path(production).expanduser()/"venv/bin/uv", "production-venv"))
    hermes_root=os.environ.get("HERMES_ROOT")
    if hermes_root:
        candidates.append((Path(hermes_root).expanduser()/"venv/bin/uv", "hermes-root-venv"))
    found=shutil.which("uv")
    if found:
        candidates.append((Path(found), "path"))
    home=Path.home()
    candidates += [
        (home/".hermes/bin/uv", "home-hermes"),
        (home/".local/bin/uv", "home-local"),
        (home/".cargo/bin/uv", "home-cargo"),
        (Path("/opt/homebrew/bin/uv"), "homebrew"),
        (Path("/usr/local/bin/uv"), "usr-local"),
        (Path("/usr/bin/uv"), "usr-bin"),
    ]
    seen=set()
    for c, source in candidates:
        try:
            c=c.resolve()
        except Exception:
            c=Path(c)
        if str(c) in seen:
            continue
        seen.add(str(c))
        if c.is_file() and os.access(c, os.X_OK):
            return str(c), source
    # Last resort: ask the user's login/interactive zsh, which may source
    # PATH additions created by the uv installer. Never execute arbitrary output.
    zsh=Path("/bin/zsh")
    if zsh.exists():
        try:
            cp=subprocess.run([str(zsh),"-lic","command -v uv"], text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5)
            for line in reversed(cp.stdout.splitlines()):
                line=line.strip()
                q=Path(line).expanduser()
                if line.startswith("/") and q.is_file() and os.access(q,os.X_OK):
                    return str(q.resolve()), "zsh-login"
        except Exception:
            pass
    return None, "missing"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--production', required=True)
    ap.add_argument('--worktree', required=True)
    ap.add_argument('--baseline', required=True)
    ap.add_argument('--python', required=True)
    ap.add_argument('--state', required=True)
    ap.add_argument('--timeout', type=int, default=1800)
    ap.add_argument('--cache-seconds', type=int, default=86400)
    ap.add_argument('--skip-tests', action='store_true')
    ns=ap.parse_args()
    production=Path(ns.production).resolve(); worktree=Path(ns.worktree).resolve(); state=Path(ns.state).resolve()
    key=hashlib.sha256(f"v{CACHE_SCHEMA}|{ns.baseline}|{Path(ns.python).resolve()}".encode()).hexdigest()[:20]
    cache=state/f"baseline-validation-{key}.json"
    now=time.time(); old=load_json(cache)
    result={"version":CACHE_SCHEMA,"baseline":ns.baseline,"created_epoch":now,"cache":"miss","worktree":str(worktree)}

    # Prepare every fresh worktree even when broad baseline evidence is cached.
    # This makes targeted candidate tests immediately available to the agent.
    uv, uv_source=find_uv(ns.python, production)
    pyproject_path=worktree/'pyproject.toml'
    pyproject=pyproject_path.exists()
    uv_lock=(worktree/'uv.lock').exists()
    extras=[]
    if pyproject:
        try:
            optional=detect_optional_extras(pyproject_path)
            if 'all' in optional:
                extras.append('all')
            if 'dev' in optional:
                extras.append('dev')
        except Exception as e:
            result['pyproject_parse_warning']=repr(e)
    # Hermes' documented full-suite contributor environment is .[all,dev].
    # Older/synthetic checkouts may not define those extras, so fall back to
    # the historical dev extra rather than inventing a dependency profile.
    if 'dev' not in extras:
        extras.append('dev')
    dependency_profile='+'.join(extras)
    result['dependency_profile']=dependency_profile
    if uv and pyproject:
        sync_cmd=[uv,'sync']
        if uv_lock:
            sync_cmd.append('--frozen')
        for extra in extras:
            sync_cmd += ['--extra',extra]
        result['dev_sync']=run(sync_cmd,cwd=worktree,timeout=min(ns.timeout,600))
        generated_lock=worktree/'uv.lock'
        removed_generated_lock=False
        if not uv_lock and generated_lock.exists():
            try:
                generated_lock.unlink()
                removed_generated_lock=True
            except OSError as e:
                result['dev_sync']['output'] += f'\nWARNING: unable to remove generated uv.lock: {e!r}'
        result['dev_sync']['mode']='frozen' if uv_lock else 'unlocked'
        result['dev_sync']['executable']=uv
        result['dev_sync']['source']=uv_source
        result['dev_sync']['removed_generated_lock']=removed_generated_lock
        result['dev_sync']['profile']=dependency_profile
    else:
        missing=[]
        if not uv: missing.append('uv')
        if not pyproject: missing.append('pyproject.toml')
        result['dev_sync']={"exit":None,"seconds":0,"output":"skipped: missing "+', '.join(missing),"mode":"skipped","executable":uv,"source":uv_source,"profile":dependency_profile}

    if old and old.get('version')==CACHE_SCHEMA and old.get('baseline')==ns.baseline and old.get('baseline_health') in {'PASS','KNOWN_RED'} and now-float(old.get('created_epoch',0)) <= ns.cache_seconds:
        old['cache']='hit' if old.get('baseline_health')=='PASS' else 'hit-red'
        old['worktree']=str(worktree); old['dev_sync']=result['dev_sync']; old['cache_file']=str(cache); print(json.dumps(old)); return 0

    result['cli_version']=run([ns.python,'-m','hermes_cli.main','--version'],cwd=production,timeout=min(ns.timeout,180))
    result['cli_help']=run([ns.python,'-m','hermes_cli.main','--help'],cwd=production,timeout=min(ns.timeout,180))
    if ns.skip_tests:
        result['tests']={"exit":None,"seconds":0,"output":"skipped by policy"}
    else:
        run_tests=worktree/'scripts/run_tests.sh'
        test_py=worktree/'.venv/bin/python'
        test_python=str(test_py) if test_py.exists() else ns.python
        result['test_python']=test_python
        if run_tests.exists():
            result['test_command']='scripts/run_tests.sh'
            result['tests']=run(['/bin/bash',str(run_tests)],cwd=worktree,timeout=ns.timeout,max_output=30000)
        else:
            result['test_command']=f'{test_python} -m pytest -q -m not integration'
            result['tests']=run([test_python,'-m','pytest','-q','-m','not integration'],cwd=worktree,timeout=ns.timeout,max_output=30000)
    result['environment_ready']=(result['dev_sync']['exit']==0) if pyproject else True
    sync_ok=result['environment_ready']
    smoke_ok=sync_ok and all(result[k]['exit']==0 for k in ('cli_version','cli_help'))
    test_exit=result['tests']['exit']
    if test_exit == 1:
        result['test_failure_summary']=parse_test_failure_summary(result['tests'].get('output',''))
    else:
        result['test_failure_summary']=parse_test_failure_summary('')
    if smoke_ok and test_exit in (0,None):
        result['baseline_health']='PASS'
    elif smoke_ok and test_exit == 1 and result['test_failure_summary']['failure_files']:
        result['baseline_health']='KNOWN_RED'
    else:
        result['baseline_health']='ATTENTION'
    result['cache_file']=str(cache)
    save_json(cache,result)
    print(json.dumps(result))
    return 0

if __name__=='__main__': raise SystemExit(main())
