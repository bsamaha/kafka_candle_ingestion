from enum import Enum
from pydantic import BaseModel, field_validator
from typing import Any, Dict, List, Optional

class MarketDataPoint(BaseModel):
    """Validates and structures incoming market data"""
    event_time: str
    symbol: str
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    start_time: str
    timestamp: str

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