#!/usr/bin/env python3
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time


def _send_group(proc: subprocess.Popen, signum: int) -> None:
    """Send a signal to the entire controlled child process tree."""
    if proc.poll() is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(proc.pid, signum)
        except ProcessLookupError:
            pass
    else:
        if signum == signal.SIGKILL:
            proc.kill()
        else:
            proc.terminate()


def _wait_briefly(proc: subprocess.Popen, seconds: float) -> bool:
    """Return True when proc exits within seconds, False otherwise."""
    end = time.monotonic() + max(0.0, seconds)
    while proc.poll() is None and time.monotonic() < end:
        time.sleep(0.05)
    return proc.poll() is not None


def main() -> int:
    if len(sys.argv) < 4 or sys.argv[2] != "--":
        print("usage: run_with_deadline.py SECONDS -- COMMAND [ARGS...]", file=sys.stderr)
        return 2

    try:
        timeout = float(sys.argv[1])
    except ValueError:
        print("invalid timeout", file=sys.stderr)
        return 2

    if timeout <= 0:
        print("timeout must be > 0", file=sys.stderr)
        return 2

    cmd = sys.argv[3:]
    if not cmd:
        return 2

    # Put the controlled command into a separate session/process group. This
    # lets us terminate Hermes plus any subprocesses it launched without
    # signalling the controller shell itself.
    kwargs = {"start_new_session": True} if os.name == "posix" else {}
    proc = subprocess.Popen(cmd, **kwargs)

    received_signal = [None]
    previous = {}

    def handle_signal(signum, _frame):
        # Keep signal handlers simple and exception-free. Raising exceptions
        # from a Python signal handler is not reliably portable across the
        # Apple system Python versions we support. Record the signal and
        # forward it immediately to the controlled child process group.
        received_signal[0] = signum
        _send_group(proc, signum)

    signals = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGHUP"):
        signals.append(signal.SIGHUP)
    for sig in signals:
        previous[sig] = signal.signal(sig, handle_signal)

    deadline = time.monotonic() + timeout

    try:
        while True:
            rc = proc.poll()
            if rc is not None:
                if received_signal[0] is not None:
                    return 128 + int(received_signal[0])
                return int(rc)

            if received_signal[0] is not None:
                signum = int(received_signal[0])
                # The signal was already forwarded by the handler. Give the
                # whole child group a bounded grace period, then force-kill it.
                if not _wait_briefly(proc, 10.0):
                    _send_group(proc, signal.SIGKILL)
                    proc.wait()
                return 128 + signum

            now = time.monotonic()
            if now >= deadline:
                print(
                    f"DEADLINE_EXCEEDED after {timeout:g}s: {' '.join(cmd)}",
                    file=sys.stderr,
                )
                _send_group(proc, signal.SIGTERM)
                if not _wait_briefly(proc, 10.0):
                    _send_group(proc, signal.SIGKILL)
                proc.wait()
                return 124

            time.sleep(min(0.1, max(0.01, deadline - now)))
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    raise SystemExit(main())
