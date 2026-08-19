# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Terminal keyboard input utilities.
"""
from __future__ import annotations

import select
import sys
import termios
import time
import tty

# ANSI color codes
_BOLD = "\033[1m"
_RESET = "\033[0m"


class KeyPoller:
    """
    Non-blocking terminal keypress poller (context manager).

    Uses stdlib-only implementation (no external dependencies).

    Example:
        with KeyPoller() as keys:
            while True:
                ch = keys.poll_char()
                if ch == " ":
                    print("Space pressed!")
                elif ch == "\\x1b":  # ESC
                    break
                time.sleep(0.05)

    Keys:
        - SPACE: ' '
        - ESC: '\\x1b'
        - Enter: '\\n' or '\\r'
    """

    def __init__(self) -> None:
        self._fd: int | None = None
        self._old: list[int] | None = None

    def __enter__(self) -> "KeyPoller":
        if sys.stdin.isatty():
            self._fd = sys.stdin.fileno()
            self._old = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)  # immediate keypresses (no Enter)
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        if self._fd is not None and self._old is not None:
            try:
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old)
            except Exception:
                pass
        self._fd = None
        self._old = None

    def poll_char(self) -> str | None:
        """
        Return one character if available, else None.

        Non-blocking: returns immediately if no key is pressed.
        """
        if self._fd is None:
            return None
        try:
            r, _w, _x = select.select([sys.stdin], [], [], 0.0)
            if not r:
                return None
            ch = sys.stdin.read(1)
            return ch if ch != "" else None
        except Exception:
            return None

    def is_available(self) -> bool:
        """Return True if keyboard polling is available (stdin is a TTY)."""
        return self._fd is not None


# ── Terminal prompts (require an active KeyPoller context) ──────────────────

def prompt_valid(keys: KeyPoller) -> bool | None:
    """Prompt for valid/invalid episode. Returns True, False, or None if skipped."""
    print(f"{_BOLD}valid?{_RESET} [y/n/enter=skip]: ", end="", flush=True)
    while True:
        ch = keys.poll_char()
        if ch is None:
            time.sleep(0.02)
            continue
        if ch.lower() == "y":
            print("yes")
            return True
        elif ch.lower() == "n":
            print("no")
            return False
        elif ch in ("\r", "\n"):
            print("(skipped)")
            return None


def prompt_success(keys: KeyPoller) -> bool | None:
    """Prompt for success/fail. Returns True, False, or None if skipped."""
    print(f"{_BOLD}success?{_RESET} [y/n/enter=skip]: ", end="", flush=True)
    while True:
        ch = keys.poll_char()
        if ch is None:
            time.sleep(0.02)
            continue
        if ch.lower() == "y":
            print("yes")
            return True
        elif ch.lower() == "n":
            print("no")
            return False
        elif ch in ("\r", "\n"):
            print("(skipped)")
            return None


def prompt_score(keys: KeyPoller) -> float | None:
    """Prompt for numeric score. Temporarily restores normal terminal mode."""
    if keys._fd is not None and keys._old is not None:
        termios.tcsetattr(keys._fd, termios.TCSADRAIN, keys._old)
    try:
        text = input(f"{_BOLD}score?{_RESET} [number/enter=skip]: ")
        if text.strip():
            try:
                return float(text.strip())
            except ValueError:
                print(f"(invalid number: {text!r}, skipped)")
                return None
        else:
            print("(skipped)")
            return None
    except (EOFError, KeyboardInterrupt):
        print("(skipped)")
        return None
    finally:
        if keys._fd is not None:
            tty.setcbreak(keys._fd)


def prompt_text(keys: KeyPoller, prompt: str) -> str | None:
    """Prompt for free-form text. Temporarily restores normal terminal mode."""
    if keys._fd is not None and keys._old is not None:
        termios.tcsetattr(keys._fd, termios.TCSADRAIN, keys._old)
    try:
        text = input(f"{_BOLD}{prompt}{_RESET} [text/enter=skip]: ")
        if text.strip():
            return text.strip()
        else:
            print("(skipped)")
            return None
    except (EOFError, KeyboardInterrupt):
        print("(skipped)")
        return None
    finally:
        if keys._fd is not None:
            tty.setcbreak(keys._fd)
