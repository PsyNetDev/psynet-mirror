"""Real task lifecycle coverage with a lightweight Unity engine stand-in."""

from pathlib import Path

from dallinger.experiment import experiment_route
from flask import abort, jsonify, send_file

import psynet.experiment
from psynet.db import with_transaction
from psynet.page import InfoPage, JsPsychPage, UnityPage
from psynet.timeline import Timeline
from psynet.trial.record import Recording


class Exp(psynet.experiment.Experiment):
    label = "Task background capture"

    @experiment_route("/test-jspsych/<name>")
    @staticmethod
    def jspsych_library(name):
        """Use the repo's vendored jsPsych instead of duplicating its library."""
        if name not in {"jspsych.js", "plugin-html-keyboard-response.js"}:
            abort(404)
        root = Path(__file__).resolve().parents[4]
        return send_file(root / "demos/experiments/jspsych/static/jspsych" / name)

    @experiment_route("/test-capture-state")
    @staticmethod
    @with_transaction
    def capture_state():
        """Expose original page identity and capture outcome in this fixture only."""
        return jsonify(
            [
                {**asset.recording_summary, "id": asset.id}
                for asset in Recording.query.order_by(Recording.id).all()
            ]
        )

    timeline = Timeline(
        UnityPage(
            "First task",
            "/static/unity",
            {"step": 1},
            "shared",
            time_estimate=1,
            background_recording="camera",
        ),
        UnityPage(
            "Second task",
            "/static/unity",
            {"step": 2},
            "shared",
            time_estimate=1,
            background_recording="camera",
        ),
        JsPsychPage(
            "keyboard_task",
            "/static/task.js",
            1,
            [
                "/test-jspsych/jspsych.js",
                "/test-jspsych/plugin-html-keyboard-response.js",
            ],
            [],
            background_recording="camera",
        ),
        InfoPage("Tasks complete.", time_estimate=1),
    )
