"""Print GroupPrompt HTML for group_prompt_layout.spec.js, as JSON.

Reads a JSON list of cases from stdin, each with ``size``, ``answers`` and
optionally ``answer`` (replacing the long answer), ``note`` and ``names``,
and prints a list of ``{"text", "group_html", "css"}``. Members get the longest
pseudonyms, and answers the longest answer text a demo might use, so the
layout is tested at its worst.
"""

import json
import sys
from datetime import datetime, timedelta
from types import SimpleNamespace

from psynet.group_prompt import GroupPrompt
from psynet.pseudonym import PseudonymScheme

LONG_ANSWER = "Probably 12"


def _longest_pseudonyms(scheme, n):
    colors, animals = scheme.colors(), scheme.animals()
    by_length = sorted(
        ((c, a) for c in colors for a in animals),
        key=lambda pair: -len(scheme._make(*pair).name),
    )
    pseudonyms, used_colors, used_animals = [], set(), set()
    # Prefer pairs that differ in both colour and animal, as groups get them.
    for color, animal in by_length:
        if color not in used_colors and animal not in used_animals:
            pseudonyms.append(scheme._make(color, animal))
            used_colors.add(color)
            used_animals.add(animal)
    taken = {(p.color, p.animal) for p in pseudonyms}
    pseudonyms += [scheme._make(*pair) for pair in by_length if pair not in taken]
    return pseudonyms[:n]


def _render(case):
    scheme = PseudonymScheme()
    members = [
        SimpleNamespace(id=i + 1, pseudonym=pseudonym, active_barriers={})
        for i, pseudonym in enumerate(_longest_pseudonyms(scheme, case["size"]))
    ]
    group = SimpleNamespace(
        id=1,
        active_participants=members,
        participant_links=[
            SimpleNamespace(
                id=m.id,
                participant_id=m.id,
                participant=m,
                removal_reason=None,
                admitted_at=datetime(2026, 1, 1) + timedelta(seconds=m.id),
            )
            for m in members
        ],
    )
    answers = highlight = None
    if case["answers"]:
        long_answer = case.get("answer", LONG_ANSWER)
        answers = {m.id: long_answer if m.id % 2 else str(m.id) for m in members}
        highlight = {members[0].id: "winner", members[-1].id: "duplicate"}
    prompt = GroupPrompt(
        "The room picked their numbers. The winning number was 3.",
        group=group,
        participant=members[0],
        answers=answers,
        highlight=highlight,
        note=case.get("note"),
        names=case.get("names", "on_hover"),
    )
    # Members with even IDs have answered, without a barrier to wait at.
    prompt._progress = lambda member: (member.id % 2 == 0, False)
    return {
        "text": str(prompt.text_html),
        "group_html": str(prompt.group_html),
        "css": "\n".join(prompt.get_css()),
    }


if __name__ == "__main__":
    print(json.dumps([_render(case) for case in json.load(sys.stdin)]))
