"""Tests for report_run_info: the hidden sheet Re-run missing reads back."""

from __future__ import annotations

import os

from openpyxl import Workbook, load_workbook

from report_run_info import (
    RUN_INFO_SHEET,
    merge_rerun_changes,
    read_run_info,
    write_run_info,
)


def _save(tmp_path, routes, changes):
    wb = Workbook()
    write_run_info(wb, routes, changes)
    path = tmp_path / "fare_report_2026-10-08_1200.xlsx"
    wb.save(path)
    return str(path)


def test_run_info_round_trips_routes_and_changes(tmp_path):
    changes = {"BS_DAC-BKK": {"Y": {"type": "increased", "new_ow_fare": 1800.0}}}
    path = _save(tmp_path, ["FZ_DAC-DXB", "BS_DAC-BKK"], changes)

    info = read_run_info(path)

    assert info["routes"] == ["BS_DAC-BKK", "FZ_DAC-DXB"]
    assert info["changes"] == changes


def test_run_info_sheet_is_hidden(tmp_path):
    path = _save(tmp_path, ["BS_DAC-BKK"], None)

    wb = load_workbook(path)

    assert wb[RUN_INFO_SHEET].sheet_state == "veryHidden"


def test_large_run_info_is_split_across_cells(tmp_path):
    changes = {
        f"BS_DAC-X{i:03d}": {"Y": {"type": "new", "note": "x" * 200}}
        for i in range(400)
    }
    path = _save(tmp_path, list(changes), changes)

    info = read_run_info(path)

    assert len(load_workbook(path)[RUN_INFO_SHEET]["A"]) > 1
    assert info["changes"] == changes


def test_report_without_run_info_returns_none(tmp_path):
    path = tmp_path / "old.xlsx"
    Workbook().save(path)

    assert read_run_info(str(path)) is None


def test_unreadable_report_returns_none(tmp_path):
    path = tmp_path / "broken.xlsx"
    path.write_text("not a workbook")

    assert read_run_info(str(path)) is None


def test_merge_keeps_original_markers_for_routes_not_rerun():
    original = {
        "BS_DAC-BKK": {"Y": {"type": "increased"}},
        "FZ_DAC-DXB": {"K": {"type": "new"}},
    }
    detected = {"BS_DAC-BKK": {"Y": {"type": "sold_out"}}}

    merged = merge_rerun_changes(original, detected, rerun_keys={"FZ_DAC-DXB"})

    assert merged == original


def test_merge_shows_new_changes_for_rerun_route_whose_fares_moved():
    original = {"FZ_DAC-DXB": {"K": {"type": "new"}}}
    detected = {"FZ_DAC-DXB": {"K": {"type": "decreased"}}}

    merged = merge_rerun_changes(original, detected, rerun_keys={"FZ_DAC-DXB"})

    assert merged == {"FZ_DAC-DXB": {"K": {"type": "decreased"}}}


def test_merge_keeps_original_markers_when_rerun_route_is_unchanged():
    original = {"FZ_DAC-DXB": {"K": {"type": "new"}}}

    merged = merge_rerun_changes(original, {}, rerun_keys={"FZ_DAC-DXB"})

    assert merged == original
    assert merged is not original


def test_backup_report_copies_into_backup_folder(tmp_path):
    from report_run_info import backup_report

    path = _save(tmp_path, ["BS_DAC-BKK"], None)

    dest = backup_report(path)

    assert os.path.dirname(dest) == str(tmp_path / "backup")
    assert os.path.basename(dest).startswith(
        "fare_report_2026-10-08_1200_before_rerun_"
    )
    assert read_run_info(dest)["routes"] == ["BS_DAC-BKK"]


def test_fare_report_stores_its_routes_and_changes(tmp_path):
    from excel_report import generate_report

    data = {
        "BS_DAC-BKK": {
            "rbd_data": {"Y": {"ow_fare": 1800, "rt_fare": 3000}},
            "currency": "BDT",
        }
    }
    changes = {"BS_DAC-BKK": {"Y": {"type": "new"}}}
    path = generate_report(data, str(tmp_path / "fare_report_x.xlsx"), changes, {})

    info = read_run_info(path)

    assert info["routes"] == ["BS_DAC-BKK"]
    assert info["changes"] == changes


def test_run_info_keeps_no_fare_routes(tmp_path):
    wb = Workbook()
    write_run_info(wb, ["BS_ZYL-DOH"], None, no_fare_routes={"BS_DOH-ZYL"})
    path = tmp_path / "r.xlsx"
    wb.save(path)

    assert read_run_info(str(path))["no_fares"] == ["BS_DOH-ZYL"]


def test_older_run_info_has_empty_no_fare_list(tmp_path):
    path = _save(tmp_path, ["BS_DAC-BKK"], None)
    wb = load_workbook(path)
    wb[RUN_INFO_SHEET]["A1"] = '{"version": 1, "routes": ["BS_DAC-BKK"]}'
    wb.save(path)

    assert read_run_info(path)["no_fares"] == []


def test_update_report_helper_rejects_old_or_missing_reports(tmp_path):
    import main

    old = tmp_path / "old.xlsx"
    Workbook().save(old)

    assert main._load_update_report(None) is None
    assert main._load_update_report(str(tmp_path / "nope.xlsx")) is None
    assert main._load_update_report(str(old)) is None
    assert main._load_update_report(_save(tmp_path, ["BS_DAC-BKK"], None))[
        "routes"
    ] == ["BS_DAC-BKK"]


def test_prepare_update_backs_up_and_returns_original_path(tmp_path):
    import main

    path = _save(tmp_path, ["BS_DAC-BKK"], None)

    out = main._prepare_report_update(path, str(tmp_path / "new.xlsx"))

    assert out == path
    assert len(os.listdir(tmp_path / "backup")) == 1


def test_prepare_update_falls_back_when_report_is_locked(tmp_path, monkeypatch):
    import builtins

    import main

    path = _save(tmp_path, ["BS_DAC-BKK"], None)
    real_open = builtins.open

    def locked_open(file, mode="r", *a, **kw):
        if str(file) == path and "+" in mode:
            raise PermissionError("open in Excel")
        return real_open(file, mode, *a, **kw)

    monkeypatch.setattr(builtins, "open", locked_open)

    out = main._prepare_report_update(path, str(tmp_path / "new.xlsx"))

    assert out == str(tmp_path / "new.xlsx")
    assert not (tmp_path / "backup").exists()
