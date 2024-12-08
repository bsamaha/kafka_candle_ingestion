import os
import asyncio
import signal
from typing import Optional
from aiokafka import AIOKafkaConsumer
from src.core.processor import KafkaTimescaleIngestion, MessageProcessor
from src.metrics.prometheus import setup_metrics_server
from src.utils.logging import setup_structured_logging, get_logger

logger = get_logger(__name__)

async def main() -> None:
    setup_structured_logging(os.getenv('LOG_LEVEL', 'INFO'))
    logger.info("application_start", version="1.0.0")
    
    # Start metrics server
    await setup_metrics_server()
    
    app = KafkaTimescaleIngestion()
    
    try:
        await app.startup()
        
        # Setup signal handlers for graceful shutdown
        loop = asyncio.get_running_loop()
        signals = (signal.SIGTERM, signal.SIGINT)
        for s in signals:
            loop.add_signal_handler(
                s, lambda s=s: asyncio.create_task(app.shutdown())
            )
            
        consumer: AIOKafkaConsumer = app.consumer # type: ignore
        message_processor: MessageProcessor = app.message_processor # type: ignore
            
        while app.running:
            try:
                logger.debug(
                    "polling_kafka",
                    timeout=message_processor.current_poll_timeout
                )
                batch = await consumer.getmany(
                    timeout_ms=int(message_processor.current_poll_timeout * 1000)
                )
                
                if not batch:
                    logger.debug("no_messages_received")
                    continue
                    
                logger.debug(
                    "received_batch",
                    partition_count=len(batch)
                )
                
                for topic_partition, messages in batch.items():
                    logger.debug(
                        "processing_messages",
                        topic=topic_partition.topic,
                        partition=topic_partition.partition,
                        message_count=len(messages)
                    )
                    for msg in messages:
                        await message_processor.process_message(msg)
                        
            except Exception as e:
                logger.error(
                    "message_processing_error",
                    error=str(e),
                    exc_info=True
                )
                if not app.running:
                    logger.debug("shutdown_signal_received")
                    break
                logger.debug("retrying_after_error", delay=1)
                await asyncio.sleep(1)
                
    except KeyboardInterrupt:
        logger.info("graceful_shutdown_initiated")
    except Exception as e:
        logger.error(
            "fatal_error",
            error=str(e),
            exc_info=True
        )
    finally:
        await app.shutdown()

if __name__ == "__main__":
    asyncio.run(main()) 