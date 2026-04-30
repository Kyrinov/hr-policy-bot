#!/usr/bin/env python3
"""
opencode_watcher.py — Wrap OpenCode and inject 'continue' when it stalls.

Run this instead of opencode directly. Your terminal works normally and
the watcher automatically sends 'continue' if OpenCode goes quiet.

Usage:
    python3 scripts/opencode_watcher.py
    python3 scripts/opencode_watcher.py --timeout 300
    python3 scripts/opencode_watcher.py -- opencode --some-flag
"""

import argparse
import fcntl
import os
import pty
import select
import signal
import struct
import sys
import termios
import time
import tty

DEFAULT_TIMEOUT = 300  # 5 minutes
NUDGE = b"continue\r"


def get_terminal_size() -> tuple[int, int]:
    try:
        cols, rows = os.get_terminal_size(sys.stdout.fileno())
        return rows, cols
    except OSError:
        return 24, 80


def set_terminal_size(fd: int) -> None:
    rows, cols = get_terminal_size()
    size = struct.pack("HHHH", rows, cols, 0, 0)
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, size)
    except OSError:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Wrap OpenCode and send 'continue' automatically when it stalls."
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        metavar="SECONDS",
        help=f"Seconds of silence before sending 'continue' (default: {DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Command to run (default: opencode)",
    )
    args = parser.parse_args()

    cmd = [c for c in args.command if c != "--"] or ["opencode"]

    master_fd, slave_fd = pty.openpty()
    set_terminal_size(slave_fd)

    pid = os.fork()
    if pid == 0:
        # Child process: become opencode
        os.close(master_fd)
        os.setsid()
        fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
        for fd in (0, 1, 2):
            os.dup2(slave_fd, fd)
        if slave_fd > 2:
            os.close(slave_fd)
        os.execvp(cmd[0], cmd)
        sys.exit(1)

    # Parent process: relay I/O and watch for idleness
    os.close(slave_fd)

    # Propagate terminal resize to the child
    def handle_sigwinch(signum, frame):
        set_terminal_size(master_fd)

    signal.signal(signal.SIGWINCH, handle_sigwinch)

    # Put our terminal in raw mode so all keystrokes pass through unmodified
    stdin_fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(stdin_fd)
    tty.setraw(stdin_fd)

    last_activity = time.monotonic()
    nudge_count = 0

    try:
        while True:
            wpid, _ = os.waitpid(pid, os.WNOHANG)
            if wpid != 0:
                break

            idle = time.monotonic() - last_activity
            wait = min(1.0, max(0.05, args.timeout - idle))

            try:
                readable, _, _ = select.select([master_fd, stdin_fd], [], [], wait)
            except (ValueError, InterruptedError):
                break

            if master_fd in readable:
                try:
                    data = os.read(master_fd, 4096)
                    if data:
                        os.write(sys.stdout.fileno(), data)
                        last_activity = time.monotonic()
                        nudge_count = 0
                except OSError:
                    break

            if stdin_fd in readable:
                try:
                    data = os.read(stdin_fd, 1024)
                    if data:
                        os.write(master_fd, data)
                        last_activity = time.monotonic()
                except OSError:
                    break

            if time.monotonic() - last_activity >= args.timeout:
                nudge_count += 1
                msg = f"\r\n[watcher] idle {args.timeout}s — sending 'continue' (nudge #{nudge_count})\r\n"
                os.write(sys.stderr.fileno(), msg.encode())
                try:
                    os.write(master_fd, NUDGE)
                except OSError:
                    break
                last_activity = time.monotonic()

    finally:
        termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_settings)
        try:
            os.close(master_fd)
        except OSError:
            pass
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


if __name__ == "__main__":
    main()
