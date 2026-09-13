"""Append-only deployment history for PsyNet experiments.

Commands that have real cost or lasting effect (live deploy, sandbox, export,
destroy) append structured JSON lines to ``data/deployment-events.jsonl``.
Operators can attach ``--comment`` to those commands, add free-floating notes
with ``psynet comment``, and browse the log with ``psynet history``.

The JSONL schema is the integration surface for a future Dallinger provisioning
hook: one object per line with ``schema_version``, ``at``, and ``event``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import click
from rich.console import Console
from rich.text import Text

logger = logging.getLogger("psynet")

_fallback_file_lock = threading.RLock()

# Same rule as local deployment IDs; kept here to avoid an import cycle with
# ``psynet.local_deployment``.
_LOCAL_ID_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")

DEFAULT_HISTORY_LIMIT = 50
_ERROR_DISPLAY_MAX = 120


def deployment_event_log(experiment_path: Path | str) -> Path:
    """Return the experiment's append-only deployment event log."""
    return Path(experiment_path).resolve() / "data" / "deployment-events.jsonl"


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def _validate_event_local_id(value: str) -> str:
    """Validate a local deployment ID stored on an event."""
    if not _LOCAL_ID_PATTERN.fullmatch(value):
        raise ValueError(
            "Local deployment IDs must contain only lowercase letters, digits, "
            "and dashes, and must start and end with a letter or digit."
        )
    return value


@contextmanager
def _file_lock(path: Path, *, blocking: bool = True):
    """Lock ``path`` for the duration of the context."""
    path.parent.mkdir(parents=True, exist_ok=True)
    file = path.open("a+")
    using_fallback = False
    try:
        try:
            import fcntl

            flags = fcntl.LOCK_EX
            if not blocking:
                flags |= fcntl.LOCK_NB
            fcntl.flock(file.fileno(), flags)
        except ImportError:
            _fallback_file_lock.acquire()
            using_fallback = True
        yield file
    finally:
        if using_fallback:
            _fallback_file_lock.release()
        else:
            import fcntl

            fcntl.flock(file.fileno(), fcntl.LOCK_UN)
        file.close()


def append_deployment_event(
    experiment_path: Path | str,
    event: str,
    local_id: Optional[str] = None,
    **details,
) -> dict:
    """Append one structured event to the experiment's deployment history."""
    if local_id is not None:
        _validate_event_local_id(local_id)
    payload = {
        "schema_version": 1,
        "at": _utc_now(),
        "event": event,
    }
    if local_id is not None:
        payload["id"] = local_id
    payload.update({key: value for key, value in details.items() if value is not None})

    path = deployment_event_log(experiment_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode()
    with _file_lock(path.parent / ".deployment-events.lock"):
        descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            remaining = memoryview(line)
            while remaining:
                written = os.write(descriptor, remaining)
                if written == 0:
                    raise OSError("Failed to append deployment event.")
                remaining = remaining[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    return payload


def command_argv() -> list[str]:
    """Return the current process argv for deployment-event context."""
    return list(sys.argv)


def normalize_comment(comment: Optional[str]) -> Optional[str]:
    """Return stripped comment text, or ``None`` when empty/absent."""
    if comment is None:
        return None
    text = comment.strip()
    return text or None


def option_comment(func):
    """Attach a shared ``--comment`` option for deployment-related commands."""
    return click.option(
        "--comment",
        default=None,
        help="Operator comment recorded in data/deployment-events.jsonl.",
    )(func)


def event_details(
    *, comment: Optional[str] = None, argv: Optional[list] = None, **extra
):
    """Build common deployment-event fields for a CLI action."""
    details = dict(extra)
    details["argv"] = list(argv) if argv is not None else command_argv()
    normalized = normalize_comment(comment)
    if normalized is not None:
        details["comment"] = normalized
    return details


def load_deployment_events(
    experiment_path: Path | str,
    *,
    limit: Optional[int] = None,
) -> list[dict]:
    """Load deployment events oldest-first, optionally truncated to the latest ``limit``."""
    path = deployment_event_log(experiment_path)
    if not path.is_file():
        return []

    events: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                logger.warning(
                    "Skipping malformed deployment event at %s:%s", path, line_number
                )
                continue
            if not isinstance(payload, dict):
                logger.warning(
                    "Skipping non-object deployment event at %s:%s", path, line_number
                )
                continue
            events.append(payload)

    if limit is not None and limit >= 0:
        events = events[-limit:]
    return events


def _subject(event: dict) -> str:
    parts = []
    for key in ("id", "app", "server", "target", "mode"):
        value = event.get(key)
        if value:
            parts.append(f"{key}={value}")
    return " ".join(parts)


def _detail(event: dict) -> Text:
    name = str(event.get("event", ""))
    if name == "comment":
        text = Text()
        text.append("✎ ", style="bold magenta")
        text.append(str(event.get("text", "")), style="bold magenta")
        author = event.get("author")
        if author:
            text.append(f"  ({author})", style="dim magenta")
        return text

    pieces: list[str] = []
    comment = event.get("comment")
    if comment:
        pieces.append(f'"{comment}"')
    error = event.get("error")
    if error:
        error_text = str(error)
        if len(error_text) > _ERROR_DISPLAY_MAX:
            error_text = error_text[: _ERROR_DISPLAY_MAX - 1] + "…"
        pieces.append(f"error={error_text}")
    for key in ("snapshot", "sequence", "path", "deployment_id", "reason"):
        value = event.get(key)
        if value is not None and value != "":
            pieces.append(f"{key}={value}")
    detail = "; ".join(pieces)
    if name.endswith(".failed") or error:
        return Text(detail, style="bold red")
    if comment:
        return Text(detail, style="magenta")
    return Text(detail)


def _event_style(event: dict) -> str:
    name = str(event.get("event", ""))
    if name == "comment":
        return "bold magenta"
    if name.endswith(".failed"):
        return "bold red"
    if name.endswith(".succeeded") or name.endswith(".stopped"):
        return "green"
    if name.endswith(".requested"):
        return "cyan"
    return ""


def render_deployment_history(
    events: Iterable[dict],
    *,
    console: Optional[Console] = None,
    title: str = "Deployment history",
) -> None:
    """Print a Rich timeline of deployment events."""
    console = console or Console()
    rows = list(events)
    if not rows:
        console.print(
            "No deployment events yet. "
            "Live deploy, sandbox, export, destroy, and comment commands "
            "append to data/deployment-events.jsonl."
        )
        return

    console.print(Text(title, style="bold italic"))
    for event in rows:
        name = str(event.get("event", ""))
        when = str(event.get("at", ""))
        subject = _subject(event)
        header = Text()
        header.append(when, style="dim")
        header.append("  ")
        header.append(name, style=_event_style(event))
        if subject:
            header.append("  ")
            header.append(subject, style="dim")
        console.print(header)
        detail = _detail(event)
        if detail.plain:
            indented = Text("  ")
            indented.append(detail)
            console.print(indented)


TYPE_FILTERS = ("all", "failures", "comments", "succeeded")
COMMAND_FILTERS = (
    "all",
    "deploy",
    "sandbox",
    "export",
    "destroy",
    "snapshot",
    "comment",
)


def event_command_family(event: dict) -> str:
    """Return the command family for filtering (deploy, export, comment, …)."""
    name = str(event.get("event", ""))
    if name == "comment":
        return "comment"
    if "." in name:
        return name.split(".", 1)[0]
    argv = event.get("argv") or []
    if len(argv) >= 2 and argv[0].endswith("psynet"):
        return str(argv[1])
    return name or "other"


def filter_deployment_events(
    events: Iterable[dict],
    *,
    type_filter: str = "all",
    command_filter: str = "all",
) -> list[dict]:
    """Filter deployment events by outcome type and command family."""
    rows = []
    for event in events:
        name = str(event.get("event", ""))
        if type_filter == "failures" and not name.endswith(".failed"):
            continue
        if type_filter == "comments" and name != "comment" and not event.get("comment"):
            continue
        if type_filter == "succeeded" and not (
            name.endswith(".succeeded") or name.endswith(".stopped")
        ):
            continue
        if command_filter != "all" and event_command_family(event) != command_filter:
            continue
        rows.append(event)
    return rows


def browse_deployment_history(
    events: Iterable[dict],
    *,
    console: Optional[Console] = None,
) -> None:
    """Browse deployment events in an interactive Textual TUI.

    Falls back to the static timeline when stdin/stdout are not interactive or
    Textual is unavailable.
    """
    console = console or Console()
    all_events = list(events)
    if not all_events:
        render_deployment_history(all_events, console=console)
        return

    stdin = getattr(sys, "stdin", None)
    interactive = False
    if stdin is not None and console.is_terminal:
        try:
            interactive = stdin.isatty()
        except (AttributeError, ValueError, OSError):
            interactive = False
    if not interactive:
        render_deployment_history(all_events, console=console)
        return

    try:
        from psynet.deployment_history_app import run_deployment_history_app
    except ImportError:
        console.print(
            "[yellow]Install the experiment extra (including textual) "
            "for interactive history; showing a static timeline instead.[/yellow]"
        )
        render_deployment_history(all_events, console=console)
        return

    run_deployment_history_app(all_events)
