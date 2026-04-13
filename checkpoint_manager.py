"""
checkpoint_manager.py - Checkpoint and Resume Functionality

Saves progress periodically so failed runs don't require starting from scratch.
Allows resuming from the last checkpoint, skipping already-completed commands.
"""

import json
import os
from datetime import datetime
from typing import Optional, Set, List, Dict, Any
import logging

logger = logging.getLogger("travelport.checkpoint")


class CheckpointManager:
    """Manages checkpoint files for resuming interrupted runs."""

    def __init__(self, checkpoint_dir: str, session_name: Optional[str] = None):
        """
        Initialize checkpoint manager.

        Args:
            checkpoint_dir: Directory to store checkpoint files
            session_name: Optional session name. If not provided, uses timestamp.
        """
        self.checkpoint_dir = checkpoint_dir
        os.makedirs(checkpoint_dir, exist_ok=True)

        if session_name:
            self.session_name = session_name
        else:
            self.session_name = datetime.now().strftime("%Y-%m-%d_%H%M")

        self.checkpoint_file = os.path.join(
            checkpoint_dir, f"checkpoint_{self.session_name}.json"
        )
        self.completed_commands: Set[str] = set()
        self.failed_commands: List[str] = []
        self.session_start = datetime.now().isoformat()

    def load_checkpoint(self) -> bool:
        """
        Load checkpoint from file if it exists.

        Returns:
            True if checkpoint was loaded, False otherwise
        """
        if not os.path.exists(self.checkpoint_file):
            logger.info("  No checkpoint file found. Starting fresh.")
            return False

        try:
            with open(self.checkpoint_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.completed_commands = set(data.get("completed_commands", []))
            self.failed_commands = data.get("failed_commands", [])
            self.session_start = data.get("session_start", self.session_start)

            logger.info(
                f"  Checkpoint loaded: {len(self.completed_commands)} completed, "
                f"{len(self.failed_commands)} failed"
            )
            return True
        except Exception as e:
            logger.warning(f"  Failed to load checkpoint: {e}")
            return False

    def save_checkpoint(self, additional_data: Optional[Dict[str, Any]] = None):
        """
        Save current progress to checkpoint file.

        Args:
            additional_data: Optional additional data to store in checkpoint
        """
        data = {
            "session_start": self.session_start,
            "last_updated": datetime.now().isoformat(),
            "completed_commands": list(self.completed_commands),
            "failed_commands": self.failed_commands,
            "total_completed": len(self.completed_commands),
            "total_failed": len(self.failed_commands),
        }

        if additional_data:
            data.update(additional_data)

        try:
            temp_file = self.checkpoint_file + ".tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(temp_file, self.checkpoint_file)
            logger.debug(
                f"  Checkpoint saved: {len(self.completed_commands)} completed"
            )
        except Exception as e:
            logger.error(f"  Failed to save checkpoint: {e}")

    def mark_completed(self, command: str):
        """
        Mark a command as completed.

        Args:
            command: Command string to mark as completed
        """
        self.completed_commands.add(command)

    def mark_failed(self, command: str):
        """
        Mark a command as failed.

        Args:
            command: Command string to mark as failed
        """
        if command not in self.failed_commands:
            self.failed_commands.append(command)

    def is_completed(self, command: str) -> bool:
        """
        Check if a command has already been completed.

        Args:
            command: Command string to check

        Returns:
            True if command is in completed set, False otherwise
        """
        return command in self.completed_commands

    def get_remaining_commands(self, all_commands: List[Dict]) -> List[Dict]:
        """
        Filter command list to only those not yet completed.

        Args:
            all_commands: List of command dictionaries

        Returns:
            List of commands not yet completed
        """
        remaining = []
        for cmd in all_commands:
            cmd_str = cmd.get("command", "")
            if not self.is_completed(cmd_str):
                remaining.append(cmd)

        return remaining

    def get_progress_stats(self) -> Dict[str, int]:
        """
        Get current progress statistics.

        Returns:
            Dict with completed and failed counts
        """
        return {
            "completed": len(self.completed_commands),
            "failed": len(self.failed_commands),
            "total_processed": len(self.completed_commands) + len(self.failed_commands),
        }

    def cleanup_old_checkpoints(self, keep_recent: int = 5):
        """
        Clean up old checkpoint files, keeping only the most recent ones.

        Args:
            keep_recent: Number of recent checkpoint files to keep
        """
        try:
            checkpoint_files = [
                f
                for f in os.listdir(self.checkpoint_dir)
                if f.startswith("checkpoint_") and f.endswith(".json")
            ]

            if len(checkpoint_files) <= keep_recent:
                return

            # Sort by modification time
            checkpoint_files.sort(
                key=lambda f: os.path.getmtime(os.path.join(self.checkpoint_dir, f)),
                reverse=True,
            )

            # Remove old checkpoints
            for old_file in checkpoint_files[keep_recent:]:
                old_path = os.path.join(self.checkpoint_dir, old_file)
                os.remove(old_path)
                logger.debug(f"  Removed old checkpoint: {old_file}")

        except Exception as e:
            logger.warning(f"  Failed to cleanup old checkpoints: {e}")

    def find_latest_checkpoint(self) -> Optional[str]:
        """
        Find the most recent checkpoint file in the checkpoint directory.

        Returns:
            Path to the latest checkpoint file, or None if not found
        """
        try:
            checkpoint_files = [
                f
                for f in os.listdir(self.checkpoint_dir)
                if f.startswith("checkpoint_") and f.endswith(".json")
            ]

            if not checkpoint_files:
                return None

            # Sort by modification time
            checkpoint_files.sort(
                key=lambda f: os.path.getmtime(os.path.join(self.checkpoint_dir, f)),
                reverse=True,
            )

            latest = os.path.join(self.checkpoint_dir, checkpoint_files[0])
            return latest
        except Exception as e:
            logger.warning(f"  Failed to find latest checkpoint: {e}")
            return None
