#!/usr/bin/env python3
"""Configuration management for memo application."""

import json
import logging
import os
import shutil
import tempfile
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional


logger = logging.getLogger(__name__)


class ConfigValidationError(Exception):
    """Raised when configuration validation fails."""
    pass


class Config:
    """Configuration manager for memo application with validation and environment variable support."""

    def __init__(self, config_file: Optional[Path] = None):
        self.config_dir = Path.home() / ".memo"
        self.config_file = config_file or (self.config_dir / "config.json")
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self._enforce_permissions()
        self._config = self._load_config()
        self._ensure_defaults()
        self._load_env_overrides()
        self._validate_config()
        self._enforce_permissions()

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file."""
        if self.config_file.exists():
            try:
                with self.config_file.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except json.JSONDecodeError as exc:
                logger.warning("Failed to parse config.json, quarantining corrupt copy: %s", exc)
                self._quarantine_corrupt_config()
            except OSError as exc:
                logger.warning("Unable to read config.json (%s), falling back to defaults", exc)

        # Return default configuration
        return self._get_default_config()

    def _enforce_permissions(self) -> None:
        """Apply restrictive permissions on config directory and file when possible."""
        if os.name != "posix":
            return

        with suppress(OSError):
            self.config_dir.chmod(0o700)

        if self.config_file.exists():
            with suppress(OSError):
                self.config_file.chmod(0o600)

    def _quarantine_corrupt_config(self) -> None:
        """Move corrupt config aside for investigation."""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        quarantine_path = self.config_dir / f"config_corrupted_{timestamp}.json"
        with suppress(OSError):
            shutil.move(str(self.config_file), quarantine_path)

    def _backup_existing(self) -> None:
        """Create a timestamped backup of current config prior to overwrite."""
        if not self.config_file.exists():
            return

        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        backup_path = self.config_dir / f"config_{timestamp}.bak"
        try:
            shutil.copy2(self.config_file, backup_path)
            if os.name == "posix":
                with suppress(OSError):
                    backup_path.chmod(0o600)
        except OSError as exc:
            logger.warning("Failed to create config backup: %s", exc)
        else:
            self._prune_backups(max_backups=5)

    def _prune_backups(self, max_backups: int) -> None:
        """Retain only the newest backup files."""
        backups = sorted(self.config_dir.glob("config_*.bak"))
        if len(backups) <= max_backups:
            return

        for stale in backups[:-max_backups]:
            with suppress(OSError):
                stale.unlink()

    def _ensure_defaults(self) -> None:
        """Ensure new default keys exist in loaded configuration."""
        defaults = self._get_default_config()

        def merge(config: Dict[str, Any], default_values: Dict[str, Any]) -> None:
            for key, value in default_values.items():
                if key not in config:
                    config[key] = value
                elif isinstance(config[key], dict) and isinstance(value, dict):
                    merge(config[key], value)

        merge(self._config, defaults)

    def _load_env_overrides(self) -> None:
        """Load configuration overrides from environment variables."""
        env_mappings = {
            "MEMO_DB_PATH": "storage.db_path",
            "MEMO_BACKUP_DIR": "storage.backup_dir",
            "MEMO_LOG_DIR": "logging.log_dir",
            "MEMO_MAX_MEMO_SIZE": ("limits.max_memo_bytes", int),
            "MEMO_LOCK_TIMEOUT": ("limits.lock_timeout_seconds", float),
            "MEMO_LOCK_RETRY_INTERVAL": ("limits.lock_retry_interval_seconds", float),
            "MEMO_AUTO_TAG": ("behavior.auto_tag_extraction", self._parse_bool),
            "MEMO_DATE_FORMAT": "display.date_format",
            "MEMO_EDITOR": "editor.command",
        }

        for env_var, config_key in env_mappings.items():
            env_value = os.getenv(env_var)
            if env_value is not None:
                if isinstance(config_key, tuple):
                    key, converter = config_key
                    try:
                        self.set(key, converter(env_value))
                    except (ValueError, TypeError):
                        pass
                else:
                    self.set(config_key, env_value)

    def _parse_bool(self, value: str) -> bool:
        """Parse boolean from string."""
        return value.lower() in ("true", "1", "yes", "on")

    def _validate_config(self) -> None:
        """Validate configuration values."""
        limits = self._config.get("limits", {})

        max_memo_bytes = limits.get("max_memo_bytes", 0)
        if max_memo_bytes < 1024 or max_memo_bytes > 100 * 1024 * 1024:
            raise ConfigValidationError("max_memo_bytes must be between 1KB and 100MB")

        max_tags = limits.get("max_tags_per_memo", 0)
        if max_tags < 1 or max_tags > 100:
            raise ConfigValidationError("max_tags_per_memo must be between 1 and 100")

        lock_timeout = limits.get("lock_timeout_seconds", 0)
        if lock_timeout < 0.1 or lock_timeout > 60.0:
            raise ConfigValidationError("lock_timeout_seconds must be between 0.1 and 60.0")

        lock_retry = limits.get("lock_retry_interval_seconds", 0)
        if lock_retry < 0.01 or lock_retry > 5.0:
            raise ConfigValidationError("lock_retry_interval_seconds must be between 0.01 and 5.0")

        billing = self._config.get("billing", {})
        model = billing.get("model", "subscription")
        if model not in {"subscription", "buyout"}:
            raise ConfigValidationError("billing.model must be either 'subscription' or 'buyout'")

        enforcement_enabled = billing.get("enforcement_enabled", True)
        if not isinstance(enforcement_enabled, bool):
            raise ConfigValidationError("billing.enforcement_enabled must be boolean")

        stripe_cfg = billing.get("stripe", {})
        if not isinstance(stripe_cfg, dict):
            raise ConfigValidationError("billing.stripe must be a mapping")

        if model == "subscription":
            for key_name in ("api_key_env", "price_id_env"):
                value = stripe_cfg.get(key_name)
                if not isinstance(value, str) or not value.strip():
                    raise ConfigValidationError(f"billing.stripe.{key_name} must be a non-empty string")
            buyout_var = stripe_cfg.get("buyout_price_id_env")
            if buyout_var and (not isinstance(buyout_var, str) or not buyout_var.strip()):
                raise ConfigValidationError("billing.stripe.buyout_price_id_env must be a non-empty string when provided")

            for url_key in ("success_url", "cancel_url", "billing_portal_return_url"):
                url_value = stripe_cfg.get(url_key)
                if not isinstance(url_value, str) or not url_value.strip():
                    raise ConfigValidationError(f"billing.stripe.{url_key} must be configured")

        cache_ttl = billing.get("cache_ttl_seconds", 0)
        if not isinstance(cache_ttl, (int, float)) or cache_ttl < 300:
            raise ConfigValidationError("billing.cache_ttl_seconds must be at least 300 seconds")

        pricing_cfg = billing.get("pricing", {})
        if not isinstance(pricing_cfg, dict):
            raise ConfigValidationError("billing.pricing must be a mapping")

        default_currency = pricing_cfg.get("default_currency", "")
        if not isinstance(default_currency, str) or not default_currency.strip():
            raise ConfigValidationError("billing.pricing.default_currency must be a non-empty string")

        monthly_minimums = pricing_cfg.get("monthly_minimums", {})
        if not isinstance(monthly_minimums, dict) or not monthly_minimums:
            raise ConfigValidationError("billing.pricing.monthly_minimums must be a non-empty mapping")
        for currency, amount in monthly_minimums.items():
            if not isinstance(currency, str) or not currency.strip():
                raise ConfigValidationError("billing.pricing.monthly_minimums keys must be non-empty currency codes")
            if not isinstance(amount, (int, float)) or amount <= 0:
                raise ConfigValidationError("billing.pricing.monthly_minimums values must be positive numbers")

        if default_currency not in monthly_minimums:
            raise ConfigValidationError("billing.pricing.default_currency must exist within monthly_minimums")

        buyout_multiplier = pricing_cfg.get("buyout_multiplier", 3)
        if not isinstance(buyout_multiplier, (int, float)) or buyout_multiplier <= 0:
            raise ConfigValidationError("billing.pricing.buyout_multiplier must be a positive number")

    def _get_default_config(self) -> Dict[str, Any]:
        """Get default configuration."""
        return {
            "display": {
                "date_format": "%Y-%m-%d %H:%M",
                "short_date_format": "%m/%d %H:%M",
                "max_text_preview": 100,
                "show_icons": True,
                "color_coding": True
            },
            "behavior": {
                "auto_archive_completed": False,
                "default_category": "default",
                "default_status": "active",
                "auto_tag_extraction": True,
                "auto_link_detection": True,
                "reminder_check_interval": 300
            },
            "limits": {
                "max_memo_bytes": 16384,
                "max_tags_per_memo": 32,
                "lock_timeout_seconds": 10.0,
                "lock_retry_interval_seconds": 0.1
            },
            "storage": {
                "db_path": str(Path.home() / ".memo" / "memos.json"),
                "backup_dir": str(Path.home() / ".memo" / "backups"),
                "enable_compression": False
            },
            "logging": {
                "log_dir": str(Path.home() / ".memo" / "logs"),
                "log_level": "INFO",
                "max_log_size_mb": 5,
                "backup_count": 5
            },
            "performance": {
                "enable_caching": True,
                "cache_ttl_seconds": 300,
                "max_cache_items": 1000
            },
            "export": {
                "default_format": "json",
                "include_metadata": True,
                "markdown_include_toc": False
            },
            "filters": {
                "presets": {}
            },
            "aliases": {
                "m": "add",
                "ls": "list",
                "find": "search",
                "rm": "delete"
            },
            "editor": {
                "command": "nano",
                "use_external": False
            },
            "billing": {
                "model": "subscription",
                "enforcement_enabled": True,
                "license_file": str(Path.home() / ".memo" / "license.json"),
                "cache_ttl_seconds": 21600,
                "stripe": {
                    "api_key_env": "STRIPE_API_KEY",
                    "publishable_key_env": "STRIPE_PUBLISHABLE_KEY",
                    "price_id_env": "STRIPE_PRICE_ID",
                    "buyout_price_id_env": "STRIPE_PRICE_ID_BUYOUT",
                    "success_url": "http://localhost:4242/success?session_id={CHECKOUT_SESSION_ID}",
                    "cancel_url": "http://localhost:4242/cancel",
                    "billing_portal_return_url": "http://localhost:4242/portal-return",
                    "webhook_secret_env": "STRIPE_WEBHOOK_SECRET"
                },
                "pricing": {
                    "default_currency": "JPY",
                    "tiers": {
                        "free": {
                            "JPY": 0,
                            "USD": 0,
                            "EUR": 0
                        },
                        "personal": {
                            "JPY": 50,
                            "USD": 50,
                            "EUR": 50
                        },
                        "professional": {
                            "JPY": 1980,
                            "USD": 1500,
                            "EUR": 1500
                        },
                        "enterprise": {
                            "JPY": 9800,
                            "USD": 7900,
                            "EUR": 7900
                        }
                    },
                    "monthly_minimums": {
                        "JPY": 50,
                        "USD": 50,
                        "EUR": 50
                    },
                    "buyout_multiplier": 6
                }
            }
        }

    def save(self) -> bool:
        """Save configuration to file."""
        try:
            self._backup_existing()
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=self.config_dir, suffix=".json") as tmp:
                json.dump(self._config, tmp, ensure_ascii=False, indent=2)
                tmp.flush()
                os.fsync(tmp.fileno())
                tmp_path = Path(tmp.name)

            tmp_path.replace(self.config_file)
            self._enforce_permissions()
            return True
        except OSError as exc:
            logger.error("Failed to persist config: %s", exc)
            return False

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value using dot notation."""
        keys = key.split(".")
        value = self._config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def set(self, key: str, value: Any) -> None:
        """Set configuration value using dot notation."""
        keys = key.split(".")
        config = self._config

        for k in keys[:-1]:
            if k not in config or not isinstance(config[k], dict):
                config[k] = {}
            config = config[k]

        config[keys[-1]] = value

    def reset_to_defaults(self) -> None:
        """Reset configuration to defaults."""
        self._config = self._get_default_config()

    def get_all(self) -> Dict[str, Any]:
        """Get entire configuration."""
        return self._config.copy()

    def update(self, updates: Dict[str, Any]) -> None:
        """Update configuration with dictionary."""
        def deep_update(base: dict, updates: dict):
            for key, value in updates.items():
                if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                    deep_update(base[key], value)
                else:
                    base[key] = value

        deep_update(self._config, updates)


def show_config(config: Config):
    """Display current configuration."""
    print("Current Configuration:")
    print("=" * 40)

    def print_dict(d: dict, indent: int = 0):
        for key, value in d.items():
            prefix = "  " * indent
            if isinstance(value, dict):
                print(f"{prefix}{key}:")
                print_dict(value, indent + 1)
            else:
                print(f"{prefix}{key}: {value}")

    print_dict(config.get_all())


def validate_config_file(config_path: Path) -> bool:
    """Validate a configuration file without loading it."""
    try:
        with config_path.open("r", encoding="utf-8") as f:
            config_data = json.load(f)

        temp_config = Config.__new__(Config)
        temp_config._config = config_data
        temp_config._validate_config()
        return True
    except (json.JSONDecodeError, ConfigValidationError) as e:
        print(f"Configuration validation failed: {e}")
        return False


if __name__ == "__main__":
    import sys

    config = Config()

    if len(sys.argv) > 1:
        if sys.argv[1] == "show":
            show_config(config)
        elif sys.argv[1] == "reset":
            config.reset_to_defaults()
            config.save()
            print("Configuration reset to defaults")
        elif len(sys.argv) == 4 and sys.argv[1] == "set":
            key, value = sys.argv[2], sys.argv[3]
            # Try to parse as JSON first, then as string
            try:
                parsed_value = json.loads(value)
            except json.JSONDecodeError:
                parsed_value = value

            config.set(key, parsed_value)
            config.save()
            print(f"Set {key} = {parsed_value}")
        elif len(sys.argv) == 3 and sys.argv[1] == "get":
            key = sys.argv[2]
            value = config.get(key)
            print(f"{key} = {value}")
        else:
            print("Usage: config.py [show|reset|set KEY VALUE|get KEY]")
    else:
        show_config(config)