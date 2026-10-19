import time

import pytest
from sqlalchemy import Column, Integer, String, create_engine, event, text
from sqlalchemy.orm import declarative_base, sessionmaker

from psynet.sqlalchemy_profiling import (
    _parse_bool,
    aggregate_sqlalchemy_profiles,
    assert_query_count,
    assert_query_duration,
    format_aggregated_html,
    format_aggregated_profile,
    parse_env_settings,
    sqlalchemy_profile,
)

Base = declarative_base()


class Widget(Base):
    __tablename__ = "widget"

    id = Column(Integer, primary_key=True)
    name = Column(String)


def make_session_factory(engine):
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def commit_in_helper(session):
    session.commit()


@pytest.fixture
def sqlite_engine():
    engine = create_engine("sqlite:///:memory:")
    try:
        yield engine
    finally:
        engine.dispose()


def test_sqlalchemy_profile_counts_queries(sqlite_engine):
    engine = sqlite_engine
    with sqlalchemy_profile(engine) as profiler:
        with engine.begin() as conn:
            conn.execute(text("SELECT 1"))
            conn.execute(text("SELECT 1"))
            conn.execute(text("SELECT 2"))

    assert profiler.total_count == 3
    stats = {stat.statement: stat for stat in profiler.get_stats()}
    assert stats["SELECT 1"].count == 2
    assert stats["SELECT 2"].count == 1
    assert profiler.total_time_ms >= 0.0


def test_env_profiler_honours_stack_depth(sqlite_engine, monkeypatch):
    import psynet.sqlalchemy_profiling as profiling

    monkeypatch.setenv("PSYNET_SQL_PROFILE", "stack=1,stack_depth=40")
    monkeypatch.setenv("PSYNET_SQL_PROFILE_SILENT", "1")
    monkeypatch.delenv("PSYNET_SQL_PROFILE_DIR", raising=False)
    monkeypatch.setattr(profiling, "_AUTO_PROFILER", None)
    profiler = profiling.maybe_enable_sqlalchemy_profiling(sqlite_engine)
    try:
        with sqlite_engine.begin() as conn:
            conn.execute(text("SELECT 1"))
    finally:
        profiler.stop()

    [stat] = profiler.get_stats()
    assert len(stat.stack) > 6


def test_sqlalchemy_profile_filters_by_min_duration(sqlite_engine):
    engine = sqlite_engine
    with sqlalchemy_profile(engine, min_duration_ms=1e9) as profiler:
        with engine.begin() as conn:
            conn.execute(text("SELECT 1"))

    assert profiler.total_count == 0
    assert profiler.get_stats() == []
    assert "No queries captured." in profiler.format_summary()


def test_sqlalchemy_profile_normalizes_statements(sqlite_engine):
    engine = sqlite_engine
    with sqlalchemy_profile(engine, normalize_sql=True) as profiler:
        with engine.begin() as conn:
            conn.execute(text("SELECT  1"))
            conn.execute(text("SELECT\t1"))

    stats = profiler.get_stats()
    assert len(stats) == 1
    assert stats[0].statement == "SELECT 1"
    assert stats[0].count == 2


def test_sqlalchemy_profile_truncates_statements(sqlite_engine):
    engine = sqlite_engine
    long_number = "1" * 50
    statement = f"SELECT {long_number}"
    max_chars = 20
    with sqlalchemy_profile(engine, max_statement_chars=max_chars) as profiler:
        with engine.begin() as conn:
            conn.execute(text(statement))

    stats = profiler.get_stats()
    assert len(stats) == 1
    assert stats[0].statement.endswith("...")
    assert len(stats[0].statement) == max_chars


def test_sqlalchemy_profile_captures_stack(sqlite_engine):
    engine = sqlite_engine
    with sqlalchemy_profile(engine, capture_stack=True, stack_depth=2) as profiler:
        with engine.begin() as conn:
            conn.execute(text("SELECT 1"))

    stats = profiler.get_stats()
    assert len(stats) == 1
    assert stats[0].stack is not None
    assert 1 <= len(stats[0].stack) <= 2
    assert all("/sqlalchemy/" not in frame for frame in stats[0].stack)
    assert all(
        "/psynet/sqlalchemy_profiling.py" not in frame for frame in stats[0].stack
    )


def test_sqlalchemy_profile_reset_clears_stats(sqlite_engine):
    engine = sqlite_engine
    with sqlalchemy_profile(engine) as profiler:
        with engine.begin() as conn:
            conn.execute(text("SELECT 1"))
            conn.execute(text("SELECT 1"))

    profiler.reset()
    assert profiler.total_count == 0
    assert profiler.get_stats() == []


def test_get_stats_sorted_by_count(sqlite_engine):
    engine = sqlite_engine
    with sqlalchemy_profile(engine) as profiler:
        with engine.begin() as conn:
            conn.execute(text("SELECT 1"))
            conn.execute(text("SELECT 1"))
            conn.execute(text("SELECT 2"))

    stats = profiler.get_stats(sort_by="count")
    assert stats[0].statement == "SELECT 1"
    assert stats[0].count >= stats[1].count


def test_commit_profile_classifies_types(sqlite_engine):
    engine = sqlite_engine
    SessionLocal = make_session_factory(engine)
    with sqlalchemy_profile(engine) as profiler:
        session = SessionLocal()
        widget = Widget(name="alpha")
        session.add(widget)
        commit_in_helper(session)

        widget.name = "beta"
        commit_in_helper(session)

        other = Widget(name="gamma")
        session.add(other)
        widget.name = "delta"
        commit_in_helper(session)

        session.delete(other)
        commit_in_helper(session)

        session.execute(text("SELECT 1"))
        commit_in_helper(session)
        session.close()

    stats = profiler.get_commit_stats()
    assert len(stats) == 1
    assert "commit_in_helper" in stats[0].callsite
    commit_types = stats[0].commit_type_counts
    assert commit_types["insert"] >= 1
    assert commit_types["update"] >= 1
    assert commit_types["insert+update"] >= 1
    assert commit_types["delete"] >= 1
    assert commit_types["no-op"] >= 1
    assert profiler.commit_total_count >= 5
    assert profiler.commit_total_time_ms >= 0.0


def test_profile_json_aggregation(sqlite_engine, tmp_path):
    engine = sqlite_engine
    with sqlalchemy_profile(engine) as profiler:
        with engine.begin() as conn:
            conn.execute(text("SELECT 1"))
    profiler.write_json_summary(str(tmp_path))

    with sqlalchemy_profile(engine) as profiler:
        with engine.begin() as conn:
            conn.execute(text("SELECT 1"))
            conn.execute(text("SELECT 2"))
    profiler.write_json_summary(str(tmp_path))

    aggregated = aggregate_sqlalchemy_profiles(str(tmp_path))
    formatted = format_aggregated_profile(aggregated, top_n=10, commit_top_n=10)
    html_report = format_aggregated_html(
        aggregated, top_n=10, commit_top_n=10, query_preview_chars=4
    )
    assert aggregated["profiles"] == 2
    assert aggregated["queries"]["total_count"] == 3
    assert "Aggregated SQLAlchemy query profile" in formatted
    assert "<table" in html_report
    assert "SELECT 1" in html_report
    assert "..." in html_report
    stats = {
        (stat["statement"], tuple(stat["stack"]) if stat["stack"] else None): stat
        for stat in aggregated["queries"]["stats"]
    }
    assert stats[("SELECT 1", None)]["callsite_counts"]
    assert stats[("SELECT 1", None)]["count"] == 2
    assert stats[("SELECT 2", None)]["count"] == 1


def test_format_aggregated_html_adds_severity_classes():
    aggregated = {
        "queries": {
            "total_count": 3,
            "total_time_ms": 100.0,
            "stats": [
                {
                    "statement": "SELECT 1",
                    "count": 1,
                    "total_ms": 70.0,
                    "max_ms": 3.0,
                    "stack": None,
                    "callsite_counts": {},
                },
                {
                    "statement": "SELECT 2",
                    "count": 1,
                    "total_ms": 20.0,
                    "max_ms": 2.0,
                    "stack": None,
                    "callsite_counts": {},
                },
                {
                    "statement": "SELECT 3",
                    "count": 1,
                    "total_ms": 10.0,
                    "max_ms": 1.0,
                    "stack": None,
                    "callsite_counts": {},
                },
            ],
        },
        "commits": {
            "total_count": 3,
            "total_time_ms": 100.0,
            "stats": [
                {
                    "callsite": "high",
                    "count": 1,
                    "total_ms": 70.0,
                    "max_ms": 4.0,
                    "commit_type_counts": {"insert": 1},
                },
                {
                    "callsite": "medium",
                    "count": 1,
                    "total_ms": 20.0,
                    "max_ms": 3.0,
                    "commit_type_counts": {"update": 1},
                },
                {
                    "callsite": "low",
                    "count": 1,
                    "total_ms": 10.0,
                    "max_ms": 2.0,
                    "commit_type_counts": {"no-op": 1},
                },
            ],
        },
    }

    html_report = format_aggregated_html(
        aggregated,
        query_severity_high_percent=60.0,
        query_severity_medium_percent=15.0,
        query_severity_low_percent=5.0,
        query_severity_high_max_ms=1e9,
        query_severity_medium_max_ms=1e9,
        query_severity_low_max_ms=1e9,
        commit_severity_high_percent=60.0,
        commit_severity_medium_percent=15.0,
        commit_severity_low_percent=5.0,
        commit_severity_high_max_ms=1e9,
        commit_severity_medium_max_ms=1e9,
        commit_severity_low_max_ms=1e9,
    )

    assert html_report.count("class='sev-high'") == 2
    assert html_report.count("class='sev-medium'") == 2
    assert html_report.count("class='sev-low'") == 2
    assert "tr.sev-high td" in html_report
    assert "tr.sev-medium td" in html_report
    assert "tr.sev-low td" in html_report


def test_assert_query_count_raises_when_exceeded(sqlite_engine):
    engine = sqlite_engine
    with pytest.raises(AssertionError, match="Expected between 0 and 1 queries"):
        with assert_query_count(max_queries=1, engine=engine):
            with engine.begin() as conn:
                conn.execute(text("SELECT 1"))
                conn.execute(text("SELECT 1"))


def test_assert_query_count_raises_when_below_minimum(sqlite_engine):
    engine = sqlite_engine
    with pytest.raises(AssertionError, match="Expected between 1 and 2 queries"):
        with assert_query_count(max_queries=2, min_queries=1, engine=engine):
            pass


def test_assert_query_duration_passes_with_high_limit(sqlite_engine):
    engine = sqlite_engine
    with assert_query_duration(max_total_duration_ms=1e6, engine=engine):
        with engine.begin() as conn:
            conn.execute(text("SELECT 1"))


def test_assert_query_duration_raises_when_below_minimum(sqlite_engine):
    engine = sqlite_engine
    with pytest.raises(
        AssertionError,
        match="Expected total query time >= 1.0 ms",
    ):
        with assert_query_duration(
            max_total_duration_ms=2.0, min_total_duration_ms=1.0, engine=engine
        ):
            pass


def test_assert_query_duration_raises_when_over_max_query(sqlite_engine):
    engine = sqlite_engine

    def slow(*args, **kwargs):
        time.sleep(0.01)

    event.listen(engine, "after_cursor_execute", slow)
    try:
        with pytest.raises(
            AssertionError,
            match="Expected max query time <= 1.0 ms",
        ):
            with assert_query_duration(
                max_total_duration_ms=1e6, max_query_duration_ms=1.0, engine=engine
            ):
                with engine.begin() as conn:
                    conn.execute(text("SELECT 1"))
    finally:
        event.remove(engine, "after_cursor_execute", slow)


def test_parse_env_settings_and_bool():
    assert parse_env_settings(None) == {"enabled": False, "options": {}}
    assert parse_env_settings("") == {"enabled": False, "options": {}}
    assert parse_env_settings("0") == {"enabled": False, "options": {}}

    settings = parse_env_settings("min_ms=50,top_n=5,stack=1")
    assert settings["enabled"] is True
    assert settings["options"] == {"min_ms": "50", "top_n": "5", "stack": "1"}

    assert _parse_bool("0") is False
    assert _parse_bool("false") is False
    assert _parse_bool("off") is False
    assert _parse_bool("1") is True
    assert _parse_bool("true") is True
