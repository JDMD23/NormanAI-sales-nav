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
