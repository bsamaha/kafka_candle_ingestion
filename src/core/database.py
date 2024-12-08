import logging
import asyncio
from typing import List, Dict, Any
from asyncpg import Pool, Connection, DeadlockDetectedError, UniqueViolationError
from src.core.circuit_breaker import DatabaseCircuitBreaker
from src.metrics.prometheus import (
    db_connection_pool_size, db_insert_latency, db_insert_errors,
    db_connection_errors, db_pool_waiting_clients
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
                start_time = time.time()
                try:
                    async with self.pool.acquire() as conn:
                        self._update_pool_metrics()
                        
                        values = [
                            (
                                r['event_time'], r['symbol'], r['open_price'],
                                r['high_price'], r['low_price'], r['close_price'],
                                r['volume']
                            ) for r in records
                        ]
                        
                        async with conn.transaction():
                            await self._execute_with_retry(
                                conn,
                                """
                                INSERT INTO market_data (
                                    time, symbol, open_price, high_price, 
                                    low_price, close_price, volume
                                ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                                """,
                                values
                            )
                            
                    db_insert_latency.observe(time.time() - start_time)
                    
                except Exception as e:
                    db_connection_errors.inc()
                    logger.error(f"Database operation failed: {str(e)}", exc_info=True)
                    raise DatabaseError(f"Batch insert failed: {str(e)}") from e
                finally:
                    self._update_pool_metrics()

            return await self.circuit_breaker.execute(_do_insert)
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
                    DELETE FROM market_data 
                    WHERE time < NOW() - INTERVAL '90 days'
                """)
        except Exception as e:
            logger.error(f"Cleanup failed: {str(e)}")
            raise DatabaseError(f"Data cleanup failed: {str(e)}") from e 