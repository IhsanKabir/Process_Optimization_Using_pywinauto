"""
Unit tests for change_detector.py

Tests fare change detection logic.
"""

import pytest
from change_detector import detect_changes, format_change_summary


class TestDetectChanges:
    """Test change detection logic."""

    def test_detect_new_fare(self):
        """Test detection of new fares."""
        previous = {
            "BG_DAC-CGP": {
                "rbd_data": {"Y": {"rbd": "Y", "ow_fare": 100, "rt_fare": 200}}
            }
        }

        current = {
            "BG_DAC-CGP": {
                "rbd_data": {
                    "Y": {"rbd": "Y", "ow_fare": 100, "rt_fare": 200},
                    "J": {"rbd": "J", "ow_fare": 300, "rt_fare": 600},  # New
                }
            }
        }

        changes = detect_changes(current, previous)

        assert "BG_DAC-CGP" in changes
        assert "J" in changes["BG_DAC-CGP"]
        assert changes["BG_DAC-CGP"]["J"]["type"] == "new"
        assert changes["BG_DAC-CGP"]["J"]["new_ow_fare"] == 300

    def test_detect_sold_out_fare(self):
        """Test detection of sold out fares."""
        previous = {
            "BG_DAC-CGP": {
                "rbd_data": {
                    "Y": {"rbd": "Y", "ow_fare": 100, "rt_fare": 200},
                    "J": {"rbd": "J", "ow_fare": 300, "rt_fare": 600},
                }
            }
        }

        current = {
            "BG_DAC-CGP": {
                "rbd_data": {
                    "Y": {"rbd": "Y", "ow_fare": 100, "rt_fare": 200}
                    # J is gone
                }
            }
        }

        changes = detect_changes(current, previous)

        assert "BG_DAC-CGP" in changes
        assert "J" in changes["BG_DAC-CGP"]
        assert changes["BG_DAC-CGP"]["J"]["type"] == "sold_out"
        assert changes["BG_DAC-CGP"]["J"]["old_ow_fare"] == 300

    def test_detect_price_increase(self):
        """Test detection of price increases."""
        previous = {
            "BG_DAC-CGP": {
                "rbd_data": {"Y": {"rbd": "Y", "ow_fare": 100, "rt_fare": 200}}
            }
        }

        current = {
            "BG_DAC-CGP": {
                "rbd_data": {
                    "Y": {"rbd": "Y", "ow_fare": 120, "rt_fare": 220}  # Increased
                }
            }
        }

        changes = detect_changes(current, previous)

        assert "BG_DAC-CGP" in changes
        assert "Y" in changes["BG_DAC-CGP"]
        assert changes["BG_DAC-CGP"]["Y"]["type"] == "increased"
        assert changes["BG_DAC-CGP"]["Y"]["old_ow_fare"] == 100
        assert changes["BG_DAC-CGP"]["Y"]["new_ow_fare"] == 120

    def test_detect_price_decrease(self):
        """Test detection of price decreases."""
        previous = {
            "BG_DAC-CGP": {
                "rbd_data": {"Y": {"rbd": "Y", "ow_fare": 100, "rt_fare": 200}}
            }
        }

        current = {
            "BG_DAC-CGP": {
                "rbd_data": {
                    "Y": {"rbd": "Y", "ow_fare": 90, "rt_fare": 180}  # Decreased
                }
            }
        }

        changes = detect_changes(current, previous)

        assert "BG_DAC-CGP" in changes
        assert "Y" in changes["BG_DAC-CGP"]
        assert changes["BG_DAC-CGP"]["Y"]["type"] == "decreased"
        assert changes["BG_DAC-CGP"]["Y"]["old_ow_fare"] == 100
        assert changes["BG_DAC-CGP"]["Y"]["new_ow_fare"] == 90

    def test_no_changes(self):
        """Test when there are no changes."""
        data = {
            "BG_DAC-CGP": {
                "rbd_data": {"Y": {"rbd": "Y", "ow_fare": 100, "rt_fare": 200}}
            }
        }

        changes = detect_changes(data, data)

        assert len(changes) == 0

    def test_multiple_changes_same_route(self):
        """Test multiple changes on same route."""
        previous = {
            "BG_DAC-CGP": {
                "rbd_data": {
                    "Y": {"rbd": "Y", "ow_fare": 100, "rt_fare": 200},
                    "J": {"rbd": "J", "ow_fare": 300, "rt_fare": 600},
                    "C": {"rbd": "C", "ow_fare": 250, "rt_fare": 500},
                }
            }
        }

        current = {
            "BG_DAC-CGP": {
                "rbd_data": {
                    "Y": {"rbd": "Y", "ow_fare": 110, "rt_fare": 200},  # Increased
                    "J": {"rbd": "J", "ow_fare": 300, "rt_fare": 600},  # No change
                    "F": {"rbd": "F", "ow_fare": 500, "rt_fare": 1000},  # New
                    # C is gone (sold out)
                }
            }
        }

        changes = detect_changes(current, previous)

        assert "BG_DAC-CGP" in changes
        assert len(changes["BG_DAC-CGP"]) == 3  # Y increased, C sold out, F new
        assert "Y" in changes["BG_DAC-CGP"]
        assert "C" in changes["BG_DAC-CGP"]
        assert "F" in changes["BG_DAC-CGP"]
        assert "J" not in changes["BG_DAC-CGP"]  # No change for J


class TestFormatChangeSummary:
    """Test change summary formatting."""

    def test_format_single_change(self):
        """Test formatting a single change."""
        changes = {
            "BG_DAC-CGP": {
                "Y": {
                    "type": "increased",
                    "old_ow_fare": 100.0,
                    "new_ow_fare": 120.0,
                    "old_rt_fare": 200.0,
                    "new_rt_fare": 220.0,
                }
            }
        }

        summary = format_change_summary(changes)

        assert "BG_DAC-CGP" in summary
        assert "Y" in summary
        assert "INCREASED" in summary
        assert "$100.00 -> $120.00" in summary

    def test_format_empty_changes(self):
        """Test formatting empty changes."""
        summary = format_change_summary({})

        assert "No changes" in summary

    def test_format_multiple_changes(self):
        """Test formatting multiple changes."""
        changes = {
            "BG_DAC-CGP": {
                "Y": {
                    "type": "increased",
                    "old_ow_fare": 100,
                    "new_ow_fare": 120,
                    "old_rt_fare": None,
                    "new_rt_fare": None,
                },
                "J": {
                    "type": "new",
                    "old_ow_fare": None,
                    "new_ow_fare": 300,
                    "old_rt_fare": None,
                    "new_rt_fare": 600,
                },
            },
            "BG_DAC-MLE": {
                "C": {
                    "type": "sold_out",
                    "old_ow_fare": 250,
                    "new_ow_fare": None,
                    "old_rt_fare": 500,
                    "new_rt_fare": None,
                }
            },
        }

        summary = format_change_summary(changes)

        assert "BG_DAC-CGP" in summary
        assert "BG_DAC-MLE" in summary
        assert "Total changes: 3" in summary
