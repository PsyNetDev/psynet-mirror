"""Check a timeline_lifecycle_prolific export and print one line per check.

Usage::

    python analyze.py path/to/export

The argument is an extracted ``psynet export`` directory (the one containing
``database/``). Each check prints PASS, FAIL, or WARN with the internal
participant IDs involved. WARN marks results that real participants can
cause without a PsyNet bug, such as a manual page reload or blocked
autoplay. INFO lines summarise statuses, devices, and transition times. The
script exits non-zero if any check fails.

See the ``experiment.py`` docstring for the transitions being checked.
"""

import csv
import hashlib
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

COMPONENT_TOKEN = "component-js-vars-ok"
LEAVE_EVERY = 8
LEAVE_REMAINDER = 3

# WaitPage always uses the label "wait".
PAGE_BY_QUESTION = {"wait": "lt_auto_advance"}
AUTO_ADVANCING = {"lt_auto_advance"}

SAME = "same document"
NEW = "new document"

# How each probed page's document should relate to the previous probed page's.
EXPECTED_DOCUMENT = {
    "lt_component": SAME,
    "lt_choices": SAME,
    "lt_after_wait": SAME,
    "lt_audio": SAME,
    "lt_after_audio": SAME,
    "lt_auto_advance": SAME,
    "lt_after_auto": SAME,
    "lt_reload": NEW,
    "lt_full_reload": NEW,
    "lt_after_full_reload": NEW,
    "lt_after_jspsych": NEW,
    "lt_leave_request": SAME,
    "lt_final": SAME,
}

# Transitions timed from the previous page's submission, with nothing else in
# between (no hold, jsPsych page, or participant-initiated reload).
TIMED_IN_PLACE = {
    "lt_component",
    "lt_choices",
    "lt_audio",
    "lt_after_audio",
    "lt_auto_advance",
    "lt_after_auto",
    "lt_final",
}
TIMED_RELOAD = {"lt_full_reload", "lt_after_full_reload"}

results = []


def report(status, name, detail=""):
    results.append(status)
    print(f"{status:4}  {name}" + (f": {detail}" if detail else ""))


def check(name, failures, warnings=(), detail=""):
    if failures:
        report("FAIL", name, f"participants {sorted(set(failures))} {detail}".strip())
    elif warnings:
        report("WARN", name, f"participants {sorted(set(warnings))} {detail}".strip())
    else:
        report("PASS", name, detail)


def read_table(export_dir, table):
    path = export_dir / "database" / f"{table}.csv"
    if not path.exists():
        return []
    with open(path, newline="") as file:
        return list(csv.DictReader(file))


def load_pages(responses, participant_ids):
    """Return {participant_id: [page, ...]} for this test's pages, in response order."""
    by_participant = defaultdict(list)
    for row in sorted(responses, key=lambda r: int(r["id"])):
        pid = int(row["participant_id"])
        question = row["question"]
        page = PAGE_BY_QUESTION.get(question, question)
        if pid not in participant_ids or not page.startswith("lt_"):
            continue
        metadata = json.loads(row["metadata_"] or "{}")
        by_participant[pid].append(
            {
                "page": page,
                "question": question,
                "lifecycle": metadata.get("lifecycle"),
                "answer": json.loads(row["answer"]) if row["answer"] else None,
            }
        )
    return by_participant


def jspsych_document_id(answer):
    data = json.loads(answer) if isinstance(answer, str) else answer
    return data[0].get("lifecycle_document_id") if data else None


def check_transitions(pages):
    failures, manual_reloads = [], []
    not_reloaded, reload_failures = [], []
    for pid, rows in pages.items():
        previous = None
        jspsych_doc = None
        for row in rows:
            page, lc = row["page"], row["lifecycle"]
            if page == "lt_jspsych":
                jspsych_doc = jspsych_document_id(row["answer"])
                if previous and jspsych_doc == previous["document_id"]:
                    failures.append(pid)
                continue
            if lc is None:
                continue
            same = previous is not None and lc["document_id"] == previous["document_id"]
            expected = EXPECTED_DOCUMENT.get(page)
            if page == "lt_reload":
                if lc["navigation_type"] == "reload" and not same:
                    pass
                elif same:
                    not_reloaded.append(pid)
                else:
                    reload_failures.append(pid)
            elif previous and expected == SAME and not same:
                if lc["navigation_type"] in ("reload", "back_forward"):
                    manual_reloads.append(pid)
                else:
                    failures.append(pid)
            elif previous and expected == NEW and same:
                failures.append(pid)
            if page == "lt_after_jspsych" and jspsych_doc == lc["document_id"]:
                failures.append(pid)
            previous = lc
    check(
        "document kept or replaced as expected at each transition",
        failures,
        manual_reloads,
        "(WARN: participant reloaded the page)"
        if manual_reloads and not failures
        else "",
    )
    check(
        "lt_reload was answered from a page rebuilt after a reload",
        reload_failures,
        not_reloaded,
        "(WARN: sessionStorage unavailable, so Next was shown without a reload)"
        if not_reloaded and not reload_failures
        else "",
    )


def check_page_records(pages):
    probed = {
        pid: [
            (row["page"], row["question"], row["lifecycle"])
            for row in rows
            if row["lifecycle"]
        ]
        for pid, rows in pages.items()
    }
    probed = {pid: rows for pid, rows in probed.items() if rows}

    def failing(predicate):
        return [
            pid
            for pid, rows in probed.items()
            if any(predicate(p, q, lc) for p, q, lc in rows)
        ]

    missing = [pid for pid in pages if pid not in probed]
    check("every participant with lt_ responses submitted lifecycle records", missing)

    check(
        "js_dependencies ran once per document",
        failing(lambda p, q, lc: lc["dependency_executions"] != 1),
    )
    check(
        "page modules activated once per page",
        failing(lambda p, q, lc: lc["activations_of_this_page"] != 1),
    )

    module_mismatch = []
    for pid, rows in probed.items():
        instances = defaultdict(set)
        for _, _, lc in rows:
            instances[lc["document_id"]].add(lc["module_instance"])
        if any(len(v) > 1 for v in instances.values()):
            module_mismatch.append(pid)
    check("page module evaluated once per document", module_mismatch)

    check(
        "psynet.var belongs to the current page",
        failing(lambda p, q, lc: lc["step"] != p),
    )
    check(
        "page stylesheet applies only to its own page",
        failing(lambda p, q, lc: lc["page_style_applied"] != (p == "lt_component")),
    )
    check(
        "component get_js_vars reaches only its own page",
        failing(
            lambda p, q, lc: (
                lc["component_token"]
                != (COMPONENT_TOKEN if p == "lt_component" else None)
            )
        ),
    )
    check(
        "pages needing a click were submitted after participant input",
        failing(
            lambda p, q, lc: (
                p not in AUTO_ADVANCING and not lc["user_input_before_submit"]
            )
        ),
    )

    silent, still_playing = [], []
    for pid, rows in probed.items():
        by_page = {p: lc for p, _, lc in rows}
        audio, after = by_page.get("lt_audio"), by_page.get("lt_after_audio")
        if audio and audio["sounds_at_submit"] == 0:
            silent.append(pid)
        if after and (
            after["sounds_at_activation"]
            or after["media_elements_playing_at_activation"]
            or after["sounds_at_submit"]
        ):
            still_playing.append(pid)
    check("audio stops at the in-place transition", still_playing)
    check(
        "audio was playing on lt_audio (positive control)",
        [],
        silent,
        "(WARN: autoplay blocked, so the stop check proves nothing for them)"
        if silent
        else "",
    )

    layout = defaultdict(Counter)
    for pid, rows in probed.items():
        device = "touch" if rows[0][2]["touch"] else "no-touch"
        for p, _, lc in rows:
            layout[(p, device)].update(lc["layout_violations"] or [])
    layout = {key: counts for key, counts in layout.items() if counts}
    if layout:
        detail = "; ".join(
            f"{p} [{device}] {dict(counts)}"
            for (p, device), counts in sorted(layout.items())
        )
        report("WARN", "psynetLayout violations", detail)
    else:
        report("PASS", "psynetLayout violations", "none")

    return probed


def check_duplicate_responses(responses, participant_ids):
    counts = Counter(
        (int(r["participant_id"]), r["question"])
        for r in responses
        if int(r["participant_id"]) in participant_ids
        and r["successful_validation"] == "True"
    )
    duplicates = [(pid, q) for (pid, q), n in counts.items() if n > 1]
    check(
        "each page accepted exactly one response",
        [pid for pid, _ in duplicates],
        detail=f"pages {sorted({q for _, q in duplicates})}" if duplicates else "",
    )


def report_transition_times(probed):
    samples = defaultdict(list)
    for rows in probed.values():
        device = "touch" if rows[0][2]["touch"] else "no-touch"
        previous = None
        for p, _, lc in rows:
            timed = (
                lc["transition_ms"] is not None and lc["transition_from"] == previous
            )
            if timed and p in TIMED_IN_PLACE:
                samples[("in place", device)].append(lc["transition_ms"])
            elif timed and p in TIMED_RELOAD:
                samples[("full reload", device)].append(lc["transition_ms"])
            previous = p
    if not samples:
        report("INFO", "transition times", "no timed transitions")
        return
    detail = "; ".join(
        f"{kind} [{device}] median {statistics.median(values):.0f} ms, "
        f"max {max(values):.0f} ms (n={len(values)})"
        for (kind, device), values in sorted(samples.items())
    )
    report("INFO", "transition times from submit to next page", detail)


def check_server_side(export_dir, pages, participants, probed):
    by_id = {int(p["id"]): p for p in participants}

    def reached(page):
        return [
            pid
            for pid, rows in pages.items()
            if any(row["page"] == page for row in rows)
        ]

    check(
        "AsyncCodeBlock finished before lt_after_wait",
        [
            pid
            for pid in reached("lt_after_wait")
            if not json.loads(by_id[pid]["vars"] or "{}").get(
                "lifecycle_async_finished"
            )
        ],
    )

    assets = [
        a
        for a in read_table(export_dir, "asset")
        if a["local_key"] == "lifecycle_summary"
    ]
    by_owner = {int(a["participant_id"]): a for a in assets}
    bad_assets = []
    for pid in reached("lt_after_jspsych"):
        row = by_owner.get(pid)
        if (
            row is None
            or row["object_path"] != f"objects/sha256/{row['sha256_contents']}"
        ):
            bad_assets.append(pid)
            continue
        for candidate in (
            export_dir / "assets" / row["export_path"],
            export_dir / row["object_path"],
            Path.home() / "psynet-data" / "cache" / "assets" / row["object_path"],
        ):
            if candidate.is_file():
                if (
                    hashlib.sha256(candidate.read_bytes()).hexdigest()
                    != row["sha256_contents"]
                ):
                    bad_assets.append(pid)
                break
    check("participant asset stored under its SHA-256 digest", bad_assets)

    # Leave submits no response, so select by ID among those who reached the branch.
    asked = [
        pid
        for pid in reached("lt_after_jspsych")
        if pid % LEAVE_EVERY == LEAVE_REMAINDER
    ]
    left = [pid for pid in asked if by_id[pid]["early_exited"] == "True"]
    pressed_next = [pid for pid in asked if pid in reached("lt_final")]
    check(
        "participants asked to leave used Leave",
        [pid for pid in asked if pid not in left and pid not in pressed_next],
        pressed_next,
        f"({len(left)} of {len(asked)} left; WARN: pressed Next instead)"
        if pressed_next
        else f"({len(left)} of {len(asked)} left)",
    )

    statuses = defaultdict(list)
    for p in participants:
        if int(p["id"]) in by_id:
            statuses[p["status"]].append(int(p["id"]))
    report("INFO", "participant statuses", json.dumps(dict(statuses), sort_keys=True))

    devices = Counter(
        str(row["answer"])
        for rows in pages.values()
        for row in rows
        if row["page"] == "lt_choices" and row["answer"] is not None
    )
    touch = sum(1 for rows in probed.values() if rows[0][2]["touch"])
    report(
        "INFO",
        "devices",
        f"self-reported {dict(devices)}; touch screens {touch}/{len(probed)}",
    )


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    export_dir = Path(argv[1])
    responses = read_table(export_dir, "response")
    # Bots do not run JavaScript, so they cannot submit lifecycle records.
    participants = [
        p
        for p in read_table(export_dir, "participant")
        if not p["type"].endswith(".Bot")
    ]
    participant_ids = {int(p["id"]) for p in participants}
    pages = load_pages(responses, participant_ids)
    if not pages:
        report(
            "FAIL",
            "export contains lt_ responses from non-bot participants",
            str(export_dir),
        )
        return 1

    check_transitions(pages)
    probed = check_page_records(pages)
    check_duplicate_responses(responses, participant_ids)
    check_server_side(export_dir, pages, participants, probed)
    report_transition_times(probed)
    return 1 if "FAIL" in results else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
