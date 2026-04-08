"""
config_manager.py - Centralized Configuration Management

Handles loading, validation, and environment-specific configuration.
"""

import json
import os
from typing import Dict, Any, Optional
from exceptions import ConfigurationError
from validators import validate_config


class ConfigManager:
    """Manages application configuration with environment support."""

    def __init__(self, config_path: Optional[str] = None, environment: str = "default"):
        """
        Initialize configuration manager.

        Args:
            config_path: Path to configuration file. If None, uses default.
            environment: Environment name (default, dev, prod, test)
        """
        self.environment = environment
        self.config_path = config_path
        self.config: Dict[str, Any] = {}
        self._loaded = False

    def load(self, config_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Load and validate configuration.

        Args:
            config_path: Override config path

        Returns:
            Validated configuration dictionary

        Raises:
            ConfigurationError: If config is invalid or not found
        """
        path = config_path or self.config_path

        if not path:
            raise ConfigurationError("No configuration path specified")

        # Try environment-specific config first
        if self.environment != "default":
            env_path = self._get_env_config_path(path)
            if os.path.exists(env_path):
                path = env_path

        try:
            with open(path, "r", encoding="utf-8") as f:
                self.config = json.load(f)
        except FileNotFoundError:
            raise ConfigurationError(f"Config file not found: {path}")
        except json.JSONDecodeError as e:
            raise ConfigurationError(f"Invalid JSON in config file: {e}")

        # Validate configuration
        self.config = validate_config(self.config)
        self._loaded = True

        return self.config

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a configuration value.

        Args:
            key: Configuration key (supports dot notation for nested keys)
            default: Default value if key not found

        Returns:
            Configuration value or default
        """
        if not self._loaded:
            raise ConfigurationError("Configuration not loaded. Call load() first.")

        # Support dot notation for nested keys
        keys = key.split(".")
        value = self.config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def set(self, key: str, value: Any) -> None:
        """
        Set a configuration value (in memory only).

        Args:
            key: Configuration key (supports dot notation)
            value: Value to set
        """
        if not self._loaded:
            raise ConfigurationError("Configuration not loaded. Call load() first.")

        keys = key.split(".")
        config = self.config

        # Navigate to the nested dictionary
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]

        config[keys[-1]] = value

    def save(self, path: Optional[str] = None) -> None:
        """
        Save configuration to file.

        Args:
            path: Path to save to. If None, uses original config path.
        """
        if not self._loaded:
            raise ConfigurationError("Configuration not loaded. Nothing to save.")

        save_path = path or self.config_path

        if not save_path:
            raise ConfigurationError("No save path specified")

        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)

    def _get_env_config_path(self, base_path: str) -> str:
        """
        Get environment-specific config path.

        Args:
            base_path: Base configuration path (e.g., 'config.json')

        Returns:
            Environment-specific path (e.g., 'config.dev.json')
        """
        base_dir = os.path.dirname(base_path)
        base_name = os.path.basename(base_path)
        name, ext = os.path.splitext(base_name)

        env_name = f"{name}.{self.environment}{ext}"
        return os.path.join(base_dir, env_name)

    @staticmethod
    def get_environment() -> str:
        """
        Get current environment from environment variable.

        Returns:
            Environment name (default, dev, prod, test)
        """
        return os.getenv("APP_ENV", "default")


# Global configuration instance
_config_manager: Optional[ConfigManager] = None


def get_config_manager(
    config_path: Optional[str] = None, environment: Optional[str] = None
) -> ConfigManager:
    """
    Get the global configuration manager instance.

    Args:
        config_path: Config file path (only used on first call)
        environment: Environment name (only used on first call)

    Returns:
        ConfigManager instance
    """
    global _config_manager

    if _config_manager is None:
        env = environment or ConfigManager.get_environment()
        _config_manager = ConfigManager(config_path, env)

    return _config_manager
