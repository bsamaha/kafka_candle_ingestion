from enum import Enum
from pydantic import BaseModel, field_validator
from typing import Any, Dict, List, Optional, Union
from datetime import datetime

class MarketDataPoint(BaseModel):
    """Validates and structures incoming market data"""
    event_time: datetime
    symbol: str
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    start_time: datetime
    timestamp: datetime

    @field_validator('event_time', 'start_time', 'timestamp', mode='before')
    @classmethod
    def validate_timestamps(cls, v: Union[str, int]) -> datetime:
        # Convert integer timestamps to datetime
        if isinstance(v, int):
            try:
                return datetime.fromtimestamp(v)
            except (ValueError, OSError) as e:
                raise ValueError(f"Invalid timestamp value: {v}") from e
        # Convert ISO format strings to datetime
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v)
            except ValueError as e:
                raise ValueError(f"Invalid datetime string: {v}") from e
        return v

    @field_validator('open_price', 'high_price', 'low_price', 'close_price', 'volume')
    @classmethod
    def validate_numeric_fields(cls, v: float) -> float:
        if v < 0:
            raise ValueError("Numeric fields must be non-negative")
        return v

    @field_validator('symbol')
    @classmethod
    def validate_symbol(cls, v: str) -> str:
        if not v or len(v) > 20:
            raise ValueError("Symbol must be non-empty and reasonable length")
        return v.upper()

class CircuitBreakerState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open" 