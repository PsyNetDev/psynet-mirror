import atexit
import html
import json
import os
import re
import sys
import threading
import time
import traceback
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import perf_counter
from typing import Dict, Iterable, List, Optional, Tuple, TypeVar

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Mapper
from sqlalchemy.orm import Session as SASession

_AUTO_PROFILER = None
_MODULE_PATH = os.path.abspath(__file__).replace("\\", "/")
_RAW_PROFILE_FILENAME_RE = re.compile(r"^sql-profile-\d+-\d+\.json$")
_StatType = TypeVar("_StatType")


@dataclass
class QueryStats:
    """
    Aggregate statistics for a normalized SQL statement.

    Parameters
    ----------
    statement
        Normalized SQL statement.
    stack
        Optional stack trace identifying the callsite.
    callsite_counts
        Counts of execution callsites observed for this statement.
    """

    statement: str
    stack: Optional[Tuple[str, ...]]
    callsite_counts: Dict[str, int] = field(default_factory=dict)
    count: int = 0
    total_ms: float = 0.0
    min_ms: float = float("inf")
    max_ms: float = 0.0

    def add(self, duration_ms: float, callsite: Optional[str] = None) -> None:
        _update_timing_aggregates(self, duration_ms)
        if callsite:
            self.callsite_counts[callsite] = self.callsite_counts.get(callsite, 0) + 1

    @property
    def mean_ms(self) -> float:
        if self.count == 0:
            return 0.0
        return self.total_ms / self.count


@dataclass
class CommitStats:
    """
    Aggregate commit timing statistics grouped by callsite.

    Parameters
    ----------
    callsite
        The resolved callsite for the commit.
    commit_type_counts
        Counts of commit types observed at this callsite.
    """

    callsite: str
    commit_type_counts: Dict[str, int] = field(default_factory=dict)
    count: int = 0
    total_ms: float = 0.0
    min_ms: float = float("inf")
    max_ms: float = 0.0

    def add(self, duration_ms: float, commit_type: str) -> None:
        _update_timing_aggregates(self, duration_ms)
        self.commit_type_counts[commit_type] = (
            self.commit_type_counts.get(commit_type, 0) + 1
        )

    @property
    def mean_ms(self) -> float:
        if self.count == 0:
            return 0.0
        return self.total_ms / self.count

    @property
    def types_summary(self) -> str:
        if not self.commit_type_counts:
            return "unknown"
        parts = [
            f"{commit_type}={count}"
            for commit_type, count in sorted(self.commit_type_counts.items())
        ]
        return ", ".join(parts)


class SQLAlchemyQueryProfiler:
    """
    Collect timing statistics for SQLAlchemy statements and commits.

    Parameters
    ----------
    engine :
        SQLAlchemy engine to attach to.
    capture_stack : bool, optional
        Whether to capture stack traces and group by them.
    stack_depth : int, optional
        Maximum number of frames to keep when capturing stacks.
    min_duration_ms : float, optional
        Minimum duration in milliseconds for a statement to be recorded.
    normalize_sql : bool, optional
        Whether to collapse whitespace in statements.
    max_statement_chars : int, optional
        Maximum statement length to retain before truncation.
    """

    def __init__(
        self,
        engine: Engine,
        *,
        capture_stack: bool = False,
        capture_callsite: bool = True,
        stack_depth: int = 6,
        min_duration_ms: float = 0.0,
        normalize_sql: bool = True,
        max_statement_chars: Optional[int] = None,
    ) -> None:
        self.engine = engine
        self._capture_stack = capture_stack
        self._capture_callsite = capture_callsite
        self._stack_depth = stack_depth
        self._min_duration_ms = min_duration_ms
        self._normalize_sql = normalize_sql
        self._max_statement_chars = max_statement_chars
        self._stats: Dict[Tuple[str, Optional[Tuple[str, ...]]], QueryStats] = {}
        self._commit_stats: Dict[str, CommitStats] = {}
        self._total_count = 0
        self._total_time_ms = 0.0
        self._commit_total_count = 0
        self._commit_total_time_ms = 0.0
        self._started = False
        self._lock = threading.Lock()

    def __enter__(self) -> "SQLAlchemyQueryProfiler":
        self.start()
        return self

    def __exit__(self, exc_type, exc, exc_tb) -> None:
        self.stop()

    @property
    def total_count(self) -> int:
        return self._total_count

    @property
    def total_time_ms(self) -> float:
        return self._total_time_ms

    @property
    def commit_total_count(self) -> int:
        return self._commit_total_count

    @property
    def commit_total_time_ms(self) -> float:
        return self._commit_total_time_ms

    def start(self) -> None:
        if self._started:
            return
        event.listen(self.engine, "before_cursor_execute", self._before_cursor_execute)
        event.listen(self.engine, "after_cursor_execute", self._after_cursor_execute)
        event.listen(SASession, "before_commit", self._before_commit)
        event.listen(SASession, "after_commit", self._after_commit)
        event.listen(SASession, "after_rollback", self._after_rollback)
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        event.remove(self.engine, "before_cursor_execute", self._before_cursor_execute)
        event.remove(self.engine, "after_cursor_execute", self._after_cursor_execute)
        event.remove(SASession, "before_commit", self._before_commit)
        event.remove(SASession, "after_commit", self._after_commit)
        event.remove(SASession, "after_rollback", self._after_rollback)
        self._started = False

    def reset(self) -> None:
        with self._lock:
            self._stats.clear()
            self._total_count = 0
            self._total_time_ms = 0.0
            self._commit_stats.clear()
            self._commit_total_count = 0
            self._commit_total_time_ms = 0.0

    def get_stats(
        self,
        *,
        top_n: Optional[int] = None,
        sort_by: str = "total_ms",
        min_total_ms: Optional[float] = None,
        min_count: int = 1,
    ) -> List[QueryStats]:
        return _filter_and_sort_stats(
            self._stats.values(),
            top_n=top_n,
            sort_by=sort_by,
            min_total_ms=min_total_ms,
            min_count=min_count,
        )

    def get_commit_stats(
        self,
        *,
        top_n: Optional[int] = None,
        sort_by: str = "total_ms",
        min_total_ms: Optional[float] = None,
        min_count: int = 1,
    ) -> List[CommitStats]:
        return _filter_and_sort_stats(
            self._commit_stats.values(),
            top_n=top_n,
            sort_by=sort_by,
            min_total_ms=min_total_ms,
            min_count=min_count,
        )

    def format_summary(
        self,
        *,
        top_n: int = 20,
        sort_by: str = "total_ms",
        min_total_ms: Optional[float] = None,
        min_count: int = 1,
        include_commits: bool = True,
    ) -> str:
        stats = self.get_stats(
            top_n=top_n,
            sort_by=sort_by,
            min_total_ms=min_total_ms,
            min_count=min_count,
        )
        lines = [
            "SQLAlchemy query profile: "
            f"{self.total_count} queries, {self.total_time_ms:.2f} ms"
        ]
        if not stats:
            lines.append("No queries captured.")
            if include_commits:
                lines.append(self.format_commit_summary())
            return "\n".join(lines)

        lines.append("count total_ms mean_ms  max_ms statement")
        for stat in stats:
            lines.append(
                f"{stat.count:5d} "
                f"{stat.total_ms:8.2f} "
                f"{stat.mean_ms:7.2f} "
                f"{stat.max_ms:7.2f} "
                f"{stat.statement}"
            )
            if stat.stack:
                lines.extend([f"      at {frame}" for frame in stat.stack])
        if include_commits:
            lines.append("")
            lines.append(self.format_commit_summary())
        return "\n".join(lines)

    def print_summary(self, **kwargs) -> None:
        print(self.format_summary(**kwargs))

    def to_dict(self) -> Dict[str, object]:
        query_stats = [
            {
                "statement": stat.statement,
                "stack": list(stat.stack) if stat.stack else None,
                "callsite_counts": dict(stat.callsite_counts),
                "count": stat.count,
                "total_ms": stat.total_ms,
                "min_ms": stat.min_ms,
                "max_ms": stat.max_ms,
            }
            for stat in self.get_stats(top_n=None, sort_by="total_ms")
        ]
        commit_stats = [
            {
                "callsite": stat.callsite,
                "count": stat.count,
                "total_ms": stat.total_ms,
                "min_ms": stat.min_ms,
                "max_ms": stat.max_ms,
                "commit_type_counts": dict(stat.commit_type_counts),
            }
            for stat in self.get_commit_stats(top_n=None, sort_by="total_ms")
        ]
        return {
            "schema_version": 1,
            "pid": os.getpid(),
            "command": " ".join(sys.argv),
            "generated_at": time.time(),
            "queries": {
                "total_count": self.total_count,
                "total_time_ms": self.total_time_ms,
                "stats": query_stats,
            },
            "commits": {
                "total_count": self.commit_total_count,
                "total_time_ms": self.commit_total_time_ms,
                "stats": commit_stats,
            },
        }

    def write_json_summary(self, output_dir: str) -> str:
        os.makedirs(output_dir, exist_ok=True)
        filename = f"sql-profile-{os.getpid()}-{time.time_ns()}.json"
        path = os.path.join(output_dir, filename)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.to_dict(), handle, indent=2, sort_keys=True)
        return path

    def format_commit_summary(
        self,
        *,
        top_n: int = 10,
        sort_by: str = "total_ms",
        min_total_ms: Optional[float] = None,
        min_count: int = 1,
    ) -> str:
        stats = self.get_commit_stats(
            top_n=top_n,
            sort_by=sort_by,
            min_total_ms=min_total_ms,
            min_count=min_count,
        )
        lines = [
            "Commit profile: "
            f"{self.commit_total_count} commits, {self.commit_total_time_ms:.2f} ms"
        ]
        if not stats:
            lines.append("No commits captured.")
            return "\n".join(lines)

        lines.append("count total_ms mean_ms  max_ms callsite types")
        for stat in stats:
            lines.append(
                f"{stat.count:5d} "
                f"{stat.total_ms:8.2f} "
                f"{stat.mean_ms:7.2f} "
                f"{stat.max_ms:7.2f} "
                f"{stat.callsite} [{stat.types_summary}]"
            )
        return "\n".join(lines)

    def print_commit_summary(self, **kwargs) -> None:
        print(self.format_commit_summary(**kwargs))

    def _before_cursor_execute(
        self, conn, cursor, statement, parameters, context, executemany
    ) -> None:
        if context is None:
            return
        context._psynet_query_start_time = perf_counter()
        if self._capture_stack:
            context._psynet_query_stack = _build_stack(self._stack_depth)
        if self._capture_callsite:
            context._psynet_query_callsite = _execution_callsite()

    def _after_cursor_execute(
        self, conn, cursor, statement, parameters, context, executemany
    ) -> None:
        if context is None:
            return
        start_time = getattr(context, "_psynet_query_start_time", None)
        if start_time is None:
            return
        duration_ms = (perf_counter() - start_time) * 1000.0
        if duration_ms < self._min_duration_ms:
            return
        statement_text = _format_statement(
            statement, self._normalize_sql, self._max_statement_chars
        )
        stack = (
            getattr(context, "_psynet_query_stack", None)
            if self._capture_stack
            else None
        )
        callsite = getattr(context, "_psynet_query_callsite", None)
        key = (statement_text, stack)
        with self._lock:
            stat = self._stats.get(key)
            if stat is None:
                stat = QueryStats(statement=statement_text, stack=stack)
                self._stats[key] = stat
            stat.add(duration_ms, callsite=callsite)
            self._total_count += 1
            self._total_time_ms += duration_ms

    def _before_commit(self, session: SASession) -> None:
        if not self._session_matches_engine(session):
            return
        session.info["_psynet_commit_start_time"] = perf_counter()
        session.info["_psynet_commit_snapshot"] = _commit_snapshot(session)
        session.info["_psynet_commit_callsite"] = _execution_callsite()

    def _after_commit(self, session: SASession) -> None:
        self._record_commit(session, rolled_back=False)

    def _after_rollback(self, session: SASession) -> None:
        self._record_commit(session, rolled_back=True)

    def _record_commit(self, session: SASession, *, rolled_back: bool) -> None:
        if not self._session_matches_engine(session):
            return
        start_time = session.info.pop("_psynet_commit_start_time", None)
        snapshot = session.info.pop("_psynet_commit_snapshot", None)
        callsite = session.info.pop("_psynet_commit_callsite", "unknown")
        if start_time is None:
            return
        duration_ms = (perf_counter() - start_time) * 1000.0
        commit_type = _classify_commit(snapshot)
        if rolled_back:
            commit_type = f"{commit_type} (rolled back)"
        key = callsite
        with self._lock:
            stat = self._commit_stats.get(key)
            if stat is None:
                stat = CommitStats(callsite=callsite)
                self._commit_stats[key] = stat
            stat.add(duration_ms, commit_type)
            self._commit_total_count += 1
            self._commit_total_time_ms += duration_ms

    def _session_matches_engine(self, session: SASession) -> bool:
        try:
            bind = session.get_bind()
        except Exception:
            return False
        if bind is None:
            return False
        if bind is self.engine:
            return True
        if hasattr(bind, "engine") and bind.engine is self.engine:
            return True
        return False


@contextmanager
def sqlalchemy_profile(engine: Engine, **kwargs) -> Iterable[SQLAlchemyQueryProfiler]:
    """
    Profile SQLAlchemy statements executed against an engine.

    Parameters
    ----------
    engine :
        SQLAlchemy engine to attach to.
    **kwargs
        Keyword arguments forwarded to ``SQLAlchemyQueryProfiler``.

    Yields
    ------
    SQLAlchemyQueryProfiler
        The active profiler instance.
    """
    profiler = SQLAlchemyQueryProfiler(engine, **kwargs)
    profiler.start()
    try:
        yield profiler
    finally:
        profiler.stop()


@contextmanager
def assert_query_count(
    max_queries: int,
    *,
    min_queries: int = 0,
    engine: Optional[Engine] = None,
    **profiler_kwargs,
) -> Iterable[SQLAlchemyQueryProfiler]:
    """
    Assert a query count budget within a block.

    Parameters
    ----------
    max_queries :
        Maximum number of SQL statements allowed.
    min_queries :
        Minimum number of SQL statements expected.
    engine :
        SQLAlchemy engine to attach to. Defaults to Dallinger's engine.
    **profiler_kwargs
        Keyword arguments forwarded to ``SQLAlchemyQueryProfiler``.

    Yields
    ------
    SQLAlchemyQueryProfiler
        The active profiler instance.
    """
    if engine is None:
        from dallinger import db

        engine = db.engine
    with sqlalchemy_profile(engine, **profiler_kwargs) as profiler:
        yield profiler
    if profiler.total_count < min_queries or profiler.total_count > max_queries:
        raise AssertionError(
            f"Expected between {min_queries} and {max_queries} queries, "
            f"but saw {profiler.total_count}."
        )


@contextmanager
def count_orm_loads() -> Iterable[Counter]:
    """
    Count ORM objects loaded from the database within a block, by class name.

    Query counts miss work that grows with the number of rows a query
    returns; the number of loaded objects captures it, independent of timing.

    Yields
    ------
    collections.Counter
        Mapping from class name to the number of objects loaded.
    """
    loads = Counter()

    def on_load(target, context):
        loads[type(target).__name__] += 1

    event.listen(Mapper, "load", on_load)
    try:
        yield loads
    finally:
        event.remove(Mapper, "load", on_load)


@contextmanager
def assert_query_duration(
    max_total_duration_ms: Optional[float] = None,
    *,
    max_query_duration_ms: Optional[float] = None,
    min_total_duration_ms: float = 0.0,
    engine: Optional[Engine] = None,
    **profiler_kwargs,
) -> Iterable[SQLAlchemyQueryProfiler]:
    """
    Assert query duration budgets within a block.

    Parameters
    ----------
    max_total_duration_ms :
        Maximum total query time in milliseconds allowed.
    max_query_duration_ms :
        Maximum single-query time in milliseconds allowed.
    min_total_duration_ms :
        Minimum total query time in milliseconds expected.
    engine :
        SQLAlchemy engine to attach to. Defaults to Dallinger's engine.
    **profiler_kwargs
        Keyword arguments forwarded to ``SQLAlchemyQueryProfiler``.

    Yields
    ------
    SQLAlchemyQueryProfiler
        The active profiler instance.
    """
    if max_total_duration_ms is None and max_query_duration_ms is None:
        raise ValueError(
            "Provide max_total_duration_ms, max_query_duration_ms, or both."
        )
    if engine is None:
        from dallinger import db

        engine = db.engine
    with sqlalchemy_profile(engine, **profiler_kwargs) as profiler:
        yield profiler
    total_ms = profiler.total_time_ms
    if total_ms < min_total_duration_ms:
        raise AssertionError(
            f"Expected total query time >= {min_total_duration_ms} ms, "
            f"but saw {total_ms:.2f} ms."
        )
    if max_total_duration_ms is not None and total_ms > max_total_duration_ms:
        raise AssertionError(
            f"Expected total query time <= {max_total_duration_ms} ms, "
            f"but saw {total_ms:.2f} ms."
        )
    if max_query_duration_ms is not None:
        stats = profiler.get_stats(top_n=None, sort_by="max_ms")
        max_stat_ms = max((stat.max_ms for stat in stats), default=0.0)
        if max_stat_ms > max_query_duration_ms:
            raise AssertionError(
                f"Expected max query time <= {max_query_duration_ms} ms, "
                f"but saw {max_stat_ms:.2f} ms."
            )


def get_active_sqlalchemy_profiler() -> Optional[SQLAlchemyQueryProfiler]:
    """
    Return the profiler enabled by environment variables, if any.

    Returns
    -------
    SQLAlchemyQueryProfiler or None
        The active environment-configured profiler instance.
    """
    return _AUTO_PROFILER


def maybe_enable_sqlalchemy_profiling(
    engine: Optional[Engine] = None,
    *,
    env_var: str = "PSYNET_SQL_PROFILE",
) -> Optional[SQLAlchemyQueryProfiler]:
    """
    Enable SQLAlchemy profiling based on environment variables.

    Parameters
    ----------
    engine :
        SQLAlchemy engine to attach to. Defaults to Dallinger's engine.
    env_var :
        Environment variable that enables profiling. Set to a truthy value or
        a comma-separated list like ``min_ms=50,top_n=20,stack=1``.
        If ``PSYNET_SQL_PROFILE_DIR`` is set, a JSON summary file will be written
        to that directory when the process exits.

    Returns
    -------
    SQLAlchemyQueryProfiler or None
        The active profiler instance if enabled.
    """
    value = os.getenv(env_var)
    settings = parse_env_settings(value)
    if not settings["enabled"]:
        return None
    if engine is None:
        from dallinger import db

        engine = db.engine
    global _AUTO_PROFILER
    if _AUTO_PROFILER is not None:
        if _AUTO_PROFILER.engine is engine:
            return _AUTO_PROFILER
        _AUTO_PROFILER.stop()
        _AUTO_PROFILER = None
    options = settings["options"]
    min_duration_ms = float(options.get("min_ms", 0.0))
    top_n = int(options.get("top_n", 20))
    capture_stack = _parse_bool(options.get("stack", "0"))
    stack_depth = int(options.get("stack_depth", 6))
    normalize_sql = _parse_bool(options.get("normalize", "1"))
    max_statement_chars = options.get("max_statement_chars")
    if max_statement_chars is not None:
        max_statement_chars = int(max_statement_chars)
    profiler = SQLAlchemyQueryProfiler(
        engine,
        capture_stack=capture_stack,
        stack_depth=stack_depth,
        min_duration_ms=min_duration_ms,
        normalize_sql=normalize_sql,
        max_statement_chars=max_statement_chars,
    )
    profiler.start()
    silent = _parse_bool(os.getenv("PSYNET_SQL_PROFILE_SILENT", "0"))
    if not silent:
        atexit.register(profiler.print_summary, top_n=top_n)
    profile_dir = os.getenv("PSYNET_SQL_PROFILE_DIR")
    if profile_dir:
        atexit.register(profiler.write_json_summary, profile_dir)
    _AUTO_PROFILER = profiler
    return profiler


def _build_stack(stack_depth: int) -> Optional[Tuple[str, ...]]:
    filtered = _filtered_stack_frames()
    if stack_depth:
        filtered = filtered[-stack_depth:]
    if not filtered:
        return None
    return tuple(
        f"{frame.filename}:{frame.lineno} in {frame.name}" for frame in filtered
    )


def _format_statement(
    statement: str,
    normalize_sql: bool,
    max_statement_chars: Optional[int],
) -> str:
    statement_text = str(statement)
    if normalize_sql:
        statement_text = " ".join(statement_text.split())
    if max_statement_chars and len(statement_text) > max_statement_chars:
        statement_text = statement_text[: max_statement_chars - 3] + "..."
    return statement_text


def _sort_key(sort_by: str):
    sort_by = sort_by.lower()
    if sort_by == "mean_ms":
        return lambda stat: stat.mean_ms
    if sort_by == "count":
        return lambda stat: stat.count
    if sort_by == "max_ms":
        return lambda stat: stat.max_ms
    return lambda stat: stat.total_ms


def _update_timing_aggregates(stat, duration_ms: float) -> None:
    stat.count += 1
    stat.total_ms += duration_ms
    if stat.count == 1:
        stat.min_ms = duration_ms
    else:
        stat.min_ms = min(stat.min_ms, duration_ms)
    stat.max_ms = max(stat.max_ms, duration_ms)


def _filter_and_sort_stats(
    stats: Iterable[_StatType],
    *,
    top_n: Optional[int],
    sort_by: str,
    min_total_ms: Optional[float],
    min_count: int,
) -> List[_StatType]:
    filtered_stats = [
        stat
        for stat in stats
        if stat.count >= min_count
        and (min_total_ms is None or stat.total_ms >= min_total_ms)
    ]
    sort_key = _sort_key(sort_by)
    filtered_stats.sort(key=sort_key, reverse=True)
    if top_n is not None:
        filtered_stats = filtered_stats[:top_n]
    return filtered_stats


def _parse_bool(value: str) -> bool:
    value = value.strip().lower()
    return value not in {"0", "false", "no", "off", ""}


def parse_env_settings(value: Optional[str]) -> Dict[str, object]:
    if value is None:
        return {"enabled": False, "options": {}}
    raw = value.strip()
    if raw == "":
        return {"enabled": False, "options": {}}
    enabled = raw.lower() not in {"0", "false", "no", "off"}
    options: Dict[str, str] = {}
    if "=" in raw:
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            if "=" not in part:
                options[part.lower()] = "true"
                continue
            key, val = part.split("=", 1)
            options[key.strip().lower()] = val.strip()
    return {"enabled": enabled, "options": options}


# Backwards-compatibility alias; prefer parse_env_settings.
_parse_env_settings = parse_env_settings


def aggregate_sqlalchemy_profiles(profile_dir: str) -> Dict[str, object]:
    profiles = []
    if os.path.isdir(profile_dir):
        for filename in sorted(os.listdir(profile_dir)):
            if not _RAW_PROFILE_FILENAME_RE.match(filename):
                continue
            path = os.path.join(profile_dir, filename)
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            data["_source_path"] = path
            profiles.append(data)
    return _aggregate_profile_dicts(profiles)


def _aggregate_profile_dicts(
    profiles: Iterable[Dict[str, object]],
) -> Dict[str, object]:
    query_stats_map: Dict[Tuple[str, Optional[Tuple[str, ...]]], Dict[str, object]] = {}
    commit_stats_map: Dict[str, Dict[str, object]] = {}
    total_query_count = 0
    total_query_time_ms = 0.0
    total_commit_count = 0
    total_commit_time_ms = 0.0
    sources = []

    for profile in profiles:
        sources.append(
            {
                "pid": profile.get("pid"),
                "command": profile.get("command"),
                "source_path": profile.get("_source_path"),
            }
        )
        queries = profile.get("queries", {})
        total_query_count += int(queries.get("total_count", 0) or 0)
        total_query_time_ms += float(queries.get("total_time_ms", 0.0) or 0.0)
        for stat in queries.get("stats", []) or []:
            statement = stat.get("statement", "")
            stack = stat.get("stack")
            stack_key = tuple(stack) if stack else None
            key = (statement, stack_key)
            existing = query_stats_map.get(key)
            if existing is None:
                existing = {
                    "statement": statement,
                    "stack": list(stack) if stack else None,
                    "callsite_counts": {},
                    "count": 0,
                    "total_ms": 0.0,
                    "min_ms": float("inf"),
                    "max_ms": 0.0,
                }
                query_stats_map[key] = existing
            count = int(stat.get("count", 0) or 0)
            total_ms = float(stat.get("total_ms", 0.0) or 0.0)
            min_ms = float(stat.get("min_ms", 0.0) or 0.0)
            max_ms = float(stat.get("max_ms", 0.0) or 0.0)
            existing["count"] += count
            existing["total_ms"] += total_ms
            existing["min_ms"] = min(existing["min_ms"], min_ms)
            existing["max_ms"] = max(existing["max_ms"], max_ms)
            for callsite, call_count in (stat.get("callsite_counts") or {}).items():
                existing["callsite_counts"][callsite] = existing["callsite_counts"].get(
                    callsite, 0
                ) + int(call_count or 0)

        commits = profile.get("commits", {})
        total_commit_count += int(commits.get("total_count", 0) or 0)
        total_commit_time_ms += float(commits.get("total_time_ms", 0.0) or 0.0)
        for stat in commits.get("stats", []) or []:
            callsite = stat.get("callsite", "unknown")
            existing = commit_stats_map.get(callsite)
            if existing is None:
                existing = {
                    "callsite": callsite,
                    "count": 0,
                    "total_ms": 0.0,
                    "min_ms": float("inf"),
                    "max_ms": 0.0,
                    "commit_type_counts": {},
                }
                commit_stats_map[callsite] = existing
            count = int(stat.get("count", 0) or 0)
            total_ms = float(stat.get("total_ms", 0.0) or 0.0)
            min_ms = float(stat.get("min_ms", 0.0) or 0.0)
            max_ms = float(stat.get("max_ms", 0.0) or 0.0)
            existing["count"] += count
            existing["total_ms"] += total_ms
            existing["min_ms"] = min(existing["min_ms"], min_ms)
            existing["max_ms"] = max(existing["max_ms"], max_ms)
            for commit_type, type_count in (
                stat.get("commit_type_counts") or {}
            ).items():
                existing["commit_type_counts"][commit_type] = existing[
                    "commit_type_counts"
                ].get(commit_type, 0) + int(type_count or 0)

    query_stats = sorted(
        query_stats_map.values(), key=lambda item: item["total_ms"], reverse=True
    )
    commit_stats = sorted(
        commit_stats_map.values(), key=lambda item: item["total_ms"], reverse=True
    )
    return {
        "schema_version": 1,
        "profiles": len(sources),
        "generated_at": time.time(),
        "sources": sources,
        "queries": {
            "total_count": total_query_count,
            "total_time_ms": total_query_time_ms,
            "stats": query_stats,
        },
        "commits": {
            "total_count": total_commit_count,
            "total_time_ms": total_commit_time_ms,
            "stats": commit_stats,
        },
    }


def format_aggregated_profile(
    aggregated: Dict[str, object],
    *,
    top_n: int = 20,
    commit_top_n: int = 10,
    sort_by: str = "total_ms",
) -> str:
    queries = aggregated.get("queries", {})
    commits = aggregated.get("commits", {})
    query_stats = list(queries.get("stats", []) or [])
    commit_stats = list(commits.get("stats", []) or [])

    query_stats.sort(key=lambda stat: _sort_value_for_dict(stat, sort_by), reverse=True)
    commit_stats.sort(
        key=lambda stat: _sort_value_for_dict(stat, sort_by), reverse=True
    )

    lines = [
        "Aggregated SQLAlchemy query profile: "
        f"{queries.get('total_count', 0)} queries, "
        f"{float(queries.get('total_time_ms', 0.0) or 0.0):.2f} ms"
    ]
    if not query_stats:
        lines.append("No queries captured.")
    else:
        lines.append("count total_ms mean_ms  max_ms statement")
        for stat in query_stats[:top_n]:
            count = int(stat.get("count", 0) or 0)
            total_ms = float(stat.get("total_ms", 0.0) or 0.0)
            mean_ms = total_ms / count if count else 0.0
            max_ms = float(stat.get("max_ms", 0.0) or 0.0)
            statement = stat.get("statement", "")
            lines.append(
                f"{count:5d} {total_ms:8.2f} {mean_ms:7.2f} {max_ms:7.2f} {statement}"
            )
            for frame in stat.get("stack") or []:
                lines.append(f"      at {frame}")

    lines.append("")
    lines.append(
        "Commit profile: "
        f"{commits.get('total_count', 0)} commits, "
        f"{float(commits.get('total_time_ms', 0.0) or 0.0):.2f} ms"
    )
    if not commit_stats:
        lines.append("No commits captured.")
    else:
        lines.append("count total_ms mean_ms  max_ms callsite types")
        for stat in commit_stats[:commit_top_n]:
            count = int(stat.get("count", 0) or 0)
            total_ms = float(stat.get("total_ms", 0.0) or 0.0)
            mean_ms = total_ms / count if count else 0.0
            max_ms = float(stat.get("max_ms", 0.0) or 0.0)
            callsite = stat.get("callsite", "unknown")
            types = _format_commit_type_counts(stat.get("commit_type_counts") or {})
            lines.append(
                f"{count:5d} {total_ms:8.2f} {mean_ms:7.2f} {max_ms:7.2f} "
                f"{callsite} [{types}]"
            )

    return "\n".join(lines)


def _sort_value_for_dict(stat: Dict[str, object], sort_by: str) -> float:
    sort_by = sort_by.lower()
    if sort_by == "mean_ms":
        total_ms = float(stat.get("total_ms", 0.0) or 0.0)
        count = int(stat.get("count", 0) or 0)
        return total_ms / count if count else 0.0
    if sort_by == "count":
        return float(stat.get("count", 0) or 0)
    if sort_by == "max_ms":
        return float(stat.get("max_ms", 0.0) or 0.0)
    return float(stat.get("total_ms", 0.0) or 0.0)


def _format_commit_type_counts(type_counts: Dict[str, int]) -> str:
    if not type_counts:
        return "unknown"
    parts = [
        f"{commit_type}={count}" for commit_type, count in sorted(type_counts.items())
    ]
    return ", ".join(parts)


def _severity_class(
    percent_total: float,
    max_ms: float,
    *,
    high_percent: float,
    medium_percent: float,
    low_percent: float,
    high_max_ms: float,
    medium_max_ms: float,
    low_max_ms: float,
) -> str:
    if percent_total >= high_percent or max_ms >= high_max_ms:
        return "sev-high"
    if percent_total >= medium_percent or max_ms >= medium_max_ms:
        return "sev-medium"
    if percent_total >= low_percent or max_ms >= low_max_ms:
        return "sev-low"
    return "sev-none"


def format_aggregated_html(
    aggregated: Dict[str, object],
    *,
    top_n: int = 20,
    commit_top_n: int = 10,
    query_preview_chars: int = 200,
    query_severity_high_percent: float = 15.0,
    query_severity_medium_percent: float = 5.0,
    query_severity_low_percent: float = 1.0,
    query_severity_high_max_ms: float = 50.0,
    query_severity_medium_max_ms: float = 20.0,
    query_severity_low_max_ms: float = 5.0,
    commit_severity_high_percent: float = 20.0,
    commit_severity_medium_percent: float = 8.0,
    commit_severity_low_percent: float = 2.0,
    commit_severity_high_max_ms: float = 100.0,
    commit_severity_medium_max_ms: float = 40.0,
    commit_severity_low_max_ms: float = 10.0,
) -> str:
    queries = aggregated.get("queries", {})
    commits = aggregated.get("commits", {})
    query_stats = list(queries.get("stats", []) or [])[:top_n]
    commit_stats = list(commits.get("stats", []) or [])[:commit_top_n]
    total_query_ms = float(queries.get("total_time_ms", 0.0) or 0.0)
    total_commit_ms = float(commits.get("total_time_ms", 0.0) or 0.0)

    def fmt_number(value):
        return f"{value:.2f}"

    def esc(value):
        return html.escape(value or "")

    rows = []
    for stat in query_stats:
        count = int(stat.get("count", 0) or 0)
        total_ms = float(stat.get("total_ms", 0.0) or 0.0)
        mean_ms = total_ms / count if count else 0.0
        max_ms = float(stat.get("max_ms", 0.0) or 0.0)
        percent = (total_ms / total_query_ms * 100.0) if total_query_ms else 0.0
        statement = stat.get("statement", "")
        preview = _truncate_query(statement, query_preview_chars)
        stack_lines = stat.get("stack") or []
        callsite_counts = stat.get("callsite_counts") or {}
        stack_html = ""
        if stack_lines:
            stack_html = (
                "<div class='stack'><pre>"
                + esc("\n".join(stack_lines))
                + "</pre></div>"
            )
        callsite_html = ""
        if callsite_counts:
            callsite_html = (
                "<div class='callsites'>"
                "<strong>Callsites</strong><ul>"
                + "".join(
                    f"<li>{esc(site)} ({count})</li>"
                    for site, count in _top_callsite_counts(callsite_counts)
                )
                + "</ul></div>"
            )
        severity_class = _severity_class(
            percent,
            max_ms,
            high_percent=query_severity_high_percent,
            medium_percent=query_severity_medium_percent,
            low_percent=query_severity_low_percent,
            high_max_ms=query_severity_high_max_ms,
            medium_max_ms=query_severity_medium_max_ms,
            low_max_ms=query_severity_low_max_ms,
        )
        rows.append(
            f"<tr class='{severity_class}'>"
            f"<td class='num'>{count:d}</td>"
            f"<td class='num'>{fmt_number(total_ms)}</td>"
            f"<td class='num'>{fmt_number(mean_ms)}</td>"
            f"<td class='num'>{fmt_number(max_ms)}</td>"
            f"<td class='num'>{fmt_number(percent)}</td>"
            "<td class='query'>"
            "<details>"
            f"<summary>{esc(preview)}</summary>"
            f"<pre>{esc(statement)}</pre>"
            f"{callsite_html}"
            f"{stack_html}"
            "</details>"
            "</td>"
            "</tr>"
        )

    commit_rows = []
    for stat in commit_stats:
        count = int(stat.get("count", 0) or 0)
        total_ms = float(stat.get("total_ms", 0.0) or 0.0)
        mean_ms = total_ms / count if count else 0.0
        max_ms = float(stat.get("max_ms", 0.0) or 0.0)
        percent = (total_ms / total_commit_ms * 100.0) if total_commit_ms else 0.0
        callsite = stat.get("callsite", "unknown")
        types = _format_commit_type_counts(stat.get("commit_type_counts") or {})
        severity_class = _severity_class(
            percent,
            max_ms,
            high_percent=commit_severity_high_percent,
            medium_percent=commit_severity_medium_percent,
            low_percent=commit_severity_low_percent,
            high_max_ms=commit_severity_high_max_ms,
            medium_max_ms=commit_severity_medium_max_ms,
            low_max_ms=commit_severity_low_max_ms,
        )
        commit_rows.append(
            f"<tr class='{severity_class}'>"
            f"<td class='num'>{count:d}</td>"
            f"<td class='num'>{fmt_number(total_ms)}</td>"
            f"<td class='num'>{fmt_number(mean_ms)}</td>"
            f"<td class='num'>{fmt_number(max_ms)}</td>"
            f"<td class='callsite'>{esc(callsite)}</td>"
            f"<td class='types'>{esc(types)}</td>"
            "</tr>"
        )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>SQLAlchemy profiling report</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; vertical-align: top; }}
    th {{ background: #f5f5f5; text-align: left; }}
    td.num {{ text-align: right; white-space: nowrap; }}
    td.query summary {{ cursor: pointer; }}
    td.query pre {{ white-space: pre-wrap; margin: 8px 0 0 0; }}
    .callsites {{ margin-top: 8px; }}
    .stack pre {{ background: #fafafa; padding: 8px; }}
    tr.sev-high td {{ background: #f8d7da; }}
    tr.sev-medium td {{ background: #fff3cd; }}
    tr.sev-low td {{ background: #d1e7dd; }}
    .section {{ margin-top: 28px; }}
  </style>
</head>
<body>
  <h1>SQLAlchemy profiling report</h1>
  <p>Total queries: {queries.get("total_count", 0)}; total time: {fmt_number(total_query_ms)} ms</p>
  <div class="section">
    <h2>Queries</h2>
    <table>
      <thead>
        <tr>
          <th>Count</th>
          <th>Total ms</th>
          <th>Mean ms</th>
          <th>Max ms</th>
          <th>% total</th>
          <th>Query</th>
        </tr>
      </thead>
      <tbody>
        {"".join(rows) if rows else '<tr><td colspan="6">No queries captured.</td></tr>'}
      </tbody>
    </table>
  </div>
  <div class="section">
    <h2>Commits</h2>
    <p>Total commits: {commits.get("total_count", 0)}; total time: {fmt_number(float(commits.get("total_time_ms", 0.0) or 0.0))} ms</p>
    <table>
      <thead>
        <tr>
          <th>Count</th>
          <th>Total ms</th>
          <th>Mean ms</th>
          <th>Max ms</th>
          <th>Callsite</th>
          <th>Types</th>
        </tr>
      </thead>
      <tbody>
        {"".join(commit_rows) if commit_rows else '<tr><td colspan="6">No commits captured.</td></tr>'}
      </tbody>
    </table>
  </div>
</body>
</html>
"""


def _truncate_query(statement: str, max_chars: int) -> str:
    if max_chars <= 0:
        return "..."
    if len(statement) <= max_chars:
        return statement
    return statement[: max_chars - 3] + "..."


def _top_callsite_counts(callsite_counts: Dict[str, int], limit: int = 5):
    return sorted(callsite_counts.items(), key=lambda item: item[1], reverse=True)[
        :limit
    ]


def _commit_snapshot(session: SASession) -> Tuple[int, int, int]:
    return (len(session.new), len(session.dirty), len(session.deleted))


def _classify_commit(snapshot: Optional[Tuple[int, int, int]]) -> str:
    if snapshot is None:
        return "unknown"
    new_count, dirty_count, deleted_count = snapshot
    has_new = new_count > 0
    has_dirty = dirty_count > 0
    has_deleted = deleted_count > 0
    if not (has_new or has_dirty or has_deleted):
        return "no-op"
    parts = []
    if has_new:
        parts.append("insert")
    if has_dirty:
        parts.append("update")
    if has_deleted:
        parts.append("delete")
    return "+".join(parts)


def _execution_callsite() -> str:
    filtered = _filtered_stack_frames()
    if not filtered:
        return "unknown"
    fallback = filtered[-1]
    for frame in reversed(filtered):
        filename = frame.filename.replace("\\", "/")
        if filename.startswith("<"):
            continue
        if not os.path.isabs(filename) or not os.path.exists(filename):
            continue
        return f"{frame.filename}:{frame.lineno} in {frame.name}"
    return f"{fallback.filename}:{fallback.lineno} in {fallback.name}"


def _filtered_stack_frames():
    filtered = []
    for frame in traceback.extract_stack():
        filename = frame.filename.replace("\\", "/")
        if "/sqlalchemy/" in filename or filename == _MODULE_PATH:
            continue
        filtered.append(frame)
    return filtered
