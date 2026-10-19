import json

from dominate import tags

import psynet.experiment
from psynet.page import InfoPage, JsPsychPage
from psynet.timeline import PageMaker, Timeline

JSPSYCH = "static/jspsych/jspsych.js"
HTML_KEYBOARD_PLUGIN = "static/jspsych/plugin-html-keyboard-response.js"
JSPSYCH_CSS = ["static/jspsych/jspsych.css"]


def display_answer(answer):
    prompt = tags.div()
    with prompt:
        tags.p("The jsPsych page generated the following output: ")
        tags.pre(json.dumps(answer, indent=4))
    return InfoPage(prompt)


class Exp(psynet.experiment.Experiment):
    label = "jsPsych demo"

    timeline = Timeline(
        InfoPage("A quick jsPsych task begins on the next page.", time_estimate=1),
        JsPsychPage(
            "quick_task",
            timeline="/static/quick-timeline.js",
            time_estimate=1,
            js_dependencies=[JSPSYCH, HTML_KEYBOARD_PLUGIN],
            css_links=JSPSYCH_CSS,
            bot_response=None,
        ),
        InfoPage(
            "The quick jsPsych task completed. The main task begins next.",
            time_estimate=1,
        ),
        JsPsychPage(
            "reaction_time_task",
            timeline="/static/reaction-time-task.js",
            time_estimate=25,
            js_vars={
                "trial_durations": [250, 500, 750, 1000, 1250, 1500, 1750, 2000],
                "welcome_message": "Welcome to the experiment. Press any key to begin.",
            },
            js_dependencies=[
                JSPSYCH,
                HTML_KEYBOARD_PLUGIN,
                "static/jspsych/plugin-image-keyboard-response.js",
                "static/jspsych/plugin-preload.js",
            ],
            css_links=JSPSYCH_CSS,
            bot_response=None,
        ),
        PageMaker(
            lambda participant: display_answer(participant.answer), time_estimate=5
        ),
    )
