# pylint: disable=abstract-method

from typing import TYPE_CHECKING, Type

if TYPE_CHECKING:
    from psynet.asset import Asset
    from psynet.trial.main import TrialNode

import copy
import inspect
import json
import random
import re
import time
import warnings
from collections import Counter
from datetime import datetime
from functools import cached_property
from importlib import resources
from statistics import median
from types import FunctionType
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Sequence, Union

from bs4 import BeautifulSoup
from dallinger import db
from dominate import tags
from jsonpickle.util import importable_name
from markupsafe import Markup
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm import backref, relationship
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.orm.collections import attribute_mapped_collection

from . import templates
from .data import SQLBase, SQLMixin, register_table
from .field import PythonObject
from .serialize import is_lambda_function, prepare_function_for_serialization
from .utils import (
    NoArgumentProvided,
    call_function,
    call_function_with_context,
    format_datetime,
    get_args,
    get_language_dict,
    get_locale,
    get_logger,
    log_time_taken,
    merge_dicts,
    pretty_format_seconds,
    render_string_with_translations,
    serialise,
    unserialise_datetime,
)

if TYPE_CHECKING:
    from .participant import Participant

logger = get_logger()


def _normalize_javascript_urls(urls, argument_name):
    """Validate and normalize a list of JavaScript resource URLs."""
    if urls is None:
        return []
    if not isinstance(urls, (list, tuple)):
        raise TypeError(f"{argument_name} must be a list or tuple.")

    normalized = []
    seen = set()
    for url in urls:
        if not isinstance(url, str):
            raise TypeError(f"{argument_name} entries must be strings.")
        if not url.strip():
            raise ValueError(f"{argument_name} entries must be non-empty.")
        url = url.strip()
        if url not in seen:
            normalized.append(url)
            seen.add(url)
    return normalized


def _normalize_js_page_code(code, argument_name="js_page_code"):
    """Validate and normalize inline page activation code."""
    if code is None:
        return []
    if isinstance(code, str):
        code = [code]
    elif not isinstance(code, (list, tuple)):
        raise TypeError(f"{argument_name} must be a string, list, or tuple.")

    normalized = []
    for item in code:
        if not isinstance(item, str):
            raise TypeError(f"{argument_name} entries must be strings.")
        if not item.strip():
            raise ValueError(f"{argument_name} entries must be non-empty.")
        normalized.append(item)
    return normalized


# Common Window names that legacy ``window.<js_vars key>`` access would
# silently read instead of the page value. Not exhaustive; authors should
# still prefer ``psynet.var``.
_JS_VAR_WINDOW_COLLISION_KEYS = frozenset(
    {
        "alert",
        "closed",
        "confirm",
        "console",
        "crypto",
        "document",
        "event",
        "fetch",
        "frames",
        "history",
        "length",
        "localStorage",
        "location",
        "name",
        "navigator",
        "opener",
        "origin",
        "parent",
        "performance",
        "prompt",
        "screen",
        "self",
        "sessionStorage",
        "status",
        "top",
        "window",
    }
)


def _warn_js_var_window_collisions(js_vars):
    """Warn when js_vars keys would not get a legacy window accessor."""
    if not js_vars:
        return
    collisions = sorted(key for key in js_vars if key in _JS_VAR_WINDOW_COLLISION_KEYS)
    if not collisions:
        return
    names = ", ".join(repr(key) for key in collisions)
    warnings.warn(
        "js_vars keys collide with existing window properties "
        f"({names}). Legacy window.<key> reads will not see the page "
        "value; use psynet.var instead. Common collisions include "
        "name, status, event, and history.",
        UserWarning,
        stacklevel=3,
    )


class Event(dict):
    """
    Defines an event that occurs on the front-end for a given page.
    This event is triggered once custom conditions are satisfied;
    it can then trigger future events to occur.
    One can define custom JS code to be run when these events execute
    in one of two ways.
    One approach is to register this custom JS code by writing something
    like this:

    ::

        psynet.trial.onEvent("myEventId", function() {
            // custom code goes here
        });

    A second approach is to add JS code directly to the ``js`` argument
    of the present function.

    The resulting object should be passed to the ``events`` parameter in
    :class:`~psynet.timeline.Page`.

    Parameters
    ----------

    is_triggered_by:
        Defines the triggers for the present event.
        A trigger can be specified either as a string corresponding to an event ID,
        for example ``"trialStart"``, or as an object of class :class:`~psynet.timeline.Trigger`.
        The latter case is more flexible because it allows a particular trigger to be delayed
        by a specified number of seconds.
        Multiple triggers can be defined by instead passing a list of these strings
        or :class:`~psynet.timeline.Trigger` objects.
        Alternatively, one can pass ``None``, in which case the event won't be triggered automatically,
        but instead will only be triggered if/when ``psynet.trial.registerEvent`` is called
        in the Javascript front-end.

    trigger_condition:
        If this is set to ``"all"`` (default), then all triggers must be satisfied before the
        event will be cued. If this is set to ``"any"``, then the event will be cued when
        any one of these triggers occurred.

    delay:
        Determines the time interval (in seconds) between the trigger condition being satisfied
        and the event being triggered (default = 0.0).

    once:
        If ``True``, then the event will only be cued once, at the point when the
        trigger condition is first satisfied. If ``False`` (default), then the event will be recued
        each time one of the triggers is hit again.

    message:
        Optional message to display when this event occurs (default = ``""``).

    message_color:
        CSS color specification for the message (default = ``"black"``).

    js:
        Optional Javascript code to execute when the event occurs (default = ``None``).

    """

    def __init__(
        self,
        is_triggered_by,
        trigger_condition: str = "all",
        delay: float = 0.0,
        once: bool = False,
        message: Optional[str] = None,
        message_color: str = "black",
        js: Optional[str] = None,
    ):
        if is_triggered_by is None:
            is_triggered_by = []
        elif not isinstance(is_triggered_by, list):
            is_triggered_by = [is_triggered_by]

        is_triggered_by = [
            x if isinstance(x, Trigger) else Trigger(x) for x in is_triggered_by
        ]

        super().__init__(
            is_triggered_by=is_triggered_by,
            trigger_condition=trigger_condition,
            delay=delay,
            once=once,
            message=message,
            message_color=message_color,
            js=js,
        )

    def add_trigger(self, trigger, **kwargs):
        if isinstance(trigger, str):
            t = Trigger(triggering_event=trigger, **kwargs)
        elif isinstance(trigger, Trigger):
            t = trigger
        else:
            raise ValueError("trigger must be an object of class str or Trigger.")
        self["is_triggered_by"].append(t)

    def add_triggers(self, *args):
        for arg in args:
            self.add_trigger(arg)


class Trigger(dict):
    def __init__(self, triggering_event, delay=0.0):
        assert isinstance(triggering_event, str)
        super().__init__(triggering_event=triggering_event, delay=float(delay))


def get_template(name):
    assert isinstance(name, str)
    path_all_templates = resources.files(templates)
    path_template = path_all_templates.joinpath(name)
    with open(path_template, "r") as file:
        return file.read()


class Elt:
    returns_time_credit = False
    time_estimate = None
    expected_repetitions = None
    id = None
    created_within_page_maker = False

    def __init__(self):
        self.links = {}

    def consume(self, experiment, participant):
        raise NotImplementedError

    def render(self, experiment, participant):
        raise NotImplementedError

    def multiply_expected_repetitions(self, factor):
        # pylint: disable=unused-argument
        if self.expected_repetitions is not None:
            self.expected_repetitions *= factor


class EltCollection:
    def resolve(self) -> Union[Elt, List[Elt]]:
        raise NotImplementedError


WEBSOCKET_CHANNEL = "psynet_experiment"
"""Global Redis channel set on the experiment when any ``WebSocketElt`` is
present.

The experiment will activate a subscription to this channel and Dallinger's
automatic ``dallinger_control`` subscription, giving the experiment visibility
into websocket connect/disconnect/subscribe events. Experiments that want to
send or receive messages on this channel directly may do so, but it is not used
for ``WebSocketElt`` dispatch by default.
"""


class WebSocketElt(Elt):
    """
    A timeline element that registers a WebSocket message handler on the
    experiment.

    Adding a ``WebSocketElt`` to the timeline will:

    1. Subscribe the experiment to ``WebSocketElt.channel`` at launch, enabling
       it to receive WebSocket messages on that channel.
    2. Register ``handle_message`` as a handler called by the experiment's
       ``receive_message`` whenever a message arrives on that channel.

    Each ``WebSocketElt`` subclass should define a unique ``channel`` name so
    that multiple Websocket consumers in the same timeline can remain isolated
    from one another.

    Example::

        from psynet.timeline import WebSocketElt

        class RoundOneChatElt(WebSocketElt):
            channel = "chat_round_one"

            def handle_message(self, message, channel_name, participant, node,
                               receive_time, experiment):
                import json
                data = json.loads(message)
                # ... process data ...

    Attributes
    ----------
    channel : str
        The Redis channel name this Elt subscribes to. If ``None``, no
        subscribers will be registered.
    """

    channel = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def consume(self, experiment, participant):
        super().consume(experiment, participant)

    def render(self, experiment, participant):
        return super().render(experiment, participant)

    def handle_message(
        self, message, channel_name, participant, node, receive_time, experiment
    ):
        """Called when a WebSocket message arrives on this element's channel.

        Subclasses must override this method.

        Parameters
        ----------
        message : str
            The raw message string (typically JSON).
        channel_name : str
            The name of the channel the message was received on.
        participant : Participant or None
            The participant associated with the message, if any.
        node : Node or None
            The node associated with the message, if any.
        receive_time : datetime.datetime or None
            The server time the message was received.
        experiment : Experiment
            The running experiment instance.
        """
        raise NotImplementedError


class NullElt(Elt):
    def consume(self, experiment, participant):
        pass

    def render(self, experiment, participant):
        pass


class CodeBlock(Elt):
    """
    A timeline component that executes some back-end logic without showing
    anything to the participant.

    Parameters
    ----------

    function:
        A function with up to two arguments named ``participant`` and ``experiment``,
        that is executed once the participant reaches the corresponding part of the timeline.
    """

    def __init__(self, function: Callable):
        super().__init__()
        self.function = function

    def consume(self, experiment, participant):
        """
        Executes the code block's function synchronously.

        Parameters
        ----------
        experiment : ``Experiment``
            The current experiment instance.
        participant : ``Participant``
            The current participant instance.
        """
        call_function_with_context(
            self.function,
            self=self,
            code_block=self,
            experiment=experiment,
            participant=participant,
        )


class AsyncCodeBlock(EltCollection):
    """
    A version of CodeBlock that executes its function asynchronously.

    Parameters
    ----------

    function:
        A function with up to two arguments named ``participant`` and ``experiment``.

    wait:
        If ``True``, then the participant will be held on a wait page until the function has finished.
        If ``False``, the participant will proceed immediately, and the function will execute in the background.

    expected_wait:
        Only relevant if ``wait=True``; corresponds to the time we expect the participant to wait on the wait page.

    check_interval:
        Only relevant if ``wait=True``; corresponds to the time between checks we make to see if the function has finished.
    """

    def __init__(
        self,
        function: Callable,
        wait: bool = True,
        expected_wait: Optional[float] = None,
        check_interval: float = 0.5,
    ):
        if is_lambda_function(function):
            raise ValueError(
                "Asynchronous code blocks require named functions rather than lambda functions."
            )

        if wait and expected_wait is None:
            raise ValueError(
                "Asynchronous code blocks must be specified with an expected wait time unless wait=False."
            )

        if inspect.ismethod(function):
            raise ValueError(
                "Sorry, but AsyncCodeBlocks currently do not support instance methods or class methods. "
                "Please make your method a static method instead."
            )

        self.function = function
        self.wait = wait
        self.expected_wait = expected_wait
        self.check_interval = check_interval

    def resolve(self):
        return join(
            CodeBlock(self.initiate),
            self.wait_logic() if self.wait else [],
            CodeBlock(self.wrap_up),
        )

    def initiate(self, participant, code_block):
        from psynet.process import WorkerAsyncProcess

        code_block_id = code_block.id
        stale = participant.awaited_async_code_block_process
        if stale is not None:
            if stale.pending and not stale.failed:
                if self.wait and self.matches_pending_process(stale, code_block_id):
                    logger.warning(
                        "Participant %s already has an async code block process "
                        "(id=%s) pending; waiting for the existing process instead "
                        "of starting a duplicate.",
                        participant.id,
                        stale.id,
                    )
                    return
                raise RuntimeError(
                    "Participant already has an async code block process pending, this shouldn't happen."
                )
            # The previous process finished (successfully or with failure) but its
            # ``wrap_up`` was never executed -- e.g. the participant was rerouted
            # off the wait page (back button, dashboard force_advance, recruiter
            # rejection flow re-entering an AsyncCodeBlock, ...). Rather than
            # leaving the participant permanently stuck, clear the stale
            # reference and start a fresh process.
            logger.warning(
                "Participant %s already had a %s async code block process "
                "(id=%s) attached when initiating a new one; clearing the "
                "stale reference and continuing.",
                participant.id,
                "failed" if stale.failed else "finished",
                stale.id,
            )
            participant.awaited_async_code_block_process = None

        participant.awaited_async_code_block_process = WorkerAsyncProcess(
            call_function_with_context,
            label="AsyncCodeBlock",
            participant=participant,
            arguments=dict(
                function=self.function,
                participant=participant,
                code_block_id=code_block_id,
            ),
        )

    def matches_pending_process(self, process, code_block_id):
        try:
            pending_function = process.arguments["function"]
            pending_code_block_id = process.arguments["code_block_id"]
        except (KeyError, TypeError):
            return False

        return pending_code_block_id == code_block_id and self.function_key(
            pending_function
        ) == self.function_key(self.function)

    @staticmethod
    def function_key(function):
        function, _ = prepare_function_for_serialization(function, {})
        return importable_name(function)

    def wait_logic(self):
        from .page import wait_while

        return join(
            wait_while(
                condition=lambda participant: not self.process_is_finished(participant),
                expected_wait=self.expected_wait,
                check_interval=self.check_interval,
                log_message="Waiting for async code block to finish.",
            ),
            CodeBlock(lambda: logger.info("Finished waiting for async code block.")),
        )

    def process_is_finished(self, participant):
        process = participant.awaited_async_code_block_process
        if process.failed:
            raise RuntimeError("The awaited async code block process failed.")
        assert process.finished or process.pending
        return process.finished

    def wrap_up(self, participant):
        participant.awaited_async_code_block_process = None


class StartFixElt(Elt):
    """
    This class is not to be used directly; use instead
    ``with_fixed_time_credit`` and ``with_fixed_progress``.
    """

    def __init__(self, time_credit: float, end_fix: "EndFixElt"):
        super().__init__()
        self.time_credit = time_credit
        self.expected_repetitions = 1
        self.end_fix = end_fix


class EndFixElt(Elt):
    def __init__(self, time_credit: float):
        super().__init__()
        self.time_credit = time_credit
        self.expected_repetitions = 1


class StartFixTimeCredit(StartFixElt):
    """
    This class is not to be used directly; use instead
    ``with_fixed_time_credit`` and ``with_fixed_progress``.
    """

    def consume(self, experiment, participant):
        bound = participant.time_credit + self.time_credit
        participant.time_credit_fixes.append(bound)


class EndFixTimeCredit(EndFixElt):
    """
    This class is not to be used directly; use instead
    ``with_fixed_time_credit`` and ``with_fixed_progress``.
    """

    def consume(self, experiment, participant):
        participant.time_credit = participant.time_credit_fixes.pop()


class StartFixProgress(StartFixElt):
    """
    This class is not to be used directly; use instead
    ``with_fixed_time_credit`` and ``with_fixed_progress``.
    """

    def consume(self, experiment, participant: "Participant"):
        if participant.estimated_max_time_credit == 0.0:
            new_bound = 1.0
        else:
            try:
                old_bound = participant.progress_fixes[-1]
            except IndexError:
                old_bound = 1.0

            new_bound = (
                participant.progress
                + self.time_credit / participant.estimated_max_time_credit
            )
            new_bound = min(new_bound, old_bound)

        participant.progress_fixes.append(new_bound)


class EndFixProgress(EndFixElt):
    """
    This class is not to be used directly; use instead
    ``with_fixed_time_credit`` and ``with_fixed_progress``.
    """

    def consume(self, experiment, participant):
        participant.progress = participant.progress_fixes.pop()


class GoTo(Elt):
    def __init__(self, target: Union[Elt, str, callable]):
        super().__init__()
        self.target = target

    def get_target(self, experiment, participant):
        # pylint: disable=unused-argument
        return self.target

    def consume(self, experiment, participant):
        target_elt = self.get_target(experiment, participant)
        participant.elt_id = target_elt.id
        # We subtract 1 because elt_id will be incremented again when
        # we return to the start of the advance page loop.
        # Remember that ``elt_id`` corresponds to a nested representation,
        # where each element corresponds to successively deeper and deeper
        # levels of page makers.
        # We therefore perform our subtraction to the last element
        # of the list.
        participant.elt_id[-1] -= 1


# Todo - remove ReactiveGoTo and move its code into Switch
class ReactiveGoTo(GoTo):
    def __init__(
        self,
        function,  # function taking experiment, participant and returning a key
        targets,  # dict of possible target elements
    ):
        # pylint: disable=super-init-not-called
        super().__init__(target=None)
        self.function = function
        self.targets = targets
        self.check_args()

    def check_args(self):
        self.check_targets()

    def check_targets(self):
        try:
            assert isinstance(self.targets, dict)
            for target in self.targets.values():
                assert isinstance(target, Elt)
        except AssertionError:
            raise TypeError("<targets> must be a dictionary of Elt objects.")

    def get_target(self, experiment, participant):
        val = call_function_with_context(
            self.function,
            self=self,
            experiment=experiment,
            participant=participant,
        )
        try:
            return self.targets[val]
        except KeyError:
            raise ValueError(
                f"ReactiveGoTo returned {val}, which is not present among the target keys: "
                + f"{list(self.targets)}."
            )


class MediaSpec:
    """
    This object enumerates the media assets available for a given
    :class:`~psynet.timeline.Page` object.

    Parameters
    ----------

    audio: dict
        A dictionary of audio assets.
        Each item can either be a string,
        corresponding to the URL for a single file (e.g. "/static/audio/test.wav"),
        or a dictionary, corresponding to metadata for a batch of media assets.
        A batch dictionary must contain the field "url", providing the URL to the batch file,
        and the field "ids", providing the list of IDs for the batch's constituent assets.
        A valid audio argument might look like the following:

        ::

            {
                'bier': '/static/bier.wav',
                'my_batch': {
                    'url': '/static/file_concatenated.mp3',
                    'ids': ['funk_game_loop', 'honey_bee', 'there_it_is'],
                    'type': 'batch'
                }
            }

    html: dict
        An analogously structured dictionary of HTML stimuli (e.g., SVG stimuli).

    image: dict
        An analogously structured dictionary of image stimuli.

    video: dict
        An analogously structured dictionary of video stimuli.
    """

    modalities = ["audio", "image", "html", "video"]

    def __init__(
        self,
        audio: Optional[dict] = None,
        image: Optional[dict] = None,
        html: Optional[dict] = None,
        video: Optional[dict] = None,
    ):
        from .asset import Asset

        if audio is None:
            audio = {}

        if image is None:
            image = {}

        if html is None:
            html = {}

        if video is None:
            video = {}

        self.data = {"audio": audio, "image": image, "html": html, "video": video}

        for modality in self.data.values():
            for key, value in modality.items():
                if isinstance(value, Asset):
                    modality[key] = value.url
                elif isinstance(value, dict):
                    for _key, _value in value.items():
                        if isinstance(_value, Asset):
                            value[_key] = _value.url

        assert list(self.data) == self.modalities

    @property
    def audio(self):
        return self.data["audio"]

    @property
    def image(self):
        return self.data["image"]

    @property
    def html(self):
        return self.data["html"]

    @property
    def video(self):
        return self.data["video"]

    @property
    def ids(self):
        res = {}
        for media_type, media in self.data.items():
            res[media_type] = set()
            for key, value in media.items():
                if isinstance(value, str):
                    res[media_type].add(key)
                else:
                    assert isinstance(value, dict)
                    res[media_type].update(value["ids"])
        return res

    @property
    def num_files(self):
        counter = 0
        for modality in self.data.values():
            counter += len(modality)
        return counter

    def add(self, modality: str, entries: dict):
        if modality not in self.data:
            self.data[modality] = {}
        for key, value in entries.items():
            self.data[modality][key] = value

    @classmethod
    def merge(self, *args, overwrite: bool = False):
        if len(args) == 0:
            return MediaSpec()

        new_args = {}
        for modality in self.modalities:
            new_args[modality] = merge_dicts(
                *[x.data[modality] for x in args], overwrite=overwrite
            )

        return MediaSpec(**new_args)

    def check(self):
        assert isinstance(self.data, dict)
        for key, value in self.data.items():
            assert key in self.modalities
            ids = set()
            for file_id, file in value.items():
                if file_id in ids:
                    raise ValueError(
                        f"{file_id} occurred more than once in page's {key} specification."
                    )
                ids.add(file_id)
                if not isinstance(file, str):
                    if not isinstance(file, dict):
                        raise TypeError(
                            f"Media entry must either be a string URL or a dict (got {file})."
                        )
                    if not ("url" in file and "ids" in file):
                        raise ValueError(
                            "Batch specifications must contain both 'url' and 'ids' keys."
                        )
                    batch_ids = file["ids"]
                    if not isinstance(batch_ids, list):
                        raise TypeError(
                            f"The ids component of the batch specification must be a list (got {ids})."
                        )
                    for _id in batch_ids:
                        if not isinstance(_id, str):
                            raise TypeError(
                                f"Each id in the batch specification must be a string (got {_id})."
                            )
                        ids.add(_id)

    def to_json(self):
        return json.dumps(self.data)


class ProgressStage(dict):
    def __init__(
        self,
        time: Union[float, int, List],
        caption: str = "",
        color: str = "rgb(49, 124, 246)",
        persistent: bool = False,
    ):
        if isinstance(time, list):
            duration = time[1] - time[0]
        else:
            duration = time

        self["time"] = time
        self["duration"] = duration
        self["caption"] = caption
        self["color"] = color
        self["persistent"] = persistent


class ProgressDisplay(dict):
    def __init__(
        self,
        stages: List,
        start="trialStart",
        show_bar: bool = True,
        show_caption: bool = True,
        **kwargs,
    ):
        self.consolidate_stages(stages)

        if len(stages) == 0:
            _duration = 0.0
        else:
            last_stage = stages[-1]
            _duration = last_stage["time"][1]

        self["duration"] = _duration
        self["start"] = start
        self["show_bar"] = show_bar
        self["show_caption"] = show_caption
        self["stages"] = stages

        self.validate()

        if "duration" in kwargs:
            logger.warning(
                "ProgressDisplay no longer takes a 'duration' argument, please remove it."
            )
            del kwargs["duration"]

        if (len(kwargs)) > 0:
            logger.warning(
                "The following unrecognized arguments were passed to ProgressDisplay: "
                + ", ".join(list(kwargs))
            )

    def consolidate_stages(self, stages):
        """
        Goes through the list of stages, and whenever the ``time`` argument
        is a single number, replaces this argument with a pair of numbers
        corresponding to the computed start time and end time for that stage.
        """
        _start_time = 0.0
        for s in stages:
            if not isinstance(s["time"], list):
                _duration = s["time"]
                _end_time = _start_time + _duration
                s["time"] = [_start_time, _end_time]
            _end_time = s["time"][1]
            _start_time = _end_time

    def validate(self):
        stages = self["stages"]
        for i, stage in enumerate(stages):
            start_time = stage["time"][0]
            if i == 0:
                if start_time != 0.0:
                    raise ValueError(
                        "The first stage in the progress bar must have a start time of 0.0."
                    )
            else:
                prev_stage = stages[i - 1]
                prev_stage_end_time = prev_stage["time"][1]
                if start_time != prev_stage_end_time:
                    raise ValueError(
                        f"The start time of stages[{i}] did not match the end time of the previous stage."
                    )
            if i == len(stages) - 1:
                end_time = stage["time"][1]
                if end_time != self["duration"]:
                    raise ValueError(
                        "The final stage must have an end time equal to the progress bar's duration."
                    )


_SPA_UPGRADE_DOCS_URL = (
    "https://psynetdev.gitlab.io/PsyNet/whats_new/upgrading_to_psynet_14.html"
)

# Stable footer for author-facing SPA errors; HTTP extractors match on this.
_SPA_INCOMPATIBILITY_MARKER = "[psynet-spa-incompatibility]"


def _format_spa_incompatibility_message(page_label, codes):
    """Build the author-facing SPA incompatibility message.

    Keep this short: plain-language reload consequence, stable error codes,
    and migrate-first vs per-page / experiment-wide opt-out.
    """
    unique_codes = list(dict.fromkeys(codes))
    codes_text = ", ".join(unique_codes)
    tips = []
    if "window_listener_no_cleanup" in unique_codes:
        tips.append(
            "For window_listener_no_cleanup, register cleanup PsyNet can see: "
            "return () => { ... } or return function cleanup() { ... } from "
            "js_page_code / activate(), or use psynet.addPageCleanupCallback(...) "
            "/ psynet.addPageEventListener(...). Returning another function "
            "reference (for example return teardown) is not detected."
        )
    tip_text = ("\n\n" + "\n".join(tips)) if tips else ""
    return (
        f"Page '{page_label}' uses HTML/JS that needs a full browser reload "
        f"between pages (error codes: {codes_text}).\n\n"
        "Ideally, PsyNet pages are designed to support in-place loading, "
        "which creates a smoother user experience. However, this is not "
        "compulsory.\n\n"
        "What would you like to do?\n"
        "1. Update this page to support in-place loading:\n"
        f"   {_SPA_UPGRADE_DOCS_URL}\n"
        "   (or in Cursor, run /upgrade-to-psynet-14)\n"
        "2. Leave the HTML/JS as is, and allow full reloads for this page by "
        "passing requires_full_page_reload=True to the Page or ModularPage "
        "constructor (or set inplace_timeline_transitions = false in "
        "config.txt for a temporary experiment-wide opt-out)"
        f"{tip_text}\n"
        f"{_SPA_INCOMPATIBILITY_MARKER}"
    )


# Accept only zero-arg arrow cleanups or an explicitly named cleanup function.
# Broader patterns like ``return (x) =>`` are ordinary returns, not SPA cleanup.
_SPA_CLEANUP_RETURN_RE = re.compile(
    r"\breturn\s+(?:async\s+)?(?:function\s+cleanup\b|\(\s*\)\s*=>)"
)


class Page(Elt):
    """
    The base class for pages, customised by passing values to the ``__init__``
    function and by overriding the following methods:

    * :meth:`~psynet.timeline.Page.format_answer`
    * :meth:`~psynet.timeline.Page.validate`
    * :meth:`~psynet.timeline.Page.metadata`

    Parameters
    ----------

    time_estimate:
        Time estimated for the page.

    template_path:
        Path to the jinja2 template to use for the page.

    template_str:
        Alternative way of specifying the jinja2 template as a string.

    template_fragment_path:
        Path to a jinja2 template containing only the contents of the timeline
        page's ``main_body`` block. This is the recommended custom-template
        style for pages used with ``inplace_timeline_transitions``.

    template_fragment_str:
        Alternative way of specifying a main-body template fragment as a string.

    framework_owned_template:
        Internal marker for PsyNet-owned templates. Framework pages may still
        use complete templates in SPA mode because PsyNet controls their page
        shell and lifecycle; experiment-authored complete templates should use
        ``template_fragment_path`` or ``template_fragment_str`` for SPA.

    requires_full_page_reload:
        If ``True``, this page always uses a full browser reload rather than an
        in-place transition. Use this as a per-page opt-out while migrating
        older custom frontends. Deprecated ``js_links`` / ``scripts`` also set
        this automatically. Default: ``False``.

    template_arg:
        Dictionary of arguments to pass to the jinja2 template.

    label:
        Internal label to give the page, used for example in results saving.

    js_vars:
        Dictionary of page-scoped values exposed to JavaScript through
        ``psynet.var``. Legacy access through matching ``window`` properties is
        deprecated and controlled by ``legacy_js_var_globals``.

    js_links:
        Deprecated list of classic JavaScript files executed as linked classic
        scripts. Using this argument forces a full page reload. Prefer
        ``js_dependencies`` or ``js_page_modules``.

    js_dependencies:
        Optional list of JavaScript file URLs to load once per browser document.

    js_page_modules:
        Optional JavaScript files activated for each page. Each file must export
        an ``activate(context)`` function and may return a cleanup function.

    js_page_code:
        Optional inline JavaScript activation code, supplied as a string, list,
        or tuple. Code receives the same ``root``, ``trial``, ``vars``, ``page``,
        and ``psynet`` values as a page module and may return cleanup.

    media: :class:`psynet.timeline.MediaSpec`
        Optional specification of media assets to preload
        (see the documentation for :class:`psynet.timeline.MediaSpec`).

    scripts:
        Deprecated classic inline JavaScript executed with global script
        semantics. Using this argument forces a full page reload. Prefer
        ``js_page_code``.

    css:
        Optional list of CSS specification to include in the page.
        Each specification should be represented as a string, which will be passed
        verbatim to the page's HTML.
        A valid CSS specification might look like this:

        ::

            .modal-content {
                background-color: #4989C8;
                margin: auto;
                padding: 20px;
                border: 1px solid #888;
                width: 80%;
            }

            .close {
                color: #aaaaaa;
                float: right;
                font-size: 28px;
                font-weight: bold;
            }

    css_links:
        Optional list of links to CSS stylesheets to include in the page.

    contents:
        Optional dictionary to store some experiment specific data. For example, in an experiment about melodies, the contents property might look something like this: {”melody”: [1, 5, 2]}.

    save_answer:
        If ``True`` (default), then the answer generated by the page is saved to ``participant.answer``,
        and a link to the corresponding ``Response`` object is saved in ``participant.last_response_id``.
        If ``False``, these slots are left unchanged.
        If a string, then the answer is not only saved to ``participant.answer`` and ``participant.last_response_id``,
        but it is additionally saved as a participant variable named by that string.

    events:
        An optional dictionary of event specifications for the page.
        This determines the timing of various Javascript events that happen on the page.
        Each key of this dictionary corresponds to a particular event.
        Each value should then correspond to an object of class :class:`~psynet.timeline.Event`.
        The :class:`~psynet.timeline.Event` object specifies how the event is triggered by other events.
        For example, if I want to define an event that occurs 3 seconds after the trial starts,
        I would write ``events={"myEvent": Event(is_triggered_by="trialStart", delay=3.0)}``.
        Useful standard events to know are
        ``pageReady`` (the page is initialized and navigation is valid),
        ``trialStart`` (start of the trial),
        ``promptStart`` (start of the prompt),
        ``promptEnd`` (end of the prompt),
        ``recordStart`` (beginning of a recording),
        ``recordEnd`` (end of a recording),
        ``responseEnable`` (enables the response options),
        and ``submitEnable`` (enables the user to submit their response).
        These events and their triggers are set to sensible defaults,
        but the user is welcome to modify them for greater customization.
        See also the ``update_events`` methods of
        :class:`~psynet.modular_page.Prompt`
        and
        :class:`~psynet.modular_page.Control`,
        which provide alternative ways to customize event sequences for modular pages.

    progress_display
        Optional :class:`~psynet.timeline.ProgressDisplay` object.

    show_termination_button:
        If ``True``, a button is displayed allowing the participant to terminate the experiment, Defaults to ``recruiter.show_termination_button``
        which can be ``False`` for all recruiters except for the Lucid recruiter where it should be ``True``.

    start_trial_automatically
        If ``True`` (default), the trial starts automatically, e.g. by the playing
        of a queued audio file. Otherwise the trial will wait for the
        trialPrepare event to be triggered (e.g. by clicking a 'Play' button,
        or by calling `psynet.trial.registerEvent("trialPrepare")` in JS).

    bot_response
        Optional function to call when this page is consumed by a bot.
        This will override any ``bot_response`` function specified in the class's
        ``bot_response`` method.

    validate
        Optional validation function to use for the participant's response.
        Alternatively, the validation function can be set by overriding this class's ``validate`` method.
        If no validation function is found, no validation is performed.
        See :meth:`~psynet.timeline.Page.validate` for information about how to write this function.

        Validation functions provided via the present route may contain various optional arguments.
        Most typically the function will be of the form ``lambda answer: ...` or ``lambda answer, participant: ...``,
        but it is also possible to include the arguments ``raw_answer``, ``response``, ``page``, and ``experiment``.
        Note that ``raw_answer`` is the answer before applying ``format_answer``, and ``answer`` is the answer
        after applying ``format_answer``.

        Validation functions should return ``None`` if the validation passes,
        or if it fails a string corresponding to a message to pass to the participant.

        For example, a validation function testing that the answer contains exactly 3 characters might look like this:
        ``lambda answer: "Answer must contain exactly 3 characters!" if len(answer) != 3 else None``.


    Attributes
    ----------

    contents : dict
        A dictionary containing experiment specific data.

    session_id : str
        If session_id is not None, then it must be a string. If two consecutive pages occur with the same session_id, then when it's time to move to the second page, the browser will not navigate to a new page, but will instead update the Javascript variable psynet.page with metadata for the new page, and will trigger an event called pageUpdated. This event can be listened for with Javascript code like window.addEventListener(”pageUpdated”, ...).

    dynamically_update_progress_bar_and_reward : bool
        If ``True``, then the page will regularly poll for updates to the progress bar and the reward.
        If ``False`` (default), the progress bar and reward are updated only on page refresh or on transition to
        the next page.
    """

    returns_time_credit = True
    dynamically_update_progress_bar_and_reward = False
    is_unity_page = False
    requires_full_page_reload = False
    skip_beforeunload = False

    def __init__(
        self,
        *,
        time_estimate: Optional[float] = None,
        template_path: Optional[str] = None,
        template_str: Optional[str] = None,
        template_fragment_path: Optional[str] = None,
        template_fragment_str: Optional[str] = None,
        template_arg: Optional[Dict] = None,
        label: str = "untitled",
        js_vars: Optional[Dict] = None,
        js_links: Optional[Sequence[str]] = None,
        js_dependencies: Optional[Sequence[str]] = None,
        js_page_modules: Optional[Sequence[str]] = None,
        js_page_code: Optional[Union[str, Sequence[str]]] = None,
        media: Optional[MediaSpec] = None,
        scripts: Optional[Sequence[str]] = None,
        css: Optional[List] = None,
        css_links: Optional[List] = None,
        contents: Optional[Dict] = None,
        session_id: Optional[str] = None,
        save_answer: bool = True,
        events: Optional[Dict] = None,
        progress_display: Optional[ProgressDisplay] = None,
        start_trial_automatically: bool = True,
        show_termination_button: bool = None,
        aggressive_termination_on_no_focus: bool = False,
        bot_response=NoArgumentProvided,
        validate: Optional[callable] = None,
        framework_owned_template: bool = False,
        requires_full_page_reload: bool = False,
    ):
        super().__init__()

        legacy_js_links = _normalize_javascript_urls(js_links, "js_links")
        legacy_scripts = _normalize_js_page_code(scripts, "scripts")
        if legacy_js_links:
            warnings.warn(
                "js_links is deprecated; migrate to js_dependencies or "
                "js_page_modules.",
                FutureWarning,
                stacklevel=3,
            )
        if legacy_scripts:
            warnings.warn(
                "scripts is deprecated; migrate to js_page_code.",
                FutureWarning,
                stacklevel=3,
            )

        if template_arg is None:
            template_arg = {}
        if js_vars is None:
            js_vars = {}
        if contents is None:
            contents = {}
        if css_links is None:
            css_links = []

        complete_template_provided = (
            template_path is not None or template_str is not None
        )
        fragment_template_provided = (
            template_fragment_path is not None or template_fragment_str is not None
        )

        if not complete_template_provided and not fragment_template_provided:
            raise ValueError(
                "Must provide either template_path/template_str or "
                "template_fragment_path/template_fragment_str."
            )
        if template_path is not None and template_str is not None:
            raise ValueError("Cannot provide both template_path and template_str.")
        if template_fragment_path is not None and template_fragment_str is not None:
            raise ValueError(
                "Cannot provide both template_fragment_path and template_fragment_str."
            )
        if complete_template_provided and fragment_template_provided:
            raise ValueError(
                "Cannot provide both a complete template and a template fragment."
            )

        if template_path is not None:
            with open(template_path, "r") as file:
                template_str = file.read()

        template_kind = "complete"
        template_contract_source = template_str
        if fragment_template_provided:
            template_kind = "fragment"
            if template_fragment_path is not None:
                with open(template_fragment_path, "r") as file:
                    template_fragment_str = file.read()
            template_contract_source = template_fragment_str
            template_str = self._wrap_template_fragment(template_fragment_str)

        assert len(label) <= 250
        assert isinstance(template_arg, dict)
        assert isinstance(label, str)

        self.time_estimate = time_estimate
        self.template_str = template_str
        self.template_kind = template_kind
        self.template_contract_source = template_contract_source
        self.framework_owned_template = framework_owned_template
        self._spa_template_contract_warning_shown = False
        self.template_arg = template_arg
        self.label = label
        self.js_vars = js_vars
        _warn_js_var_window_collisions(js_vars)
        self.legacy_js_links = legacy_js_links
        self.legacy_scripts = legacy_scripts
        self.js_dependencies = _normalize_javascript_urls(
            js_dependencies, "js_dependencies"
        )
        self.js_page_modules = _normalize_javascript_urls(
            js_page_modules, "js_page_modules"
        )
        self.js_page_code = _normalize_js_page_code(js_page_code)
        # Framework classes (e.g. JsPsychPage) and explicit constructor opt-out
        # skip the SPA migration error. Deprecated js_links/scripts still force
        # a reload but continue to surface legacy_* error codes until migrated
        # or opted out explicitly.
        class_requires_reload = type(self).requires_full_page_reload
        self._spa_contract_opt_out = bool(
            requires_full_page_reload or class_requires_reload
        )
        if (
            requires_full_page_reload
            or legacy_js_links
            or legacy_scripts
            or class_requires_reload
        ):
            # Classic script semantics (global ``var``, non-module scope) are not
            # emulated across in-place transitions; force a clean document instead.
            # Authors may also opt in explicitly via requires_full_page_reload=True.
            self.requires_full_page_reload = True
        overlapping_javascript = set(self.js_dependencies) & set(self.js_page_modules)
        if overlapping_javascript:
            raise ValueError(
                "The same URL cannot be used in both js_dependencies and "
                f"js_page_modules: {sorted(overlapping_javascript)}"
            )

        self.expected_repetitions = 1

        self.media = MediaSpec() if media is None else media
        self.media.check()

        self.css = [] if css is None else [Markup(x) for x in css]
        assert isinstance(self.css, list)

        self.css_links = css_links

        self._contents = contents
        self.session_id = session_id
        self.save_answer = save_answer
        self.start_trial_automatically = start_trial_automatically
        self.show_termination_button = show_termination_button
        self.aggressive_termination_on_no_focus = aggressive_termination_on_no_focus

        self.events = {
            **self.prepare_default_events(),
            **({} if events is None else events),
        }

        if progress_display is None:
            progress_display = ProgressDisplay(
                stages=[], show_bar=False, show_caption=False
            )
        self.progress_display = progress_display

        self._bot_response = bot_response
        self._validate_function = validate

    @staticmethod
    def _wrap_template_fragment(template_fragment_str):
        return (
            '{% extends "timeline-page.html" %}\n\n'
            "{% block main_body %}\n"
            f"{template_fragment_str}\n"
            "{% endblock %}"
        )

    def call__get_bot_response(self, experiment, bot, response=NoArgumentProvided):
        """
        Constructs the appropriate bot_response for the page.

        The bot_response can be specified in two main ways:
        - By passing an argument to the __init__ method
        - By overriding the :meth:`~psynet.timeline.Page.get_bot_response` method

        The former takes priority.
        """
        from .bot import BotResponse

        if response != NoArgumentProvided:
            res = response
        elif self._bot_response == NoArgumentProvided:
            res = self.get_bot_response(experiment, bot)
        elif callable(self._bot_response):
            res = call_function_with_context(
                self._bot_response,
                experiment=experiment,
                bot=bot,
                participant=bot,
                page=self,
            )
        else:
            res = self._bot_response

        if not isinstance(res, BotResponse):
            res = BotResponse(answer=res)

        return res

    def get_bot_response(self, experiment, bot):
        """
        This function is used when a bot simulates a participant responding to a given page.
        In the simplest form, the function just returns the value of the
        answer that the bot returns.
        For more sophisticated treatment, the function can return a
        ``BotResponse`` object which contains other parameters
        such as ``blobs`` and ``metadata``.
        """
        raise NotImplementedError

    def prepare_default_events(self):
        return {
            "trialConstruct": Event(is_triggered_by=None, once=True),
            "pageReady": Event(is_triggered_by=None, once=True),
            "trialManualRequest": Event(
                is_triggered_by=["trialConstruct", "buttonStart"],
                once=True,
                js="$('#buttonStart').attr('disabled', true)",
            ),
            "trialPrepare": Event(
                is_triggered_by=(
                    "pageReady"
                    if self.start_trial_automatically
                    else ["trialManualRequest", "pageReady"]
                ),
                once=True,
            ),
            "trialStart": Event(is_triggered_by="trialPrepare", once=True),
            "responseEnable": Event(is_triggered_by="trialStart", delay=0.0, once=True),
            "submitEnable": Event(is_triggered_by="trialStart", delay=0.0, once=True),
            "trialFinish": Event(
                is_triggered_by=None
            ),  # only called when trial comes to a natural end
            "trialFinished": Event(is_triggered_by="trialFinish"),
            "trialStop": Event(is_triggered_by=None),  # only called at premature end
            "trialStopped": Event(is_triggered_by="trialStop"),
        }

    def __json__(self, participant):
        return {
            "attributes": self.attributes(participant),
            "contents": self.contents,
        }

    def attributes(self, participant):
        """
        Returns a dictionary containing the `session_id`, the page `type`, and the `page_uuid` .
        """
        from psynet.page import UnityPage

        return {
            "session_id": self.session_id,
            "type": type(self).__name__,
            "unique_id": participant.unique_id,
            "page_uuid": participant.page_uuid,
            "is_unity_page": isinstance(self, UnityPage),
            "requires_full_page_reload": self.requires_full_page_reload,
        }

    @property
    def contents(self):
        return self._contents

    @contents.setter
    def contents(self, contents):
        self._contents = contents

    @property
    def initial_download_progress(self):
        if self.media.num_files > 0:
            return 0
        else:
            return 100

    def visualize(self, trial):
        return ""

    def consume(self, experiment, participant):
        participant.page_uuid = experiment.make_uuid()
        participant.page_count += 1

    def on_complete(self, experiment, participant):
        pass

    @log_time_taken
    def process_response(
        self,
        raw_answer,
        blobs,
        metadata,
        experiment,
        participant,
        client_ip_address,
        answer=NoArgumentProvided,
    ):
        from psynet.trial.main import Trial

        if raw_answer == NoArgumentProvided and answer == NoArgumentProvided:
            raise ValueError("At least one of raw_answer and answer must be provided.")
        if blobs is None:
            blobs = {}
        if metadata is None:
            metadata = {}

        resp = Response(
            participant=participant,
            label=self.label,
            page_type=type(self).__name__,
            client_ip_address=client_ip_address,
        )
        db.session.add(resp)

        trial = participant.current_trial

        if answer == NoArgumentProvided:
            answer = self.format_answer(
                raw_answer,
                blobs=blobs,
                metadata=metadata,
                experiment=experiment,
                participant=participant,
                trial=participant.current_trial,
                response=resp,
            )

        extra_metadata = self.metadata(
            metadata=metadata,
            raw_answer=raw_answer,
            answer=answer,
            experiment=experiment,
            participant=participant,
        )

        combined_metadata = {**metadata, **extra_metadata}

        resp.answer = answer
        resp.metadata = combined_metadata

        if isinstance(trial, Trial):
            trial.response = resp
            if trial.time_taken is None:
                trial.time_taken = resp.metadata["time_taken"]
            else:
                trial.time_taken += resp.metadata["time_taken"]

        if self.save_answer:
            if len(participant.answer_accumulators) > 0:
                page_label = self.label
                accumulator = participant.answer_accumulators[-1]
                answer_label = self._find_answer_label(page_label, accumulator)
                accumulator[answer_label] = resp.answer
                flag_modified(participant, "answer_accumulators")
            else:
                participant.answer = resp.answer
            participant.answer_is_fresh = True
            if isinstance(self.save_answer, str):
                participant.var.set(self.save_answer, resp.answer)
        else:
            participant.answer_is_fresh = False

        participant.browser_platform = metadata.get(
            "platform", "Browser platform info could not be retrieved."
        )

        self.on_complete(experiment=experiment, participant=participant)

        return resp

    def _find_answer_label(self, page_label, accumulator):
        if page_label not in accumulator:
            return page_label
        else:
            i = 0
            while i < 1e7:
                i += 1
                label = f"{page_label}_{i}"
                if label not in accumulator:
                    return label
        raise ValueError("Failed to construct an appropriate answer label")

    def metadata(self, **kwargs):
        """
        Compiles metadata about the page or its response from the participant.
        This metadata will be merged with the default metadata object returned
        from the browser, with any duplicate terms overwritten.

        Parameters
        ----------

        **kwargs
            Keyword arguments, including:

            1. ``raw_answer``:
               The raw answer returned from the participant's browser.

            2. ``answer``:
               The formatted answer.

            3. ``metadata``:
               The original metadata returned from the participant's browser.

            3. ``experiment``:
               An instantiation of :class:`psynet.experiment.Experiment`,
               corresponding to the current experiment.

            4. ``participant``:
               An instantiation of :class:`psynet.participant.Participant`,
               corresponding to the current participant.

        Returns
        -------

        dict
            A dictionary of metadata.
        """
        return {}

    def format_answer(self, raw_answer, **kwargs):
        """
        Formats the raw answer object returned from the participant's browser.

        Parameters
        ----------

        raw_answer
            The raw answer object returned from the participant's browser.

        **kwargs
            Keyword arguments, including:

            1. ``blobs``:
               A dictionary of any blobs that were returned from the
               participant's browser.

            2. ``metadata``:
               The metadata returned from the participant's browser.

            3. ``experiment``:
               An instantiation of :class:`psynet.experiment.Experiment`,
               corresponding to the current experiment.

            4. ``participant``:
               An instantiation of :class:`psynet.participant.Participant`,
               corresponding to the current participant.

        Returns
        -------

        Object
            The formatted answer, suitable for serialisation to JSON
            and storage in the database.
        """
        # pylint: disable=unused-argument
        return raw_answer

    def validate(self, response, **kwargs):
        # pylint: disable=unused-argument
        """
        Takes the :class:`psynet.timeline.Response` object
        created by the page and runs a validation check
        to determine whether the participant may continue to the next page.

        Parameters
        ----------

        response:
            An instance of :class:`psynet.timeline.Response`.
            Typically the ``answer`` attribute of this object
            is most useful for validation.

        **kwargs:
            Keyword arguments, including:

            1. ``experiment``:
               An instantiation of :class:`psynet.experiment.Experiment`,
               corresponding to the current experiment.

            2. ``participant``:
               An instantiation of :class:`psynet.participant.Participant`,
               corresponding to the current participant.

            3. ``answer``:
               The formatted answer returned by the participant.

            4. ``raw_answer``:
               The unformatted answer returned by the participant.

            5. ``page``:
               The page to which the participant is responding.

        Returns
        -------

        ``None`` or an object of class :class:`psynet.timeline.FailedValidation`
            On the case of failed validation, an instantiation of
            :class:`psynet.timeline.FailedValidation`
            containing a message to pass to the participant.
        """
        if self._validate_function is not None:
            return call_function(self._validate_function, response=response, **kwargs)

    def pre_render(self):
        """
        This method is called immediately prior to rendering the page for
        the participant. It will be called again each time the participant
        refreshes the page.
        """
        pass

    def render(self, experiment, participant, partial_mode=False):
        from .utils import get_config

        # Architecture: docs/developer/page_lifecycle.rst
        # `partial_mode` is an internal render shape used for inplace
        # transitions. The public timeline route now serves full pages (plus
        # mode=json), while /response embeds this fragment payload directly.
        internal_js_vars = {
            "uniqueId": participant.unique_id,
            "pageUuid": participant.page_uuid,
            "dynamicallyUpdateProgressBarAndReward": self.dynamically_update_progress_bar_and_reward,
        }
        locale = get_locale()
        language_dict = get_language_dict(locale)
        config = get_config()
        # The SPA template contract applies to author-provided template source,
        # not to PsyNet's generated timeline shell or supported page assets.
        self._check_spa_template_contract(
            inplace_timeline_transitions=config.get("inplace_timeline_transitions"),
        )
        js_vars = {**self.js_vars, **internal_js_vars}
        inplace_timeline_transitions = config.get("inplace_timeline_transitions")

        all_template_args = {
            **self.template_arg,
            "js_vars": js_vars,
            "page": self,
            "initial_download_progress": self.initial_download_progress,
            "time_reward": "%.2f" % participant.time_reward,
            "performance_reward": "%.2f" % participant.performance_reward,
            "total_reward": "%.2f"
            % (participant.performance_reward + participant.time_reward),
            "progress_percentage": round(participant.progress * 100),
            "contact_email_on_error": config.get("contact_email_on_error"),
            "experiment_title": config.get("title"),
            "app_id": experiment.app_id,
            "participant": participant,
            "unique_id": participant.unique_id,
            "worker_id": participant.worker_id,
            "legacy_js_links": self.legacy_js_links,
            "legacy_scripts": self.legacy_scripts,
            "js_dependencies": self.js_dependencies,
            "js_page_code": self.js_page_code,
            "js_page_modules": self.js_page_modules,
            "css": self.css + experiment.css,
            "css_links": self.css_links + experiment.css_links,
            "events": self.events,
            "trial_progress_display_config": self.progress_display,
            "attributes": self.attributes,
            "contents": self.contents,
            "supported_language_dict": {
                iso: language_dict[iso] for iso in experiment.supported_locales
            },
            "locale": locale,
            "partial_mode": partial_mode,
            "inplace_timeline_transitions": inplace_timeline_transitions,
            "start_experiment_in_popup_window": experiment.start_experiment_in_popup_window,
            "show_termination_button": self.show_termination_button,
            "aggressive_termination_on_no_focus": self.aggressive_termination_on_no_focus,
        }
        rendered = render_string_with_translations(
            template_string=self.template_str, **all_template_args
        )
        if partial_mode:
            rendered = self._extract_partial_render(rendered)
        else:
            self._check_embedded_script_contract(rendered)
        return rendered

    def _check_spa_template_contract(self, inplace_timeline_transitions):
        # Explicit / framework reload opt-out skips the migration error.
        # Legacy js_links/scripts still force reload but keep raising so authors
        # see legacy_* codes unless they also pass requires_full_page_reload=True.
        if getattr(self, "_spa_contract_opt_out", False):
            return

        codes = self._collect_spa_incompatibility_codes()
        if not codes:
            return

        message = _format_spa_incompatibility_message(self.label, codes)
        if inplace_timeline_transitions:
            raise ValueError(message)

        if not self._spa_template_contract_warning_shown:
            warnings.warn(message, UserWarning, stacklevel=2)
            self._spa_template_contract_warning_shown = True

    def _collect_spa_incompatibility_codes(self):
        """Return stable SPA error codes for this page."""
        codes = []

        if not self.framework_owned_template:
            if self.template_kind == "complete":
                codes.append("complete_template")
            codes.extend(
                self._collect_spa_markup_contract_codes(self.template_contract_source)
            )

        if getattr(self, "legacy_js_links", None):
            codes.append("legacy_js_links")
        if getattr(self, "legacy_scripts", None):
            codes.append("legacy_scripts")
            codes.extend(
                self._collect_spa_javascript_contract_codes(
                    "\n".join(self.legacy_scripts)
                )
            )

        js_page_code = getattr(self, "js_page_code", None) or []
        if js_page_code:
            codes.extend(
                self._collect_spa_javascript_contract_codes("\n".join(js_page_code))
            )

        return list(dict.fromkeys(codes))

    @staticmethod
    def _collect_spa_javascript_contract_codes(javascript_source):
        """SPA checks for plain JavaScript (js_page_code / legacy scripts).

        Do not parse JS with BeautifulSoup: HTML-tag heuristics false-positive on
        ordinary script text (for example strings containing ``<script``).
        """
        codes = []
        javascript_source = javascript_source or ""

        if re.search(
            r"\b(?:document|window)\s*\.\s*addEventListener\s*\(\s*"
            r"['\"]DOMContentLoaded['\"]",
            javascript_source,
        ):
            codes.append("dom_content_loaded")

        has_window_event_listener = re.search(
            r"\bwindow\s*\.\s*addEventListener\s*\(",
            javascript_source,
        )
        has_page_cleanup = (
            "psynet.addPageEventListener" in javascript_source
            or "psynet.addPageCleanupCallback" in javascript_source
            or _SPA_CLEANUP_RETURN_RE.search(javascript_source) is not None
        )
        if has_window_event_listener and not has_page_cleanup:
            codes.append("window_listener_no_cleanup")

        return codes

    @staticmethod
    def _collect_spa_markup_contract_codes(markup_source, allow_scripts=False):
        # These checks intentionally cover common authoring mistakes rather
        # than trying to prove that arbitrary HTML/JS is SPA-safe.
        #
        # `allow_scripts` is set for page content/prompt markup, where embedded
        # <script> tags are a supported pattern: PsyNet defers and replays them
        # across in-place transitions (see Page._make_embedded_scripts_inert). The
        # prohibition still applies to author-provided page/prompt/control
        # templates, which should route page JavaScript through
        # js_dependencies, js_page_code, and js_page_modules.
        codes = []
        markup_source = markup_source or ""
        soup = BeautifulSoup(markup_source, "html.parser")

        if not allow_scripts and soup.find_all("script"):
            codes.append("embedded_script")

        if soup.find_all("style"):
            codes.append("style_tag")

        if soup.find_all("link", rel=lambda value: value and "stylesheet" in value):
            codes.append("stylesheet_link")

        codes.extend(Page._collect_spa_javascript_contract_codes(markup_source))

        return codes

    @staticmethod
    def _extract_partial_render(rendered_html):
        soup = BeautifulSoup(rendered_html, "html.parser")
        Page._check_embedded_script_contract(soup)
        Page._make_embedded_scripts_inert(soup)
        return Page._extract_partial_body(soup)

    @staticmethod
    def _check_embedded_script_contract(html):
        """Reject embedded modules in favor of managed page modules."""
        soup = (
            html
            if isinstance(html, BeautifulSoup)
            else BeautifulSoup(html, "html.parser")
        )
        for script in soup.find_all("script"):
            script_type = (script.get("type") or "").strip().lower()
            if script_type == "module":
                raise ValueError(
                    'Embedded <script type="module"> tags are not supported '
                    "(error codes: embedded_module).\n\n"
                    "Migrate following "
                    f"{_SPA_UPGRADE_DOCS_URL}"
                    " — or, in Cursor, run /upgrade-to-psynet-14"
                )

    @staticmethod
    def _make_embedded_scripts_inert(soup):
        """Make rendered HTML scripts inert until the fragment is activated."""
        parsed_from_string = isinstance(soup, str)
        if parsed_from_string:
            soup = BeautifulSoup(soup, "html.parser")

        executable_script_types = {
            "",
            "application/ecmascript",
            "application/javascript",
            "text/ecmascript",
            "text/javascript",
        }
        for script in soup.find_all("script"):
            script_type = (script.get("type") or "").strip().lower()
            if script_type not in executable_script_types:
                continue
            script["type"] = "text/psynet-script"
        if parsed_from_string:
            return str(soup)
        return soup

    @staticmethod
    def _extract_partial_body(soup):
        if isinstance(soup, str):
            soup = BeautifulSoup(soup, "html.parser")

        fragment = soup.find(id="psynet-timeline-fragment")
        if fragment is None:
            raise ValueError(
                "Failed to extract partial timeline body: could not find fragment root."
            )
        Page._copy_head_stylesheet_assets_to_fragment(soup, fragment)
        return fragment.decode_contents()

    @staticmethod
    def _copy_head_stylesheet_assets_to_fragment(soup, fragment):
        head = soup.find("head")
        if head is None:
            return

        css_container = fragment.find(id="psynet-page-css")
        if css_container is not None:
            existing_styles = {
                style.get_text() for style in css_container.find_all("style")
            }
            for style in head.find_all(
                "style", attrs={"data-psynet-fragment-style": True}, recursive=False
            ):
                style_text = style.get_text()
                if style_text not in existing_styles:
                    css_container.append(copy.copy(style))
                    existing_styles.add(style_text)

        css_link_container = fragment.find(id="psynet-page-css-links")
        if css_link_container is not None:
            existing_hrefs = {
                link.get("href")
                for link in css_link_container.find_all(
                    "link", rel=lambda value: value and "stylesheet" in value
                )
            }
            for link in head.find_all(
                "link",
                attrs={"data-psynet-fragment-stylesheet": True},
                rel=lambda value: value and "stylesheet" in value,
                recursive=False,
            ):
                href = link.get("href")
                if href not in existing_hrefs:
                    css_link_container.append(copy.copy(link))
                    existing_hrefs.add(href)

    @property
    def plain_text(self):
        """
        A plain text version of the page's content.
        This is used for testing purposes.
        Users are invited to override this method in subclasses.
        """
        return "Not implemented"


class PageMaker(Elt):
    """
    A page maker is defined by a function that is executed when
    the participant requests the relevant page.

    Parameters
    ----------

    function:
        A function that may take up to two arguments, named ``experiment``
        and ``participant``. These arguments correspond to instantiations
        of the class objects :class:`psynet.experiment.Experiment`
        and :class:`psynet.participant.Participant` respectively.
        The function should return either a single test element
        (e.g. :class:`psynet.timeline.Page`, :class:`psynet.timeline.PageMaker`,
        :class:`psynet.timeline.CodeBlock`) or a list of such elements.
        Note that :class:`psynet.timeline.PageMaker` objects can be nested
        arbitrarily deeply. Note also that, if the page maker returns multiple pages,
        then the function will be recomputed each time the participant progresses
        to the next page. This functionality can be used to make the latter
        pages depend on the earlier pages in the page maker.

    time_estimate:
        Time estimated to complete the segment. This time estimate is used
        for predicting the overall length of the experiment and hence
        generating the progress bar. The actual time credit given to the
        participant is determined by ``time_estimate`` parameters
        provided to the pages generated by ``function``.
        However, there is an exception provided for back-compatibility:
        if ``function`` generates a list containing solely :class:`psynet.timeline.Page`
        or :class:`psynet.timeline.PageMaker` objects, and if those objects are all missing
        ``time_estimate`` values, then these ``time_estimate`` values will be imputed by dividing
        the parent :class:`psynet.timeline.PageMaker`'s ``time_estimate``
        by the number of produced elements.
    """

    returns_time_credit = True

    def __init__(
        self,
        function: Callable[..., "TimelineLogic"],
        time_estimate: Optional[float] = None,
        accumulate_answers: bool = False,
        label: str = "page_maker",
    ):
        super().__init__()

        assert callable(function)

        self.function = function
        self.time_estimate = time_estimate
        self.accumulate_answers = accumulate_answers
        self.expected_repetitions = 1
        self.label = label

    def resolve(self, experiment, participant, position):
        """
        This function 'resolves' the page maker by calling its underlying
        function and hence returning its underlying timeline logic.

        Parameters
        ----------
        experiment :
            The experiment instance.

        participant :
            The participant instance.

        position :
            The position of the page maker within the timeline.
            This is used for setting the IDs of the timeline
            elements that are produced.

        Returns
        -------

        A list of ``Elt`` objects.
        """
        res = call_function_with_context(
            self.function,
            self=self,
            experiment=experiment,
            participant=participant,
        )
        res = join(res)

        for elt in res:
            if isinstance(elt, StartModule):
                raise ValueError(
                    "Sorry, you cannot use modules or trial makers inside the lambda functions of "
                    "page makers or for loops. These need to be defined upon construction of the timeline."
                )

        self.impute_time_estimates(res)
        self.check_time_estimates(res)

        res = join(
            StartAccumulateAnswers() if self.accumulate_answers else None,
            res,
            EndAccumulateAnswers() if self.accumulate_answers else None,
        )

        res = with_fixed_progress(res, self.time_estimate)

        for i, elt in enumerate(res):
            elt.id = position + [i]
            elt.created_within_page_maker = True
            elt.links = {**self.links, **elt.links}
        return res

    def impute_time_estimates(self, elts):
        # This is performed for back-compatibility;
        # basically, if all the elements are pages or page makers
        # and none of them have time estimates, then we compute
        # their time estimates by equally subdividing the time estimate
        # for the parent page maker.
        if all(
            [
                isinstance(elt, (Page, PageMaker)) and elt.time_estimate is None
                for elt in elts
            ]
        ):
            n = len(elts)
            for elt in elts:
                elt.time_estimate = self.time_estimate / n

    def check_time_estimates(self, elts):
        for elt in elts:
            if elt.returns_time_credit and elt.time_estimate is None:
                raise RuntimeError(
                    f"One of the elements in the page maker was missing a time estimate ({elt})"
                )


class PageMakerFinishedError(Exception):
    pass


class Timeline:
    def __init__(self, *args, **branch_kwargs):
        from collections import OrderedDict

        from psynet.end import (
            RejectedConsentLogic,
            SuccessfulEndLogic,
            UnsuccessfulEndLogic,
        )
        from psynet.page import SuccessfulEndPage

        default_branches = OrderedDict(
            [
                ("successful_end", SuccessfulEndLogic()),
                ("unsuccessful_end", UnsuccessfulEndLogic()),
                ("rejected_consent", RejectedConsentLogic()),
            ]
        )
        default_branches.update(branch_kwargs)

        self.elts = OrderedDict()
        self.elts["main"] = join(*args, SuccessfulEndPage())
        for name, content in default_branches.items():
            self.elts[name] = join(content)

        self.modules, self.module_list = self.compile_modules()
        self.check_elts()
        self.add_elt_ids()
        self.estimated_time_credit = CreditEstimate(list(self.all_elts))

    @property
    def all_elts(self):
        """Iterate over all elements across all branches."""
        for branch_elts in self.elts.values():
            yield from branch_elts

    def get_participant_branch(self, participant):
        """Return the name of the branch the participant is currently in."""
        return participant.elt_id[0]

    def participant_is_in_end_logic(self, participant):
        """Return True if the participant is in any end logic branch."""
        return self.get_participant_branch(participant) != "main"

    def redirect_to_branch(self, experiment, participant, branch_name):
        """Redirect a participant to the start of a named branch.

        This should only be called from within ``advance_page`` (i.e. from
        an ``Elt.consume`` method).  For redirects originating outside the
        page-advance loop (e.g. background tasks), set
        ``participant.pending_redirect`` instead so that the redirect is
        applied on the next page transition. That queued redirect does not
        keep an in-progress trial valid; ``participant.fail()`` has already
        failed incomplete trials.
        """
        if branch_name not in self.elts:
            raise ValueError(f"Unknown timeline branch: {branch_name!r}")
        participant.elt_id = [branch_name, -1]
        participant.elt_id_max = []

    def compile_modules(self):
        modules = {}
        module_list = []
        for elt in self.all_elts:
            if isinstance(elt, StartModule):
                module = elt.module
                if module.id in modules:
                    raise ValueError(f"Duplicated module name detected: {module.id}")
                modules[module.id] = module
                module_list.append(module)
        return modules, module_list

    def check_elts(self):
        assert isinstance(self.elts, dict)
        assert "main" in self.elts
        assert len(self.elts["main"]) > 0
        self.check_for_time_estimate()
        self.check_modules()

    def check_for_time_estimate(self):
        for elt in self.all_elts:
            if (
                isinstance(elt, Page) or isinstance(elt, PageMaker)
            ) and elt.time_estimate is None:
                raise ValueError(
                    f"Element {elt!r} of the timeline was missing a time_estimate value."
                )

    def check_modules(self):
        modules = [x.label for x in self.all_elts if isinstance(x, StartModule)]
        counts = Counter(modules)
        duplicated = [key for key, value in counts.items() if value > 1]
        if len(duplicated) > 0:
            raise ValueError(
                "The following module ID(s) were duplicated in your timeline: "
                + ", ".join(duplicated)
                + ". PsyNet timelines may not contain duplicated module IDs. "
                + "You will need to update your timeline to fix this. "
                + "This will probably mean updating one or more `id_` arguments in your "
                + "trial makers and/or pre-screening tasks."
            )

    @property
    def consents(self):
        from .consent import Consent

        return [elt for elt in self.elts["main"] if isinstance(elt, Consent)]

    def check_consents(self, experiment):
        recruiter = experiment.recruiter
        recruiter.check_consents(self.consents)

    def get_module(self, module_id):
        try:
            return self.modules[module_id]
        except IndexError:
            raise RuntimeError(f"Couldn't find module with id = {module_id}.")

    @cached_property
    def trial_makers(self):
        return {
            e.trial_maker_id: e.trial_maker
            for e in self.all_elts
            if isinstance(e, RegisterTrialMaker)
        }

    def get_trial_maker(self, trial_maker_id):
        try:
            return self.trial_makers[trial_maker_id]
        except IndexError:
            raise RuntimeError(f"Couldn't find trial maker with id = {trial_maker_id}.")

    def add_elt_ids(self):
        for branch_name, branch_elts in self.elts.items():
            for i, elt in enumerate(branch_elts):
                expected_id = [branch_name, i]
                if elt.id is not None and elt.id != expected_id:
                    raise ValueError(
                        f"Failed to set unique IDs for each element in the timeline "
                        f"(the same element was reused at positions {elt.id} and {expected_id}). "
                        "This usually means that the same Python object instantiation is reused multiple times "
                        "in the same timeline. This kind of reusing is not permitted, instead you should "
                        "create a fresh instantiation of each element, e.g. by calling a function twice."
                    )
                elt.id = expected_id

    def __len__(self):
        return sum(len(branch) for branch in self.elts.values())

    def __getitem__(self, key: Union[str, list]):
        if isinstance(key, str):
            return self.elts[key]

        if isinstance(key, list):
            selected = self.elts
            for k in key:
                selected = selected[k]
            return selected

        raise TypeError(
            f"Timeline indices must be strings or lists, not {type(key).__name__}"
        )

    def index(self, elt: Elt):
        if elt.id is None:
            raise ValueError(
                "Cannot index an element that has yet to be assigned an ID."
            )

        return elt.id

    @log_time_taken
    def get_current_elt(self, experiment, participant):
        # ``participant.elt_id`` is a list where the first element is the branch
        # name (e.g. ``"main"``), the second element is the index within that
        # branch, and any further elements represent position within nested
        # page makers.
        # For example, ``["main", 10, 3, 2]`` means: go to the ``main`` branch,
        # element 10 (which must be a page maker), element 3 within that page
        # maker (also a page maker), element 2 within that.
        num_levels = len(participant.elt_id)
        selected = self.elts

        for depth, index in enumerate(participant.elt_id):
            try:
                index_max = participant.elt_id_max[depth]
            except IndexError:
                index_max = None

            if isinstance(selected, PageMaker):
                try:
                    if index_max is not None and index > index_max:
                        raise IndexError
                    position = participant.elt_id[0:depth]
                    selected = selected.resolve(experiment, participant, position)
                    if index_max is None:
                        participant.elt_id_max.append(len(selected) - 1)
                except IndexError:
                    assert depth + 1 == num_levels
                    raise PageMakerFinishedError

            selected = selected[index]

        return selected

    @log_time_taken
    def advance_page(self, experiment, participant):
        participant._in_advance_page = True
        try:
            if participant.pending_redirect:
                # Apply a queued fail() redirect before further timeline
                # logic, so ``_finalize_trial`` does not run for the page
                # that was open when the participant was failed.
                branch = participant.pending_redirect
                participant.pending_redirect = None
                self.redirect_to_branch(experiment, participant, branch)

            finished = False
            while not finished:
                participant.elt_id[-1] += 1

                try:
                    new_elt = self.get_current_elt(experiment, participant)
                except PageMakerFinishedError:
                    participant.elt_id = participant.elt_id[:-1]
                    participant.elt_id_max = participant.elt_id_max[:-1]
                    continue
                if isinstance(new_elt, PageMaker):
                    participant.elt_id.append(-1)
                    continue

                new_elt.consume(experiment, participant)

                if isinstance(new_elt, Page):
                    finished = True
        finally:
            participant._in_advance_page = False

    def estimated_max_reward(self, wage_per_hour):
        return self.estimated_time_credit.get_max("reward", wage_per_hour=wage_per_hour)

    def estimated_completion_time(self, wage_per_hour):
        return self.estimated_time_credit.get_max("time", wage_per_hour=wage_per_hour)


class CreditEstimate:
    def __init__(self, elts):
        self._elts = join(elts)
        self._max_time = self._estimate_max_time(self._elts)

    def get_max(self, mode, wage_per_hour=None):
        if mode == "time":
            return self._max_time
        elif mode == "reward":
            assert wage_per_hour is not None
            return self._max_time * wage_per_hour / (60 * 60)
        elif mode == "all":
            return {
                "time_seconds": self._max_time,
                "time_minutes": self._max_time / 60,
                "time_hours": self._max_time / (60 * 60),
                "reward": self.get_max("reward", wage_per_hour=wage_per_hour),
            }

    def _estimate_max_time(self, elts: List[Elt]):
        time_credit = 0.0
        pos = 0

        while True:
            if pos == len(elts):
                return time_credit

            elt = elts[pos]

            if elt.returns_time_credit:
                time_credit += elt.time_estimate * elt.expected_repetitions

            if isinstance(elt, StartFixElt):
                pos = elts.index(elt.end_fix)

            elif isinstance(elt, EndFixElt):
                time_credit += elt.time_credit * elt.expected_repetitions
                pos += 1

            elif isinstance(elt, StartSwitch):
                time_credit += self._estimate_switch_credit(elt, elts)
                pos = elts.index(elt.end_switch)

            elif isinstance(elt, EndSwitchBranch):
                pos = elts.index(elt.target)

            elif isinstance(elt, GoTo):
                pos = self._follow_go_to(go_to=elt, elts=elts)

            else:
                pos += 1

    def _estimate_switch_credit(self, elt, elts):
        return max(
            [
                self._estimate_max_time(
                    elts[elts.index(branch_start) : (1 + elts.index(elt.end_switch))]
                )
                for key, branch_start in elt.branch_start_elts.items()
            ]
        )

    def _follow_go_to(self, go_to, elts) -> Union[List, int]:
        if callable(go_to.target):
            raise ValueError(
                "Cannot proceed with timeline simulation as this GoTo's target is only known at run time"
            )
        elif isinstance(go_to.target, Elt):
            return elts.index(go_to.target)
        elif isinstance(go_to.target, list):
            for i, elt in enumerate(elts):
                if elt.id == go_to.target:
                    return i
        raise ValueError(f"Failed to follow GoTo to target {go_to.target}")


def estimate_duration(logic):
    # This join ensures that any modules are resolved into lists of Elts.
    elts = join(logic)
    return CreditEstimate(elts).get_max("time")


class FailedValidation:
    def __init__(self, message="Invalid response, please try again."):
        self.message = message


@register_table
class _Response(SQLBase, SQLMixin):
    """
    This virtual class is not to be used directly.
    We use it as the parent class for the ``Response`` class
    to sidestep the following SQLAlchemy error:

    sqlalchemy.exc.InvalidRequestError: Attribute name 'metadata'
    is reserved for the MetaData instance when using a declarative base class.
    """

    __tablename__ = "response"


class Response(_Response):
    """
    A database-backed object that stores the participant's response to a
    :class:`~psynet.timeline.Page`.
    By default, one such object is created each time the participant
    tries to advance to a new page.

    Attributes
    ----------

    answer
        The participant's answer, after formatting.

    page_type: str
        The type of page administered.

    successful_validation: bool
        Whether the response validation was successful,
        allowing the participant to advance to the next page.

    client_ip_address : str
        The participant's IP address as reported by Flask.
    """

    __extra_vars__ = {}

    participant_id = Column(Integer, ForeignKey("participant.id"), index=True)
    participant = relationship(
        "psynet.participant.Participant",
        back_populates="all_responses",
        foreign_keys=[participant_id],
    )

    question = Column(String)
    answer = Column(PythonObject)
    page_type = Column(String)
    successful_validation = Column(Boolean)
    client_ip_address = Column(String)

    # metadata is a protected attribute in SQLAlchemy, hence the underscore
    # and the functional setter/getter.
    metadata_ = Column(PythonObject)

    @property
    def metadata(self):
        """
        A dictionary of metadata associated with the Response object.
        Stored in the ``details`` field in the database.
        """
        return self.metadata_

    @metadata.setter
    def metadata(self, metadata):
        self.metadata_ = metadata

    async_processes = relationship("AsyncProcess")
    # assets = relationship(
    #     "Asset", collection_class=attribute_mapped_collection("label_or_key")
    # )

    errors = relationship("ErrorRecord")

    def __init__(
        self,
        participant,
        label,
        page_type,
        client_ip_address,
        answer=None,
        metadata=None,
    ):
        self.participant_id = participant.id
        self.question = label
        self.page_type = page_type
        self.metadata = metadata
        self.client_ip_address = client_ip_address
        self.answer = answer
        self.metadata = metadata


def is_list_of(x, what):
    if not isinstance(x, list):
        return False
    for val in x:
        if not isinstance(val, what):
            return False
    return True


def join(*args):
    from .asset import AssetSpecification

    list_classes = (list, tuple)

    def normalize(arg, index):
        if arg is None:
            return []
        if isinstance(arg, FunctionType):
            return [CodeBlock(arg)]
        if isinstance(arg, EltCollection):
            return normalize(arg.resolve(), index)
        if isinstance(arg, (AssetSpecification, Elt)):
            return [arg]
        if isinstance(arg, list_classes):
            normalized = []
            for item in arg:
                normalized.extend(normalize(item, index))
            return normalized
        raise TypeError(
            f"Element {index + 1} of the input to join() was neither an Asset/Elt/EltCollection "
            f"nor a list/tuple of such objects: ({arg})."
        )

    normalized = []
    for i, arg in enumerate(args):
        normalized.extend(normalize(arg, i))
    return normalized


class StartWhile(NullElt):
    def __init__(self, label):
        # targets = {
        #     True: self,
        #     False: end_while
        # }
        # super().__init__(condition, targets)
        super().__init__()
        self.label = label


class EndWhile(NullElt):
    def __init__(self, label):
        super().__init__()
        self.label = label


def while_loop(
    label: str,
    condition: Callable,
    logic,
    expected_repetitions: int,
    max_loop_time: float = None,
    fix_time_credit=True,
    fail_on_timeout=True,
    on_timeout: Optional[Callable] = None,
):
    """
    Loops a series of elts while a given criterion is satisfied.
    The criterion function is evaluated once at the beginning of each loop.

    Parameters
    ----------

    label:
        Internal label to assign to the construct.

    condition:
        A function with up to two arguments named ``participant`` and ``experiment``,
        that is executed once the participant reaches the corresponding part of the timeline,
        returning a Boolean.

    logic:
        An elt (or list of elts) to display while ``condition`` returns ``True``.

    expected_repetitions:
        The number of times the loop is expected to be seen by a given participant.
        This doesn't have to be completely accurate, but it is used for estimating the length
        of the total experiment.

    max_loop_time:
        The maximum time in seconds for staying in the loop. Once exceeded, the participant is
        is presented the ``UnsuccessfulEndPage``. Default: None.

    fix_time_credit:
        Whether participants should receive the same time credit irrespective of whether
        ``condition`` returns ``True`` or not; defaults to ``True``, so that all participants
        receive the same credit.

    fail_on_timeout:
        Whether the participants should be failed when the ``max_loop_time`` is reached.
        Setting this to ``False`` will not return the ``UnsuccessfulEndPage`` when maximum time has elapsed
        but allow them to proceed to the next page.

    on_timeout:
        Optional callable invoked when ``max_loop_time`` is exceeded.
        Called with ``participant=...``.

    Returns
    -------

    list
        A list of elts that can be embedded in a timeline using :func:`psynet.timeline.join`.
    """
    start_while = StartWhile(label)
    end_while = EndWhile(label)

    logic = join(logic)
    logic = multiply_expected_repetitions(logic, expected_repetitions)

    def condition_wrapped(participant, experiment):
        result = call_function_with_context(
            condition, participant=participant, experiment=experiment
        )
        logger.info(f"Evaluating while_loop ({label}) condition: result = {result}")
        return result

    conditional_logic = join(logic, GoTo(start_while))

    def with_namespace(x=None):
        prefix = f"__{label}__{x}"
        if x is None:
            return prefix
        return f"{prefix}__{x}"

    if max_loop_time is not None:

        def max_loop_time_condition(participant, experiment):
            return (
                datetime.now()
                - unserialise_datetime(
                    participant.var.get(with_namespace("loop_start_time"))
                )
            ).seconds > max_loop_time

    else:

        def max_loop_time_condition(participant, experiment):
            return False

    from .page import UnsuccessfulEndPage

    timeout_callback = (
        CodeBlock(
            lambda participant: call_function_with_context(
                on_timeout, participant=participant
            )
        )
        if on_timeout is not None
        else None
    )

    if fail_on_timeout is True:
        after_timeout_logic = join(
            timeout_callback,
            UnsuccessfulEndPage(
                failure_tags=[f"while_loop:{label}", "fail_on_timeout"]
            ),
        )
    else:
        after_timeout_logic = join(timeout_callback, GoTo(end_while))

    time_estimate = CreditEstimate(logic).get_max("time")

    elts = join(
        CodeBlock(
            lambda participant: participant.var.set(
                with_namespace("loop_start_time"), serialise(datetime.now())
            )
        ),
        start_while,
        conditional(
            "max_loop_time_condition",
            lambda participant, experiment: call_function_with_context(
                max_loop_time_condition,
                participant=participant,
                experiment=experiment,
            ),
            after_timeout_logic,
            # The while loop includes its own progress bounds, so we don't need to bound progress
            # within this inner component.
            bound_progress=False,
            log_chosen_branch=False,
            time_estimate=0.0,
        ),
        conditional(
            label,
            condition_wrapped,
            conditional_logic,
            # The while loop includes its own progress bounds, so we don't need to bound progress here.
            # Moreover, this conditional contains a GoTo, which will cause the progress bound logic
            # to fail if enabled here.
            bound_progress=False,
            log_chosen_branch=False,
            time_estimate=time_estimate,
        ),
        end_while,
    )

    elts = with_fixed_progress(elts, time_estimate)

    if fix_time_credit:
        elts = with_fixed_time_credit(elts, time_estimate)

    return elts


def check_branches(branches):
    for branch_name, branch_elts in branches.items():
        branches[branch_name] = join(branch_elts)
    return branches


def switch(
    label: str,
    function: Callable,
    branches: dict,
    fix_time_credit: bool = False,
    bound_progress: bool = True,
    log_chosen_branch: bool = True,
    time_estimate: float = None,
):
    """
    Selects a series of elts to display to the participant according to a
    certain condition.

    Parameters
    ----------

    label:
        Internal label to assign to the construct.

    function:
        A function with up to two arguments named ``participant`` and ``experiment``,
        that is executed once the participant reaches the corresponding part of the timeline,
        returning a key value with which to index ``branches``.

    branches:
        A dictionary indexed by the outputs of ``function``; each value should correspond
        to an elt (or list of elts) that can be selected by ``function``.

    fix_time_credit:
        Whether participants should receive the same time credit irrespective of the branch taken.
        Defaults to ``False``; if set to ``True``,
        all participants receive the same credit, corresponding to the branch with the maximum time credit.

    bound_progress:
        Whether the progress estimate should be 'bound' such that, whatever happens, when the participant
        exits the conditional construct, the progress estimate will be the same as if the participant
        had taken the branch with the maximum time credit. Defaults to ``True``.

    log_chosen_branch:
        Whether to keep a log of which participants took each branch; defaults to ``True``.

    time_estimate:
        An optional time estimate to use for the switch construct. If not provided, the time estimate
        will be estimated by computing time estimates for all branches and taking the maximum.

    Returns
    -------

    list
        A list of elts that can be embedded in a timeline using :func:`psynet.timeline.join`.
    """
    branches = check_branches(branches)

    all_branch_starts = dict()
    all_elts = []
    end_switch = EndSwitch(label)

    for branch_name, branch_elts in branches.items():
        branch_start = StartSwitchBranch(branch_name)
        branch_end = EndSwitchBranch(branch_name, end_switch)
        branch_elts = join(branch_elts)
        all_branch_starts[branch_name] = branch_start
        all_elts = all_elts + [branch_start] + branch_elts + [branch_end]

    start_switch = StartSwitch(
        label,
        function,
        branch_start_elts=all_branch_starts,
        end_switch=end_switch,
        log_chosen_branch=log_chosen_branch,
    )
    combined_elts = [start_switch] + all_elts + [end_switch]

    if time_estimate is None:
        time_estimate = max(
            [
                CreditEstimate(branch_elts).get_max("time")
                for branch_elts in branches.values()
            ]
        )

    if bound_progress:
        combined_elts = with_fixed_progress(combined_elts, time_estimate)

    if fix_time_credit:
        combined_elts = with_fixed_time_credit(combined_elts, time_estimate)

    return combined_elts


class StartSwitch(ReactiveGoTo):
    def __init__(
        self, label, function, branch_start_elts, end_switch, log_chosen_branch=True
    ):
        if log_chosen_branch:

            def function_2(experiment, participant):
                val = call_function_with_context(
                    function,
                    experiment=experiment,
                    participant=participant,
                )
                log_entry = [label, val]
                participant.append_branch_log(log_entry)
                return val

            super().__init__(function_2, targets=branch_start_elts)
        else:
            super().__init__(function, targets=branch_start_elts)
        self.label = label
        self.branch_start_elts = branch_start_elts
        self.end_switch = end_switch
        self.log_chosen_branch = log_chosen_branch


class EndSwitch(NullElt):
    def __init__(self, label):
        super().__init__()
        self.label = label


class StartSwitchBranch(NullElt):
    def __init__(self, name):
        super().__init__()
        self.name = name


class EndSwitchBranch(GoTo):
    def __init__(self, name, final_elt):
        super().__init__(target=final_elt)
        self.name = name


def conditional(
    label: str,
    condition: Callable,
    logic_if_true,
    logic_if_false=None,
    fix_time_credit: bool = False,
    bound_progress: bool = True,
    log_chosen_branch: bool = True,
    time_estimate: float = None,
):
    """
    Executes a series of elts if and only if a certain condition is satisfied.

    Parameters
    ----------

    label:
        Internal label to assign to the construct.

    condition:
        A function with up to two arguments named ``participant`` and ``experiment``,
        that is executed once the participant reaches the corresponding part of the timeline,
        returning a Boolean.

    logic_if_true:
        An elt (or list of elts) to display if ``condition`` returns ``True``.

    logic_if_false:
        An optional elt (or list of elts) to display if ``condition`` returns ``False``.

    fix_time_credit:
        Whether participants should receive the same time credit irrespective of the branch taken.
        Defaults to ``False``; if set to ``True``,
        all participants receive the same credit, corresponding to the branch with the maximum time credit.

    bound_progress:
        Whether the progress estimate should be 'bound' such that, whatever happens, when the participant
        exits the conditional construct, the progress estimate will be the same as if the participant
        had taken the branch with the maximum time credit. Defaults to ``True``.

    log_chosen_branch:
        Whether to keep a log of which participants took each branch; defaults to ``True``.

    time_estimate:
        An optional time estimate to use for the conditional construct. If not provided, the time estimate
        will be estimated by computing time estimates for the two branches and taking the maximum.

    Returns
    -------

    list
        A list of elts that can be embedded in a timeline using :func:`psynet.timeline.join`.
    """
    return switch(
        label,
        function=condition,
        branches={
            True: logic_if_true,
            False: NullElt() if logic_if_false is None else logic_if_false,
        },
        fix_time_credit=fix_time_credit,
        bound_progress=bound_progress,
        log_chosen_branch=log_chosen_branch,
        time_estimate=time_estimate,
    )


class ConditionalElt(Elt):
    def __init__(self, label: str):
        super().__init__()
        self.label = label


class StartConditional(ConditionalElt):
    pass


class EndConditional(ConditionalElt):
    pass


def with_fixed_progress(elts: List[Elt], time_credit: float):
    """
    Ensures that, when the provided list of elts has been consumed,
    the participant's progress corresponds exactly to the specified
    time credit, irrespective of whatever happens within those elts.

    Parameters
    ----------

    elts :
        A list of timeline Elts.

    time_credit :
        The progress increment is calculated as if the participant had acquired
        this amount of time credit (in units of seconds).
    """
    end_fix = EndFixProgress(time_credit)
    start_fix = StartFixProgress(time_credit, end_fix)
    return join(
        start_fix,
        elts,
        end_fix,
    )


def with_fixed_time_credit(elts, time_credit):
    """
    Ensures that, when the provided list of elts has been consumed,
    the participant's resulting time credit corresponds exactly to the specified
    value, irrespective of whatever happens within those elts.

    Parameters
    ----------

    elts :
        A list of timeline Elts.

    time_credit :
        The amount of time credit to allocate (in units of seconds).
    """
    end_fix = EndFixTimeCredit(time_credit)
    start_fix = StartFixTimeCredit(time_credit, end_fix)
    return join(start_fix, elts, end_fix)


def multiply_expected_repetitions(logic, factor: float):
    assert isinstance(logic, Elt) or is_list_of(logic, Elt)
    if isinstance(logic, Elt):
        logic.multiply_expected_repetitions(factor)
    else:
        for elt in logic:
            elt.multiply_expected_repetitions(factor)
    return logic


@register_table
class ModuleState(SQLBase, SQLMixin):
    __tablename__ = "module_state"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, unique=True)
    module_id = Column(String)
    # parent_id = Column(Integer, ForeignKey("module_state.id"))
    # parent = relationship("ModuleState", foreign_keys=[parent_id], post_update=True)
    participant_id = Column(
        Integer,
        ForeignKey("participant.id"),
        # back_populates="_module_states",
    )
    participant = relationship(
        "psynet.participant.Participant",
        foreign_keys=[participant_id],
        backref=backref("_module_states", post_update=True, lazy="selectin"),
        post_update=True,
    )
    # current_trial = Column(
    #     PythonObject
    # )  # Note: this can sometimes be a trial object or alternatively a string

    time_started = Column(DateTime)
    time_finished = Column(DateTime)
    time_aborted = Column(DateTime)
    started = Column(Boolean, default=False)
    finished = Column(Boolean, default=False)
    aborted = Column(Boolean, default=False)

    asset_links = relationship(
        "AssetModuleState",
        collection_class=attribute_mapped_collection("local_key"),
        cascade="all, delete-orphan",
    )

    @staticmethod
    def _create_asset_module_state(local_key, asset):
        from psynet.asset import AssetModuleState

        return AssetModuleState(local_key=local_key, asset=asset)

    assets = association_proxy(
        "asset_links",
        "asset",
        creator=lambda k, v: _create_asset_module_state(local_key=k, asset=v),  # noqa
    )

    nodes = relationship("psynet.trial.main.TrialNode")

    def __init__(self, module, participant):
        self.module_id = module.id
        self.participant = participant

    def start(self):
        self.time_started = datetime.now()
        self.started = True

    def finish(self):
        self.time_finished = datetime.now()
        self.finished = True

    def abort(self):
        self.time_finished = datetime.now()
        self.aborted = True

    # def get(self, module_id: str):
    #     return self.participant.get_module_state(module_id)


class ModuleAssets:
    def __init__(self, module_id):
        self.module_id = module_id

    def __getitem__(self, item):
        from psynet.asset import Asset

        return Asset.query.filter_by(
            module_id=self.module_id, key_within_module=item
        ).one()


class Module(EltCollection):
    default_id = None
    default_elts = None
    state_class = ModuleState  # type: Type[ModuleState]

    def __init__(
        self,
        id_: str = None,
        *args,
        assets: Union[None, Callable, dict[str, "Asset"], list["Asset"]] = None,
        nodes: Union[None, list["TrialNode"]] = None,
        state_class: Optional[Type["ModuleState"]] = None,
    ):
        elts = join(*args)

        if self.default_id is None and id_ is None:
            raise ValueError("Either one of <default_id> or <id_> must not be None.")
        if self.default_elts is None and elts is None:
            raise ValueError("Either one of <default_elts> or <elts> must not be None.")

        self.id = id_ if id_ is not None else self.default_id
        self.elts = elts if elts is not None else self.default_elts
        self.nodes = nodes if nodes else []

        self._assets = assets  # Stores the literal input from the constructor
        self._staged_assets = (
            None  # Will store the unpacked collection of assets in due course
        )

        self.state_class = state_class if state_class else self.__class__.state_class

        for node in self.nodes:
            if node.module_id is not None and node.module_id != self.id:
                raise RuntimeError(
                    "Nodes cannot belong to multiple modules/trial makers. "
                    "Please make a separate node list for each one."
                )
            node.module_id = self.id

    @property
    def assets(self):
        return ModuleAssets(self.id)

    def prepare_for_deployment(self, experiment):
        self.prepare_nodes_for_deployment(experiment)
        self.prepare_assets_for_deployment(experiment)

    def prepare_nodes_for_deployment(self, experiment):
        self.nodes_register_in_db()
        self.nodes_stage_assets(experiment)

    def prepare_assets_for_deployment(self, experiment):
        self._compile_staged_assets()
        for asset in self._staged_assets:
            experiment.assets.stage(asset)
        db.session.commit()

    def _compile_staged_assets(self):
        # self._assets stores the literal input from the constructor
        # _compile_staged_assets processes self._assets, evaluating callables,
        # providing keys to the assets as appropriate, and storing the result in self._staged_assets.
        from psynet.asset import Asset

        # Evaluate the callable (if applicable)
        if callable(self._assets):
            assets = self._assets()
        else:
            assets = self._assets

        # Unpack the assets into a list of Asset objects
        if assets is None:
            self._staged_assets = []
        elif isinstance(assets, dict):
            self._staged_assets = []
            for _key_within_module, _asset in assets.items():
                _asset.key_within_module = _key_within_module
                self._staged_assets.append(_asset)
        else:
            assert isinstance(assets, list)
            self._staged_assets = assets

        # Add any assets that are defined within the module's timeline logic
        for elt in self.elts:
            if isinstance(elt, Asset):
                self._staged_assets.append(elt)

        # Add the module ID to each asset
        for asset in self._staged_assets:
            asset.module_id = self.id

    def deposit_assets_on_the_fly(self):
        assets_to_deposit = [
            asset for asset in self._staged_assets if not asset.deposited
        ]
        if len(assets_to_deposit) > 0:
            logger.info(
                "Depositing %i assets on-the-fly (i.e. while the participant waits for the "
                "experiment to continue. This is a bad idea if the number of assets is large "
                "and if they need to be uploaded to a remote server. "
                "To avoid this, avoid defining your module/trial maker within a page maker.",
                len(assets_to_deposit),
            )
            for asset in assets_to_deposit:
                # TODO - parallelize this deposit, see code in Experiment class
                asset.deposit()

    def nodes_register_in_db(self):
        for node in self.nodes:
            db.session.add(node)
            assert node.module_id == self.id
            if node.network is None:
                node.add_default_network()
        db.session.commit()
        for node in self.nodes:
            node.check_on_deploy()
        db.session.commit()

    def nodes_stage_assets(self, experiment):
        for node in self.nodes:
            node.stage_assets(experiment)
        db.session.commit()

    def start(self, participant):
        participant.start_module(self)

    def end(self, participant):
        participant.end_module(self)

    @classmethod
    def started_and_finished_times(cls, participants, module_id):
        logs = cls.state_class.query.filter_by(module_id=module_id, finished=True).all()
        return [
            {"time_started": log.time_started, "time_finished": log.time_finished}
            # "time_aborted": log.time_aborted,
            for log in logs
        ]

    @classmethod
    def median_finish_time_in_s(cls, participants, module_id):
        started_and_finished_times = cls.started_and_finished_times(
            participants, module_id
        )

        if not started_and_finished_times:
            return None

        durations_in_s = []
        for start_end_times in started_and_finished_times:
            if not (
                start_end_times["time_started"] and start_end_times["time_finished"]
            ):
                continue
            t1 = start_end_times["time_started"]
            t2 = start_end_times["time_finished"]
            durations_in_s.append((t2 - t1).total_seconds())

        if not durations_in_s:
            return None

        return median(sorted(durations_in_s))

    @classmethod
    def median_finish_time_in_min_and_s(cls, participants, module_id):
        return pretty_format_seconds(
            cls.median_finish_time_in_s(participants, module_id)
        )

    @property
    def aborted_participants(self):
        from .participant import Participant

        aborted_participants = (
            db.session.query(Participant)
            .filter(self.state_class.module_id == self.id, self.state_class.aborted)
            .all()
        )
        return sorted(
            [p for p in aborted_participants if self.id in p.aborted_modules],
            key=lambda p: p.module_states[self.id][0].time_aborted,
        )

    @property
    def started_participants(self):
        from .participant import Participant

        started_participants = (
            db.session.query(Participant)
            .filter(self.state_class.module_id == self.id, self.state_class.started)
            .all()
        )
        return sorted(
            [p for p in started_participants if self.id in p.started_modules],
            key=lambda p: p.module_states[self.id][0].time_started,
        )

    @property
    def finished_participants(self):
        from .participant import Participant

        finished_participants = (
            db.session.query(Participant)
            .filter(self.state_class.module_id == self.id, self.state_class.finished)
            .all()
        )
        return sorted(
            [p for p in finished_participants if self.id in p.finished_modules],
            key=lambda p: p.module_states[self.id][0].time_finished,
        )

    def resolve(self):
        return join(
            StartModule(self.id, module=self),
            self.elts,
            EndModule(self.id, module=self),
        )

    def visualize(self):
        if self.started_participants:
            time_started_last = (
                self.started_participants[-1].module_states[self.id][0].time_started
            )
        if self.finished_participants:
            time_finished_last = (
                self.finished_participants[-1].module_states[self.id][0].time_finished
            )
            median_finish_time_in_min_and_s = Module.median_finish_time_in_min_and_s(
                self.finished_participants, self.id
            )
        if self.aborted_participants:
            time_aborted_last = (
                self.aborted_participants[-1].module_states[self.id][0].time_aborted
            )

        div = tags.div()
        with div:
            with tags.h4():
                tags.b(f"Module: {self.id}")
            with tags.ul(cls="details"):
                tags.b("Participants:")
                if self.started_participants:
                    tags.li(
                        f"{len(self.started_participants)} started (last at {format_datetime(time_started_last)})"
                    )
                if self.finished_participants:
                    tags.li(
                        f"{len(self.finished_participants)} finished (last at {format_datetime(time_finished_last)})"
                    )
                if self.aborted_participants:
                    tags.li(
                        f"{len(self.aborted_participants)} aborted (last at {format_datetime(time_aborted_last)})"
                    )

                if self.finished_participants:
                    tags.br()
                    tags.li(
                        f"Median time spent to finish: {median_finish_time_in_min_and_s}"
                    )

        return div.render()

    def visualize_tooltip(self):
        if self.finished_participants:
            median_finish_time_in_min_and_s = Module.median_finish_time_in_min_and_s(
                self.finished_participants, self.id
            )

        span = tags.span()
        with span:
            tags.b(self.id)
            tags.br()
            tags.span(
                f"{len(self.started_participants)} started, {len(self.finished_participants)} finished,"
            )
            tags.br()
            tags.span(f"{len(self.aborted_participants)} aborted")
            if self.finished_participants:
                tags.br()
                tags.span(f"{median_finish_time_in_min_and_s} (median)")

        return span.render()

    def get_progress_info(self, participant_counts, **kwargs):
        target_n_participants = (
            self.target_n_participants
            if hasattr(self, "target_n_participants")
            else None
        )
        # TODO a more sophisticated calculation of progress
        progress = (
            participant_counts["finished"] / target_n_participants
            if target_n_participants is not None and target_n_participants > 0
            else 1
        )

        return {
            self.id: {
                "started_n_participants": participant_counts["started"],
                "finished_n_participants": participant_counts["finished"],
                "aborted_n_participants": participant_counts["aborted"],
                "target_n_participants": target_n_participants,
                "progress": progress,
            }
        }


class StartModule(NullElt):
    def __init__(self, label, module):
        super().__init__()
        self.label = label
        self.module = module

    def consume(self, experiment, participant):
        self.module.start(participant)

        if self.created_within_page_maker:
            self.module.deposit_assets_on_the_fly()


class EndModule(NullElt):
    def __init__(self, label, module):
        super().__init__()
        self.label = label
        self.module = module

    def consume(self, experiment, participant):
        self.module.end(participant)


class StartAccumulateAnswers(NullElt):
    def consume(self, experiment, participant):
        participant.answer_accumulators = participant.answer_accumulators + [{}]


class EndAccumulateAnswers(NullElt):
    def consume(self, experiment, participant):
        participant.answer = participant.answer_accumulators[-1]
        participant.answer_accumulators = participant.answer_accumulators[:-1]


class DatabaseCheck(NullElt):
    def __init__(self, label, function):
        super().__init__()
        self.label = label
        self.function = function

    def run(self):
        start_time = time.monotonic()
        logger.info("Executing the database check '%s'...", self.label)
        try:
            self.function()
            end_time = time.monotonic()
            time_taken = end_time - start_time
            logger.info(
                "The database check '%s' completed in %s seconds.",
                self.label,
                f"{time_taken:.3f}",
            )
        except Exception:
            logger.info(
                "An exception was thrown in the database check '%s'.",
                self.label,
                exc_info=True,
            )


class PreDeployRoutine(NullElt):
    """
    A timeline component that allows for the definition of tasks to be performed
    before deployment. It is possible to make database changes as part of these
    routines and these will be propagated to the deployed experiment.

    Parameters
    ----------

    label
        A label describing the pre-deployment task.

    function
        The name of a function to be executed.

    args
        The arguments for the function to be executed.
    """

    def __init__(self, label, function, args=None):
        super().__init__()
        if args is None:
            args = {}
        self.label = label
        self.function = function
        self.args = args


class ParticipantFailRoutine(NullElt):
    def __init__(self, label, function):
        super().__init__()
        self.label = label
        self.function = function


class RecruitmentCriterion(NullElt):
    def __init__(self, label, function):
        super().__init__()
        self.label = label
        self.function = function


FOR_LOOP_STACK_DEPTH = -1


def for_loop(
    *,
    label: str,
    iterate_over: Union[Sequence, Callable[..., Sequence]],
    logic: Union["TimelineLogic", Callable[..., "TimelineLogic"]],
    time_estimate_per_iteration: Optional[float] = None,
    expected_repetitions=None,
):
    if time_estimate_per_iteration is None:
        if callable(logic):
            raise ValueError(
                "If logic is a callable, then time_estimate_per_iteration must be provided"
            )
        else:
            time_estimate_per_iteration = CreditEstimate(logic).get_max("time")

    def estimate_num_repetitions(iterate_over):
        if not callable(iterate_over):
            return len(iterate_over)
        else:
            if len(get_args(iterate_over)) > 0:
                raise ValueError(
                    "If iterate_over takes arguments then expected_repetitions cannot be inferred automatically "
                    "and must be provided explicitly."
                )
            return len(iterate_over())

    def setup(experiment, participant):
        nonlocal iterate_over
        nonlocal label
        if callable(iterate_over):
            lst = call_function_with_context(
                iterate_over,
                experiment=experiment,
                participant=participant,
            )
        else:
            lst = iterate_over
        state = {"lst": lst, "index": 0}
        # participant.for_loops.append(state)
        if label in participant.for_loops:
            raise ValueError(
                f"Duplicated for_loop label detected: {label}. "
                "This suggests that you have tried to nest two for loops with the same label, "
                "which is not permitted. Please disambiguate the labels."
            )
        participant.for_loops[label] = state
        flag_modified(participant, "for_loops")

    def wrapup(experiment, participant):
        nonlocal label
        del participant.for_loops[label]
        flag_modified(participant, "for_loops")

    def content(experiment, participant):
        # global FOR_LOOP_STACK_DEPTH
        # FOR_LOOP_STACK_DEPTH += 1
        # state = participant.for_loops[FOR_LOOP_STACK_DEPTH]
        if not callable(logic):
            return logic
        nonlocal label
        state = participant.for_loops[label]
        lst = state["lst"]
        index = state["index"]
        input = lst[index]
        return call_function_with_context(
            logic,
            input,
            experiment=experiment,
            participant=participant,
        )

    def should_stay_in_loop(participant):
        nonlocal label
        # state = participant.for_loops[-1]
        state = participant.for_loops[label]
        return state["index"] < len(state["lst"])

    def increment_counter(participant):
        # state = participant.for_loops[-1]
        nonlocal label
        state = participant.for_loops[label]
        state["index"] += 1
        flag_modified(participant, "for_loops")

    return join(
        CodeBlock(setup),
        while_loop(
            "for_loop",
            should_stay_in_loop,
            logic=join(
                PageMaker(content, time_estimate_per_iteration),
                CodeBlock(increment_counter),
            ),
            expected_repetitions=(
                expected_repetitions
                if expected_repetitions
                else estimate_num_repetitions(iterate_over)
            ),
            fix_time_credit=False,
        ),
        CodeBlock(wrapup),
    )


def sequence(
    *,
    label: str,
    function: Callable,
    logic: list,
):
    """
    Administers a sequence of logical units in an order determined by a function.
    This could be used, for example, to determine the order of a series of questionnaires.
    See ``randomize`` for a special case where the order is randomized.

    Parameters
    ----------

    label:
        Internal label to assign to the construct.

    function:
        A function with up to two arguments named ``participant`` and ``experiment``,
        that is executed once the participant reaches the corresponding part of the timeline,
        returning a list of indices that will be used to determine the order of the sequence.

    logic:
        A list of logical units to be administered in the order determined by ``function``.
        Each element should be a unit of timeline logic, for example a trial maker
        or a sequence of Elts created through the join function.
    """
    assert isinstance(logic, list)

    for elt in logic:
        if isinstance(elt, (StartModule, StartSwitch)):
            raise ValueError(
                f"Saw an unexpected element within `sequence`: f{elt} ."
                "Perhaps you are misusing the function? "
                "`logic` should be a list where each element is a unit of timeline to be inserted into a sequence. "
                "This could be a page, or it could be a module, a trial maker, or something like that. "
                "Note that you do NOT want to pass the output of `join` directly to `sequence`."
            )

    sequence_length = len(logic)

    def initialize_sequence(participant, experiment):
        seq = call_function_with_context(
            function, participant=participant, experiment=experiment
        )
        assert isinstance(seq, list)
        assert len(seq) == sequence_length
        participant.sequences.append(seq)
        flag_modified(participant, "sequences")

    def sequence_is_not_finished(participant):
        return len(participant.sequences[-1]) > 0

    def get_current_position(participant):
        return participant.sequences[-1][0]

    def progress_sequence(participant):
        participant.sequences[-1].pop(0)
        flag_modified(participant, "sequences")

    def tear_down_sequence(participant):
        participant.sequences.pop()
        flag_modified(participant, "sequences")

    label = f"sequence_{label}"

    return join(
        CodeBlock(initialize_sequence),
        while_loop(
            label=label,
            condition=sequence_is_not_finished,
            logic=join(
                switch(
                    label=label,
                    function=get_current_position,
                    branches={i: logic[i] for i in range(sequence_length)},
                ),
                CodeBlock(progress_sequence),
            ),
            expected_repetitions=sequence_length,
            fix_time_credit=False,
        ),
        CodeBlock(tear_down_sequence),
    )


def randomize(*, label, logic):
    """
    Randomizes the order of a series of logical units.
    This could be used, for example, to randomize the order of a series of questionnaires.
    Each participant will receive a different random order.

    Parameters
    ----------

    label:
        Internal label to assign to the construct.

    logic:
        A list to be randomized.
        Each element should be a unit of timeline logic, for example a trial maker
        or a sequence of Elts created through the join function.
    """
    n = len(logic)
    return sequence(
        label=label,
        function=lambda participant: random.sample(range(n), k=n),
        logic=logic,
    )


class RegisterTrialMaker(NullElt):
    def __init__(self, trial_maker):
        super().__init__()
        self.trial_maker_id = trial_maker.id
        self.trial_maker = trial_maker


TimelineLogic = Union[Elt, List[Elt], EltCollection]
