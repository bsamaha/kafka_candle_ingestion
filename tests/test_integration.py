import json
import pytest
from typing import AsyncGenerator, Any
import asyncio
from aiokafka import AIOKafkaProducer
from src.core.processor import KafkaTimescaleIngestion
from src.config.test_config import test_config
from datetime import datetime
from pytest import FixtureRequest
from _pytest.fixtures import FixtureFunction

@pytest.fixture(scope="session")
async def docker_setup(request: FixtureRequest) -> AsyncGenerator[None, None]:
    # Setup code would go here
    yield
    # Teardown code would go here

@pytest.mark.asyncio
async def test_end_to_end(docker_setup: AsyncGenerator[None, None]) -> None:
    # Start the application
    app = KafkaTimescaleIngestion()
    await app.startup()
    
    # Create a producer with proper config access
    producer = AIOKafkaProducer(
        bootstrap_servers=test_config.kafka.bootstrap_servers
    )
    await producer.start()
    
    try:
        # Send test messages
        messages = [
            {
                "event_time": datetime.now().isoformat(),
                "symbol": f"TEST-{i}",
                "open_price": 100.0 + i,
                "high_price": 101.0 + i,
                "low_price": 99.0 + i,
                "close_price": 100.5 + i,
                "volume": 10.0 + i,
                "start_time": datetime.now().isoformat(),
                "timestamp": datetime.now().isoformat()
            }
            for i in range(5)
        ]
        
        for msg in messages:
            await producer.send_and_wait(
                test_config.kafka.topic,
                bytes(json.dumps(msg), 'utf-8')
            )
        
        # Wait for processing
        await asyncio.sleep(5)
        
        # Verify in database
        if app.db_pool is None:
            pytest.fail("Database pool not initialized")
            
        async with app.db_pool.acquire() as conn:
            result = await conn.fetchrow(
                "SELECT COUNT(*) FROM market_data WHERE symbol LIKE 'TEST-%'"
            )
            assert result[0] == 5, "Expected 5 records in database"
            
    finally:
        await producer.stop()
        await app.shutdown() 