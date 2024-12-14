import logging
import asyncio
from typing import List, Dict, Any, Optional, cast
from asyncpg import Pool, Connection, DeadlockDetectedError, UniqueViolationError, Record
from datetime import datetime
from src.models.metrics_models import DBStats, ManagerStats, DBQueryResult
from src.core.circuit_breaker import DatabaseCircuitBreaker
from src.metrics.prometheus import (
    db_connection_pool_size, db_insert_latency, db_insert_errors,
    db_connection_errors, db_pool_waiting_clients,
    batch_size_histogram, message_processing_rate,
    db_records_total, db_oldest_record, db_newest_record, db_retry_queue_size,
    batch_processing_total, data_validation_errors, update_db_stats_metrics
)
import time
from src.utils.logging import get_logger

logger = get_logger(__name__)

class DatabaseError(Exception):
    """Base exception for database operations"""
    pass


class DatabaseManager:
    def __init__(self, pool: Pool, circuit_breaker: DatabaseCircuitBreaker):
        self.pool = pool
        self.circuit_breaker = circuit_breaker
        self._update_pool_metrics()
        self.logger = logger
        self.retry_queue: List[Dict[str, Any]] = []
        self.max_retry_queue_size = 10000  # Configurable
        self.batch_stats = {
            'total_processed': 0,
            'total_retried': 0,
            'total_dropped': 0
        }

    def _update_pool_metrics(self) -> None:
        """Update Prometheus metrics for pool status"""
        try:
            # Get current pool size and max size
            current_size = self.pool.get_size()
            max_size = self.pool.get_max_size()
            
            db_connection_pool_size.set(current_size)
            
            # Estimate pool utilization (connections in use)
            db_pool_waiting_clients.set(current_size)
            
        except Exception:
            logger.warning("Could not update pool metrics", exc_info=True)
            # Set default values to avoid missing metrics
            db_connection_pool_size.set(0)
            db_pool_waiting_clients.set(0)

    async def _execute_with_retry(self, conn: Connection, query: str, values: List[tuple]) -> Any:
        """Execute a query with retry logic for deadlocks"""
        max_retries = 3
        base_delay = 0.1  # 100ms

        for attempt in range(max_retries):
            try:
                return await conn.executemany(query, values)
            except DeadlockDetectedError:
                if attempt == max_retries - 1:
                    raise
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Deadlock detected, retry attempt {attempt + 1} after {delay}s")
                await asyncio.sleep(delay)
            except UniqueViolationError:
                logger.warning("Duplicate record detected, skipping")
                db_insert_errors.labels(error_type="unique_violation").inc()
                return None
            except Exception as e:
                logger.error(f"Query execution error: {str(e)}")
                db_insert_errors.labels(error_type=type(e).__name__).inc()
                raise DatabaseError(f"Query execution failed: {str(e)}") from e

    async def insert_batch(self, records: List[Dict[str, Any]]) -> None:
        """Insert a batch of records into the market_data table"""
        if not records:
            return

        logger.info(
            "inserting_batch",
            batch_size=len(records),
            table="market_data"
        )
        
        try:
            async def _do_insert():
                # First try to insert any queued records
                if self.retry_queue:
                    await self._insert_records(self.retry_queue)
                    self.retry_queue.clear()
                
                # Then insert new records
                await self._insert_records(records)

            result = await self.circuit_breaker.execute(_do_insert)
            
            if result is None:  # Circuit breaker is open
                # Queue records for later retry if there's space
                if len(self.retry_queue) + len(records) <= self.max_retry_queue_size:
                    self.retry_queue.extend(records)
                    logger.info(
                        "queued_records_for_retry",
                        queue_size=len(self.retry_queue)
                    )
                else:
                    logger.error(
                        "retry_queue_full",
                        dropped_records=len(records)
                    )
                    
        except Exception as e:
            logger.error(
                "batch_insert_failed",
                error=str(e),
                batch_size=len(records),
                exc_info=True
            )

    async def get_health(self) -> bool:
        """Check database health by executing a simple query"""
        try:
            async with self.pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
                return True
        except Exception as e:
            logger.error(f"Health check failed: {str(e)}")
            return False

    async def cleanup(self) -> None:
        """Cleanup old data based on retention policy"""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    DELETE FROM candles 
                    WHERE time < NOW() - INTERVAL '90 days'
                """)
        except Exception as e:
            logger.error(f"Cleanup failed: {str(e)}")
            raise DatabaseError(f"Data cleanup failed: {str(e)}") from e

    async def _insert_records(self, records: List[Dict[str, Any]]) -> None:
        """Insert or update records in the candles table"""
        start_time = time.time()
        try:
            async with self.pool.acquire() as conn:
                self._update_pool_metrics()
                
                # Add validation for numeric fields
                values = []
                for r in records:
                    try:
                        values.append((
                            r['start_time'], r['symbol'],
                            float(r['open_price']), float(r['high_price']),
                            float(r['low_price']), float(r['close_price']),
                            float(r['volume'])
                        ))
                    except (ValueError, TypeError) as e:
                        logger.error(
                            "invalid_record_data",
                            record=r,
                            error=str(e)
                        )
                        data_validation_errors.labels(
                            field=str(e).split()[0],
                            error_type=type(e).__name__
                        ).inc()
                        continue

                if not values:
                    return

                async with conn.transaction():
                    await self._execute_with_retry(
                        conn,
                        """
                        INSERT INTO candles (
                            time, symbol, open, high, 
                            low, close, volume
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                        ON CONFLICT (time, symbol) DO UPDATE SET
                            open = EXCLUDED.open,
                            high = GREATEST(candles.high, EXCLUDED.high),
                            low = LEAST(candles.low, EXCLUDED.low),
                            close = EXCLUDED.close,
                            volume = EXCLUDED.volume
                        RETURNING time, symbol
                        """,
                        values
                    )
                    
            insert_duration = time.time() - start_time
            db_insert_latency.observe(insert_duration)
            
            # Track batch processing metrics
            batch_size = len(records)
            batch_size_histogram.observe(batch_size)
            message_processing_rate.observe(batch_size / insert_duration)
            
            self.batch_stats['total_processed'] += batch_size
            
            batch_processing_total.labels(status="success").inc()
            
        except Exception as e:
            db_connection_errors.inc()
            logger.error(
                "database_operation_failed",
                error=str(e),
                record_count=len(records),
                exc_info=True
            )
            raise DatabaseError(f"Batch insert failed: {str(e)}") from e
        finally:
            self._update_pool_metrics()

    async def get_stats(self) -> ManagerStats:
        """Get database operation statistics"""
        try:
            async with self.pool.acquire() as conn:
                result: Optional[Record] = await conn.fetchrow("""
                    SELECT 
                        COUNT(*) as total_records,
                        COUNT(DISTINCT symbol) as unique_symbols,
                        MIN(time) as oldest_record,
                        MAX(time) as newest_record
                    FROM candles
                """)
                
                if not result:
                    return ManagerStats(
                        db_stats=DBStats(
                            total_records=0,
                            unique_symbols=0,
                            oldest_record=datetime.now(),
                            newest_record=datetime.now()
                        ),
                        batch_stats=self.batch_stats,
                        retry_queue_size=len(self.retry_queue)
                    )

                # Cast the Record to our TypedDict
                query_result = DBQueryResult(
                    total_records=int(result['total_records']),
                    unique_symbols=int(result['unique_symbols']),
                    oldest_record=result['oldest_record'],
                    newest_record=result['newest_record']
                )

                stats = ManagerStats(
                    db_stats=DBStats(
                        total_records=query_result['total_records'],
                        unique_symbols=query_result['unique_symbols'],
                        oldest_record=query_result['oldest_record'],
                        newest_record=query_result['newest_record']
                    ),
                    batch_stats=self.batch_stats,
                    retry_queue_size=len(self.retry_queue)
                )

                # Update Prometheus metrics with latest stats
                await update_db_stats_metrics(stats, conn)

                return stats
        except Exception as e:
            logger.error("Failed to get stats", error=str(e))
            return ManagerStats(
                db_stats=DBStats(
                    total_records=0,
                    unique_symbols=0,
                    oldest_record=datetime.now(),
                    newest_record=datetime.now()
                ),
                batch_stats=self.batch_stats,
                retry_queue_size=len(self.retry_queue)
            )

    async def vacuum_analyze(self) -> None:
        """Perform maintenance on the candles table"""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("VACUUM ANALYZE candles")
                logger.info("vacuum_analyze_completed")
        except Exception as e:
            logger.error("vacuum_analyze_failed", error=str(e))