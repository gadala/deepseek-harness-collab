#!/usr/bin/env python3
"""Read-only Harness dispatch gate. No networking, launching, waiting or scheduling."""
from __future__ import annotations
import argparse
import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

BEIJING = timezone(timedelta(hours=8), name="Asia/Shanghai")
DEFAULT_CALENDARS = Path(__file__).resolve().parents[1] / "assets" / "calendars"
REST_WINDOWS = ((time(9), time(12)), (time(14), time(18)))
EXIT_CODES = {"allow": 0, "rest": 10, "hold_calendar_unknown": 20, "hold_clock_invalid": 30}


def load_holidays(directory: Path, year: int) -> tuple[set[date] | None, str]:
    path = directory / f"china-holidays-{year}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if (data["schemaVersion"] != 1 or data["year"] != year
                or data["timezone"] != "Asia/Shanghai"):
            raise ValueError("calendar metadata mismatch")
        host = urlparse(data["source"]["url"]).hostname or ""
        if not (host == "gov.cn" or host.endswith(".gov.cn")):
            raise ValueError("missing government-source provenance")
        date.fromisoformat(data["verifiedOn"])
        entries = data["holidayRanges"]
        if not isinstance(entries, list) or not entries:
            raise ValueError("missing annual holiday arrangement")
        holidays: set[date] = set()
        for entry in entries:
            start, end = date.fromisoformat(entry["start"]), date.fromisoformat(entry["end"])
            if start.year != year or end.year != year or start > end:
                raise ValueError("invalid holiday range")
            while start <= end:
                if start in holidays:
                    raise ValueError("overlapping holiday ranges")
                holidays.add(start)
                start += timedelta(days=1)
        return holidays, str(path)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None, str(path)


def evaluate(at: datetime, calendar_dir: Path = DEFAULT_CALENDARS) -> dict:
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("an aware timestamp is required")
    now = at.astimezone(BEIJING)
    result = {"status": "allow", "timezone": "Asia/Shanghai", "checkedAt": now.isoformat(),
              "reason": "outside_rest_windows", "resumeNotBefore": None,
              "calendarEvidence": None, "nextCheckAt": None}
    if now.weekday() >= 5:
        result["reason"] = "weekend_even_if_makeup_workday"
        return result
    current = now.time()
    window = next(((start, end) for start, end in REST_WINDOWS if start <= current < end), None)
    if window is None:
        upcoming = next((start for start, _ in REST_WINDOWS if start > current), None)
        if upcoming:
            result["nextCheckAt"] = datetime.combine(now.date(), upcoming, BEIJING).isoformat()
        return result
    holidays, evidence = load_holidays(calendar_dir, now.year)
    result["calendarEvidence"] = evidence
    if holidays is not None and now.date() in holidays:
        result["reason"] = "official_holiday"
        return result
    result["resumeNotBefore"] = datetime.combine(now.date(), window[1], BEIJING).isoformat()
    if holidays is None:
        result.update(status="hold_calendar_unknown", reason="verify_official_calendar_before_dispatch")
    else:
        result.update(status="rest", reason="weekday_nonholiday_peak")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--at", help="Aware ISO timestamp for testing/replay ONLY; omit for live dispatch.")
    parser.add_argument("--calendar-dir", type=Path, default=DEFAULT_CALENDARS)
    args = parser.parse_args()
    try:
        at = datetime.fromisoformat(args.at) if args.at else datetime.now(timezone.utc)
        result = evaluate(at, args.calendar_dir)
    except ValueError:
        result = {"status": "hold_clock_invalid", "timezone": "Asia/Shanghai",
                  "reason": "invalid_or_naive_timestamp_do_not_dispatch"}
    print(json.dumps(result, ensure_ascii=False))
    return EXIT_CODES[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
