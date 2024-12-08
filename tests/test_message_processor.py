import json
import pytest
from typing import Dict, Any
from datetime import datetime
from src.core.processor import MessageProcessor
from src.models.data_models import MarketDataPoint
from src.config.test_config import test_config
from src.config import CircuitBreakerConfig

@pytest.fixture
def sample_message() -> Dict[str, Any]:
    return {
        "event_time": datetime.now().isoformat(),
        "symbol": "BTC-USD",
        "open_price": 50000.0,
        "high_price": 51000.0,
        "low_price": 49000.0,
        "close_price": 50500.0,
        "volume": 100.0,
        "start_time": datetime.now().isoformat(),
        "timestamp": datetime.now().isoformat()
    }

@pytest.mark.asyncio
async def test_message_processing(db_pool, sample_message: Dict[str, Any]) -> None:
    from src.core.database import DatabaseManager
    from src.core.circuit_breaker import DatabaseCircuitBreaker
    
    # Setup with proper circuit breaker configuration
    cb_config = CircuitBreakerConfig(
        failure_threshold=3,        # Number of failures before opening circuit
        reset_timeout=30,          # Seconds to wait before attempting reset
        half_open_timeout=5        # Seconds to wait in half-open state
    )
    circuit_breaker = DatabaseCircuitBreaker(cb_config)
    db_manager = DatabaseManager(db_pool, circuit_breaker)
    processor = MessageProcessor(db_manager)
    
    # Test message parsing
    encoded_message = bytes(json.dumps(sample_message), 'utf-8')
    parsed_data = processor.parse_message(encoded_message)
    assert parsed_data is not None
    assert parsed_data["symbol"] == "BTC-USD"
    
    # Test batch processing
    await processor.process_message(MockMessage(encoded_message))
    assert len(processor.records_buffer) == 1
    
    # Test flush
    await processor._flush_buffer()
    assert len(processor.records_buffer) == 0

class MockMessage:
    def __init__(self, value: bytes):
        self.value = value