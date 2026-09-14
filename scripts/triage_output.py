#!/usr/bin/env python3
"""Materialize a validated triage handoff from Hermes transcript output.

Safety rule: free-form transcript fallback may synthesize only NO_CHANGE.
IMPLEMENT always requires a complete controller-validated JSON object.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from triage_plan import REQUIRED, validate

MAX_TRANSCRIPT_BYTES = 2 * 1024 * 1024
DECISION_NO_CHANGE_RE = re.compile(r"(?im)^\s*(?:[-*]\s*)?Decision:\s*NO_CHANGE\s*$")
DECISION_IMPLEMENT_RE = re.compile(r"(?im)^\s*(?:[-*]\s*)?Decision:\s*IMPLEMENT\s*$")


def _json_objects(text: str):
    dec = json.JSONDecoder()
    pos = 0
    while True:
        start = text.find("{", pos)
        if start < 0:
            return
        try:
            obj, consumed = dec.raw_decode(text[start:])
        except json.JSONDecodeError:
            pos = start + 1
            continue
        pos = start + max(consumed, 1)
        if isinstance(obj, dict):
            yield obj


def _looks_like_plan(obj: dict) -> bool:
    return set(obj) == REQUIRED and obj.get("decision") in {"IMPLEMENT", "NO_CHANGE"}


def _write_and_validate(obj: dict, plan_path: Path, worktree: Path) -> dict:
    plan_path.write_text(json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n")
    try:
        return validate(plan_path, worktree)
    except Exception:
        plan_path.unlink(missing_ok=True)
        raise


def materialize(transcript_path: Path, plan_path: Path, worktree: Path) -> tuple[dict, str]:
    raw = transcript_path.read_bytes()
    if len(raw) > MAX_TRANSCRIPT_BYTES:
        raw = raw[-MAX_TRANSCRIPT_BYTES:]
    text = raw.decode("utf-8", errors="replace")

    # Prefer the last complete structured plan emitted by the model.
    structured = [obj for obj in _json_objects(text) if _looks_like_plan(obj)]
    last_error = None
    for obj in reversed(structured):
        try:
            return _write_and_validate(obj, plan_path, worktree), "transcript-json"
        except Exception as exc:  # keep looking for an earlier valid object
            last_error = exc

    # Conservative recovery only: an explicit NO_CHANGE is safe to synthesize.
    # Never infer IMPLEMENT from prose because that could authorize code changes.
    no_change = bool(DECISION_NO_CHANGE_RE.search(text))
    implement = bool(DECISION_IMPLEMENT_RE.search(text))
    if no_change and not implement:
        obj = {
            "decision": "NO_CHANGE",
            "summary": "Triage explicitly selected NO_CHANGE.",
            "problem": "No sufficiently justified low-risk implementation candidate was selected.",
            "fresh_evidence": "The current triage transcript exited cleanly and explicitly reported Decision: NO_CHANGE.",
            "files": [],
            "targeted_tests": [],
            "risk": "low",
            "expected_benefit": "Avoid speculative or unverified changes and preserve production safety.",
        }
        return _write_and_validate(obj, plan_path, worktree), "safe-no-change-fallback"

    if last_error is not None:
        raise ValueError(f"structured triage JSON was present but invalid: {last_error}")
    raise ValueError("no validated structured triage JSON and no unambiguous NO_CHANGE decision found")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--transcript", required=True)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--worktree", required=True)
    ns = ap.parse_args()
    try:
        data, source = materialize(Path(ns.transcript), Path(ns.plan), Path(ns.worktree))
    except Exception as exc:
        print(f"INVALID_TRIAGE_OUTPUT: {exc}")
        return 2
    print(json.dumps({"source": source, "plan": data}, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
