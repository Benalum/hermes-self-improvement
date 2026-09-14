"""Load the exact v3.19 controller regression corpus from transport fragments.

The GitHub connector used to seed this public repository accepts UTF-8 text payloads
but not a local source-file upload. The original 110,071-byte v3.19 test module is
therefore stored as line-boundary fragments under ``test_controller_v2.parts``.

Before executing anything, this loader verifies both the exact byte length and the
SHA-256 of the concatenated original source. A missing, reordered, truncated, or
modified fragment fails closed.
"""
from pathlib import Path
import hashlib as _hashlib

_parts_dir = Path(__file__).with_name("test_controller_v2.parts")
_parts = sorted(_parts_dir.glob("part[0-9][0-9]"))
if len(_parts) != 10:
    raise RuntimeError(f"controller regression corpus part count mismatch: {len(_parts)} != 10")

_source = b"".join(p.read_bytes() for p in _parts)
_expected_len = 110071
if len(_source) != _expected_len:
    raise RuntimeError(
        f"controller regression corpus length mismatch: {len(_source)} != {_expected_len}"
    )

_expected_sha256 = "b7ce618d1670259e59e54f71bd55644da67ac436e1d54d6fb2a89b348b619d0a"
_actual_sha256 = _hashlib.sha256(_source).hexdigest()
if _actual_sha256 != _expected_sha256:
    raise RuntimeError(
        "controller regression corpus hash mismatch: "
        f"{_actual_sha256} != {_expected_sha256}"
    )

exec(compile(_source, str(__file__), "exec"), globals(), globals())
