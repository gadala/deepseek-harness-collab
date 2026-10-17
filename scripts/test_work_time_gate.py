"""Behavior tests for the read-only gate, not for Harness runtime enforcement."""
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import work_time_gate as gate


class WorkTimeGateTests(unittest.TestCase):
    def check(self, stamp, expected, directory=gate.DEFAULT_CALENDARS):
        result = gate.evaluate(datetime.fromisoformat(stamp), directory)
        self.assertEqual(result["status"], expected, result)
        return result

    def test_0900_start(self):
        self.check("2026-10-13T08:59:59+08:00", "allow")
        r = self.check("2026-10-13T09:00:00+08:00", "rest")
        self.assertEqual(r["resumeNotBefore"], "2026-10-13T12:00:00+08:00")

    def test_1200_end(self):
        self.check("2026-10-13T11:59:59+08:00", "rest")
        r = self.check("2026-10-13T12:00:00+08:00", "allow")
        self.assertEqual(r["nextCheckAt"], "2026-10-13T14:00:00+08:00")

    def test_1400_start(self):
        self.check("2026-10-13T13:59:59+08:00", "allow")
        r = self.check("2026-10-13T14:00:00+08:00", "rest")
        self.assertEqual(r["resumeNotBefore"], "2026-10-13T18:00:00+08:00")

    def test_1800_end(self):
        self.check("2026-10-13T17:59:59+08:00", "rest")
        self.check("2026-10-13T18:00:00+08:00", "allow")

    def test_lunch_and_night(self):
        for time in ("00:00:00", "12:30:00", "13:30:00", "19:00:00", "23:59:59"):
            with self.subTest(time=time):
                self.check(f"2026-10-13T{time}+08:00", "allow")

    def test_all_five_weekdays(self):
        for day in range(12, 17):
            for hour in (10, 15):
                with self.subTest(day=day,hour=hour):
                    self.check(f"2026-10-{day}T{hour}:00:00+08:00", "rest")

    def test_every_official_holiday_date(self):
        holidays, _ = gate.load_holidays(gate.DEFAULT_CALENDARS, 2026)
        self.assertIsNotNone(holidays)
        self.assertEqual(len(holidays), 33)
        for day in holidays:
            for hour in (10, 15):
                with self.subTest(day=day,hour=hour):
                    self.check(f"{day.isoformat()}T{hour}:00:00+08:00", "allow")

    def test_client_date_national_holiday(self):
        r = self.check("2026-10-05T10:00:00+08:00", "allow")
        self.assertEqual(r["reason"], "official_holiday")

    def test_ordinary_weekend(self):
        for day in ("2026-10-17", "2026-10-18"):
            self.check(f"{day}T10:00:00+08:00", "allow")

    def test_all_six_weekend_makeup_workdays(self):
        data = json.loads((gate.DEFAULT_CALENDARS / "china-holidays-2026.json").read_text(encoding="utf-8"))
        self.assertEqual(len(data["makeupWorkdays"]), 6)
        for day in data["makeupWorkdays"]:
            self.assertGreaterEqual(date.fromisoformat(day).weekday(), 5)
            self.check(f"{day}T15:00:00+08:00", "allow")

    def test_holiday_does_not_leak_to_adjacent_weekday(self):
        for day in ("2026-02-13", "2026-02-24", "2026-10-08"):
            self.check(f"{day}T10:00:00+08:00", "rest")

    def test_convert_utc_and_other_offset(self):
        r = self.check("2026-10-13T01:00:00+00:00", "rest")
        self.assertEqual(r["checkedAt"], "2026-10-13T09:00:00+08:00")
        self.check("2026-10-12T21:00:00-04:00", "rest")

    def test_naive_timestamp_not_accepted(self):
        with self.assertRaises(ValueError):
            gate.evaluate(datetime(2026,10,13,10))

    def test_missing_annual_calendar_only_holds_peak(self):
        self.check("2027-01-05T10:00:00+08:00", "hold_calendar_unknown")
        self.check("2027-01-05T12:00:00+08:00", "allow")
        self.check("2027-01-09T10:00:00+08:00", "allow")

    def test_missing_calendar_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.check("2026-10-13T10:00:00+08:00", "hold_calendar_unknown", Path(tmp))
            self.check("2026-10-13T18:00:00+08:00", "allow", Path(tmp))

    def test_invalid_calendar_fails_closed(self):
        original = json.loads((gate.DEFAULT_CALENDARS / "china-holidays-2026.json").read_text(encoding="utf-8"))
        bad_metadata = dict(original, year=2027)
        bad_source = dict(original, source={"url":"https://example.com/calendar"})
        bad_ranges = dict(original, holidayRanges=[{"start":"2026-10-07","end":"2026-10-01"}])
        empty_ranges = dict(original, holidayRanges=[])
        for bad in (bad_metadata, bad_source, bad_ranges, empty_ranges, [], None):
            with self.subTest(bad=bad):
                with tempfile.TemporaryDirectory() as tmp:
                    (Path(tmp)/"china-holidays-2026.json").write_text(json.dumps(bad),encoding="utf-8")
                    self.check("2026-10-13T10:00:00+08:00", "hold_calendar_unknown", Path(tmp))

    def test_malformed_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/"china-holidays-2026.json").write_text("{",encoding="utf-8")
            self.check("2026-10-13T10:00:00+08:00", "hold_calendar_unknown", Path(tmp))

    def test_cli_json_and_exit_codes(self):
        cases = [("2026-10-13T12:00:00+08:00",0,"allow"),
                 ("2026-10-13T10:00:00+08:00",10,"rest"),
                 ("2027-01-05T10:00:00+08:00",20,"hold_calendar_unknown"),
                 ("2026-10-13T10:00:00",30,"hold_clock_invalid"),
                 ("invalid",30,"hold_clock_invalid")]
        for stamp, code, status in cases:
            with self.subTest(stamp=stamp):
                proc = subprocess.run([sys.executable,"-B",str(Path(gate.__file__)),"--at",stamp],capture_output=True,text=True,encoding="utf-8")
                self.assertEqual(proc.returncode,code,proc.stderr)
                self.assertEqual(json.loads(proc.stdout)["status"],status)


if __name__ == "__main__":
    unittest.main(verbosity=2)
