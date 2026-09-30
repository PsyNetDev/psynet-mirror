"""Check a timeline_lifecycle_prolific export and print one line per check.

Usage::

    python analyze.py path/to/export

The argument is an extracted ``psynet export`` directory (the one containing
``database/``). Each check prints PASS, FAIL, or WARN with the internal
participant IDs involved. WARN marks results that real participants can
cause without a PsyNet bug, such as a manual page reload or blocked
autoplay. The script exits non-zero if any check fails.

See the ``experiment.py`` docstring for the transitions being checked.
"""

import csv
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

COMPONENT_TOKEN = "component-js-vars-ok"
LEAVE_EVERY = 8
LEAVE_REMAINDER = 3

SAME = "same document"
NEW = "new document"

# How each probed step's document should relate to the previous probed step's.
EXPECTED_DOCUMENT = {
    "lt_component": SAME,
    "lt_choices": SAME,
    "lt_after_wait": SAME,
    "lt_audio": SAME,
    "lt_after_audio": SAME,
    "lt_full_reload": NEW,
    "lt_after_full_reload": NEW,
    "lt_after_jspsych": NEW,
    "lt_leave_request": SAME,
    "lt_final": SAME,
}

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


def load_records(responses):
    """Return {participant_id: [(question, lifecycle, answer), ...]} in response order."""
    by_participant = defaultdict(list)
    for row in sorted(responses, key=lambda r: int(r["id"])):
        if not row["question"].startswith("lt_"):
            continue
        metadata = json.loads(row["metadata_"] or "{}")
        answer = json.loads(row["answer"]) if row["answer"] else None
        by_participant[int(row["participant_id"])].append(
            (row["question"], metadata.get("lifecycle"), answer)
        )
    return by_participant


def jspsych_document_id(answer):
    data = json.loads(answer) if isinstance(answer, str) else answer
    return data[0].get("lifecycle_document_id") if data else None


def check_transitions(records):
    failures, reloads = [], []
    for pid, rows in records.items():
        previous = None
        jspsych_doc = None
        for question, lifecycle, answer in rows:
            if question == "lt_jspsych":
                jspsych_doc = jspsych_document_id(answer)
                if previous and jspsych_doc == previous["document_id"]:
                    failures.append(pid)
                continue
            if lifecycle is None:
                continue
            expected = EXPECTED_DOCUMENT.get(question)
            if previous and expected:
                same = lifecycle["document_id"] == previous["document_id"]
                if expected == SAME and not same:
                    if lifecycle["navigation_type"] in ("reload", "back_forward"):
                        reloads.append(pid)
                    else:
                        failures.append(pid)
                elif expected == NEW and same:
                    failures.append(pid)
            if (
                question == "lt_after_jspsych"
                and jspsych_doc == lifecycle["document_id"]
            ):
                failures.append(pid)
            previous = lifecycle
    check(
        "document kept or replaced as expected at each transition",
        failures,
        reloads,
        "(WARN: participant reloaded the page)" if reloads and not failures else "",
    )


def check_per_record(records):
    probed = {
        pid: [(q, lc) for q, lc, _ in rows if lc is not None]
        for pid, rows in records.items()
    }
    probed = {pid: rows for pid, rows in probed.items() if rows}

    missing = [pid for pid, rows in records.items() if pid not in probed]
    check("every participant with lt_ responses submitted lifecycle records", missing)

    check(
        "js_dependencies ran once per document",
        [
            pid
            for pid, rows in probed.items()
            if any(lc["dependency_executions"] != 1 for _, lc in rows)
        ],
    )
    check(
        "page modules activated once per page",
        [
            pid
            for pid, rows in probed.items()
            if any(lc["activations_of_this_page"] != 1 for _, lc in rows)
        ],
    )

    module_mismatch = []
    for pid, rows in probed.items():
        instances = defaultdict(set)
        for _, lc in rows:
            instances[lc["document_id"]].add(lc["module_instance"])
        if any(len(v) > 1 for v in instances.values()):
            module_mismatch.append(pid)
    check("page module evaluated once per document", module_mismatch)

    check(
        "psynet.var belongs to the current page",
        [pid for pid, rows in probed.items() if any(lc["step"] != q for q, lc in rows)],
    )
    check(
        "page stylesheet applies only to its own page",
        [
            pid
            for pid, rows in probed.items()
            if any(lc["page_style_applied"] != (q == "lt_component") for q, lc in rows)
        ],
    )
    check(
        "component get_js_vars reaches only its own page",
        [
            pid
            for pid, rows in probed.items()
            if any(
                lc["component_token"]
                != (COMPONENT_TOKEN if q == "lt_component" else None)
                for q, lc in rows
            )
        ],
    )

    silent, still_playing = [], []
    for pid, rows in probed.items():
        by_step = dict(rows)
        audio, after = by_step.get("lt_audio"), by_step.get("lt_after_audio")
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

    layout = defaultdict(lambda: defaultdict(int))
    for pid, rows in probed.items():
        device = "touch" if rows[0][1]["touch"] else "no-touch"
        for q, lc in rows:
            for violation in lc["layout_violations"] or []:
                layout[(q, device)][violation] += 1
    if layout:
        detail = "; ".join(
            f"{q} [{device}] {dict(counts)}"
            for (q, device), counts in sorted(layout.items())
        )
        report("WARN", "psynetLayout violations", detail)
    else:
        report("PASS", "psynetLayout violations", "none")

    return probed


def check_server_side(export_dir, records, participants, probed):
    by_id = {int(p["id"]): p for p in participants}

    reached_wait = [
        pid
        for pid, rows in records.items()
        if any(q == "lt_after_wait" for q, _, _ in rows)
    ]
    check(
        "AsyncCodeBlock finished before lt_after_wait",
        [
            pid
            for pid in reached_wait
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
    reached_asset = [
        pid
        for pid, rows in records.items()
        if any(q == "lt_after_jspsych" for q, _, _ in rows)
    ]
    bad_assets = []
    for pid in reached_asset:
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

    asked = [pid for pid in records if pid % LEAVE_EVERY == LEAVE_REMAINDER]
    left = [pid for pid in asked if by_id[pid]["early_exited"] == "True"]
    pressed_next = [
        pid for pid in asked if any(q == "lt_final" for q, _, _ in records[pid])
    ]
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
        statuses[p["status"]].append(int(p["id"]))
    report("INFO", "participant statuses", json.dumps(dict(statuses), sort_keys=True))

    devices = defaultdict(int)
    for pid, rows in records.items():
        for q, _, answer in rows:
            if q == "lt_choices" and answer is not None:
                devices[str(answer)] += 1
    touch = sum(1 for rows in probed.values() if rows[0][1]["touch"])
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
    participants = read_table(export_dir, "participant")
    # Bots do not run JavaScript, so they cannot submit lifecycle records.
    bots = {int(p["id"]) for p in participants if p["type"].endswith(".Bot")}
    records = {
        pid: rows for pid, rows in load_records(responses).items() if pid not in bots
    }
    if not records:
        report(
            "FAIL",
            "export contains lt_ responses from non-bot participants",
            str(export_dir),
        )
        return 1

    check_transitions(records)
    probed = check_per_record(records)
    check_server_side(export_dir, records, participants, probed)
    return 1 if "FAIL" in results else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
