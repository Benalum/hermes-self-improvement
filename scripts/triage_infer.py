#!/usr/bin/env python3
"""Run the read-only discovery model directly through local Ollama.

No Hermes agent and no tools are involved. The controller supplies all evidence in
one prompt and Ollama constrains the answer to the exact triage JSON schema.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

MAX_PROMPT_BYTES = 256 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
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
SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["IMPLEMENT", "NO_CHANGE"]},
        "summary": {"type": "string"},
        "problem": {"type": "string"},
        "fresh_evidence": {"type": "string"},
        "files": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
        "targeted_tests": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
        "risk": {"type": "string", "enum": ["low"]},
        "expected_benefit": {"type": "string"},
    },
    "required": sorted(REQUIRED),
    "additionalProperties": False,
}


def _local_endpoint(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"}


def _validate_shape(obj: object) -> dict:
    if not isinstance(obj, dict) or set(obj) != REQUIRED:
        raise ValueError("response must contain exactly the required triage keys")
    if obj.get("decision") not in {"IMPLEMENT", "NO_CHANGE"}:
        raise ValueError("invalid decision")
    if obj.get("risk") != "low":
        raise ValueError("triage risk must be low")
    for key in ("summary", "problem", "fresh_evidence", "expected_benefit"):
        if not isinstance(obj.get(key), str) or not obj[key].strip():
            raise ValueError(f"{key} must be a non-empty string")
    if not isinstance(obj.get("files"), list) or not all(isinstance(x, str) for x in obj["files"]):
        raise ValueError("files must be an array of strings")
    if not isinstance(obj.get("targeted_tests"), list) or not all(isinstance(x, str) for x in obj["targeted_tests"]):
        raise ValueError("targeted_tests must be an array of strings")
    return obj


def infer(model: str, prompt: str, endpoint: str, timeout: int) -> dict:
    if not _local_endpoint(endpoint):
        raise ValueError("triage endpoint must resolve to loopback/local Ollama")
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a read-only software triage classifier. You have no tools. "
                    "Use only the evidence in the user prompt. Return exactly the JSON object "
                    "required by the supplied schema. Prefer NO_CHANGE when evidence is incomplete."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "think": False,
        "format": SCHEMA,
        "options": {"temperature": 0, "seed": 1, "num_predict": 1200},
        "keep_alive": "5m",
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(endpoint, data=raw, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=max(1, timeout)) as resp:
            body = resp.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        detail = exc.read(4096).decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise RuntimeError(f"Ollama request failed: {exc}") from exc
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("Ollama response exceeded controller limit")
    outer = json.loads(body.decode("utf-8"))
    content = ((outer.get("message") or {}).get("content") or "").strip()
    if not content:
        raise ValueError("Ollama returned no structured content")
    return _validate_shape(json.loads(content))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--prompt-file", required=True)
    ap.add_argument("--endpoint", default=os.environ.get("TRIAGE_OLLAMA_URL", "http://127.0.0.1:11434/api/chat"))
    ap.add_argument("--timeout", type=int, default=120)
    ns = ap.parse_args()
    try:
        prompt_path = Path(ns.prompt_file)
        raw = prompt_path.read_bytes()
        if len(raw) > MAX_PROMPT_BYTES:
            raise ValueError(f"triage prompt exceeds {MAX_PROMPT_BYTES} bytes")
        obj = infer(ns.model, raw.decode("utf-8"), ns.endpoint, ns.timeout)
    except Exception as exc:
        print(f"TRIAGE_INFERENCE_ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(obj, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
