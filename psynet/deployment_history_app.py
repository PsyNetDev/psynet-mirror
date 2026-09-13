"""Textual browser for ``data/deployment-events.jsonl``.

Uses Textual instead of a hand-rolled Rich Live + raw-TTY loop so arrow keys,
layout, and key legends behave reliably across terminals.
"""

from __future__ import annotations

from typing import Iterable, Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static

from psynet.deployment_events import (
    _detail,
    _subject,
    filter_deployment_events,
)


def _event_label(event: dict) -> str:
    when = str(event.get("at", ""))
    name = str(event.get("event", ""))
    subject = _subject(event)
    if subject:
        return f"{when}  {name}  {subject}"
    return f"{when}  {name}"


def _event_detail_text(event: dict) -> str:
    lines = []
    detail = _detail(event).plain
    if detail:
        lines.append(detail)
    argv = event.get("argv")
    if argv:
        lines.append("Command: " + " ".join(str(part) for part in argv))
    error = event.get("error")
    if error:
        lines.append(f"Error: {error}")
    author = event.get("author")
    if author and event.get("event") == "comment":
        lines.append(f"Author: {author}")
    for key in ("deployment_id", "path", "reason", "snapshot", "sequence"):
        value = event.get(key)
        if value is not None and value != "":
            lines.append(f"{key}: {value}")
    return "\n".join(lines) if lines else "(no details)"


class EventListItem(ListItem):
    """One selectable row in the event list."""

    def __init__(self, event: dict) -> None:
        super().__init__()
        self.event = event

    def compose(self) -> ComposeResult:
        name = str(self.event.get("event", ""))
        classes = ""
        if name == "comment" or self.event.get("comment"):
            classes = "comment"
        elif name.endswith(".failed"):
            classes = "failed"
        elif name.endswith(".succeeded") or name.endswith(".stopped"):
            classes = "ok"
        yield Label(_event_label(self.event), classes=classes)


class DeploymentHistoryApp(App[None]):
    """Interactive deployment-history browser."""

    TITLE = "PsyNet deployment history"
    CSS = """
    Screen {
        layout: vertical;
    }
    #filters {
        height: 3;
        padding: 0 1;
        background: $surface;
        color: $text;
    }
    #filters Label {
        width: 1fr;
    }
    #body {
        height: 1fr;
    }
    #events {
        width: 3fr;
        border: solid $accent;
    }
    #detail-pane {
        width: 2fr;
        border: solid $secondary;
        padding: 0 1;
    }
    #detail-title {
        text-style: bold;
        padding: 1 0 0 0;
    }
    ListItem {
        padding: 0 1;
        height: 1;
    }
    ListItem.-highlight {
        background: $accent;
    }
    .comment {
        color: magenta;
        text-style: bold;
    }
    .failed {
        color: red;
        text-style: bold;
    }
    .ok {
        color: green;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("question_mark", "help", "Help", key_display="?"),
        Binding("a", "type_all", "All", show=True),
        Binding("f", "type_failures", "Failures", show=True),
        Binding("c", "type_comments", "Comments", show=True),
        Binding("s", "type_succeeded", "Succeeded", show=True),
        Binding("0", "command_all", "All cmds", show=True),
        Binding("1", "command_deploy", "Deploy", show=True),
        Binding("2", "command_sandbox", "Sandbox", show=True),
        Binding("3", "command_export", "Export", show=True),
        Binding("4", "command_destroy", "Destroy", show=True),
        Binding("5", "command_snapshot", "Snapshot", show=True),
        Binding("6", "command_comment", "Comment cmds", show=True),
        Binding("up", "cursor_up", "Up", show=False),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("g", "cursor_top", "Top", show=False),
        Binding("G", "cursor_bottom", "Bottom", show=False),
    ]

    def __init__(self, events: Iterable[dict]) -> None:
        super().__init__()
        self._all_events = list(events)
        self.type_filter = "all"
        self.command_filter = "all"
        self._help_visible = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="filters"):
            yield Label(id="filter-status")
        with Horizontal(id="body"):
            yield ListView(id="events")
            with Vertical(id="detail-pane"):
                yield Label("Detail", id="detail-title")
                yield VerticalScroll(Static(id="detail"))
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_list(select_last=True)
        self._update_filter_status()

    def _visible_events(self) -> list[dict]:
        return filter_deployment_events(
            self._all_events,
            type_filter=self.type_filter,
            command_filter=self.command_filter,
        )

    def _update_filter_status(self) -> None:
        visible = len(self._visible_events())
        total = len(self._all_events)
        help_hint = "  |  ? help" if not self._help_visible else ""
        self.query_one("#filter-status", Label).update(
            f"Type: {self.type_filter}   Command: {self.command_filter}   "
            f"Showing {visible}/{total}{help_hint}"
        )

    def _refresh_list(self, *, select_last: bool = False) -> None:
        events_view = self.query_one("#events", ListView)
        events_view.clear()
        rows = self._visible_events()
        if not rows:
            events_view.append(ListItem(Label("(no matching events)")))
            self.query_one("#detail", Static).update(
                "No events match the current filters.\n"
                "Press a / f / c / s for type, or 0–6 for command family."
            )
            return
        for event in rows:
            events_view.append(EventListItem(event))
        index = len(rows) - 1 if select_last else min(
            events_view.index or 0, len(rows) - 1
        )
        events_view.index = index
        self._show_event(rows[index])

    def _show_event(self, event: dict) -> None:
        self.query_one("#detail", Static).update(_event_detail_text(event))

    def _selected_event(self) -> Optional[dict]:
        events_view = self.query_one("#events", ListView)
        highlighted = events_view.highlighted_child
        if isinstance(highlighted, EventListItem):
            return highlighted.event
        return None

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        item = event.item
        if isinstance(item, EventListItem):
            self._show_event(item.event)

    def action_type_all(self) -> None:
        self.type_filter = "all"
        self._apply_filters()

    def action_type_failures(self) -> None:
        self.type_filter = "failures"
        self._apply_filters()

    def action_type_comments(self) -> None:
        self.type_filter = "comments"
        self._apply_filters()

    def action_type_succeeded(self) -> None:
        self.type_filter = "succeeded"
        self._apply_filters()

    def action_command_all(self) -> None:
        self.command_filter = "all"
        self._apply_filters()

    def action_command_deploy(self) -> None:
        self.command_filter = "deploy"
        self._apply_filters()

    def action_command_sandbox(self) -> None:
        self.command_filter = "sandbox"
        self._apply_filters()

    def action_command_export(self) -> None:
        self.command_filter = "export"
        self._apply_filters()

    def action_command_destroy(self) -> None:
        self.command_filter = "destroy"
        self._apply_filters()

    def action_command_snapshot(self) -> None:
        self.command_filter = "snapshot"
        self._apply_filters()

    def action_command_comment(self) -> None:
        self.command_filter = "comment"
        self._apply_filters()

    def _apply_filters(self) -> None:
        self._help_visible = False
        self._update_filter_status()
        self._refresh_list(select_last=True)

    def action_help(self) -> None:
        self._help_visible = not self._help_visible
        detail = self.query_one("#detail", Static)
        if self._help_visible:
            detail.update(
                "Keys\n"
                "----\n"
                "↑/↓ or j/k  move selection\n"
                "a           show all event types\n"
                "f           failures only\n"
                "c           comments / events with --comment\n"
                "s           succeeded / stopped only\n"
                "0           all command families\n"
                "1 deploy  2 sandbox  3 export  4 destroy  5 snapshot  6 comment\n"
                "q           quit\n"
                "\n"
                "Filters combine: type AND command."
            )
        else:
            event = self._selected_event()
            if event is not None:
                self._show_event(event)
            self._update_filter_status()

    def action_cursor_up(self) -> None:
        self.query_one("#events", ListView).action_cursor_up()

    def action_cursor_down(self) -> None:
        self.query_one("#events", ListView).action_cursor_down()

    def action_cursor_top(self) -> None:
        events_view = self.query_one("#events", ListView)
        if len(events_view):
            events_view.index = 0

    def action_cursor_bottom(self) -> None:
        events_view = self.query_one("#events", ListView)
        if len(events_view):
            events_view.index = len(events_view) - 1


def run_deployment_history_app(events: Iterable[dict]) -> None:
    """Run the Textual deployment-history browser."""
    DeploymentHistoryApp(events).run()
