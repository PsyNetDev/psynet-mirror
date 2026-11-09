"""A prompt that shows the members of a small group, and later their answers.

Round-based games with a handful of players share a common display:
everyone in the group as an animal, ticks for who has answered, and then
everyone's answer in a speech bubble. :class:`GroupPrompt` draws that
display above a page's controls.

Design constraints:

- Members are shown by pseudonym (:mod:`psynet.pseudonym`), or all as the
  same figure with ``names="anonymous"``, never by participant ID. The page
  refers to members by seat (:func:`psynet.sync.group_seats`), which is also
  how :class:`~psynet.sync.GroupBarrier` reports live ticks.
- By default a member has answered once they are waiting at a barrier of
  the group (:func:`psynet.sync.is_waiting_at_barrier`), typically the barrier after
  the decision page. Live ticks come from that barrier's arrival updates, so
  they need ``notify_arrivals`` (the default). A member who reached the
  barrier because their page's time limit ran out gets a dash instead of a
  tick (:func:`psynet.sync.reached_barrier_after_time_limit`).
- Live redraws re-create the prompt on the server from a signed token, so
  only options that can be serialized take part in them; functions and
  ``answers`` fix the display when the page loads.
- Members who drop out of the group stay in their seat, faded and marked
  "(left)" if they failed or left the experiment, "(removed)" if a
  barrier removed them for being late, "(finished)" if they left after
  playing their part, and "(dropped out)" otherwise.
  Members who moved on to their next group, as in a new round, are no
  longer shown, except on pages with ``answers`` that include their answer,
  where they keep their seat and bubble. The reason comes from
  :meth:`psynet.sync.SyncGroup.remove_participant`. While the group accepts
  top-ups, members who left are omitted; after top-ups stop they appear too
  (:ref:`sync-lobby-top-ups`).
- The HTML is built on the server; ``static/scripts/group-prompt.js`` only
  updates ticks and dashes, so pages without JavaScript still show the group.
"""

import math
import os
from typing import Callable, Dict, Optional, Union

from itsdangerous import BadSignature, URLSafeSerializer
from markupsafe import Markup

from .modular_page import Prompt
from .pseudonym import anonymous_sticker_html
from .static_resources import package_static_url
from .utils import as_plain_text, get_logger, get_translator

logger = get_logger()

_MAX_ROW_MEMBERS = 4
_MAX_ZIGZAG_COLUMNS = 7
_NAMES = ("on_hover", "shown", "anonymous")
_warned_no_secret = False


class _ParticipantsGroup:
    """Default for ``GroupPrompt(group=...)``: look up the participant's group."""

    def __repr__(self):
        return "<the participant's group>"


_PARTICIPANTS_GROUP = _ParticipantsGroup()


def _link_order(link):
    """Sort key putting sync group links in creation order, unflushed ones last."""
    return float("inf") if link.id is None else link.id


class GroupPrompt(Prompt):
    """Shows the members of a group, who has answered, and their answers.

    Members appear as their pseudonym animals drawn in their colours
    (:attr:`~psynet.pseudonym.Pseudonym.sticker_html`; see
    :doc:`/code/multiplayer/pseudonyms`): in a row for up to four people,
    and in a zigzag across the width of the page for more. Hovering over or
    tapping a member brings their speech bubble to the front. A member who
    dropped out of the group is drawn faded and marked "(left)",
    "(removed)", "(finished)" or "(dropped out)"; one who moved on to their next group, as in a
    new round, is no longer shown, unless the page shows their answer.
    While the group accepts top-ups, members who left are omitted; after
    top-ups stop they appear too (:ref:`sync-lobby-top-ups`).

    A page shows either progress (ticks for who has answered) or
    ``answers``, and what it draws from the group's state updates live:
    ticks and dashes as members reach a barrier of the group, and members as
    they join or leave. Only what the server can't work out again later is
    fixed when the page loads: who has answered by a custom
    ``has_answered``, clusters from a ``subgroups`` function, and the members
    shown with ``answers``.

    Parameters
    ----------
    text
        Text shown above the group, as for :class:`~psynet.modular_page.Prompt`.
    participant
        The participant viewing the page.
    group
        The :class:`~psynet.sync.SyncGroup` to show. By default, the
        participant's group of type ``group_type``, or, if they have only
        ever been in groups of one type, their group of that type; a
        participant who is or has been in groups of several types needs
        ``group_type`` or ``group``.
        If the lookup finds no group, for example because a barrier removed
        them for being late, the page shows just ``text``, as it does for
        ``group=None``. A group passed explicitly, such as
        ``trial.sync_group``, which keeps the group the trial was played in,
        is drawn even if the viewer has left it.
    group_type
        The type of group to show when ``group`` is omitted, for example
        ``"pair"``.
    answers
        Optional ``{participant_id: answer}`` to show in speech bubbles, for
        example after the group's barrier has released. Answers are shown
        as text; pass :class:`~markupsafe.Markup` for HTML such as an image.
        Members with an entry, even ``None`` (as for a member who ran out of
        time), keep their seat after moving on to their next group; ``None``
        shows no bubble. Members without an entry get no bubble either, and
        are omitted once they have moved on.
    highlight
        Optional ``{participant_id: style}``. ``"winner"`` and
        ``"duplicate"`` have built-in styles; any other style becomes the
        CSS class ``psynet-group-member--<style>``. In both dictionaries the
        IDs may be strings, as in a dictionary read back from a participant
        variable.
    note
        Optional short text shown below the group, for example
        "1 was picked twice". Like the group, it is hidden when there is no
        group to show.
    show_progress
        Whether members who have answered get a tick. A member who reached a
        barrier of the group because their page's time limit ran out gets a
        dash instead. While ticks appear live, the page hides the group
        arrival notice ("2/3 of your group are ready."), which would repeat
        them. Defaults to ``True``, or ``False`` with ``answers``, which
        can't be combined with ``True``.
    has_answered
        Optional ``has_answered(participant) -> bool`` deciding who gets a
        tick when the page is drawn, in place of
        :func:`~psynet.sync.is_waiting_at_barrier`, which a custom check can call.
        Members waiting after a time-out
        (:func:`~psynet.sync.reached_barrier_after_time_limit`) get a dash whatever it
        returns. Only used with ``show_progress``, so it can't be combined
        with ``answers`` or ``show_progress=False``.
    subgroups
        Optional way to cluster the members: a sync group type, such as
        ``"pair"`` for pairs formed within the group, or a function
        ``subgroups(participant)`` returning a key, members with equal keys
        forming a cluster. The viewer's cluster comes first. Members without a
        subgroup (``None``) are shown together in one cluster. With a sync
        group type, a former member who is still shown stays in the latest
        such group that a current member is still in.
    names
        How members other than the viewer, who is labelled "You", are named:

        - ``"on_hover"`` (default): by pseudonym, read out by screen readers
          and shown on hover;
        - ``"shown"``: by pseudonym, also written below each animal;
        - ``"anonymous"``: all drawn as the same neutral figure, labelled
          below with "Your partner" in the viewer's pair (or two-member
          subgroup) and "Another player" otherwise, so that nobody can recognise a member
          they met in an earlier group. Pair it with
          ``ChatRoom(names="anonymous")`` on pages with a chat room.
    text_align
        CSS alignment of the text.
    """

    macro = "group"

    def __init__(
        self,
        text=None,
        *,
        participant,
        group=_PARTICIPANTS_GROUP,
        group_type: Optional[str] = None,
        answers: Optional[Dict[Union[int, str], Union[str, Markup, None]]] = None,
        highlight: Optional[Dict[Union[int, str], str]] = None,
        note: Optional[str] = None,
        show_progress: Optional[bool] = None,
        has_answered: Optional[Callable] = None,
        subgroups: Union[str, Callable, None] = None,
        names: str = "on_hover",
        text_align: str = "left",
    ):
        super().__init__(text=text, text_align=text_align)
        if names not in _NAMES:
            raise ValueError(
                f"GroupPrompt's names must be one of {', '.join(map(repr, _NAMES))}, "
                f"not {names!r}."
            )
        if show_progress is None:
            show_progress = answers is None
        elif show_progress and answers is not None:
            raise ValueError(
                "GroupPrompt shows either progress or answers: "
                "don't pass show_progress=True with answers."
            )
        if has_answered is not None and not show_progress:
            raise ValueError(
                "GroupPrompt only uses has_answered to show progress, so it can't "
                "be combined with answers or show_progress=False."
            )
        if group is not _PARTICIPANTS_GROUP and group_type is not None:
            raise ValueError(
                "Pass either group or group_type to GroupPrompt, not both."
            )
        if group is _PARTICIPANTS_GROUP:
            group = _participants_group(participant, group_type)
        self.group = group
        self.participant = participant
        self.answers = (
            None if answers is None else {int(k): v for k, v in answers.items()}
        )
        self.highlight = {int(k): v for k, v in (highlight or {}).items()}
        self.note = note
        self.show_progress = show_progress
        self.has_answered = has_answered
        self.live_ticks = show_progress and has_answered is None
        self.live_members = (
            answers is None and has_answered is None and not callable(subgroups)
        )
        self.subgroups = subgroups
        self.names = names

    @property
    def metadata(self):
        return {
            "group_id": None if self.group is None else self.group.id,
            "answers": None
            if self.answers is None
            else {
                str(k): None if v is None else str(v) for k, v in self.answers.items()
            },
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
        if self.group is None:
            return {}
        _p = get_translator(context=True)
        return {
            "group_prompt": {
                "group_id": self.group.id,
                "live_ticks": self.live_ticks,
                "live_members": self.live_members,
                "answered_label": _p("group prompt", "has answered"),
                "answered_announcement": _p("group prompt", "{NAME} has answered."),
                "ran_out_of_time_label": _p("group prompt", "ran out of time"),
                "ran_out_of_time_announcement": _p(
                    "group prompt", "{NAME} ran out of time."
                ),
                "redraw_token": self._redraw_token() if self.live_members else None,
            }
        }

    def _redraw_token(self):
        """Return a signed description of this display for :func:`redrawn_group_html`.

        Signed so that a participant can't ask for a display other than the
        one they were shown, such as names where the prompt is anonymous.
        """
        serializer = _token_serializer()
        if serializer is None:
            return None
        # Readable by the page, so refer to other members by seat, not ID.
        seats = _group_seats(self.group)
        return serializer.dumps(
            {
                "group": self.group.id,
                "participant": self.participant.id,
                "names": self.names,
                "subgroups": self.subgroups,
                "show_progress": self.show_progress,
                "highlight": {
                    seats[pid]: style
                    for pid, style in self.highlight.items()
                    if pid in seats
                },
                "note": None if self.note is None else str(Markup.escape(self.note)),
            }
        )

    def get_js_page_modules(self):
        """The module that adds ticks as members answer."""
        if self.group is None:
            return []
        return [package_static_url("psynet", "scripts/group-prompt.js")]

    @property
    def plain_text(self):
        """The prompt's text followed by its ``note``, which shows only with a group."""
        text = super().plain_text
        if self.group is None or not self.note:
            return text
        note = as_plain_text(Markup.escape(self.note))
        return note if not text else f"{text} {note}"

    @property
    def group_html(self) -> Markup:
        """HTML for the group display, or nothing without a group."""
        if self.group is None:
            return Markup("")
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
        if self.names in ("shown", "anonymous"):
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
        """Return the members and those who left, the viewer first and then by seat."""
        seats = _group_seats(self.group)
        members = sorted(
            [*self.group.active_participants, *self._left_members()],
            key=lambda p: seats.get(p.id, len(seats)),
        )
        me = [m for m in members if m.id == self.participant.id]
        return me + [m for m in members if m.id != self.participant.id]

    def _left_members(self):
        """Return former members who dropped out, and those who moved on whose answer the page shows.

        Groups that take top-ups are open-ended, like a lobby, so their
        leavers are not shown.
        """
        if getattr(self.group, "accepts_top_ups", False):
            return []
        active_ids = {p.id for p in self.group.active_participants}
        left = {}
        reasons = self._removal_reasons()
        moved_on = self._moved_on_with_answers()
        for link in self.group.participant_links:
            member = link.participant
            if (
                member.id in active_ids
                or member.id == self.participant.id
                or (reasons.get(member.id) == "moved_on" and member.id not in moved_on)
            ):
                continue
            left[member.id] = member
        return list(left.values())

    def _moved_on_with_answers(self):
        """Return the IDs of members who moved on but whose answers this page shows.

        Results pages keep their seats, so the page reads the same for
        players who reload it after others have gone on to the next round.
        """
        if self.answers is None:
            return set()
        reasons = self._removal_reasons()
        return {
            member_id
            for member_id, reason in reasons.items()
            if reason == "moved_on" and member_id in self.answers
        }

    def _removal_reasons(self):
        """Return ``{participant_id: reason}`` from each member's latest link to the group."""
        links = sorted(self.group.participant_links, key=_link_order)
        return {link.participant_id: link.removal_reason for link in links}

    def _left_label(self, member, label):
        """Return ``label`` marked with why ``member`` is no longer in the group."""
        _p = get_translator(context=True)
        if member.failed:
            return _p("group prompt", "{NAME} (left)").format(NAME=label)
        if self._removal_reasons().get(member.id) == "finished":
            return _p("group prompt", "{NAME} (finished)").format(NAME=label)
        if member.status != "working":
            return _p("group prompt", "{NAME} (left)").format(NAME=label)
        if self._removal_reasons().get(member.id) == "late":
            return _p("group prompt", "{NAME} (removed)").format(NAME=label)
        return _p("group prompt", "{NAME} (dropped out)").format(NAME=label)

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
        """Return the member's subgroup.

        A former member is placed in their latest subgroup that someone still
        in the group is in now, even after joining a new one, or else with
        the members without a subgroup.
        """
        if callable(self.subgroups):
            return self.subgroups(member)
        if member in self.group.active_participants:
            subgroup = member.active_sync_groups.get(self.subgroups)
            return None if subgroup is None else subgroup.id
        links = sorted(
            (
                link
                for link in member.sync_group_links
                if link.sync_group.group_type == self.subgroups
            ),
            key=_link_order,
        )
        current = {
            self._subgroup_key(other) for other in self.group.active_participants
        }
        shared = [link for link in links if link.sync_group_id in current]
        return shared[-1].sync_group_id if shared else None

    def _progress(self, member):
        """Return ``(answered, timed_out)`` for a member still in the group."""
        from .sync import is_waiting_at_barrier, reached_barrier_after_time_limit

        if reached_barrier_after_time_limit(member, self.group):
            return False, True
        has_answered = self.has_answered or (
            lambda m: is_waiting_at_barrier(m, self.group)
        )
        return bool(has_answered(member)), False

    def _member_html(self, member, seat, index, partner_label):
        _p = get_translator(context=True)
        is_me = member.id == self.participant.id
        anonymous = self.names == "anonymous"
        if is_me:
            label = _p("group prompt", "You")
        elif not anonymous:
            label = member.pseudonym.name
        elif partner_label:
            label = _p("group prompt", "Your partner")
        else:
            label = _p("group prompt", "Another player")
        sticker = (
            anonymous_sticker_html() if anonymous else member.pseudonym.sticker_html
        )
        has_left = (
            member not in self.group.active_participants
            and member.id not in self._moved_on_with_answers()
        )
        classes = ["psynet-group-member"]
        if is_me:
            classes.append("psynet-group-member--me")
        if has_left:
            classes.append("psynet-group-member--left")
            label = self._left_label(member, label)
        style = self.highlight.get(member.id)
        if style:
            classes.append(f"psynet-group-member--{_css_identifier(style)}")
        answered = timed_out = False
        if self.show_progress and not has_left:
            answered, timed_out = self._progress(member)
        if timed_out:
            classes.append("psynet-group-member--ran-out-of-time")
        elif answered:
            classes.append("psynet-group-member--answered")
        bubble = Markup("")
        focusable = Markup("")
        if self.answers is not None:
            # Tapping a member brings their bubble to the front.
            focusable = Markup(' tabindex="0"')
            answer = self.answers.get(member.id)
            if answer is not None and not isinstance(answer, Markup):
                focusable += Markup(' aria-label="{}: {}"').format(label, answer)
            if answer is not None:
                bubble = Markup('<span class="psynet-group-bubble">{}</span>').format(
                    answer
                )
            else:
                # Keeps the animals of members without an answer in line.
                bubble = Markup(
                    '<span class="psynet-group-bubble psynet-group-bubble--none"'
                    ' aria-hidden="true">&nbsp;</span>'
                )
        status = Markup("")
        if self.show_progress:
            if timed_out:
                status_text = _p("group prompt", "ran out of time")
            elif answered:
                status_text = _p("group prompt", "has answered")
            else:
                status_text = ""
            status = Markup(
                '<span class="psynet-group-tick" aria-hidden="true">✓</span>'
                '<span class="psynet-group-dash" aria-hidden="true">–</span>'
                '<span class="psynet-group-status visually-hidden">{}</span>'
            ).format(status_text)
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


def redrawn_group_html(unique_id, token):
    """Return ``{"html": ...}``, the group display a live page shows, drawn again now.

    Parameters
    ----------
    unique_id : str
        The participant's unique ID.
    token : str
        The page's redraw token (see ``GroupPrompt.get_js_vars``).

    Returns
    -------
    dict
        ``{"html": None}`` if the token is invalid or belongs to someone else.
    """
    from .participant import Participant
    from .sync import SyncGroup

    serializer = _token_serializer()
    try:
        options = serializer.loads(token or "") if serializer else None
    except BadSignature:
        options = None
    participant = (
        Participant.query.filter_by(unique_id=unique_id).one_or_none()
        if options and unique_id
        else None
    )
    if participant is None or participant.id != options["participant"]:
        return {"html": None}
    group = SyncGroup.query.get(options["group"])
    if group is None or participant not in group.active_participants:
        # A removed viewer keeps the drawing they have until their next page.
        return {"html": None}
    prompt = GroupPrompt(
        group=group,
        participant=participant,
        names=options["names"],
        subgroups=options["subgroups"],
        show_progress=options["show_progress"],
        highlight={
            pid: options["highlight"][str(seat)]
            for pid, seat in _group_seats(group).items()
            if str(seat) in options["highlight"]
        },
        note=None if options["note"] is None else Markup(options["note"]),
    )
    return {"html": str(prompt.group_html)}


def _token_serializer():
    """Return the serializer for redraw tokens, or ``None`` without a server secret."""
    global _warned_no_secret
    secret = os.environ.get("FLASK_SECRET_KEY")
    if not secret:
        if not _warned_no_secret:
            _warned_no_secret = True
            logger.warning(
                "FLASK_SECRET_KEY is not set, so GroupPrompt pages won't redraw "
                "the group when members join or leave."
            )
        return None
    return URLSafeSerializer(secret, salt="psynet.group_prompt")


def _participants_group(participant, group_type):
    """Return the participant's active group of ``group_type``, or of their only group type.

    A participant who is or has been in groups of several types must name
    one: their only active group would change type as they leave one, such
    as a pair, and fall back to another, such as their cohort.
    """
    if group_type is None:
        group_types = {
            link.sync_group.group_type for link in participant.sync_group_links
        }
        if len(group_types) > 1:
            raise ValueError(
                f"Participant {participant.id} is or has been in groups of several "
                f"types ({', '.join(sorted(group_types))}), so pass GroupPrompt "
                "the group_type or group to show."
            )
        if not group_types:
            return None
        (group_type,) = group_types
    return participant.active_sync_groups.get(group_type)


def _css_identifier(style: str) -> str:
    """Return ``style`` reduced to characters that are safe in a CSS class name."""
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in str(style))
