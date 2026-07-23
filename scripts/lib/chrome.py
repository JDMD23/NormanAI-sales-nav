"""Drive JD's real logged-in Chrome via AppleScript, crm-core LinkedIn-lane style.

Reads only. Raises DependencyError on auth walls so the run stops (lane outcome: retry).
"""

from __future__ import annotations

import json
import subprocess
import time


class DependencyError(RuntimeError):
    pass


AUTH_WALL_MARKERS = (
    "checkpoint/challenge",
    "linkedin.com/uas/login",
    "linkedin.com/authwall",
    "Sign in to LinkedIn",
)


def _osascript(script: str, *, timeout: int = 30) -> str:
    proc = subprocess.run(
        ["osascript"], input=script, text=True, capture_output=True, timeout=timeout
    )
    if proc.returncode != 0:
        raise DependencyError(f"Chrome AppleScript failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def open_url(url: str) -> None:
    script = f'''
    tell application "Google Chrome"
        activate
        if (count of windows) = 0 then make new window
        set URL of active tab of front window to {json.dumps(url)}
    end tell
    '''
    _osascript(script)


def run_js(js_expr: str) -> str:
    """Evaluate a JS expression in the active tab; returns its string result."""
    script = f'''
    tell application "Google Chrome"
        execute active tab of front window javascript {json.dumps(js_expr)}
    end tell
    '''
    return _osascript(script)


def current_title_url() -> tuple[str, str]:
    script = '''
    tell application "Google Chrome"
        set t to title of active tab of front window
        set u to URL of active tab of front window
        return t & "\\n" & u
    end tell
    '''
    out = _osascript(script, timeout=15)
    parts = out.split("\n", 1)
    return (parts[0], parts[1] if len(parts) > 1 else "")


def body_text() -> str:
    return run_js("document.body ? document.body.innerText : ''")


def body_html() -> str:
    return run_js("document.body ? document.body.outerHTML : ''")


def assert_logged_in() -> None:
    _title, url = current_title_url()
    text = body_text()
    for marker in AUTH_WALL_MARKERS:
        if marker in url or marker in text:
            raise DependencyError(f"Sales Nav auth wall detected ({marker}) — stopping run (retry later)")


def read_body_until(predicate, *, timeout_seconds: int = 15, interval_seconds: float = 2.0) -> str:
    """Poll body text until predicate(text) is truthy or timeout; returns last text."""
    deadline = time.monotonic() + timeout_seconds
    text = ""
    while time.monotonic() < deadline:
        text = body_text()
        if predicate(text):
            return text
        time.sleep(interval_seconds)
    return text
