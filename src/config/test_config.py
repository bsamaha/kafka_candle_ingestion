from .config_models import (
    AppConfig, KafkaConfig, TimescaleDBConfig, InsertConfig,
    MetricsConfig, DynamicPollingConfig, CircuitBreakerConfig
)

def create_test_config() -> AppConfig:
    """Create a test configuration that mirrors the production structure"""
    return AppConfig(
        kafka=KafkaConfig(
            bootstrap_servers="localhost:9092",
            topic="test.candles",
            group_id="test_group",
            initial_poll_timeout=1.0,
            initial_max_batch_size=10,
            consumer_timeout_ms=1000
        ),
        timescaledb=TimescaleDBConfig(
            host="localhost",
            port=5432,
            dbname="test_market_data",
            user="test_user",
            password="test_password",
            pool_size=2,
            connection_timeout=5
        ),
        insert=InsertConfig(
            batch_size=500,
            time_interval=5.0,
            retry_attempts=3,
            retry_delay=1.0
        ),
        metrics=MetricsConfig(
            port=8000
        ),
        dynamic_polling=DynamicPollingConfig(
            latency_threshold_high=1.0,
            latency_threshold_low=0.2,
            poll_timeout_min=0.5,
            poll_timeout_max=5.0,
            batch_size_min=100,
            batch_size_max=2000
        ),
        circuit_breaker=CircuitBreakerConfig(
            failure_threshold=5,
            reset_timeout=60.0,
            half_open_timeout=30.0
        )
    )

test_config = create_test_config() 