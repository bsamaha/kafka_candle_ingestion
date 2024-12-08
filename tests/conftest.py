import asyncio
import pytest
from typing import AsyncGenerator, Generator
import docker
import time
from asyncpg import Pool, create_pool
from src.config.test_config import test_config
from pytest import FixtureRequest

@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session")
async def docker_setup(request: FixtureRequest) -> AsyncGenerator[None, None]:
    client = docker.from_env()
    
    # Start Kafka and Zookeeper
    kafka_network = client.networks.create("kafka_test_network", driver="bridge")
    
    zookeeper = client.containers.run(
        "confluentinc/cp-zookeeper:latest",
        environment={"ZOOKEEPER_CLIENT_PORT": "2181"},
        network="kafka_test_network",
        name="zookeeper_test",
        detach=True
    )
    
    kafka = client.containers.run(
        "confluentinc/cp-kafka:latest",
        environment={
            "KAFKA_ZOOKEEPER_CONNECT": "zookeeper_test:2181",
            "KAFKA_ADVERTISED_LISTENERS": f"PLAINTEXT://{test_config.kafka.bootstrap_servers}",
            "KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR": "1"
        },
        ports={'9092/tcp': 9092},
        network="kafka_test_network",
        name="kafka_test",
        detach=True
    )
    
    timescaledb = client.containers.run(
        "timescale/timescaledb:latest-pg14",
        environment={
            "POSTGRES_DB": test_config.timescaledb.dbname,
            "POSTGRES_USER": test_config.timescaledb.user,
            "POSTGRES_PASSWORD": test_config.timescaledb.password
        },
        ports={'5432/tcp': test_config.timescaledb.port},
        name="timescaledb_test",
        detach=True
    )
    
    # Wait for services to be ready
    time.sleep(30)  # Adjust based on your system
    
    yield
    
    # Cleanup
    kafka.stop()
    zookeeper.stop()
    timescaledb.stop()
    kafka.remove()
    zookeeper.remove()
    timescaledb.remove()
    kafka_network.remove()

@pytest.fixture
async def db_pool(docker_setup: None) -> AsyncGenerator[Pool, None]:
    pool = await create_pool(
        host=test_config.timescaledb.host,
        port=test_config.timescaledb.port,
        database=test_config.timescaledb.dbname,
        user=test_config.timescaledb.user,
        password=test_config.timescaledb.password
    )
    yield pool
    await pool.close() 