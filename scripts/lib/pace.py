"""Human pacing for Sales Nav lane. Config: config/pace.json (crm-core shape)."""

from __future__ import annotations

import json
import random
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "pace.json"

_CACHE: dict | None = None


def load() -> dict:
    global _CACHE
    if _CACHE is None:
        _CACHE = json.loads(CONFIG_PATH.read_text())["salesnav"]
    return _CACHE


def _sleep(lo: float, jitter: float) -> float:
    seconds = max(0.0, lo) + random.uniform(0.0, max(0.0, jitter))
    time.sleep(seconds)
    return seconds


def pause_navigation() -> float:
    cfg = load()
    return _sleep(cfg["minNavigationWaitSeconds"], cfg["maxNavigationJitterSeconds"])


def pause_between_companies() -> float:
    cfg = load()
    return _sleep(cfg["betweenCompaniesMinSeconds"], cfg["betweenCompaniesJitterSeconds"])


def pause_between_lead_pages() -> float:
    cfg = load()
    return _sleep(cfg["betweenLeadPagesMinSeconds"], cfg["betweenLeadPagesJitterSeconds"])


def batch_limit() -> int:
    return int(load()["batchLimit"])


# --- daily budget -----------------------------------------------------------
# dailyCompanyCap sat in pace.json and no code ever read it. On 2026-07-25 that
# let six back-to-back runs put 397 companies (>1000 page loads) through JD's
# seat in a day against a configured cap of 25, and LinkedIn noticed. The seat
# is the scarce, unreplaceable resource in this system — a cap that is not
# enforced in code is not a cap.

_LEDGER = ROOT / "state" / "daily_scans.json"


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def scans_today() -> int:
    try:
        d = json.loads(_LEDGER.read_text())
    except Exception:
        return 0
    return int(d.get(_today(), 0))


def remaining_today() -> int:
    return max(0, int(load()["dailyCompanyCap"]) - scans_today())


def record_scan() -> None:
    try:
        d = json.loads(_LEDGER.read_text())
    except Exception:
        d = {}
    d = {k: v for k, v in d.items() if k >= _today()}   # keep today onward only
    d[_today()] = d.get(_today(), 0) + 1
    _LEDGER.parent.mkdir(parents=True, exist_ok=True)
    _LEDGER.write_text(json.dumps(d, indent=1, sort_keys=True))


class DailyCapReached(RuntimeError):
    pass


def check_budget() -> None:
    if remaining_today() <= 0:
        raise DailyCapReached(
            f"daily cap of {load()['dailyCompanyCap']} companies reached "
            f"({scans_today()} scanned today). Resumes tomorrow.")
