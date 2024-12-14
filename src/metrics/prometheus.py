from prometheus_client import Counter, Histogram, Gauge, Summary, CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST
from src.utils.logging import get_logger
from src.config import config
from aiohttp import web
from typing import Any, Dict, cast, List, Sequence
from asyncpg import Connection, Record
from src.models.metrics_models import DBStats, ManagerStats, DBQueryResult

logger = get_logger(__name__)

registry = CollectorRegistry()

# Message Processing Metrics
messages_consumed = Counter(
    "timescale_ingest_messages_consumed_total",
    "Total number of messages consumed",
    ["symbol"]
)

messages_inserted = Counter(
    "timescale_ingest_messages_inserted_total",
    "Total number of messages inserted",
    ["symbol"]
)

invalid_messages = Counter(
    "timescale_ingest_invalid_messages_total",
    "Total number of invalid messages",
    ["reason"]
)

# Database Metrics
db_insert_errors = Counter(
    "timescale_ingest_db_insert_errors_total",
    "Total number of DB insert errors",
    ["error_type"]
)

db_connection_errors = Counter(
    "timescale_ingest_db_connection_errors_total",
    "Total number of database connection errors"
)

db_connection_pool_size = Gauge(
    "timescale_ingest_db_connection_pool_size",
    "Current database connection pool size"
)

db_pool_waiting_clients = Gauge(
    "timescale_ingest_db_pool_waiting_clients",
    "Number of clients waiting for a database connection"
)

# Latency Metrics
message_lag = Histogram(
    "timescale_ingest_message_lag_seconds",
    "Latency from event_time to insertion time",
    buckets=[.005, .01, .025, .05, .075, .1, .25, .5, .75, 1.0, 2.5, 5.0]
)

db_insert_latency = Histogram(
    "timescale_ingest_db_insert_latency_seconds",
    "DB insertion batch latency",
    buckets=[.005, .01, .025, .05, .075, .1, .25, .5, .75, 1.0, 2.5, 5.0],
    registry=registry
)

kafka_consume_latency = Histogram(
    "timescale_ingest_kafka_consume_latency_seconds",
    "Kafka message consumption latency",
    buckets=[.001, .005, .01, .025, .05, .075, .1, .25, .5]
)

# Batch Processing Metrics
current_batch_size = Gauge(
    "timescale_ingest_current_batch_size",
    "Current batch size"
)

batch_size_histogram = Histogram(
    "timescale_ingest_batch_size",
    "Distribution of batch sizes",
    buckets=[1, 10, 50, 100, 200, 500, 1000, 2000]
)

# Circuit Breaker Metrics
circuit_breaker_state = Gauge(
    "timescale_ingest_circuit_breaker_state",
    "Circuit breaker state (0=closed, 1=half-open, 2=open)"
)

circuit_breaker_trips = Counter(
    "timescale_ingest_circuit_breaker_trips_total",
    "Number of times circuit breaker has tripped"
)

# Memory Metrics
memory_usage = Gauge(
    "timescale_ingest_memory_usage_bytes",
    "Current memory usage of the application"
)

# Kafka Consumer Metrics
kafka_consumer_lag = Gauge(
    "timescale_ingest_kafka_consumer_lag",
    "Number of messages the consumer is behind",
    ["partition"]
)

kafka_partition_offset = Gauge(
    "timescale_ingest_kafka_partition_offset",
    "Current offset for each partition",
    ["partition"]
)

# Dynamic Polling Metrics
current_poll_timeout = Gauge(
    "timescale_ingest_current_poll_timeout_seconds",
    "Current Kafka poll timeout setting"
)

current_max_batch_size = Gauge(
    "timescale_ingest_current_max_batch_size",
    "Current maximum batch size setting"
)

# Processing Rate Metrics
message_processing_rate = Summary(
    "timescale_ingest_message_processing_rate",
    "Rate of message processing per second"
)

# Enhanced Database Metrics
db_records_total = Gauge(
    "timescale_ingest_db_records_total",
    "Total number of records in the database",
    ["symbol"]
)

db_oldest_record = Gauge(
    "timescale_ingest_db_oldest_record_timestamp",
    "Timestamp of oldest record in database"
)

db_newest_record = Gauge(
    "timescale_ingest_db_newest_record_timestamp",
    "Timestamp of newest record in database"
)

db_retry_queue_size = Gauge(
    "timescale_ingest_db_retry_queue_size",
    "Number of records waiting in retry queue"
)

# Enhanced Batch Processing Metrics
batch_processing_total = Counter(
    "timescale_ingest_batch_processing_total",
    "Total number of batches processed",
    ["status"]  # success, retry, dropped
)

# Data Validation Metrics
data_validation_errors = Counter(
    "timescale_ingest_data_validation_errors_total",
    "Total number of data validation errors",
    ["field", "error_type"]
)

async def update_db_stats_metrics(stats: ManagerStats, conn: Connection) -> None:
    """Update Prometheus metrics with database statistics"""
    try:
        db_stats = stats['db_stats']
        
        # Update total records per symbol
        symbols_query: Sequence[Record] = await conn.fetch("""
            SELECT symbol, COUNT(*) as count 
            FROM candles 
            GROUP BY symbol
        """)
        for record in symbols_query:
            # Cast the record values to ensure correct types
            symbol = cast(str, record['symbol'])
            count = cast(int, record['count'])
            db_records_total.labels(symbol=symbol).set(count)
        
        # Convert datetime to timestamp for Prometheus
        oldest = db_stats['oldest_record'].timestamp() if db_stats['oldest_record'] else 0
        newest = db_stats['newest_record'].timestamp() if db_stats['newest_record'] else 0
        
        db_oldest_record.set(oldest)
        db_newest_record.set(newest)
        db_retry_queue_size.set(stats['retry_queue_size'])
        
        # Update batch stats
        for status, count in stats['batch_stats'].items():
            batch_processing_total.labels(status=str(status)).inc(int(count))
            
    except Exception as e:
        logger.error(
            "metrics_update_failed",
            error=str(e),
            exc_info=True
        )

async def health_check(request: web.Request) -> web.Response:
    """Health check endpoint for k8s probes"""
    logger.debug("health_check_called")
    return web.Response(text="healthy")

async def metrics_handler(request: web.Request) -> web.Response:
    """Handler for Prometheus metrics endpoint"""
    try:
        # Generate metrics including registry metrics
        metrics_data = generate_latest(registry)
        
        # Create response with proper content type
        return web.Response(
            body=metrics_data,
            headers={'Content-Type': CONTENT_TYPE_LATEST}
        )
    except Exception as e:
        logger.error(
            "metrics_generation_failed",
            error=str(e),
            exc_info=True
        )
        return web.Response(status=500, text=str(e))

async def setup_metrics_server():
    """Setup metrics and health check endpoints"""
    try:
        metrics_port = int(config.metrics.port)
        logger.debug(
            "starting_metrics_server",
            port=metrics_port
        )
        
        # Create new application instance
        metrics_app = web.Application()
        
        # Add routes
        metrics_app.router.add_get('/health', health_check)
        metrics_app.router.add_get('/metrics', metrics_handler)
        
        # Setup runner with cleanup on shutdown
        runner = web.AppRunner(metrics_app, handle_signals=True)
        await runner.setup()
        
        # Create and start site
        site = web.TCPSite(runner, '0.0.0.0', metrics_port)
        
        try:
            await site.start()
            logger.info(
                "metrics_server_started",
                port=metrics_port
            )
        except OSError as e:
            logger.error(
                "port_binding_failed",
                port=metrics_port,
                error=str(e)
            )
            raise
            
    except Exception as e:
        logger.error(
            "metrics_server_failed",
            error=str(e),
            exc_info=True
        )
        raise