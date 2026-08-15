"""Connectors for data source integration.

Provides abstract connector base class and concrete implementations for
air quality (OpenAQ) and weather (Open-Meteo) data sources.

Architecture:
- BaseConnector: Abstract base with common retry/rate-limit/watermark logic
- Concrete connectors: OpenAQConnector, OpenMeteoConnector (implementations)

Features:
- HTTP retry with exponential backoff + jitter
- Rate limiting (token bucket algorithm)
- Watermark management for incremental ingestion
- Thread-safe session reuse
- Response caching (development/testing)
- Comprehensive error logging
"""

from aq_engine.connectors.base import BaseConnector, TokenBucket
from aq_engine.connectors.models import (
    ConnectorConfig,
    RetryConfig,
    RateLimitConfig,
    SourceResponse,
    ParsedRecord,
    Watermark,
    IngestionRunMetadata,
)

__all__ = [
    "BaseConnector",
    "TokenBucket",
    "ConnectorConfig",
    "RetryConfig",
    "RateLimitConfig",
    "SourceResponse",
    "ParsedRecord",
    "Watermark",
    "IngestionRunMetadata",
]
