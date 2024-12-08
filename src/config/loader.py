import os
import logging
from typing import Dict, Any
from src.config import load_config, AppConfig

logger = logging.getLogger(__name__)

class ConfigurationError(Exception):
    """Custom exception for configuration-related errors"""
    pass

def validate_config(config: Dict[str, Any]) -> None:
    """Validate critical configuration values"""
    required_sections = ['kafka', 'timescaledb', 'insert', 'metrics', 'dynamic_polling', 'circuit_breaker']
    
    try:
        # Validate all required sections exist
        for section in required_sections:
            if section not in config:
                raise ConfigurationError(f"Missing required configuration section: {section}")
        
        # Validate critical values are within acceptable ranges
        if config['kafka']['initial_poll_timeout'] <= 0:
            raise ConfigurationError("Kafka initial_poll_timeout must be positive")
        
        if not (0 < config['timescaledb']['pool_size'] <= 100):
            raise ConfigurationError("TimescaleDB pool_size must be between 1 and 100")
            
        if config['insert']['batch_size'] <= 0:
            raise ConfigurationError("Insert batch_size must be positive")
            
    except KeyError as e:
        raise ConfigurationError(f"Missing required configuration key: {str(e)}")

# Load raw configuration
raw_config: Dict[str, Any] = {
    "kafka": {
        "bootstrap_servers": os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'trading-cluster-kafka-bootstrap.kafka:9092'),
        "topic": os.getenv('KAFKA_TOPIC', 'coinbase.candles'),
        "group_id": os.getenv('KAFKA_GROUP_ID', 'timescale_ingest_group'),
        "initial_poll_timeout": float(os.getenv('KAFKA_INITIAL_POLL_TIMEOUT', '1.0')),
        "initial_max_batch_size": int(os.getenv('KAFKA_INITIAL_MAX_BATCH_SIZE', '500')),
        "consumer_timeout_ms": int(os.getenv('KAFKA_CONSUMER_TIMEOUT_MS', '5000'))
    },
    "timescaledb": {
        "host": os.getenv('TIMESCALEDB_HOST', 'timescaledb.default.svc.cluster.local'),
        "port": int(os.getenv('TIMESCALEDB_PORT', '5432')),
        "dbname": os.getenv('TIMESCALEDB_DBNAME', 'market_data'),
        "user": os.getenv('TIMESCALEDB_USER', 'timescale_user'),
        "password": os.getenv('TIMESCALEDB_PASSWORD', 'timescale_password'),
        "pool_size": int(os.getenv('TIMESCALEDB_POOL_SIZE', '10')),
        "connection_timeout": int(os.getenv('TIMESCALEDB_CONNECTION_TIMEOUT', '10'))
    },
    "insert": {
        "batch_size": int(os.getenv('INSERT_BATCH_SIZE', '500')),
        "time_interval": float(os.getenv('INSERT_TIME_INTERVAL', '5.0')),
        "retry_attempts": int(os.getenv('INSERT_RETRY_ATTEMPTS', '3')),
        "retry_delay": float(os.getenv('INSERT_RETRY_DELAY', '1.0'))
    },
    "metrics": {
        "port": int(os.getenv('METRICS_PORT', '8000'))
    },
    "dynamic_polling": {
        "latency_threshold_high": float(os.getenv('LATENCY_THRESHOLD_HIGH', '1.0')),
        "latency_threshold_low": float(os.getenv('LATENCY_THRESHOLD_LOW', '0.2')),
        "poll_timeout_min": float(os.getenv('POLL_TIMEOUT_MIN', '0.5')),
        "poll_timeout_max": float(os.getenv('POLL_TIMEOUT_MAX', '5.0')),
        "batch_size_min": int(os.getenv('BATCH_SIZE_MIN', '100')),
        "batch_size_max": int(os.getenv('BATCH_SIZE_MAX', '2000'))
    },
    "circuit_breaker": {
        "failure_threshold": int(os.getenv('CB_FAILURE_THRESHOLD', '5')),
        "reset_timeout": float(os.getenv('CB_RESET_TIMEOUT', '60.0')),
        "half_open_timeout": float(os.getenv('CB_HALF_OPEN_TIMEOUT', '30.0'))
    }
}

try:
    # Validate raw configuration
    validate_config(raw_config)
    
    # Convert to strongly typed config
    config: AppConfig = load_config(raw_config)
    logger.info("Configuration successfully loaded and validated")
    
except ConfigurationError as e:
    logger.error(f"Configuration error: {str(e)}")
    raise SystemExit(1)
except Exception as e:
    logger.error(f"Unexpected error during configuration loading: {str(e)}")
    raise SystemExit(1)

# Export the config
__all__ = ['config'] 