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


def _cycle(values: tuple[str, ...], current: str, *, step: int = 1) -> str:
    index = values.index(current) if current in values else 0
    return values[(index + step) % len(values)]


def _read_key(stdin) -> str:
    """Read one keypress, including common escape sequences."""
    import select
    import termios
    import tty

    fd = stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        first = stdin.read(1)
        if first != "\x1b":
            return first
        # Arrow keys send Esc [ A/B/...; bare Esc should not block forever.
        ready, _, _ = select.select([stdin], [], [], 0.05)
        if not ready:
            return "\x1b"
        second = stdin.read(1)
        ready, _, _ = select.select([stdin], [], [], 0.05)
        third = stdin.read(1) if ready else ""
        return first + second + third
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _history_layout(
    events: list[dict],
    *,
    selected: int,
    type_filter: str,
    command_filter: str,
    show_help: bool,
):
    from rich.panel import Panel
    from rich.table import Table

    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column("marker", width=2)
    table.add_column("when", style="dim", no_wrap=True)
    table.add_column("event", no_wrap=True)
    table.add_column("subject", overflow="ellipsis")

    window = 18
    if not events:
        table.add_row("", "", Text("(no matching events)", style="dim"), "")
    else:
        start = max(0, selected - window // 2)
        end = min(len(events), start + window)
        start = max(0, end - window)
        for index in range(start, end):
            event = events[index]
            marker = Text("❯", style="bold cyan") if index == selected else Text(" ")
            name = str(event.get("event", ""))
            style = _event_style(event)
            if index == selected:
                style = f"reverse {style}".strip() if style else "reverse"
            table.add_row(
                marker,
                str(event.get("at", "")),
                Text(name, style=style),
                _subject(event),
            )

    detail_lines = Text()
    if events:
        event = events[selected]
        detail_lines.append(_detail(event))
        detail_lines.append("\n")
        argv = event.get("argv")
        if argv:
            detail_lines.append("argv: ", style="dim")
            detail_lines.append(" ".join(str(part) for part in argv))
            detail_lines.append("\n")
        error = event.get("error")
        if error:
            detail_lines.append("error: ", style="bold red")
            detail_lines.append(str(error), style="red")

    status = (
        f"type={type_filter}  command={command_filter}  "
        f"{(selected + 1) if events else 0}/{len(events)}   "
        "↑↓ move  t type  c command  ? help  q quit"
    )
    body = Table.grid(expand=True)
    body.add_row(Panel(table, title="Events", border_style="cyan"))
    body.add_row(Panel(detail_lines or Text(" "), title="Detail", border_style="magenta"))
    if show_help:
        help_text = Text(
            "↑/k  previous   ↓/j  next   g top   G bottom\n"
            "t    cycle type filter (all/failures/comments/succeeded)\n"
            "c    cycle command filter "
            "(all/deploy/sandbox/export/destroy/snapshot/comment)\n"
            "q/Esc quit"
        )
        body.add_row(Panel(help_text, title="Keys", border_style="green"))
    body.add_row(Text(status, style="dim"))
    return body


def browse_deployment_history(
    events: Iterable[dict],
    *,
    console: Optional[Console] = None,
) -> None:
    """Browse deployment events in a full-screen Rich Live TUI.

    Falls back to the static timeline when stdin/stdout are not interactive or
    when raw terminal mode is unavailable.
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
        import termios  # noqa: F401
        import tty  # noqa: F401
    except ImportError:
        render_deployment_history(all_events, console=console)
        return

    from rich.live import Live

    type_filter = "all"
    command_filter = "all"
    selected = max(0, len(all_events) - 1)
    show_help = False

    def visible():
        return filter_deployment_events(
            all_events, type_filter=type_filter, command_filter=command_filter
        )

    rows = visible()
    selected = min(selected, max(0, len(rows) - 1))

    with Live(
        _history_layout(
            rows,
            selected=selected,
            type_filter=type_filter,
            command_filter=command_filter,
            show_help=show_help,
        ),
        console=console,
        screen=True,
        redirect_stdout=False,
        redirect_stderr=False,
        transient=True,
    ) as live:
        while True:
            key = _read_key(stdin)
            if key in {"q", "Q", "\x03", "\x1b"}:  # q / Ctrl-C / Esc alone
                break
            if key == "?":
                show_help = not show_help
            elif key in {"\x1b[A", "k", "K"}:  # up
                selected = max(0, selected - 1)
            elif key in {"\x1b[B", "j", "J"}:  # down
                selected = min(max(0, len(rows) - 1), selected + 1)
            elif key == "g":
                selected = 0
            elif key == "G":
                selected = max(0, len(rows) - 1)
            elif key in {"t", "T"}:
                type_filter = _cycle(TYPE_FILTERS, type_filter)
                rows = visible()
                selected = min(selected, max(0, len(rows) - 1))
            elif key in {"c", "C"}:
                command_filter = _cycle(COMMAND_FILTERS, command_filter)
                rows = visible()
                selected = min(selected, max(0, len(rows) - 1))

            rows = visible()
            if not rows:
                selected = 0
            else:
                selected = min(selected, len(rows) - 1)
            live.update(
                _history_layout(
                    rows,
                    selected=selected,
                    type_filter=type_filter,
                    command_filter=command_filter,
                    show_help=show_help,
                )
            )
