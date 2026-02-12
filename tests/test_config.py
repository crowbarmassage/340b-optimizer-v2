"""Tests for 340B Optimizer configuration management."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from optimizer_340b.config import Settings


class TestSettings:
    """Tests for Settings dataclass and loading."""

    def test_from_env_defaults(self) -> None:
        """Settings should have sensible defaults."""
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings.from_env()
            assert settings.log_level == "INFO"
            assert settings.data_dir == Path("./data/uploads")
            assert settings.cache_enabled is True
            assert settings.cache_ttl_hours == 24

    def test_from_env_custom(self, mock_env_vars: dict[str, str]) -> None:
        """Settings should load custom values from env."""
        settings = Settings.from_env()
        assert settings.log_level == "DEBUG"
        assert settings.data_dir == Path("/tmp/test_data")
        assert settings.cache_enabled is False
        assert settings.cache_ttl_hours == 1

    def test_cache_enabled_true(self) -> None:
        """CACHE_ENABLED=true should enable caching."""
        with patch.dict(os.environ, {"CACHE_ENABLED": "true"}, clear=False):
            settings = Settings.from_env()
            assert settings.cache_enabled is True

    def test_cache_enabled_false(self) -> None:
        """CACHE_ENABLED=false should disable caching."""
        with patch.dict(os.environ, {"CACHE_ENABLED": "false"}, clear=False):
            settings = Settings.from_env()
            assert settings.cache_enabled is False

    def test_cache_enabled_case_insensitive(self) -> None:
        """CACHE_ENABLED should be case-insensitive."""
        with patch.dict(os.environ, {"CACHE_ENABLED": "TRUE"}, clear=False):
            settings = Settings.from_env()
            assert settings.cache_enabled is True

    def test_ensure_directories(self, tmp_path: Path) -> None:
        """ensure_directories should create data_dir."""
        settings = Settings(
            log_level="INFO",
            data_dir=tmp_path / "test_uploads",
            cache_enabled=True,
            cache_ttl_hours=24,
        )
        settings.ensure_directories()
        assert (tmp_path / "test_uploads").exists()
        assert (tmp_path / "test_uploads").is_dir()

    def test_log_level_from_env(self) -> None:
        """LOG_LEVEL should be read from environment."""
        with patch.dict(os.environ, {"LOG_LEVEL": "WARNING"}, clear=False):
            settings = Settings.from_env()
            assert settings.log_level == "WARNING"

    def test_cache_ttl_from_env(self) -> None:
        """CACHE_TTL_HOURS should be parsed as integer."""
        with patch.dict(os.environ, {"CACHE_TTL_HOURS": "48"}, clear=False):
            settings = Settings.from_env()
            assert settings.cache_ttl_hours == 48
