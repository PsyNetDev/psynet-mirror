"""A prompt that shows the members of a small group, and later their answers.

Round-based games with a handful of players (up to about 12) share a common
display: everyone in the group as an icon, ticks for who has answered, and
then everyone's answer in a speech bubble. :class:`GroupPrompt` draws that
display above a page's controls.

Design constraints:

- Members are shown by pseudonym (:mod:`psynet.pseudonym`), never by
  participant ID. The page refers to members by seat
  (:func:`psynet.sync.group_seats`), which is also how
  :class:`~psynet.sync.GroupBarrier` reports live ticks.
- By default a member has answered once they are waiting at a barrier of
  the group, typically the barrier after the decision page. Live ticks come
  from that barrier's arrival updates, so they need ``notify_arrivals``
  (the default).
- The HTML is built on the server; ``static/scripts/group-prompt.js`` only
  updates ticks, so pages without JavaScript still show the group.
"""

import math
from itertools import combinations
from typing import Callable, Dict, Optional, Union

from markupsafe import Markup

from .modular_page import Prompt
from .static_resources import package_static_url
from .utils import get_translator

MAX_DRAWN_MEMBERS = 12
_MAX_ROW_MEMBERS = 4
_MAX_CIRCLE_MEMBERS = 6

# Sizes in em of a member's box in the circle, which group-prompt.css matches.
# The circle is drawn as an ellipse just large enough that no two boxes
# overlap; where it is wider than the page, members wrap in rows instead.
# Members at the sides of a table stack vertically, so tables of more than six
# need more height than a laptop window has to spare; they get rows.
_MEMBER_WIDTH = 9.0
_MEMBER_HEIGHT = 4.8
_BUBBLE_HEIGHT = 2.4
_MAX_CIRCLE_WIDTH = 44.0


class GroupPrompt(Prompt):
    """Shows the members of a group, who has answered, and their answers.

    Members appear as their pseudonym icons: in a row for up to four people,
    around a table (an ellipse) for five or six, in wrapped rows for up to
    12, and as a list for larger groups. Where the table does not fit the
    page, as on a phone, its members wrap in rows too. The participant
    viewing the page is labelled "You". On a phone, the answers of more
    than about nine members can push the controls below the window; pass
    ``expect_scrolling=True`` to such a page.

    Parameters
    ----------
    text
        Text shown above the group, as for :class:`~psynet.modular_page.Prompt`.
    group
        The :class:`~psynet.sync.SyncGroup` to show.
    participant
        The participant viewing the page.
    answers
        Optional ``{participant_id: answer}`` to show in speech bubbles, for
        example after the group's barrier has released. Answers are shown
        as text; pass :class:`~markupsafe.Markup` for HTML such as an image.
        Members without an entry get no bubble.
    highlight
        Optional ``{participant_id: style}``. ``"winner"`` and
        ``"duplicate"`` have built-in styles; any other style becomes the
        CSS class ``psynet-group-member--<style>``.
    note
        Optional short text shown in the middle of the group (below a row),
        for example "1 was picked twice".
    show_progress
        If ``True`` (default) and ``answers`` is not given, members who have
        answered get a tick, which appears live as they reach the next
        barrier.
    answered
        Optional ``answered(participant) -> bool`` deciding who has answered
        when the page is drawn. By default, a member has answered while they
        wait at a barrier of this group. Live ticks still come from barrier
        arrivals.
    text_align
        CSS alignment of the text.
    """

    macro = "group"

    def __init__(
        self,
        text=None,
        *,
        group,
        participant,
        answers: Optional[Dict[int, Union[str, Markup]]] = None,
        highlight: Optional[Dict[int, str]] = None,
        note: Optional[str] = None,
        show_progress: bool = True,
        answered: Optional[Callable] = None,
        text_align: str = "left",
    ):
        super().__init__(text=text, text_align=text_align)
        self.group = group
        self.participant = participant
        self.answers = (
            None if answers is None else {int(k): v for k, v in answers.items()}
        )
        self.highlight = {int(k): v for k, v in (highlight or {}).items()}
        self.note = note
        self.show_progress = show_progress and answers is None
        self.answered = answered or _waiting_in_group(group)

    @property
    def metadata(self):
        return {
            "group_id": self.group.id,
            "answers": None
            if self.answers is None
            else {str(k): str(v) for k, v in self.answers.items()},
        }

    def get_css(self):
        """Page-local CSS for the group display."""
        from importlib import resources

        css = [
            resources.files("psynet")
            .joinpath("resources/css/group-prompt.css")
            .read_text(encoding="utf-8")
        ]
        if self._layout() == "circle":
            width, _ = self._circle()[2:]
            # Where the circle does not fit, members wrap in rows as for a row.
            css.append(
                f"@container (max-width: {width:.1f}em) {{"
                f" .psynet-group-prompt--circle[data-circle-width='{width:.1f}']"
                " .psynet-group-members { position: static; display: flex;"
                " flex-wrap: wrap; justify-content: center; gap: 1em 0.5em;"
                " width: auto !important; height: auto !important; }"
                f" .psynet-group-prompt--circle[data-circle-width='{width:.1f}']"
                " .psynet-group-member { position: relative; left: auto; top: auto;"
                " transform: none; }"
                f" .psynet-group-prompt--circle[data-circle-width='{width:.1f}']"
                " .psynet-group-note { position: static; transform: none;"
                " max-width: none; margin-top: 0.8em; }"
                " }"
            )
        return css

    def get_js_vars(self):
        """Configuration for live ticks."""
        _p = get_translator(context=True)
        return {
            "group_prompt": {
                "group_id": self.group.id,
                "show_progress": self.show_progress,
                "answered_label": _p("group prompt", "has answered"),
            }
        }

    def get_js_page_modules(self):
        """The module that adds ticks as members answer."""
        return [package_static_url("psynet", "scripts/group-prompt.js")]

    @property
    def group_html(self) -> Markup:
        """HTML for the group display."""
        _p = get_translator(context=True)
        members = self._members()
        seats = _group_seats(self.group)
        layout = self._layout()
        positions = [""] * len(members)
        attributes = Markup("")
        if layout == "circle":
            rx, ry, width, height = self._circle()
            positions = [
                f"--dx: {dx:.2f}em; --dy: {dy:.2f}em;"
                for dx, dy in _ellipse_offsets(len(members), rx, ry)
            ]
            attributes = Markup(
                ' data-circle-width="{:.1f}" style="--width: {:.1f}em;'
                ' --height: {:.1f}em; --note-width: {:.1f}em;"'
            ).format(width, width, height, max(2 * rx - _MEMBER_WIDTH, 6))
        items = Markup("").join(
            self._member_html(member, seats[member.id], index, positions[index])
            for index, member in enumerate(members)
        )
        note = (
            Markup('<p class="psynet-group-note">{}</p>').format(self.note)
            if self.note
            else Markup("")
        )
        label = _p("group prompt", "Your group")
        classes = f"psynet-group-prompt psynet-group-prompt--{layout}"
        if self.answers is not None:
            classes += " psynet-group-prompt--answers"
        return Markup(
            '<div class="{}"{}>'
            '<ul class="psynet-group-members" aria-label="{}">{}</ul>{}</div>'
        ).format(classes, attributes, label, items, note)

    def _layout(self):
        n = len(self.group.active_participants)
        if n > MAX_DRAWN_MEMBERS:
            return "list"
        if _MAX_ROW_MEMBERS < n <= _MAX_CIRCLE_MEMBERS:
            return "circle"
        return "row"

    def _circle(self):
        """Return the radii and size in em of the ellipse the members sit on."""
        height = _MEMBER_HEIGHT + (_BUBBLE_HEIGHT if self.answers is not None else 0)
        rx, ry = _ellipse_radii(
            len(self.group.active_participants),
            _MEMBER_WIDTH,
            height,
            min_ry=height / 2 + 1.5 if self.note else 0,
        )
        return rx, ry, 2 * rx + _MEMBER_WIDTH, 2 * ry + height

    def _members(self):
        """Return the active members, starting with the viewer and then by seat."""
        members = sorted(self.group.active_participants, key=lambda p: p.id)
        me = [m for m in members if m.id == self.participant.id]
        return me + [m for m in members if m.id != self.participant.id]

    def _member_html(self, member, seat, index, position):
        _p = get_translator(context=True)
        pseudonym = member.pseudonym
        is_me = member.id == self.participant.id
        classes = ["psynet-group-member"]
        if is_me:
            classes.append("psynet-group-member--me")
        style = self.highlight.get(member.id)
        if style:
            classes.append(f"psynet-group-member--{_css_identifier(style)}")
        answered = self.show_progress and self.answered(member)
        if answered:
            classes.append("psynet-group-member--answered")
        bubble = Markup("")
        if self.answers is not None and member.id in self.answers:
            bubble = Markup('<span class="psynet-group-bubble">{}</span>').format(
                self.answers[member.id]
            )
        elif self.answers is not None:
            # Keeps the icons of members without an answer in line.
            bubble = Markup(
                '<span class="psynet-group-bubble psynet-group-bubble--none"'
                ' aria-hidden="true">&nbsp;</span>'
            )
        status = Markup("")
        if self.show_progress:
            status = Markup(
                '<span class="psynet-group-tick" aria-hidden="true">✓</span>'
                '<span class="psynet-group-status visually-hidden" aria-live="polite">{}</span>'
            ).format(_p("group prompt", "has answered") if answered else "")
        name = _p("group prompt", "You") if is_me else pseudonym.name
        return Markup(
            '<li class="{}" data-seat="{}" style="{}--i: {};">'
            '{}<span class="psynet-group-avatar">{}{}</span>'
            '<span class="psynet-group-name">{}</span></li>'
        ).format(
            " ".join(classes),
            seat,
            position,
            index,
            bubble,
            pseudonym.icon_html,
            status,
            name,
        )


def _angles(n):
    """Return the angles of ``n`` seats: the viewer at the bottom, then clockwise."""
    return [math.pi / 2 + 2 * math.pi * k / n for k in range(n)]


def _ellipse_offsets(n, rx, ry):
    return [(rx * math.cos(a), ry * math.sin(a)) for a in _angles(n)]


def _ellipse_radii(n, width, height, min_ry=0.0):
    """Return the flattest ellipse on which ``n`` boxes of this size do not overlap.

    Two boxes are clear of each other if their centres are at least a box
    width apart horizontally or a box height apart vertically. The ellipse is
    kept as low as the page width allows, so the controls below stay visible.
    """
    pairs = [
        (abs(math.cos(a) - math.cos(b)), abs(math.sin(a) - math.sin(b)))
        for a, b in combinations(_angles(n), 2)
    ]
    ry = min_ry
    while True:
        needed = [
            width / dx if dx > 1e-9 else math.inf
            for dx, dy in pairs
            if ry * dy < height
        ]
        rx = max(needed, default=width / 2)
        if 2 * rx + width <= _MAX_CIRCLE_WIDTH:
            return rx, ry
        ry += 0.25


def _group_seats(group):
    from .sync import group_seats

    return group_seats(group)


def _waiting_in_group(group):
    """Return a check of whether a member is waiting at a barrier of ``group``."""

    def waiting(participant):
        return any(
            link.barrier_instance is not None
            and link.barrier_instance.group_id == group.id
            for link in participant.active_barriers.values()
            if not link.released
        )

    return waiting


def _css_identifier(style: str) -> str:
    """Return ``style`` reduced to characters that are safe in a CSS class name."""
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in str(style))
