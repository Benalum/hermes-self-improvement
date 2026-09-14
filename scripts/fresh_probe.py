#!/usr/bin/env python3
"""Run one bounded fresh probe from a KNOWN_RED baseline failure fingerprint.

The controller, not the LLM, owns this probe.  It rotates through a conservative
allowlist of core/local test files and records its cursor under controller state.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import time
import textwrap
from pathlib import Path

# Deliberately exclude updater/service/security/external-backend surfaces from
# autonomous candidate discovery.  This is stricter than the eventual plan gate.
BLOCKED = re.compile(
    r"(auth|credential|secret|security|ssh|firewall|payment|trading|broker|wallet|"
    r"update|updater|launchd|systemd|gateway|approval|daytona|video|voice|"
    r"transcription|image_generation|web_tools|computer_use|wake_word|memory|"
    r"managed_media|modal|fal_plugin|provider|anthropic|portal|vision|nous|execution)",
    re.I,
)

# Prefer core/local behavior where a small source-only fix is plausible.
PREFERRED = (
    "tests/test_hermes_state.py",
    "tests/test_guest_durability_barriers.py",
    "tests/agent/",
    "tests/run_agent/",
    "tests/tools/test_file_tools.py",
)


def _eligible(path: str) -> bool:
    if not path.startswith("tests/") or not path.endswith(".py"):
        return False
    if BLOCKED.search(path):
        return False
    return any(path == p or path.startswith(p) for p in PREFERRED)


def _run(cmd, cwd: Path, timeout: int) -> dict:
    started = time.perf_counter()
    try:
        cp = subprocess.run(
            cmd,
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            env=os.environ.copy(),
        )
        out = cp.stdout or ""
        return {
            "exit": cp.returncode,
            "seconds": round(time.perf_counter() - started, 3),
            "output": out[-4500:],
        }
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        if isinstance(out, bytes):
            out = out.decode(errors="replace")
        return {
            "exit": 124,
            "seconds": round(time.perf_counter() - started, 3),
            "output": (out + f"\nTIMEOUT after {timeout}s")[-4500:],
        }
    except Exception as exc:
        return {"exit": 125, "seconds": 0, "output": repr(exc)}


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n")
    os.replace(tmp, path)


COMMON_CALLS = {
    "append", "extend", "get", "items", "keys", "values", "len", "print",
    "count", "execute", "fetchone", "fetchall", "commit", "close", "cursor",
    "connect", "read_text", "write_text", "exists", "is_file", "mkdir",
    "sum", "join", "split", "upper", "lower", "hasattr", "getattr", "setattr",
    "loads", "dumps", "set_trace_callback",
}


def _clip(text: str, limit: int = 6000) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[: limit // 2] + "\n...<controller context clipped>...\n" + text[-limit // 2 :]


def _excerpt(path: Path, start: int, end: int, pad: int = 2, limit: int = 6000) -> str:
    try:
        lines = path.read_text(errors="replace").splitlines()
    except Exception:
        return ""
    lo = max(1, start - pad)
    hi = min(len(lines), end + pad)
    out = []
    for n in range(lo, hi + 1):
        out.append(f"{n:>5}: {lines[n-1]}")
    return _clip("\n".join(out), limit)


def _failure_node(output: str, target: str):
    # pytest short summary is the most reliable place to recover the exact node.
    m = re.search(r"^FAILED\s+(%s(?:::[^\s]+)+)" % re.escape(target), output, re.M)
    nodeid = m.group(1) if m else ""
    line = 0
    m2 = re.search(r"^%s:(\d+):\s+in\s+" % re.escape(target), output, re.M)
    if m2:
        line = int(m2.group(1))
    return nodeid, line


def _assertion_evidence_terms(node) -> list:
    """Extract a few identifier-like terms from assertions in the failing test.

    Call names locate candidate production definitions.  Assertion attributes/keys
    locate the *relevant lines inside* those definitions.  Restricting string
    literals to Python-identifier shape avoids copying URLs, tokens, or prose into
    controller-owned source lookup.
    """
    terms = []
    seen = set()
    for assertion in (n for n in ast.walk(node) if isinstance(n, ast.Assert)):
        for item in ast.walk(assertion.test):
            term = ""
            if isinstance(item, ast.Attribute):
                term = item.attr
            elif isinstance(item, ast.Constant) and isinstance(item.value, str):
                value = item.value
                if re.match(r"^[A-Za-z_][A-Za-z0-9_]{2,63}$", value):
                    term = value
            if not term or term in seen or term in COMMON_CALLS or term.startswith("test_"):
                continue
            seen.add(term)
            terms.append(term)
            if len(terms) >= 8:
                return terms
    return terms


def _patched_helper_symbols(node) -> list:
    """Recover helper names referenced through patch/monkeypatch strings.

    Tests commonly replace a production helper via ``@patch("pkg.mod._helper")``.
    The helper is therefore evidence, even though it is not a normal Python call
    node.  Only identifier-shaped final path components are retained.
    """
    out = []
    seen = set()
    for call in (n for n in ast.walk(node) if isinstance(n, ast.Call)):
        fname = ""
        if isinstance(call.func, ast.Name):
            fname = call.func.id
        elif isinstance(call.func, ast.Attribute):
            fname = call.func.attr
        if fname not in {"patch", "setattr"}:
            continue
        for arg in call.args[:2]:
            if not isinstance(arg, ast.Constant) or not isinstance(arg.value, str):
                continue
            value = arg.value
            candidate = value.rsplit(".", 1)[-1]
            if not re.match(r"^[A-Za-z_][A-Za-z0-9_]{2,127}$", candidate):
                continue
            if candidate in COMMON_CALLS or candidate.startswith("test_") or candidate in seen:
                continue
            seen.add(candidate)
            out.append(candidate)
            if len(out) >= 6:
                return out
    return out


def _find_test_node(path: Path, nodeid: str, failure_line: int):
    try:
        text = path.read_text(errors="replace")
        tree = ast.parse(text)
    except Exception:
        return None, "", [], []
    wanted = ""
    if nodeid:
        parts = nodeid.split("::")
        if len(parts) > 1:
            wanted = parts[-1]
    matches = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if wanted and node.name == wanted:
                matches.append(node)
            elif failure_line and getattr(node, "lineno", 0) <= failure_line <= getattr(node, "end_lineno", node.lineno):
                matches.append(node)
    if not matches:
        return None, "", [], []
    node = sorted(matches, key=lambda n: (0 if n.name == wanted else 1, getattr(n, "lineno", 0)))[0]
    defined = {n.name for n in ast.walk(node) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n is not node}

    # Rank production-call candidates by proximity to the failing assertion.
    # Setup calls near the beginning of a test are useful background, but the
    # operation immediately surrounding the failure is usually the behavior
    # under test.  This matters because source_definitions is deliberately
    # capped: without ranking, early setup helpers can consume every slot and
    # hide the exact function Qwen needs (for example search_messages()).
    call_distance = {}
    anchor = failure_line or getattr(node, "lineno", 0)
    for call in (n for n in ast.walk(node) if isinstance(n, ast.Call)):
        name = ""
        if isinstance(call.func, ast.Attribute):
            name = call.func.attr
        elif isinstance(call.func, ast.Name):
            name = call.func.id
        if not name or name in defined or name in COMMON_CALLS or name.startswith("assert") or name.startswith("test_"):
            continue
        lineno = getattr(call, "lineno", anchor) or anchor
        distance = abs(lineno - anchor) if anchor else 0
        if name not in call_distance or distance < call_distance[name]:
            call_distance[name] = distance

    symbols = [name for name, _ in sorted(call_distance.items(), key=lambda kv: (kv[1], kv[0]))]

    # Explicitly patched production helpers remain valuable evidence.  They
    # still follow the behavior-under-test call ranking in candidate_symbols,
    # but are also focus terms so the primary production excerpt jumps to the
    # exact mocked handoff instead of spending its budget on unrelated guards.
    patched_helpers = _patched_helper_symbols(node)
    for helper in patched_helpers:
        if helper not in symbols:
            symbols.append(helper)
    terms = _assertion_evidence_terms(node)
    for helper in patched_helpers:
        if helper not in terms and len(terms) < 8:
            terms.append(helper)
    return node, _excerpt(path, node.lineno, getattr(node, "end_lineno", node.lineno), pad=2, limit=7000), symbols[:12], terms


def _tracked_python_files(worktree: Path):
    try:
        cp = subprocess.run(
            ["git", "ls-files", "*.py"], cwd=str(worktree), text=True,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5,
        )
    except Exception:
        return []
    out = []
    for rel in (cp.stdout or "").splitlines():
        if not rel or rel.startswith("tests/") or "/tests/" in rel:
            continue
        p = (worktree / rel).resolve()
        try:
            p.relative_to(worktree)
        except ValueError:
            continue
        if p.is_file():
            out.append((rel, p))
    return out[:2500]


def _definition_end_by_indent(text: str, start_line: int) -> int:
    """Find a definition's lexical end without requiring whole-file AST parsing.

    Multi-line signatures need special handling: a closing ``) -> ...:`` may be
    aligned with ``def`` itself.  Treating that header line as a dedent truncates
    the excerpt before the function body -- exactly the failure mode the
    controller must avoid when a checked-out Hermes file uses syntax that the
    controller Python cannot parse.
    """
    lines = text.splitlines()
    if not lines or start_line < 1 or start_line > len(lines):
        return min(len(lines), max(1, start_line + 55))
    first = lines[start_line - 1]
    base_indent = len(first) - len(first.lstrip())

    # Locate the end of the ``def`` header first.  A lightweight parenthesis
    # count is sufficient here because we only use this path after locating a
    # concrete ``def <symbol>`` line; AST parsing remains preferred when it works.
    depth = 0
    saw_open = False
    header_end = start_line
    for lineno in range(start_line, min(len(lines), start_line + 80) + 1):
        raw = lines[lineno - 1]
        for ch in raw:
            if ch == "(":
                depth += 1
                saw_open = True
            elif ch == ")" and depth > 0:
                depth -= 1
        if saw_open and depth == 0 and ":" in raw:
            header_end = lineno
            break

    end = len(lines)
    # Begin dedent detection *after* the complete signature/header.
    for idx in range(header_end, len(lines)):
        raw = lines[idx]
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        if indent <= base_indent:
            end = idx
            break
    return max(header_end, end)


def _definition_docstring_lines(lines, start: int, end: int):
    """Return absolute line numbers occupied by the selected definition docstring."""
    snippet = "\n".join(lines[max(0, start - 1):min(len(lines), end)])
    try:
        tree = ast.parse(textwrap.dedent(snippet))
    except Exception:
        return set()
    if not tree.body or not isinstance(tree.body[0], (ast.FunctionDef, ast.AsyncFunctionDef)):
        return set()
    fn = tree.body[0]
    if not fn.body:
        return set()
    first = fn.body[0]
    if not (isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant) and isinstance(first.value.value, str)):
        return set()
    lo = start + getattr(first, "lineno", 1) - 1
    hi = start + getattr(first, "end_lineno", getattr(first, "lineno", 1)) - 1
    return set(range(lo, hi + 1))


def _term_hit_score(line: str, term: str, lineno: int, docstring_lines) -> int:
    """Prefer causal executable evidence over comments/docstrings for an assertion term.

    Control-flow gates are especially important: for projection/state regressions,
    the line deciding *whether* work runs is stronger evidence than the later line
    merely storing the resulting value.
    """
    stripped = line.strip()
    if lineno in docstring_lines or stripped.startswith("#"):
        return 0
    esc = re.escape(term)
    # A branch/loop guard that mentions the asserted term is usually the causal
    # decision point (for example ``if result_fields is None or "context" in
    # result_fields``). Rank it ahead of later output assignments.
    if re.match(r"^(?:if|elif|while)\b", stripped):
        return 9
    # The membership expression can be split onto a continuation line, so keep
    # an explicit membership score even when the physical line does not start
    # with ``if``.
    if re.search(r"[\"']" + esc + r"[\"']\s+(?:not\s+)?in\b", line):
        return 8
    if re.search(r"\b" + esc + r"\b\s+(?:not\s+)?in\b", line):
        return 8
    # Direct attribute/name assignment or a dict key is strong state evidence.
    if re.search(esc + r"\s*=", line):
        return 6
    if re.search(r"[\"']" + esc + r"[\"']\s*:", line):
        return 6
    if re.search(r"\[\s*[\"']" + esc + r"[\"']\s*\]", line):
        return 5
    # Other executable references (calls, comparisons, logging arguments) are
    # still more useful than prose mentions.
    return 3


def _focused_definition_excerpt(path: Path, start: int, end: int, terms, limit: int = 7000):
    """Return definition start plus bounded windows around assertion-relevant terms.

    For each assertion term, rank executable occurrences ahead of comments and
    docstrings. This prevents prose near the function header from consuming the
    two focused windows while the actual assignment is hidden hundreds of lines
    later.
    """
    try:
        lines = path.read_text(errors="replace").splitlines()
    except Exception:
        return "", []
    end = min(max(start, end), len(lines))
    base_end = min(end, start + 30)
    ranges = [(max(1, start - 3), min(end, base_end + 2))]
    matched = []
    docstring_lines = _definition_docstring_lines(lines, start, end)
    for term in terms[:8]:
        ranked = []
        for n in range(start, end + 1):
            if term not in lines[n - 1]:
                continue
            ranked.append((_term_hit_score(lines[n - 1], term, n, docstring_lines), n))
        if not ranked:
            continue
        matched.append(term)
        # Stable line-order tie-break after relevance score. Keep at most two
        # windows per term, preserving the old hard bound.
        hits = [n for _, n in sorted(ranked, key=lambda item: (-item[0], item[1]))[:2]]
        for n in hits:
            ranges.append((max(start, n - 6), min(end, n + 6)))

    ranges.sort()
    merged = []
    for lo, hi in ranges:
        if merged and lo <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))

    chunks = []
    for i, (lo, hi) in enumerate(merged):
        if i:
            chunks.append("...<controller focused source evidence>...")
        chunks.extend(f"{n:>5}: {lines[n-1]}" for n in range(lo, hi + 1))
    return _clip("\n".join(chunks), limit), matched


def _direct_callee_symbols(path: Path, start: int, end: int):
    """Return bounded call names from one production definition.

    This is intentionally one-hop only. It lets the controller accompany the
    primary behavior under test with directly invoked helpers without turning
    discovery into recursive source browsing.
    """
    try:
        lines = path.read_text(errors="replace").splitlines()
    except Exception:
        return []
    snippet = "\n".join(lines[max(0, start - 1):min(len(lines), end)])
    try:
        import textwrap
        tree = ast.parse(textwrap.dedent(snippet))
    except Exception:
        names = re.findall(r"(?<![.A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)\s*\(", snippet)
    else:
        names = []
        ordered = sorted(
            (n for n in ast.walk(tree) if isinstance(n, ast.Call)),
            key=lambda n: (getattr(n, "lineno", 0), getattr(n, "col_offset", 0)),
        )
        for call in ordered:
            if isinstance(call.func, ast.Name):
                names.append(call.func.id)
            elif isinstance(call.func, ast.Attribute):
                names.append(call.func.attr)
    out = []
    seen = set()
    for name in names:
        if (
            not name
            or name in seen
            or name in COMMON_CALLS
            or name.startswith("test_")
            or name in {"print", "len", "getattr", "setattr", "isinstance", "super"}
        ):
            continue
        seen.add(name)
        out.append(name)
        if len(out) >= 16:
            break
    return out


def _definition_record(files, symbol, evidence_terms, preferred_rel=None):
    """Locate one tracked production definition, preferring *preferred_rel*."""
    rx = re.compile(r"^\s*(?:async\s+)?def\s+%s\b" % re.escape(symbol), re.M)
    ordered = list(files)
    if preferred_rel:
        ordered.sort(key=lambda item: (0 if item[0] == preferred_rel else 1, item[0]))
    for rel, path in ordered:
        try:
            text = path.read_text(errors="replace")
        except Exception:
            continue
        m = rx.search(text)
        if not m:
            continue
        line = text.count("\n", 0, m.start()) + 1
        end = _definition_end_by_indent(text, line)
        try:
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == symbol and node.lineno == line:
                    end = getattr(node, "end_lineno", end)
                    break
        except Exception:
            pass
        excerpt, matched_terms = _focused_definition_excerpt(path, line, end, evidence_terms, limit=7000)
        return {
            "symbol": symbol,
            "path": rel,
            "line": line,
            "end_line": end,
            "evidence_terms": matched_terms,
            "excerpt": excerpt,
        }, path
    return None, None


def _source_context(worktree: Path, symbols, evidence_terms):
    # Return at most three production definitions. Slot 1 is the highest-priority
    # test behavior. Remaining slots first go to one-hop helpers called directly
    # by that function (same-file/private helpers preferred), then to secondary
    # test symbols. The hard cap remains three.
    files = _tracked_python_files(worktree)
    found = []
    seen = set()

    primary = None
    primary_path = None
    for symbol in symbols[:8]:
        rec, path = _definition_record(files, symbol, evidence_terms)
        if rec is None:
            continue
        found.append(rec)
        seen.add(symbol)
        primary = rec
        primary_path = path
        break

    if primary is not None and primary_path is not None and len(found) < 3:
        callees = _direct_callee_symbols(primary_path, primary["line"], primary["end_line"])
        candidates = []
        for order, name in enumerate(callees):
            if name in seen:
                continue
            rec, _ = _definition_record(files, name, evidence_terms, preferred_rel=primary["path"])
            if rec is None:
                continue
            rank = (
                # A direct callee explicitly referenced by the failing test
                # (commonly via @patch) is stronger causal evidence than an
                # unrelated early guard helper.  Keep traversal one-hop/bounded.
                0 if name in symbols else 1,
                0 if rec["path"] == primary["path"] else 1,
                0 if name.startswith("_") else 1,
                order,
            )
            candidates.append((rank, rec))
        for _, rec in sorted(candidates, key=lambda item: item[0]):
            if rec["symbol"] in seen:
                continue
            found.append(rec)
            seen.add(rec["symbol"])
            if len(found) >= 3:
                break

    if len(found) < 3:
        for symbol in symbols[:8]:
            if symbol in seen:
                continue
            rec, _ = _definition_record(files, symbol, evidence_terms)
            if rec is None:
                continue
            found.append(rec)
            seen.add(symbol)
            if len(found) >= 3:
                break

    for rec in found:
        rec.pop("end_line", None)
    return found


def _local_test_helpers(path: Path, failing_node, symbols, rel_path=None, max_helpers: int = 2):
    """Return bounded sibling/local test helpers referenced by the failing test.

    These records are classifier-only evidence. They are kept separate from
    ``source_definitions`` so the IMPLEMENT validator remains bound exclusively
    to tracked production code and tests remain non-editable.
    """
    try:
        text = path.read_text(errors="replace")
        tree = ast.parse(text)
    except Exception:
        return []
    wanted = [s for s in symbols if s and s != getattr(failing_node, "name", "")]
    by_name = {}
    for item in ast.walk(tree):
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in wanted:
            by_name.setdefault(item.name, item)
    out = []
    for symbol in wanted:
        item = by_name.get(symbol)
        if item is None:
            continue
        out.append({
            "symbol": symbol,
            "path": rel_path or str(path.name),
            "line": item.lineno,
            "excerpt": _excerpt(path, item.lineno, getattr(item, "end_lineno", item.lineno), pad=1, limit=2600),
        })
        if len(out) >= max_helpers:
            break
    return out


def _build_context_packet(worktree: Path, target: str, output: str) -> dict:
    target_path = (worktree / target).resolve()
    nodeid, failure_line = _failure_node(output, target)
    node, test_excerpt, symbols, evidence_terms = _find_test_node(target_path, nodeid, failure_line)
    return {
        "failure_node": nodeid,
        "failure_line": failure_line,
        "test_excerpt": test_excerpt,
        "candidate_symbols": symbols,
        "evidence_terms": evidence_terms,
        "test_helpers": _local_test_helpers(target_path, node, symbols, rel_path=target),
        "source_definitions": _source_context(worktree, symbols, evidence_terms),
    }


def _nonactionable_environment_reason(output: str):
    """Return a conservative skip reason for explicit missing-dependency failures.

    This classifier is intentionally narrow. It does not infer from generic errors;
    it only recognizes tracebacks that explicitly say an import/module/package is
    missing and therefore cannot be fixed by the source-only autonomous path.
    """
    text = output or ""
    patterns = (
        (r"ModuleNotFoundError:\s+No module named ['\"]([^'\"]+)['\"]", "missing Python module"),
        (r"ImportError:.*?['\"]([^'\"]+)['\"] package is required", "missing optional package"),
        (r"ImportError:.*?package is required.*?pip install", "missing optional package"),
        # Some provider adapters catch the ImportError and log the explicit
        # dependency requirement before falling back to another transport.
        # Treat that as the same non-actionable environment condition only
        # when the warning contains both a quoted package name and an actual
        # pip-install instruction. Generic warnings remain actionable.
        (r"(?:The\s+)?['\"]([^'\"]+)['\"]\s+package\s+is\s+required\b.{0,500}?\bpip\s+install\b", "missing optional package"),
        (r"No module named ['\"]([^'\"]+)['\"]", "missing Python module"),
    )
    for pattern, label in patterns:
        m = re.search(pattern, text, re.I | re.S)
        if m:
            detail = m.group(1) if m.lastindex else "dependency"
            return f"{label}: {detail}"
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline-json", required=True)
    ap.add_argument("--worktree", required=True)
    ap.add_argument("--state", required=True)
    ap.add_argument("--python", required=True)
    ap.add_argument("--timeout", type=int, default=45)
    ap.add_argument("--max-attempts", type=int, default=3)
    ns = ap.parse_args()

    try:
        baseline = json.loads(ns.baseline_json)
    except Exception as exc:
        print(json.dumps({"status": "SKIPPED", "reason": f"invalid baseline json: {exc}"}))
        return 0

    if baseline.get("baseline_health") != "KNOWN_RED":
        print(json.dumps({"status": "SKIPPED", "reason": "baseline is not KNOWN_RED"}))
        return 0

    summary = baseline.get("test_failure_summary") or {}
    failure_files = summary.get("failure_files") or {}
    def rank(path: str):
        for i, pref in enumerate(PREFERRED):
            if path == pref or path.startswith(pref):
                return (i, path)
        return (len(PREFERRED), path)
    candidates = sorted((p for p in failure_files if _eligible(p)), key=rank)
    if not candidates:
        print(json.dumps({"status": "SKIPPED", "reason": "no low-risk probe candidates"}))
        return 0

    signature = summary.get("signature") or hashlib.sha256(
        json.dumps(failure_files, sort_keys=True).encode()
    ).hexdigest()
    state_path = Path(ns.state) / "fresh-probe-cursor.json"
    cursor = _load(state_path)
    if cursor.get("signature") == signature:
        index = int(cursor.get("next_index", 0)) % len(candidates)
    else:
        index = 0
    worktree = Path(ns.worktree).resolve()
    max_attempts = max(1, min(int(ns.max_attempts), len(candidates)))
    budget_seconds = max(1, int(ns.timeout))
    attempts = []
    selected = None
    attempts_used = 0
    budget_started = time.perf_counter()

    for offset in range(max_attempts):
        current_index = (index + offset) % len(candidates)
        target = candidates[current_index]
        attempts_used += 1
        test_path = (worktree / target).resolve()
        try:
            test_path.relative_to(worktree)
        except ValueError:
            attempts.append({"target": target, "status": "SKIPPED", "reason": "probe path escaped worktree"})
            continue
        if not test_path.is_file():
            attempts.append({"target": target, "status": "SKIPPED", "reason": "probe file missing"})
            continue

        # FRESH_PROBE_TIMEOUT_SECONDS is a shared wall-clock budget across all
        # attempts, not a per-file multiplier. This preserves the controller's
        # bounded pre-triage cost when max_attempts > 1.
        elapsed = time.perf_counter() - budget_started
        remaining = budget_seconds - elapsed
        if remaining <= 0:
            attempts_used -= 1
            break
        per_attempt_timeout = max(0.05, remaining)

        # Use the prepared worktree Python so the probe observes the exact candidate
        # environment. One file only; no test directory or broad wrapper.
        result = _run([ns.python, "-m", "pytest", "-q", target, "--tb=short", "--maxfail=1", "-p", "no:cacheprovider"], worktree, per_attempt_timeout)
        status = "FAIL" if result["exit"] == 1 else "PASS" if result["exit"] == 0 else "TIMEOUT" if result["exit"] == 124 else "ERROR"

        if status == "PASS":
            attempts.append({
                "target": target, "status": "PASS", "reason": "baseline failure did not reproduce",
                "seconds": result["seconds"],
            })
            continue

        if status == "FAIL":
            reason = _nonactionable_environment_reason(result["output"])
            if reason:
                attempts.append({
                    "target": target, "status": "NON_ACTIONABLE_ENVIRONMENT",
                    "reason": reason, "seconds": result["seconds"],
                })
                continue

        # FAIL without an explicit environment/dependency cause is actionable
        # evidence. TIMEOUT/ERROR are retained for conservative classifier review.
        context_packet = _build_context_packet(worktree, target, result["output"]) if status == "FAIL" else {}
        selected = {
            "status": status,
            "target": target,
            "baseline_failure_count": int(failure_files.get(target, 0)),
            "exit": result["exit"],
            "seconds": result["seconds"],
            "output": result["output"],
            "rotation_index": current_index,
            "rotation_total": len(candidates),
            "context_packet": context_packet,
        }
        attempts.append({
            "target": target, "status": status, "reason": "selected for classifier review",
            "seconds": result["seconds"],
        })
        break

    next_index = (index + attempts_used) % len(candidates)
    last_target = candidates[(index + attempts_used - 1) % len(candidates)]
    _save(state_path, {
        "signature": signature, "next_index": next_index, "last_target": last_target,
        "last_attempts": attempts,
    })

    if selected is None:
        payload = {
            "status": "NO_ACTIONABLE_FAILURE",
            "reason": "bounded fresh probes found only resolved or explicit dependency/environment failures",
            "attempt_count": attempts_used,
            "max_attempts": max_attempts,
            "rotation_start_index": index,
            "rotation_total": len(candidates),
            "attempts": attempts,
            "context_packet": {},
            "probe_budget_seconds": budget_seconds,
            "probe_elapsed_seconds": round(time.perf_counter() - budget_started, 3),
        }
    else:
        payload = dict(selected)
        payload["attempt_count"] = attempts_used
        payload["max_attempts"] = max_attempts
        payload["attempts"] = attempts
        payload["probe_budget_seconds"] = budget_seconds
        payload["probe_elapsed_seconds"] = round(time.perf_counter() - budget_started, 3)

    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
