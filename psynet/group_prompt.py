"""A prompt that shows the members of a small group, and later their answers.

Round-based games with a handful of players share a common display:
everyone in the group as an animal, ticks for who has answered, and then
everyone's answer in a speech bubble. :class:`GroupPrompt` draws that
display above a page's controls.

Design constraints:

- Members are shown by pseudonym (:mod:`psynet.pseudonym`), or all as the
  same figure when ``anonymous``, never by participant ID. The page refers to members by seat
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
from typing import Callable, Dict, Optional, Union

from markupsafe import Markup

from .modular_page import Prompt
from .pseudonym import anonymous_sticker_html
from .static_resources import package_static_url
from .utils import get_translator

_MAX_ROW_MEMBERS = 4
_MAX_ZIGZAG_COLUMNS = 7


class GroupPrompt(Prompt):
    """Shows the members of a group, who has answered, and their answers.

    Members appear as their pseudonym animals drawn in their colours
    (:attr:`~psynet.pseudonym.Pseudonym.sticker_html`): in a row for up to
    four people, and in a zigzag across the width of the page for more. Only the participant viewing the page is labelled
    ("You"); the others' names are read out by screen readers and shown on
    hover. Hovering over or tapping a member brings their speech bubble to
    the front.

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
        Optional short text shown below the group, for example
        "1 was picked twice".
    show_progress
        If ``True`` (default) and ``answers`` is not given, members who have
        answered get a tick, which appears live as they reach the next
        barrier.
    answered
        Optional ``answered(participant) -> bool`` deciding who has answered
        when the page is drawn. By default, a member has answered while they
        wait at a barrier of this group, and ticks then also appear live as
        members arrive at the group's barriers. With a custom ``answered``,
        ticks are only drawn when the page loads.
    subgroups
        Optional way to cluster the members: a sync group type, such as
        ``"pair"`` for pairs formed within the group, or a function
        ``subgroups(participant)`` returning a key, members with equal keys
        forming a cluster. The viewer's cluster comes first. Members without a
        subgroup (``None``) are shown together in one cluster.
    show_names
        If ``True``, show each member's pseudonym below their animal.
    anonymous
        If ``True``, show every member as the same neutral figure, labelled
        "Your partner" in the viewer's pair (or two-member subgroup) and
        "Another player" otherwise, so that
        nobody can recognise a member they met in an earlier group.
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
        subgroups: Union[str, Callable, None] = None,
        show_names: bool = False,
        anonymous: bool = False,
        text_align: str = "left",
    ):
        super().__init__(text=text, text_align=text_align)
        self.group = group
        self.participant = participant
        self.answers = (
            None
            if answers is None
            else {int(k): v for k, v in answers.items() if v is not None}
        )
        self.highlight = {int(k): v for k, v in (highlight or {}).items()}
        self.note = note
        self.show_progress = show_progress and answers is None
        self.answered = answered or _waiting_in_group(group)
        self.live_ticks = self.show_progress and answered is None
        self.subgroups = subgroups
        self.show_names = show_names
        self.anonymous = anonymous

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

        return [
            resources.files("psynet")
            .joinpath("resources/css/group-prompt.css")
            .read_text(encoding="utf-8")
        ]

    def get_js_vars(self):
        """Configuration for live ticks."""
        _p = get_translator(context=True)
        return {
            "group_prompt": {
                "group_id": self.group.id,
                "live_ticks": self.live_ticks,
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
        seats = _group_seats(self.group)
        clusters = self._clusters()
        viewer_present = any(
            m.id == self.participant.id for cluster in clusters[:1] for m in cluster
        )
        if self.subgroups is None:
            label = (
                _p("group prompt", "Your group")
                if viewer_present
                else _p("group prompt", "Group")
            )
            body = self._members_html(clusters[0], seats, label)
        else:
            labels = [_p("group prompt", "Another subgroup")] * len(clusters)
            if viewer_present:
                labels[0] = _p("group prompt", "Your subgroup")
            body = Markup('<ul class="psynet-group-clusters">{}</ul>').format(
                Markup("").join(
                    Markup('<li class="psynet-group-cluster">{}</li>').format(
                        self._members_html(cluster, seats, label)
                    )
                    for cluster, label in zip(clusters, labels)
                )
            )
        note = (
            Markup('<p class="psynet-group-note">{}</p>').format(self.note)
            if self.note
            else Markup("")
        )
        classes = "psynet-group-prompt"
        if self.answers is not None:
            classes += " psynet-group-prompt--answers"
        if self.show_names:
            classes += " psynet-group-prompt--names"
        if viewer_present:
            classes += " psynet-group-prompt--with-viewer"
        announcer = (
            Markup(
                '<p class="psynet-group-announcer visually-hidden" aria-live="polite"></p>'
            )
            if self.live_ticks
            else Markup("")
        )
        return Markup('<div class="{}">{}{}{}</div>').format(
            classes, body, note, announcer
        )

    def _members_html(self, members, seats, label):
        layout = "row" if len(members) <= _MAX_ROW_MEMBERS else "zigzag"
        # Balanced rows: 8 members as 4 + 4 rather than 7 + 1.
        rows = max(1, math.ceil(len(members) / _MAX_ZIGZAG_COLUMNS))
        columns = math.ceil(len(members) / rows)
        with_viewer = any(m.id == self.participant.id for m in members)
        partner_label = with_viewer and len(members) == 2
        items = Markup("").join(
            self._member_html(member, seats[member.id], index, partner_label)
            for index, member in enumerate(members)
        )
        return Markup(
            '<ul class="psynet-group-members psynet-group-members--{}"'
            ' style="--columns: {};" aria-label="{}">{}</ul>'
        ).format(layout, columns, label, items)

    def _members(self):
        """Return the active members, starting with the viewer and then by seat."""
        seats = _group_seats(self.group)
        members = sorted(
            self.group.active_participants, key=lambda p: seats.get(p.id, len(seats))
        )
        me = [m for m in members if m.id == self.participant.id]
        return me + [m for m in members if m.id != self.participant.id]

    def _clusters(self):
        """Return the members in subgroups, the viewer's first."""
        members = self._members()
        if self.subgroups is None:
            return [members]
        clusters = {}
        for member in members:
            clusters.setdefault(self._subgroup_key(member), []).append(member)
        # The viewer is first in ``members``, so their cluster comes first.
        return list(clusters.values())

    def _subgroup_key(self, member):
        if callable(self.subgroups):
            return self.subgroups(member)
        subgroup = member.active_sync_groups.get(self.subgroups)
        return None if subgroup is None else subgroup.id

    def _member_html(self, member, seat, index, partner_label):
        _p = get_translator(context=True)
        is_me = member.id == self.participant.id
        if is_me:
            label = _p("group prompt", "You")
        elif not self.anonymous:
            label = member.pseudonym.name
        elif partner_label:
            label = _p("group prompt", "Your partner")
        else:
            label = _p("group prompt", "Another player")
        sticker = (
            anonymous_sticker_html()
            if self.anonymous
            else member.pseudonym.sticker_html
        )
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
        focusable = Markup("")
        if self.answers is not None:
            # Tapping a member brings their bubble to the front.
            focusable = Markup(' tabindex="0"')
            if member.id in self.answers:
                bubble = Markup('<span class="psynet-group-bubble">{}</span>').format(
                    self.answers[member.id]
                )
            else:
                # Keeps the animals of members without an answer in line.
                bubble = Markup(
                    '<span class="psynet-group-bubble psynet-group-bubble--none"'
                    ' aria-hidden="true">&nbsp;</span>'
                )
        status = Markup("")
        if self.show_progress:
            status = Markup(
                '<span class="psynet-group-tick" aria-hidden="true">✓</span>'
                '<span class="psynet-group-status visually-hidden">{}</span>'
            ).format(_p("group prompt", "has answered") if answered else "")
        name = Markup('<span class="psynet-group-name{}">{}</span>').format(
            " psynet-group-you" if is_me else "", label
        )
        return Markup(
            '<li class="{}" data-seat="{}" style="--i: {};" title="{}"{}>'
            '{}<span class="psynet-group-avatar">{}{}</span>{}</li>'
        ).format(
            " ".join(classes),
            seat,
            index,
            label,
            focusable,
            bubble,
            sticker,
            status,
            name,
        )


def _group_seats(group):
    from .sync import group_seats

    return group_seats(group)


def _waiting_in_group(group):
    """Return a check of whether a member is waiting at a barrier of ``group``."""

    from .sync import waiting_barrier_ids

    def waiting(participant):
        return bool(waiting_barrier_ids(participant, group))

    return waiting


def _css_identifier(style: str) -> str:
    """Return ``style`` reduced to characters that are safe in a CSS class name."""
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in str(style))
