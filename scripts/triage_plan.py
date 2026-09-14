#!/usr/bin/env python3
"""Validate the read-only discovery agent's structured implementation handoff."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path, PurePosixPath
from typing import Optional

MAX_BYTES = 8192
BLOCKED_PATH_RE = re.compile(r"(^|/)(\.github/workflows|\.git)(/|$)", re.I)
SENSITIVE_COMPONENT_RE = re.compile(r"(auth|credential|secret|ssh|firewall|security|payment|trading|broker|wallet|launchd|systemd|installer|updater)", re.I)
BLOCKED_BASENAMES = {"pyproject.toml","uv.lock","requirements.txt","requirements-dev.txt","package-lock.json","pnpm-lock.yaml","yarn.lock","Dockerfile","conftest.py","pytest.ini","tox.ini"}

REQUIRED = {
    "decision",
    "summary",
    "problem",
    "fresh_evidence",
    "files",
    "targeted_tests",
    "risk",
    "expected_benefit",
}


def _safe_rel(value: str) -> bool:
    if not value or value.startswith(("/", "~")) or "\\" in value:
        return False
    p = PurePosixPath(value)
    return not p.is_absolute() and ".." not in p.parts and "." not in p.parts


def _specific_test(value: str) -> bool:
    # Accept a pytest file or node, but never a directory-only target.
    target = value.strip().split()[0] if value.strip() else ""
    return target.endswith(".py") or ".py::" in target


def validate(plan_path: Path, worktree: Path, evidence: Optional[dict] = None) -> dict:
    raw = plan_path.read_bytes()
    if len(raw) > MAX_BYTES:
        raise ValueError(f"plan exceeds {MAX_BYTES} bytes")
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict) or set(data) != REQUIRED:
        raise ValueError(f"plan must contain exactly: {', '.join(sorted(REQUIRED))}")
    if data["decision"] not in {"IMPLEMENT", "NO_CHANGE"}:
        raise ValueError("decision must be IMPLEMENT or NO_CHANGE")
    if data["risk"] != "low":
        raise ValueError("triage may hand off only low-risk candidates")
    for key in ("summary", "problem", "fresh_evidence", "expected_benefit"):
        if not isinstance(data[key], str) or not data[key].strip():
            raise ValueError(f"{key} must be a non-empty string")
        if len(data[key]) > 2000:
            raise ValueError(f"{key} is too long")
    if not isinstance(data["files"], list) or len(data["files"]) > 6:
        raise ValueError("files must be a list of at most 6 paths")
    if not isinstance(data["targeted_tests"], list) or len(data["targeted_tests"]) > 6:
        raise ValueError("targeted_tests must be a list of at most 6 entries")
    for rel in data["files"]:
        if not isinstance(rel, str) or not _safe_rel(rel):
            raise ValueError(f"unsafe file path: {rel!r}")
        if Path(rel).name in BLOCKED_BASENAMES or BLOCKED_PATH_RE.search(rel) or any(SENSITIVE_COMPONENT_RE.search(part) for part in Path(rel).parts):
            raise ValueError(f"blocked/high-risk implementation path: {rel}")
        if rel.startswith("tests/"):
            raise ValueError(f"triage may not propose modifying existing tests: {rel}")
    for test in data["targeted_tests"]:
        if not isinstance(test, str) or not _safe_rel(test.split("::", 1)[0]):
            raise ValueError(f"unsafe targeted test: {test!r}")
        if not _specific_test(test):
            raise ValueError(f"targeted test must name a specific .py file/node: {test!r}")
    if data["decision"] == "IMPLEMENT":
        if not data["files"]:
            raise ValueError("IMPLEMENT requires at least one implementation file")
        if not data["targeted_tests"]:
            raise ValueError("IMPLEMENT requires at least one specific targeted test")
    else:
        if data["files"] or data["targeted_tests"]:
            raise ValueError("NO_CHANGE must not include implementation files/tests")
    if evidence is not None and data["decision"] == "IMPLEMENT":
        if not isinstance(evidence, dict) or evidence.get("status") != "FAIL":
            raise ValueError("IMPLEMENT requires a fresh failing controller probe")
        packet = evidence.get("context_packet") or {}
        defs = packet.get("source_definitions") or []
        allowed_files = {d.get("path") for d in defs if isinstance(d, dict) and isinstance(d.get("path"), str)}
        if not allowed_files:
            raise ValueError("IMPLEMENT requires a production source definition in the fresh context packet")
        extra = set(data["files"]) - allowed_files
        if extra:
            raise ValueError(f"implementation path not grounded in fresh context packet: {sorted(extra)!r}")
        failure_node = packet.get("failure_node") or ""
        target = evidence.get("target") or ""
        grounded_test = failure_node or target
        if grounded_test and grounded_test not in data["targeted_tests"]:
            raise ValueError(f"targeted_tests must include fresh failing node: {grounded_test}")
    # Resolve paths only for traversal defense; a candidate may legitimately create a new file.
    root = worktree.resolve()
    for rel in data["files"] + [x.split("::", 1)[0] for x in data["targeted_tests"]]:
        resolved = (root / rel).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"path escapes worktree: {rel}") from exc
    return data


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--worktree", required=True)
    ap.add_argument("--evidence-json")
    ns = ap.parse_args()
    try:
        evidence = json.loads(ns.evidence_json) if ns.evidence_json else None
        data = validate(Path(ns.plan), Path(ns.worktree), evidence=evidence)
    except Exception as exc:
        print(f"INVALID_TRIAGE_PLAN: {exc}")
        return 2
    print(json.dumps(data, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
