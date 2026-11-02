"""Re-run / Resume reports bring in saved screens for routes they need."""

import os
import time

import main


def _write(raw_dir, name, text, age_hours=0.0):
    path = raw_dir / name
    path.write_text(text, encoding="utf-8")
    stamp = time.time() - age_hours * 3600
    os.utime(path, (stamp, stamp))


def test_adds_fresh_return_routes_and_resumed_routes(tmp_path):
    _write(tmp_path, "FZ_DAC-DXB.txt", "FD dac-dxb")
    _write(tmp_path, "FZ_DAC-DXB_FS.txt", "FS dac-dxb")
    _write(tmp_path, "BS_DAC-DXB.txt", "FD bs dac-dxb")
    raw, fs = {"FZ_DXB-DAC": "FD dxb-dac"}, {"FZ_DXB-DAC": "FS dxb-dac"}

    added = main._add_saved_companion_routes(
        raw, fs, completed_commands=["FDDACDXB/BS"], raw_dir=str(tmp_path)
    )

    assert added == ["BS_DAC-DXB", "FZ_DAC-DXB"]
    assert raw["FZ_DAC-DXB"] == "FD dac-dxb" and fs["FZ_DAC-DXB"] == "FS dac-dxb"
    assert raw["BS_DAC-DXB"] == "FD bs dac-dxb" and "BS_DAC-DXB" not in fs


def test_skips_stale_saved_screens_and_keeps_run_data(tmp_path):
    _write(tmp_path, "FZ_DAC-DXB.txt", "old", age_hours=30)
    _write(tmp_path, "FZ_DXB-DAC.txt", "saved copy")
    raw = {"FZ_DXB-DAC": "this run"}

    added = main._add_saved_companion_routes(raw, {}, raw_dir=str(tmp_path))

    assert added == []
    assert raw == {"FZ_DXB-DAC": "this run"}


def test_report_routes_are_loaded_whatever_their_age(tmp_path):
    _write(tmp_path, "BS_DAC-BKK.txt", "FD bs", age_hours=30)
    _write(tmp_path, "BS_DAC-BKK_FS.txt", "FS bs", age_hours=30)
    raw, fs = {"FZ_DAC-DXB": "this run"}, {}

    added = main._add_saved_companion_routes(
        raw, fs, report_routes=["BS_DAC-BKK", "FZ_DAC-DXB"], raw_dir=str(tmp_path)
    )

    assert added == ["BS_DAC-BKK"]
    assert raw["BS_DAC-BKK"] == "FD bs" and fs["BS_DAC-BKK"] == "FS bs"
    assert raw["FZ_DAC-DXB"] == "this run"


def test_skips_tax_screen_older_than_its_fare_screen(tmp_path):
    # An FS screen left over from an earlier run must not fill in taxes the
    # later run failed to capture.
    _write(tmp_path, "BS_DAC-BKK_FS.txt", "old FS", age_hours=5)
    _write(tmp_path, "BS_DAC-BKK.txt", "FD bs", age_hours=1)
    raw, fs = {}, {}

    added = main._add_saved_companion_routes(
        raw, fs, report_routes=["BS_DAC-BKK"], raw_dir=str(tmp_path)
    )

    assert added == ["BS_DAC-BKK"]
    assert "BS_DAC-BKK" not in fs
