"""Configuration management for 340B Optimizer."""

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


@dataclass
class Settings:
    """Application settings loaded from environment variables.

    Attributes:
        log_level: Logging verbosity level.
        data_dir: Directory for uploaded data files.
        cache_enabled: Whether to cache computed results.
        cache_ttl_hours: Cache time-to-live in hours.
    """

    log_level: str
    data_dir: Path
    cache_enabled: bool
    cache_ttl_hours: int

    @classmethod
    def from_env(cls) -> "Settings":
        """Load settings from environment variables.

        Returns:
            Settings instance with loaded configuration.
        """
        load_dotenv()

        log_level = os.getenv("LOG_LEVEL", "INFO")
        data_dir = Path(os.getenv("DATA_DIR", "./data/uploads"))
        cache_enabled = os.getenv("CACHE_ENABLED", "true").lower() == "true"
        cache_ttl_hours = int(os.getenv("CACHE_TTL_HOURS", "24"))

        logger.debug(
            f"Loaded settings: log_level={log_level}, "
            f"data_dir={data_dir}, cache_enabled={cache_enabled}"
        )

        return cls(
            log_level=log_level,
            data_dir=data_dir,
            cache_enabled=cache_enabled,
            cache_ttl_hours=cache_ttl_hours,
        )

    def ensure_directories(self) -> None:
        """Create required directories if they don't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Ensured data directory exists: {self.data_dir}")
