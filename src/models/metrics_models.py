from typing import Dict, TypedDict
from datetime import datetime

class DBStats(TypedDict):
    total_records: int
    unique_symbols: int
    oldest_record: datetime
    newest_record: datetime

class ManagerStats(TypedDict):
    db_stats: DBStats
    batch_stats: Dict[str, int]
    retry_queue_size: int

class DBQueryResult(TypedDict):
    total_records: int
    unique_symbols: int
    oldest_record: datetime
    newest_record: datetime 