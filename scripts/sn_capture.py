#!/usr/bin/env python3
"""Capture Sales Nav pages from JD's logged-in Chrome for parser development.

Usage:
  python3 scripts/sn_capture.py --url "https://www.linkedin.com/sales/company/..." --label acme-account
  python3 scripts/sn_capture.py --current --label acme-lead   # capture whatever tab is frontmost

Writes state/captures/<timestamp>-<label>.{txt,html,meta.json}. Never writes to Notion.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import chrome, pace  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CAPTURE_DIR = ROOT / "state" / "captures"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", help="Navigate to this URL first")
    ap.add_argument("--current", action="store_true", help="Capture the current front tab as-is")
    ap.add_argument("--label", required=True, help="Short slug for the capture filenames")
    args = ap.parse_args()

    if not args.url and not args.current:
        ap.error("need --url or --current")

    if args.url:
        chrome.open_url(args.url)
        pace.pause_navigation()

    chrome.assert_logged_in()
    title, url = chrome.current_title_url()
    text = chrome.read_body_until(lambda t: len(t) > 500)
    html = chrome.body_html()

    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = CAPTURE_DIR / f"{stamp}-{args.label}"
    base.with_suffix(".txt").write_text(text)
    base.with_suffix(".html").write_text(html)
    base.with_suffix(".meta.json").write_text(
        json.dumps({"title": title, "url": url, "captured_at": stamp}, indent=2)
    )
    print(f"captured: {base}.{{txt,html,meta.json}}  ({len(text)} chars text, {len(html)} chars html)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
