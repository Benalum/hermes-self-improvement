#!/usr/bin/env python3
"""Validate that a locally installed Ollama model advertises enough context.

This checks model metadata only (the `context length` reported by `ollama show`).
It intentionally does not modify Ollama settings or Hermes configuration.
"""
import argparse
import re
import subprocess
import sys
from typing import Optional


def parse_context_length(text: str) -> Optional[int]:
    m = re.search(r"(?im)^\s*context\s+length\s+([0-9][0-9,]*)\s*$", text)
    if not m:
        return None
    return int(m.group(1).replace(",", ""))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--minimum", type=int, default=64000)
    ap.add_argument("--ollama-bin", default="ollama")
    ns = ap.parse_args()

    try:
        cp = subprocess.run(
            [ns.ollama_bin, "show", ns.model],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"ERROR: unable to inspect Ollama model {ns.model}: {exc}", file=sys.stderr)
        return 2

    if cp.returncode != 0:
        detail = (cp.stdout or "").strip()
        print(f"ERROR: ollama show failed for {ns.model}: {detail}", file=sys.stderr)
        return 2

    ctx = parse_context_length(cp.stdout or "")
    if ctx is None:
        print(f"ERROR: could not parse context length from 'ollama show {ns.model}'", file=sys.stderr)
        return 2

    print(f"{ns.model}\t{ctx}")
    if ctx < ns.minimum:
        print(
            f"ERROR: {ns.model} advertises context length {ctx}, below Hermes minimum {ns.minimum}.",
            file=sys.stderr,
        )
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
