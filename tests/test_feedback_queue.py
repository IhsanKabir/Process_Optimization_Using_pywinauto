import json
import shutil
from pathlib import Path

import pytest

import feedback_queue as fq


def _make_local_temp_dir(name: str) -> Path:
    path = Path.cwd() / name
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


@pytest.fixture()
def isolated_queue(monkeypatch):
    """Redirect APPDATA to a local temp dir for each test."""
    tmp = _make_local_temp_dir("tmp_feedback_queue_test")
    monkeypatch.setenv("APPDATA", str(tmp))
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


def test_enqueue_then_load_roundtrip(isolated_queue):
    payload = {"subject": "hello", "message": "world"}
    fq.enqueue_feedback(payload)
    entries = fq._load_queue()
    assert entries == [payload]


def test_enqueue_cap_drops_oldest(isolated_queue):
    for i in range(55):
        fq.enqueue_feedback({"idx": i})
    entries = fq._load_queue()
    assert len(entries) == 50
    assert entries[0]["idx"] == 5   # oldest 5 dropped
    assert entries[-1]["idx"] == 54


def test_malformed_json_does_not_crash(isolated_queue):
    queue_path = fq._queue_path()
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    queue_path.write_text("NOT VALID JSON", encoding="utf-8")
    assert fq._load_queue() == []


def test_drain_sends_all_on_success(isolated_queue):
    for i in range(3):
        fq.enqueue_feedback({"idx": i})

    submitted = []
    sent, remaining = fq.drain_feedback_queue(lambda p: submitted.append(p))

    assert sent == 3
    assert remaining == 0
    assert fq._load_queue() == []


def test_drain_keeps_failed_entries(isolated_queue):
    for i in range(4):
        fq.enqueue_feedback({"idx": i})

    def _fail_odd(payload):
        if payload["idx"] % 2 != 0:
            raise RuntimeError("simulated failure")

    sent, remaining = fq.drain_feedback_queue(_fail_odd)

    assert sent == 2
    assert remaining == 2
    leftover = fq._load_queue()
    assert all(e["idx"] % 2 != 0 for e in leftover)


def test_drain_empty_queue_returns_zeros(isolated_queue):
    sent, remaining = fq.drain_feedback_queue(lambda p: None)
    assert sent == 0
    assert remaining == 0


def test_enqueue_creates_directory_if_missing(isolated_queue):
    fq.enqueue_feedback({"subject": "test"})
    assert fq._queue_path().exists()


def test_second_enqueue_appends_not_overwrites(isolated_queue):
    fq.enqueue_feedback({"n": 1})
    fq.enqueue_feedback({"n": 2})
    entries = fq._load_queue()
    assert len(entries) == 2
    assert entries[0]["n"] == 1
    assert entries[1]["n"] == 2
