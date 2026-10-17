"""The profiler is a collector, not fabricated hardware evidence."""

import importlib.util
from pathlib import Path

_path = Path(__file__).resolve().parents[1] / "tools/android/profile_voice_session.py"
_spec = importlib.util.spec_from_file_location("profile_voice_session", _path)
assert _spec and _spec.loader
profiler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(profiler)


def test_sample_reports_only_resource_fields(monkeypatch):
    reports = {
        ("dumpsys", "battery"): "  level: 83\n  temperature: 318\n",
        ("dumpsys", "meminfo", "app.reva"): " TOTAL 123456 1 2\n",
        ("dumpsys", "cpuinfo"): "  8.2% 444/app.reva: 5% user\n",
        ("dumpsys", "thermalservice"): "Thermal Status: 2\n",
    }
    monkeypatch.setattr(profiler, "adb", lambda _serial, *args: reports[args])

    result = profiler.sample("physical-phone")

    assert result["battery_percent"] == 83
    assert result["battery_temperature_tenths_c"] == 318
    assert result["total_pss_kb"] == 123456
    assert result["cpu_percent_dumpsys_window"] == 8.2
    assert result["thermal_status"] == 2
    assert set(result) == {
        "recorded_at_utc",
        "battery_percent",
        "battery_temperature_tenths_c",
        "total_pss_kb",
        "cpu_percent_dumpsys_window",
        "thermal_status",
    }
