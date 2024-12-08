from dataclasses import dataclass
from typing import Dict, Any

@dataclass
class KafkaConfig:
    bootstrap_servers: str
    topic: str
    group_id: str
    initial_poll_timeout: float
    initial_max_batch_size: int
    consumer_timeout_ms: int

@dataclass
class TimescaleDBConfig:
    host: str
    port: int
    dbname: str
    user: str
    password: str
    pool_size: int
    connection_timeout: int

@dataclass
class InsertConfig:
    batch_size: int
    time_interval: float
    retry_attempts: int
    retry_delay: float

@dataclass
class MetricsConfig:
    port: int

@dataclass
class DynamicPollingConfig:
    latency_threshold_high: float
    latency_threshold_low: float
    poll_timeout_min: float
    poll_timeout_max: float
    batch_size_min: int
    batch_size_max: int

@dataclass
class CircuitBreakerConfig:
    failure_threshold: int
    reset_timeout: float
    half_open_timeout: float

@dataclass
class AppConfig:
    kafka: KafkaConfig
    timescaledb: TimescaleDBConfig
    insert: InsertConfig
    metrics: MetricsConfig
    dynamic_polling: DynamicPollingConfig
    circuit_breaker: CircuitBreakerConfig

def load_config(raw_config: Dict[str, Any]) -> AppConfig:
    """Convert raw dictionary config into strongly typed AppConfig"""
    return AppConfig(
        kafka=KafkaConfig(**raw_config['kafka']),
        timescaledb=TimescaleDBConfig(**raw_config['timescaledb']),
        insert=InsertConfig(**raw_config['insert']),
        metrics=MetricsConfig(**raw_config['metrics']),
        dynamic_polling=DynamicPollingConfig(**raw_config['dynamic_polling']),
        circuit_breaker=CircuitBreakerConfig(**raw_config['circuit_breaker'])
    ) 