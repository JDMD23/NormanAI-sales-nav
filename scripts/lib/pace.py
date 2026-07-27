"""Human pacing for Sales Nav lane. Config: config/pace.json (crm-core shape)."""

from __future__ import annotations

import fcntl
import json
import os
import random
import tempfile
import time
from contextlib import contextmanager
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
_LEDGER_LOCK = ROOT / "state" / "daily_scans.lock"


def _today() -> str:
    return time.strftime("%Y-%m-%d")


class DailyCapReached(RuntimeError):
    pass


class DailyLedgerError(RuntimeError):
    pass


def _read_ledger() -> dict:
    try:
        raw = _LEDGER.read_text()
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise DailyLedgerError(f"cannot read daily scan ledger: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DailyLedgerError(
            "daily scan ledger is corrupt; refusing to reset the safety cap"
        ) from exc
    if not isinstance(data, dict):
        raise DailyLedgerError("daily scan ledger must contain a JSON object")
    return data


def _count_today(data: dict) -> int:
    try:
        count = int(data.get(_today(), 0))
    except (TypeError, ValueError) as exc:
        raise DailyLedgerError("today's daily scan count is invalid") from exc
    if count < 0:
        raise DailyLedgerError("today's daily scan count cannot be negative")
    return count


@contextmanager
def _locked_ledger():
    _LEDGER_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with _LEDGER_LOCK.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _write_ledger(data: dict) -> None:
    _LEDGER.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=_LEDGER.parent,
            prefix=f".{_LEDGER.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp_name = tmp.name
            json.dump(data, tmp, indent=1, sort_keys=True)
            tmp.write("\n")
            tmp.flush()
            os.fsync(tmp.fileno())
        Path(tmp_name).replace(_LEDGER)
    finally:
        if tmp_name:
            Path(tmp_name).unlink(missing_ok=True)


def scans_today() -> int:
    with _locked_ledger():
        return _count_today(_read_ledger())


def remaining_today() -> int:
    return max(0, int(load()["dailyCompanyCap"]) - scans_today())


def claim_scan() -> int:
    """Atomically reserve one company scan and return today's new total."""
    with _locked_ledger():
        data = _read_ledger()
        count = _count_today(data)
        cap = int(load()["dailyCompanyCap"])
        if count >= cap:
            raise DailyCapReached(
                f"daily cap of {cap} companies reached "
                f"({count} scanned today). Resumes tomorrow."
            )
        data = {k: v for k, v in data.items() if k >= _today()}
        data[_today()] = count + 1
        _write_ledger(data)
        return count + 1
