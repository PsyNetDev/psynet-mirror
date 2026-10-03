from dallinger.db import redis_conn

from .serialize import serialize, unserialize
from .utils import NoArgumentProvided


class RedisVarStore:
    """
    The RedisVarStore class
    """

    def get(self, name, default=NoArgumentProvided):
        raw = redis_conn.get(name)
        if raw is None:
            if default == NoArgumentProvided:
                raise KeyError
            else:
                return default
        return unserialize(raw.decode("utf-8"))

    def set(self, name, value):
        redis_conn.set(name, serialize(value))

    def clear(self):
        """Delete every key in the Redis database."""
        batch = []
        for key in redis_conn.scan_iter(count=1000):
            batch.append(key)
            if len(batch) == 1000:
                redis_conn.delete(*batch)
                batch = []
        if batch:
            redis_conn.delete(*batch)


redis_vars = RedisVarStore()
