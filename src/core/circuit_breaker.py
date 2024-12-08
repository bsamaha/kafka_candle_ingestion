import time
from typing import Any, Callable
from src.models.data_models import CircuitBreakerState
from src.metrics.prometheus import (
    circuit_breaker_state, circuit_breaker_trips,
    db_connection_errors
)
from src.config import CircuitBreakerConfig
from src.utils.logging import get_logger

logger = get_logger(__name__)

class CircuitBreakerError(Exception):
    """Custom exception for circuit breaker failures"""
    pass

class DatabaseCircuitBreaker:
    def __init__(self, config: CircuitBreakerConfig):
        self.state = CircuitBreakerState.CLOSED
        self.failures = 0
        self.last_failure_time: float = 0
        self.last_success_time: float = time.time()
        self.config = config
        self._update_metrics()
        logger.info(
            "circuit_breaker_initialized",
            state=self.state.value
        )
        
    def _update_metrics(self) -> None:
        """Update Prometheus metrics for circuit breaker state"""
        try:
            circuit_breaker_state.set(
                {
                    CircuitBreakerState.CLOSED: 0,
                    CircuitBreakerState.HALF_OPEN: 1,
                    CircuitBreakerState.OPEN: 2
                }[self.state]
            )
        except Exception as e:
            logger.error(
                "metrics_update_failed",
                error=str(e),
                exc_info=True
            )

    def _should_attempt_reset(self) -> bool:
        """Determine if enough time has passed to attempt reset"""
        time_since_failure = time.time() - self.last_failure_time
        return time_since_failure >= self.config.reset_timeout

    def _handle_success(self) -> None:
        """Handle successful operation"""
        if self.state == CircuitBreakerState.HALF_OPEN:
            logger.info(
                "circuit_breaker_reset",
                previous_state=self.state.value,
                failures=self.failures
            )
            self.state = CircuitBreakerState.CLOSED
            self._update_metrics()
        
        self.failures = 0
        self.last_success_time = time.time()

    def _handle_failure(self, error: Exception) -> None:
        """Handle operation failure"""
        self.failures += 1
        self.last_failure_time = time.time()
        
        if self.failures >= self.config.failure_threshold:
            if self.state != CircuitBreakerState.OPEN:
                logger.warning(
                    "circuit_breaker_tripped",
                    failures=self.failures,
                    error=str(error)
                )
                self.state = CircuitBreakerState.OPEN
                circuit_breaker_trips.inc()
                self._update_metrics()
        
        logger.error(
            "operation_failed",
            state=self.state.value,
            failures=f"{self.failures}/{self.config.failure_threshold}",
            error=str(error)
        )

    async def execute(self, operation: Callable, *args: Any, **kwargs: Any) -> Any:
        """Execute an operation with circuit breaker protection"""
        if self.state == CircuitBreakerState.OPEN:
            if self._should_attempt_reset():
                logger.info(
                    "attempting_reset",
                    timeout=self.config.reset_timeout
                )
                self.state = CircuitBreakerState.HALF_OPEN
                self._update_metrics()
            else:
                wait_time = self.config.reset_timeout - (time.time() - self.last_failure_time)
                logger.warning(
                    "circuit_breaker_open",
                    wait_time=f"{wait_time:.1f}s"
                )
                raise CircuitBreakerError(
                    f"Circuit breaker is OPEN. Retry available in {wait_time:.1f}s"
                )

        try:
            start_time = time.time()
            result = await operation(*args, **kwargs)
            
            execution_time = time.time() - start_time
            if execution_time > 1.0:
                logger.warning(
                    "slow_operation",
                    operation=operation.__name__,
                    duration=f"{execution_time:.2f}s"
                )
            
            self._handle_success()
            return result

        except Exception as e:
            self._handle_failure(e)
            db_connection_errors.inc()
            
            logger.error(
                "circuit_breaker_operation_failed",
                state=self.state.value,
                failures=self.failures,
                last_success=time.time() - self.last_success_time,
                operation=operation.__name__,
                error=str(e),
                exc_info=True
            )
            
            raise CircuitBreakerError(
                f"Operation failed in {self.state.value} state: {str(e)}"
            ) from e

    async def get_status(self) -> dict:
        """Get current circuit breaker status"""
        return {
            'state': self.state.value,
            'failures': self.failures,
            'last_failure': self.last_failure_time,
            'last_success': self.last_success_time,
            'failure_threshold': self.config.failure_threshold,
            'reset_timeout': self.config.reset_timeout
        }