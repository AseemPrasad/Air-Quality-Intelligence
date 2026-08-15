"""Configuration loading and validation."""

import os
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional
import yaml
from pydantic import BaseModel, ValidationError, field_validator


logger = logging.getLogger(__name__)


class DatabaseConfig(BaseModel):
    """Database configuration."""
    url: str
    user: str
    password: str
    host: str
    port: int
    database: str
    pool_size: int = 10
    max_overflow: int = 20
    echo: bool = False


class DataConfig(BaseModel):
    """Data storage configuration."""
    parquet_path: str
    checkpoint_path: str
    log_path: str


class APIConfig(BaseModel):
    """API server configuration."""
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 4
    timeout_seconds: int = 30
    log_level: str = "INFO"


class ConnectorsConfig(BaseModel):
    """External API connectors configuration."""
    openaq_api_key: str
    openaq_api_url: str = "https://api.openaq.org/v2"
    openaq_timeout: int = 30
    openmeteo_api_url: str = "https://api.open-meteo.com/v1"
    openmeteo_timeout: int = 30


class AirflowConfig(BaseModel):
    """Airflow configuration."""
    home: str
    dags_folder: str
    load_examples: bool = False
    load_default_connections: bool = False


class MLConfig(BaseModel):
    """ML pipeline configuration."""
    enable_training: bool = True
    enable_inference: bool = True
    training_days: int = 90
    promotion_threshold: float = 0.05
    test_fraction: float = 0.15


class AnalyticsConfig(BaseModel):
    """Analytics configuration."""
    baseline_days: int = 365
    anomaly_z_threshold_low: float = 2.0
    anomaly_z_threshold_high: float = 3.0
    anomaly_z_threshold_extreme: float = 5.0
    event_min_anomalies: int = 3
    event_min_window_hours: int = 4
    event_merge_gap_minutes: int = 30


class Config(BaseModel):
    """Root configuration."""
    database: DatabaseConfig
    data: DataConfig
    api: APIConfig
    connectors: ConnectorsConfig
    airflow: AirflowConfig
    ml: MLConfig
    analytics: AnalyticsConfig

    @field_validator("database", "data", "api", mode="before")
    @classmethod
    def validate_nested(cls, v: Any) -> Any:
        if isinstance(v, dict):
            return v
        return v


class ConfigLoader:
    """Load and validate configuration from YAML and environment variables."""

    def __init__(self, config_dir: Optional[str] = None):
        """Initialize config loader.

        Args:
            config_dir: Directory containing config files. Defaults to ./configs
        """
        self.config_dir = Path(config_dir or "./configs")
        self.config: Optional[Config] = None

    def load(self) -> Config:
        """Load configuration from YAML and environment variables.

        Returns:
            Loaded and validated configuration

        Raises:
            FileNotFoundError: If config file not found
            yaml.YAMLError: If YAML is invalid
            ValidationError: If config schema invalid
        """
        # Load default config
        default_file = self.config_dir / "default.yaml"
        if not default_file.exists():
            raise FileNotFoundError(
                f"Default config file not found: {default_file}"
            )

        logger.info(f"Loading configuration from {default_file}")
        with open(default_file, "r") as f:
            config_dict = yaml.safe_load(f)

        if not config_dict:
            config_dict = {}

        # Override with environment variables
        config_dict = self._apply_env_overrides(config_dict)

        # Validate against schema
        try:
            self.config = Config(**config_dict)
            logger.info("Configuration loaded and validated successfully")
            return self.config
        except ValidationError as e:
            logger.error(f"Configuration validation failed:\n{e}")
            raise

    def _apply_env_overrides(self, config_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Override configuration with environment variables.

        Environment variable naming convention:
        - Top-level: use uppercase, e.g., API_PORT
        - Nested: use underscore, e.g., DATABASE_URL

        Args:
            config_dict: Base configuration dictionary

        Returns:
            Configuration with environment overrides applied
        """
        # Database overrides
        overrides = {
            "database": {
                "url": os.getenv("DATABASE_URL"),
                "user": os.getenv("POSTGRES_USER"),
                "password": os.getenv("POSTGRES_PASSWORD"),
                "host": os.getenv("DATABASE_HOST"),
                "port": os.getenv("DATABASE_PORT"),
                "database": os.getenv("POSTGRES_DB"),
            },
            "data": {
                "parquet_path": os.getenv("PARQUET_PATH"),
                "checkpoint_path": os.getenv("CHECKPOINT_PATH"),
                "log_path": os.getenv("LOG_PATH"),
            },
            "api": {
                "host": os.getenv("API_HOST"),
                "port": os.getenv("API_PORT"),
                "workers": os.getenv("API_WORKERS"),
                "log_level": os.getenv("API_LOG_LEVEL"),
            },
            "connectors": {
                "openaq_api_key": os.getenv("OPENAQ_API_KEY"),
                "openaq_api_url": os.getenv("OPENAQ_API_URL"),
                "openmeteo_api_url": os.getenv("OPENMETEO_API_URL"),
            },
            "airflow": {
                "home": os.getenv("AIRFLOW_HOME"),
                "dags_folder": os.getenv("AIRFLOW__CORE__DAGS_FOLDER"),
            },
            "ml": {
                "enable_training": os.getenv("ENABLE_ML_TRAINING"),
                "enable_inference": os.getenv("ENABLE_ML_INFERENCE"),
                "promotion_threshold": os.getenv("MODEL_PROMOTION_THRESHOLD"),
            },
            "analytics": {
                "baseline_days": os.getenv("BASELINE_DAYS"),
                "event_merge_gap_minutes": os.getenv("EVENT_MERGE_GAP_MINUTES"),
            },
        }

        # Merge overrides into config_dict (only non-None values)
        for section, values in overrides.items():
            if section not in config_dict:
                config_dict[section] = {}

            for key, value in values.items():
                if value is not None:
                    # Type conversions
                    if section == "api" and key == "port":
                        value = int(value)
                    elif section == "api" and key == "workers":
                        value = int(value)
                    elif section == "database" and key == "port":
                        value = int(value)
                    elif section == "ml" and key in ("enable_training", "enable_inference"):
                        value = value.lower() in ("true", "1", "yes")
                    elif section == "ml" and key == "promotion_threshold":
                        value = float(value)
                    elif section == "analytics" and key in ("baseline_days", "event_merge_gap_minutes"):
                        value = int(value)

                    config_dict[section][key] = value

        logger.debug(f"Applied environment variable overrides")
        return config_dict

    def get(self) -> Config:
        """Get loaded configuration (loads if not already loaded).

        Returns:
            Configuration object
        """
        if self.config is None:
            self.load()
        return self.config


def load_config(config_dir: Optional[str] = None) -> Config:
    """Convenience function to load configuration.

    Args:
        config_dir: Directory containing config files

    Returns:
        Loaded configuration
    """
    loader = ConfigLoader(config_dir)
    return loader.load()


def get_config() -> Config:
    """Get global configuration instance.

    Returns:
        Configuration object

    Raises:
        RuntimeError: If configuration not loaded
    """
    global _config
    if _config is None:
        _config = load_config()
    return _config


# Global config instance
_config: Optional[Config] = None


class LoggingConfig:
    """Load logging configuration from YAML."""

    def __init__(self, config_file: Optional[str] = None):
        """Initialize logging config.

        Args:
            config_file: Path to logging.yaml. Defaults to ./configs/logging.yaml
        """
        self.config_file = Path(config_file or "./configs/logging.yaml")

    def load(self) -> Dict[str, Any]:
        """Load logging configuration.

        Returns:
            Logging configuration dictionary

        Raises:
            FileNotFoundError: If config file not found
        """
        if not self.config_file.exists():
            logger.warning(
                f"Logging config file not found: {self.config_file}. "
                "Using default logging configuration."
            )
            return self._default_config()

        logger.debug(f"Loading logging configuration from {self.config_file}")
        with open(self.config_file, "r") as f:
            config = yaml.safe_load(f)

        return config or self._default_config()

    @staticmethod
    def _default_config() -> Dict[str, Any]:
        """Return default logging configuration."""
        return {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "json": {
                    "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
                    "fmt": "%(timestamp)s %(level)s %(name)s %(message)s"
                },
                "standard": {
                    "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "json",
                    "stream": "ext://sys.stdout"
                }
            },
            "root": {
                "level": "INFO",
                "handlers": ["console"]
            }
        }
