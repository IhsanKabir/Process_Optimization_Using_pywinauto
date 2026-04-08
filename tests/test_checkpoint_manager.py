"""
test_checkpoint_manager.py - Tests for Checkpoint/Resume Functionality

Tests the CheckpointManager class for saving and resuming progress.
"""

import pytest
import os
import json
import tempfile
import shutil
from checkpoint_manager import CheckpointManager


@pytest.fixture
def temp_checkpoint_dir():
    """Create a temporary directory for checkpoint files."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    # Cleanup
    shutil.rmtree(temp_dir)


class TestCheckpointManager:
    """Tests for CheckpointManager class."""

    def test_init_creates_directory(self, temp_checkpoint_dir):
        """Test that CheckpointManager creates checkpoint directory."""
        checkpoint_dir = os.path.join(temp_checkpoint_dir, "new_checkpoints")
        mgr = CheckpointManager(checkpoint_dir, session_name="test_session")
        assert os.path.exists(checkpoint_dir)
        assert mgr.session_name == "test_session"

    def test_mark_completed(self, temp_checkpoint_dir):
        """Test marking commands as completed."""
        mgr = CheckpointManager(temp_checkpoint_dir, session_name="test")
        mgr.mark_completed("FDDACMLE/BG")
        assert mgr.is_completed("FDDACMLE/BG")
        assert len(mgr.completed_commands) == 1

    def test_mark_failed(self, temp_checkpoint_dir):
        """Test marking commands as failed."""
        mgr = CheckpointManager(temp_checkpoint_dir, session_name="test")
        mgr.mark_failed("FDDACMLE/BG")
        assert "FDDACMLE/BG" in mgr.failed_commands
        assert len(mgr.failed_commands) == 1

    def test_save_and_load_checkpoint(self, temp_checkpoint_dir):
        """Test saving and loading checkpoint data."""
        mgr1 = CheckpointManager(temp_checkpoint_dir, session_name="test")
        mgr1.mark_completed("FDDACMLE/BG")
        mgr1.mark_completed("FDDACDOH/BG")
        mgr1.mark_failed("FDDACJFK/BG")
        mgr1.save_checkpoint()

        # Load checkpoint in new manager instance
        mgr2 = CheckpointManager(temp_checkpoint_dir, session_name="test")
        loaded = mgr2.load_checkpoint()

        assert loaded is True
        assert len(mgr2.completed_commands) == 2
        assert len(mgr2.failed_commands) == 1
        assert mgr2.is_completed("FDDACMLE/BG")
        assert mgr2.is_completed("FDDACDOH/BG")
        assert "FDDACJFK/BG" in mgr2.failed_commands

    def test_load_nonexistent_checkpoint(self, temp_checkpoint_dir):
        """Test loading checkpoint when file doesn't exist."""
        mgr = CheckpointManager(temp_checkpoint_dir, session_name="nonexistent")
        loaded = mgr.load_checkpoint()
        assert loaded is False
        assert len(mgr.completed_commands) == 0

    def test_get_remaining_commands(self, temp_checkpoint_dir):
        """Test filtering commands to get remaining ones."""
        mgr = CheckpointManager(temp_checkpoint_dir, session_name="test")
        mgr.mark_completed("FDDACMLE/BG")
        mgr.mark_completed("FDDACDOH/BG")

        all_commands = [
            {"command": "FDDACMLE/BG"},
            {"command": "FDDACDOH/BG"},
            {"command": "FDDACJFK/BG"},
            {"command": "FDDACLHR/BG"},
        ]

        remaining = mgr.get_remaining_commands(all_commands)
        assert len(remaining) == 2
        assert remaining[0]["command"] == "FDDACJFK/BG"
        assert remaining[1]["command"] == "FDDACLHR/BG"

    def test_get_progress_stats(self, temp_checkpoint_dir):
        """Test getting progress statistics."""
        mgr = CheckpointManager(temp_checkpoint_dir, session_name="test")
        mgr.mark_completed("FDDACMLE/BG")
        mgr.mark_completed("FDDACDOH/BG")
        mgr.mark_failed("FDDACJFK/BG")

        stats = mgr.get_progress_stats()
        assert stats["completed"] == 2
        assert stats["failed"] == 1
        assert stats["total_processed"] == 3

    def test_checkpoint_file_contains_metadata(self, temp_checkpoint_dir):
        """Test that checkpoint file contains required metadata."""
        mgr = CheckpointManager(temp_checkpoint_dir, session_name="test")
        mgr.mark_completed("FDDACMLE/BG")
        mgr.save_checkpoint()

        checkpoint_file = os.path.join(temp_checkpoint_dir, "checkpoint_test.json")
        assert os.path.exists(checkpoint_file)

        with open(checkpoint_file, "r") as f:
            data = json.load(f)

        assert "session_start" in data
        assert "last_updated" in data
        assert "completed_commands" in data
        assert "failed_commands" in data
        assert "total_completed" in data
        assert "total_failed" in data
        assert data["total_completed"] == 1

    def test_additional_data_in_checkpoint(self, temp_checkpoint_dir):
        """Test saving additional data with checkpoint."""
        mgr = CheckpointManager(temp_checkpoint_dir, session_name="test")
        mgr.mark_completed("FDDACMLE/BG")

        additional_data = {"custom_field": "custom_value", "counter": 42}
        mgr.save_checkpoint(additional_data)

        with open(mgr.checkpoint_file, "r") as f:
            data = json.load(f)

        assert data["custom_field"] == "custom_value"
        assert data["counter"] == 42

    def test_cleanup_old_checkpoints(self, temp_checkpoint_dir):
        """Test cleanup of old checkpoint files."""
        # Create multiple checkpoints
        for i in range(10):
            mgr = CheckpointManager(temp_checkpoint_dir, session_name=f"test_{i}")
            mgr.save_checkpoint()

        # Should have 10 checkpoint files
        checkpoint_files = [
            f for f in os.listdir(temp_checkpoint_dir) if f.startswith("checkpoint_")
        ]
        assert len(checkpoint_files) == 10

        # Cleanup, keeping only 5
        mgr = CheckpointManager(temp_checkpoint_dir, session_name="test_0")
        mgr.cleanup_old_checkpoints(keep_recent=5)

        # Should now have only 5 checkpoint files
        checkpoint_files = [
            f for f in os.listdir(temp_checkpoint_dir) if f.startswith("checkpoint_")
        ]
        assert len(checkpoint_files) == 5

    def test_find_latest_checkpoint(self, temp_checkpoint_dir):
        """Test finding the latest checkpoint file."""
        # Create checkpoints with delays to ensure different timestamps
        import time

        mgr1 = CheckpointManager(temp_checkpoint_dir, session_name="test_1")
        mgr1.save_checkpoint()
        time.sleep(0.1)

        mgr2 = CheckpointManager(temp_checkpoint_dir, session_name="test_2")
        mgr2.save_checkpoint()
        time.sleep(0.1)

        mgr3 = CheckpointManager(temp_checkpoint_dir, session_name="test_3")
        mgr3.save_checkpoint()

        # Find latest
        latest = mgr1.find_latest_checkpoint()
        assert latest is not None
        assert "checkpoint_test_3.json" in latest

    def test_find_latest_checkpoint_empty_dir(self, temp_checkpoint_dir):
        """Test finding latest checkpoint in empty directory."""
        mgr = CheckpointManager(temp_checkpoint_dir, session_name="test")
        latest = mgr.find_latest_checkpoint()
        assert latest is None

    def test_duplicate_completion_marks(self, temp_checkpoint_dir):
        """Test that duplicate completions are handled correctly."""
        mgr = CheckpointManager(temp_checkpoint_dir, session_name="test")
        mgr.mark_completed("FDDACMLE/BG")
        mgr.mark_completed("FDDACMLE/BG")  # Duplicate

        # Should still have only 1 completed command (set behavior)
        assert len(mgr.completed_commands) == 1

    def test_is_completed_for_uncompleted_command(self, temp_checkpoint_dir):
        """Test is_completed returns False for uncompleted commands."""
        mgr = CheckpointManager(temp_checkpoint_dir, session_name="test")
        assert mgr.is_completed("FDDACMLE/BG") is False

    def test_session_name_with_timestamp(self, temp_checkpoint_dir):
        """Test that default session name uses timestamp."""
        mgr = CheckpointManager(temp_checkpoint_dir)
        # Session name should be a timestamp (YYYY-MM-DD_HHMM format)
        assert len(mgr.session_name) > 0
        assert "_" in mgr.session_name
