import json
import time
import logging
import asyncio
from collections import defaultdict
from typing import Dict, Any, Optional, List
from aiokafka import AIOKafkaConsumer
from asyncpg import create_pool, Pool

from src.config import config
from src.models.data_models import MarketDataPoint
from src.core.circuit_breaker import DatabaseCircuitBreaker
from src.core.database import DatabaseManager
from src.metrics.prometheus import (
    messages_consumed, messages_inserted, invalid_messages,
    db_insert_errors, db_insert_latency, current_batch_size,
    kafka_consume_latency, batch_size_histogram, 
    current_poll_timeout, current_max_batch_size,
    message_processing_rate, kafka_consumer_lag,
    kafka_partition_offset
)

logger = logging.getLogger(__name__)  # Add if missing

class MessageProcessor:
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self.records_buffer: List[Dict[str, Any]] = []
        self.last_flush_time = time.time()
        
        self.current_poll_timeout = config.kafka.initial_poll_timeout
        self.current_max_batch_size = config.kafka.initial_max_batch_size
        
        # Update metrics for initial values
        current_poll_timeout.set(self.current_poll_timeout)
        current_max_batch_size.set(self.current_max_batch_size)

        self.logger = logger  # Consider adding instance logger

    def parse_message(self, raw_value: bytes) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(raw_value.decode("utf-8"))
            return MarketDataPoint(**data).model_dump()
        except json.JSONDecodeError:
            invalid_messages.labels(reason="json_decode_error").inc()
            return None
        except ValueError as e:
            invalid_messages.labels(reason="validation_error").inc()
            logging.warning(f"Validation error: {str(e)}")
            return None

    async def process_message(self, msg: Any) -> None:
        start_time = time.time()
        data = self.parse_message(msg.value)
        if data:
            messages_consumed.labels(symbol=data["symbol"]).inc()
            self.records_buffer.append(data)
            current_batch_size.set(len(self.records_buffer))
            batch_size_histogram.observe(len(self.records_buffer))
            
            # Track Kafka consumer metrics
            kafka_consumer_lag.labels(partition=str(msg.partition)).set(
                msg.highwater - msg.offset
            )
            kafka_partition_offset.labels(partition=str(msg.partition)).set(msg.offset)
            
            # Measure consume latency
            kafka_consume_latency.observe(time.time() - start_time)
            
            if self._should_flush():
                await self._flush_buffer()

    def _should_flush(self) -> bool:
        if len(self.records_buffer) >= self.current_max_batch_size:
            return True
        if (time.time() - self.last_flush_time) >= config.insert.time_interval:
            return True
        return False

    async def _flush_buffer(self) -> None:
        if not self.records_buffer:
            return

        start_time = time.time()
        try:
            batched_records = defaultdict(list)
            for record in self.records_buffer:
                batched_records[record["symbol"]].append(record)

            for symbol, symbol_records in batched_records.items():
                await self.db_manager.insert_batch(symbol_records)
                messages_inserted.labels(symbol=symbol).inc(len(symbol_records))

            insert_latency = time.time() - start_time
            db_insert_latency.observe(insert_latency)
            message_processing_rate.observe(len(self.records_buffer) / insert_latency)
            
            self._adapt_polling_parameters(insert_latency)
            
        except Exception as e:
            db_insert_errors.labels(error_type=type(e).__name__).inc()
            logging.error(f"Failed to insert batch: {str(e)}", exc_info=True)
            await self._handle_insert_failure(e)
        
        finally:
            self.records_buffer.clear()
            current_batch_size.set(0)
            self.last_flush_time = time.time()

    def _adapt_polling_parameters(self, insert_latency: float) -> None:
        dyn_conf = config.dynamic_polling
        
        if insert_latency > dyn_conf.latency_threshold_high:
            self.current_poll_timeout = min(
                self.current_poll_timeout * 1.5,
                dyn_conf.poll_timeout_max
            )
            self.current_max_batch_size = max(
                int(self.current_max_batch_size * 0.8),
                dyn_conf.batch_size_min
            )
        elif insert_latency < dyn_conf.latency_threshold_low:
            self.current_poll_timeout = max(
                self.current_poll_timeout * 0.8,
                dyn_conf.poll_timeout_min
            )
            self.current_max_batch_size = min(
                int(self.current_max_batch_size * 1.2),
                dyn_conf.batch_size_max
            )
        
        # Update metrics after adaptation
        current_poll_timeout.set(self.current_poll_timeout)
        current_max_batch_size.set(self.current_max_batch_size)

    async def _handle_insert_failure(self, error: Exception) -> None:
        retry_attempts = config.insert.retry_attempts
        retry_delay = config.insert.retry_delay
        
        for attempt in range(retry_attempts):
            try:
                await asyncio.sleep(retry_delay * (2 ** attempt))
                await self._flush_buffer()
                return
            except Exception as e:
                logging.warning(f"Retry attempt {attempt + 1} failed: {str(e)}")
        
        logging.error("All retry attempts failed, sending to DLQ")

class KafkaTimescaleIngestion:
    def __init__(self):
        self.consumer: Optional[AIOKafkaConsumer] = None
        self.db_pool: Optional[Pool] = None
        self.db_manager: Optional[DatabaseManager] = None
        self.message_processor: Optional[MessageProcessor] = None
        self.running: bool = False

    async def startup(self) -> None:
        from prometheus_client import start_http_server
        start_http_server(config.metrics.port)
        
        kafka_config = config.kafka
        self.consumer = AIOKafkaConsumer(
            kafka_config.topic,
            bootstrap_servers=kafka_config.bootstrap_servers,
            group_id=kafka_config.group_id,
            enable_auto_commit=True,
            auto_offset_reset="earliest"
        )
        await self.consumer.start()
        
        db_config = config.timescaledb
        self.db_pool = await create_pool(
            host=db_config.host,
            port=db_config.port,
            database=db_config.dbname,
            user=db_config.user,
            password=db_config.password,
            min_size=1,
            max_size=db_config.pool_size
        )
        
        circuit_breaker = DatabaseCircuitBreaker(config.circuit_breaker)
        self.db_manager = DatabaseManager(self.db_pool, circuit_breaker)
        self.message_processor = MessageProcessor(self.db_manager)
        
        self.running = True 

    async def shutdown(self) -> None:
        """Gracefully shut down all connections and resources."""
        self.running = False
        
        if self.consumer is not None:
            await self.consumer.stop()
            
        if self.db_pool is not None:
            await self.db_pool.close()
            
        logging.info("All resources have been cleaned up") 