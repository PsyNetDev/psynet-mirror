import json
import random
import shutil
import tempfile
import warnings
from collections.abc import Mapping
from typing import Callable, Dict, Iterable, List, Optional, Union

from dominate import tags
from dominate.dom_tag import dom_tag
from dominate.util import raw
from flask import current_app
from markupsafe import Markup

from .asset import Asset, LocalStorage
from .bot import BotResponse
from .chatroom import ChatRoom  # noqa: F401
from .javascript_hooks import JavaScriptContributor
from .static_resources import package_static_url
from .timeline import (
    Event,
    FailedValidation,
    MediaSpec,
    Page,
    Trigger,
    is_list_of,
)
from .utils import (
    NoArgumentProvided,
    as_plain_text,
    call_function,
    call_function_with_context,
    get_logger,
    get_translator,
    is_valid_html5_id,
    linspace,
)

logger = get_logger()


def _merge_js_var_sources(*sources):
    """Merge JavaScript variable sources, rejecting duplicate keys."""
    merged = {}
    owners = {}

    for source_name, values in sources:
        if not isinstance(values, Mapping):
            raise TypeError(f"{source_name} must provide a mapping.")

        for key, value in values.items():
            if key in owners:
                raise ValueError(
                    f"Duplicate JavaScript variable {key!r}: "
                    f"contributed by {owners[key]} and {source_name}."
                )

            merged[key] = value
            owners[key] = source_name

    return merged


class Blob:
    """
    Imitates the blob objects which are returned from the Flask front-end;
    used for testing.
    """

    def __init__(self, file):
        self.file = str(file)

    def save(self, dest):
        shutil.copyfile(self.file, dest)

    def __json__(self):
        return self.file


class Prompt(JavaScriptContributor):
    """
    The ``Prompt`` class displays some kind of media to the participant,
    to which they will have to respond.

    Currently the prompt must be written as a Jinja2 macro
    in ``templates/macros.html``. In the future, we will update the API
    to allow macros to be defined in external files.

    Parameters
    ----------

    text
        Optional text to display to the participant.
        This can either be a string, which will be HTML-escaped
        and displayed as regular text, or an HTML string
        as produced by ``markupsafe.Markup``.

    text_align
        CSS alignment of the text.

    buttons
        An optional list of additional buttons to include on the page.
        Normally these will be created by calls to :class:`psynet.modular_page.Button`.

    loop
        Whether or not the prompt should loop back to the beginning after finishing.
        Note: This is not yet implemented for all prompt types.


    Attributes
    ----------

    macro : str
        The name of the Jinja2 macro as defined within the respective template file.

    metadata : Object
        Metadata to save about the prompt; can take arbitrary form,
        but must be serialisable to JSON.

    media : MediaSpec
        Optional object of class :class:`~psynet.timeline.MediaSpec`
        that provisions media resources for the prompt.

    external_template : Optional[str]
        Optionally specifies a custom Jinja2 template from which the
        prompt macro should be sourced.
        If not provided, the prompt macro will be assumed to be located
        in PsyNet's built-in ``prompt.html`` file.
    """

    def __init__(
        self,
        text: Union[None, str, Markup] = None,
        text_align: str = "left",
        buttons: Optional[List] = None,
        loop: bool = False,
    ):
        self.text = text
        self.text_align = text_align
        self.loop = loop

        if isinstance(text, str) and not isinstance(text, Markup):
            self.text_html = tags.p(text)
        else:
            self.text_html = text

        if buttons is None:
            buttons = []

        self.buttons = buttons

    macro = "simple"
    external_template = None

    @property
    def metadata(self):
        return {}

    @property
    def media(self):
        return MediaSpec()

    def visualize(self, trial):
        if self.text is None:
            return ""
        elif isinstance(self.text, Markup):
            return str(self.text)
        else:
            return tags.p(self.text).render()

    def pre_render(self):
        pass

    def update_events(self, events):
        pass

    def get_js_vars(self):
        """Page-local JavaScript variables this component contributes.

        Keys must be unique across all page components and explicit
        :class:`ModularPage` ``js_vars``.
        """
        return {}

    def _collect_spa_markup_contract_codes(self):
        if self.text_html is None:
            return []

        return Page._collect_spa_markup_contract_codes(
            str(self.text_html),
            allow_scripts=True,
        )

    @property
    def plain_text(self):
        return as_plain_text(self.text_html)


class BaseAudioPrompt(Prompt):
    """
    A base class for miscellaneous audio prompts, including
    AudioPrompt and JSSynth.
    """

    def __init__(
        self,
        *args,
        controls: Union[bool, Iterable] = False,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.controls = self.preprocess_controls(controls)

    def preprocess_controls(self, controls: Union[bool, Iterable]):
        _ = get_translator()
        default_controls = {
            "Play": _("Play"),
            "Stop": _("Stop"),
            "Loop": _("Loop"),
        }

        if isinstance(controls, bool):
            if controls:
                controls = default_controls
            else:
                controls = {}

        if isinstance(controls, str):
            controls = {controls}

        if isinstance(controls, (set, list)):
            controls = {x: _(x) for x in controls}

        # For backwards compatibility: 'Play' used to be called 'Play from start'
        if "Play from start" in controls:
            controls["Play"] = controls.pop("Play from start")

        if not isinstance(controls, dict):
            raise ValueError(f"Invalid value for controls: {controls}")

        for key in controls.keys():
            if key not in default_controls:
                raise ValueError(f"{key} is not a valid control")

        return controls


class AudioPrompt(BaseAudioPrompt):
    """
    Plays an audio file to the participant.

    Parameters
    ----------

    audio
        Audio file to play.
        Can be an ``Asset`` object, or alternatively a URL written as a string.

    text
        Text to display to the participant. This can either be a string
        for plain text, or an HTML specification from ``markupsafe.Markup``.

    loop
        Whether the audio should loop back to the beginning after finishing.

    text_align
        CSS alignment of the text.

    play_window
        An optional two-element list identifying the time window in the audio file that
        should be played.
        If the first element is ``None``, then the audio file is played from the beginning;
        otherwise, the audio file starts playback from this timepoint (in seconds)
        (note that negative numbers will not be accepted here).
        If the second element is ``None``, then the audio file is played until the end;
        otherwise, the audio file finishes playback at this timepoint (in seconds).
        The behaviour is undefined when the time window extends past the end of the audio file.

    controls
        Whether to give the user playback controls, and which controls (default = ``False``).
        Accepts either a boolean or an iterable (dictionary, set, list).
        False results in no controls being displayed.
        True results in all controls being displayed (Play, Stop, Loop).
        An iterable can be used to select specific controls to display. A list, set, or dictionary with
        empty values will use standard labels. Custom labels can be specified as the dictionary values.
        A boolean, set, or list will result in automatically translated button labels if using translation.
        A dictionary will not be automatically translated - use this to specify custom values for button labels.

    fade_in
        Fade-in duration for the audio (defaults to ``0.0``).

    fade_out
        Fade-out duration for the audio (defaults to ``0.0``).

    kwargs
        Passed to :class:`~psynet.modular_page.Prompt`.
    """

    def __init__(
        self,
        audio,
        text: Union[str, Markup, dom_tag],
        loop: bool = False,
        text_align="left",
        play_window: Optional[List] = None,
        controls: Union[bool, Iterable] = False,
        fade_in: float = 0.0,
        fade_out: float = 0.0,
        **kwargs,
    ):
        from .asset import Asset

        if fade_out > 0.0:
            warnings.warn(
                "There is a bug in the underlying implementation of fade_out that causes the audio to stop playing "
                "prematurely when the audio device has high latency. This applies especially to Bluetooth devices. "
                "Until this bug is fixed, we recommend avoiding use of this parameter and instead editing the audio "
                "file itself to include a fade-out at the end."
            )

        if play_window is None:
            play_window = [None, None]
        assert len(play_window) == 2

        if play_window[0] is not None and play_window[0] < 0:
            raise ValueError("play_window[0] may not be less than 0")

        if isinstance(audio, Asset):
            url = audio.url
            assert url is not None
        elif isinstance(audio, str):
            url = audio
        else:
            raise TypeError(f"Invalid type for audio argument: {type(audio)}")

        super().__init__(text=text, text_align=text_align, loop=loop, **kwargs)

        self.url = url
        self.play_window = play_window
        self.controls = self.preprocess_controls(controls)

        self.js_play_options = dict(
            start=play_window[0],
            end=play_window[1],
            fade_in=fade_in,
            fade_out=fade_out,
        )

    macro = "audio"

    @property
    def metadata(self):
        return {
            "text": str(self.text),
            "url": self.url,
            "play_window": self.play_window,
        }

    @property
    def media(self):
        return MediaSpec(audio={"prompt": self.url})

    def visualize(self, trial):
        start, end = tuple(self.play_window)
        src = f"{self.url}#t={'' if start is None else start},{'' if end is None else end}"

        html = (
            super().visualize(trial)
            + "\n"
            + tags.audio(
                tags.source(src=src),
                id="visualize-audio-prompt",
                controls=self.controls,
            ).render()
        )
        return html

    def update_events(self, events):
        super().update_events(events)

        events["promptStart"] = Event(
            is_triggered_by=[
                Trigger(
                    triggering_event="trialStart",
                    delay=0,
                )
            ]
        )

        events["promptEnd"] = Event(is_triggered_by=[], once=False)
        events["trialFinish"].add_trigger("promptEnd")


class VideoPrompt(Prompt):
    """
    Plays a video file to the participant.

    Parameters
    ----------

    video
        Video file to play.
        Can be an ``Asset`` object, or alternatively a URL written as a string.

    text
        Text to display to the participant. This can either be a string
        for plain text, or an HTML specification from ``markupsafe.Markup``.

    text_align
        CSS alignment of the text.

    width
        Width of the video frame to be displayed. Default: "560px".

    height
        Height of the video frame to be displayed. Default is "auto"
        whereby the height is automatically adjusted to match the width.

    play_window
        An optional two-element list identifying the time window in the video file that
        should be played.
        If a list is provided, the first element must be a number specifying the timepoint in seconds
        at which the video should begin.
        The second element may then either be ``None``, in which case the video is played until the end,
        or a number specifying the timepoint in seconds at which the video should end.

    controls
        Determines whether the user should be given controls for manipulating video playback.

    muted
        If ``True``, then the video will be muted (i.e. it will play without audio).
        The default is ``False``.

    hide_when_finished
        If ``True`` (default), the video will disappear once it has finished playing.

    mirrored
        Whether to mirror the video on playback. Default: `False`.

    kwargs
        Passed to :class:`~psynet.modular_page.Prompt`.
    """

    def __init__(
        self,
        video,
        text: Union[str, Markup],
        text_align: str = "left",
        width: str = "560px",
        height: str = "auto",
        play_window: Optional[List] = None,
        controls: bool = False,
        muted: bool = False,
        hide_when_finished: bool = True,
        mirrored: bool = False,
        **kwargs,
    ):
        from .asset import Asset

        if play_window is None:
            play_window = [0.0, None]
        assert len(play_window) == 2
        assert play_window[0] is not None
        assert play_window[0] >= 0.0

        if isinstance(video, Asset):
            url = video.url
        elif isinstance(video, str):
            url = video
        else:
            raise TypeError(f"Invalid type for video argument: {type(video)}")

        super().__init__(text=text, text_align=text_align, **kwargs)

        self.url = url
        self.width = width
        self.height = height
        self.play_window = play_window
        self.mirrored = mirrored

        self.js_play_options = dict(
            start_at=play_window[0],
            end_at=play_window[1],
            muted=muted,
            controls=controls,
            hide_when_finished=hide_when_finished,
        )

    macro = "video"

    @property
    def metadata(self):
        return {
            "text": str(self.text),
            "url": self.url,
            "play_window": self.play_window,
            "mirrored": self.mirrored,
        }

    @property
    def media(self):
        return MediaSpec(video={"prompt": self.url})

    def visualize(self, trial):
        start, end = tuple(self.play_window)
        src = f"{self.url}#t={'' if start is None else start},{'' if end is None else end}"

        html = (
            super().visualize(trial)
            + "\n"
            + tags.video(
                tags.source(src=src), id="visualize-video-prompt", controls=True
            ).render()
        )
        return html

    def update_events(self, events):
        super().update_events(events)

        events["promptStart"] = Event(
            is_triggered_by=[
                Trigger(
                    triggering_event="trialStart",
                    delay=0,
                )
            ],
            once=True,
        )

        events["promptEnd"] = Event(is_triggered_by=None, once=False)
        events["trialFinish"].add_trigger("promptEnd")


class ImagePrompt(Prompt):
    """
    Displays an image to the participant.

    Parameters
    ----------

    url
        URL of the image to show.

    text
        Text to display to the participant. This can either be a string
        for plain text, or an HTML specification from ``markupsafe.Markup``.

    width
        CSS width specification for the image (e.g. ``'50%'``).

    height
        CSS height specification for the image (e.g. ``'50%'``).
        ``'auto'`` will choose the height automatically to match the width;
        the disadvantage of this is that other page content may move
        once the image loads.

    show_after
        Specifies the time in seconds when the image will be displayed, calculated relative to the start of the trial.
        Defaults to 0.0.

    hide_after
        If not ``None``, specifies a time in seconds after which the image should be hidden.

    margin_top
        CSS specification of the image's top margin.

    margin_bottom
        CSS specification of the image's bottom margin.

    text_align
        CSS alignment of the text.

    """

    def __init__(
        self,
        url: str,
        text: Union[str, Markup],
        width: str,
        height: str,
        show_after: float = 0.0,
        hide_after: Optional[float] = None,
        margin_top: str = "0px",
        margin_bottom: str = "0px",
        text_align: str = "left",
    ):
        super().__init__(text=text, text_align=text_align)
        if isinstance(url, Asset):
            url = url.url
        self.url = url
        self.width = width
        self.height = height
        self.show_after = show_after
        self.hide_after = hide_after
        self.margin_top = margin_top
        self.margin_bottom = margin_bottom

    macro = "image"

    @property
    def metadata(self):
        return {
            "text": str(self.text),
            "url": self.url,
            "show_after": self.show_after,
            "hide_after": self.hide_after,
        }

    def update_events(self, events):
        events["promptStart"] = Event(
            is_triggered_by="trialStart", delay=self.show_after
        )

        if self.hide_after is not None:
            events["promptEnd"] = Event(
                is_triggered_by="promptStart", delay=self.hide_after
            )


class ColorPrompt(Prompt):
    """
    Displays a color to the participant.

    Parameters
    ----------

    color
        Color to show, specified as a list of HSL values.

    text
        Text to display to the participant. This can either be a string
        for plain text, or an HTML specification from ``markupsafe.Markup``.

    width
        CSS width specification for the color box (default ``'200px'``).

    height
        CSS height specification for the color box (default ``'200px'``).

    text_align
        CSS alignment of the text.

    """

    def __init__(
        self,
        color: List[float],
        text: Union[str, Markup],
        width: str = "200px",
        height: str = "200px",
        text_align: str = "left",
    ):
        assert isinstance(color, list)
        super().__init__(text=text, text_align=text_align)
        self.hsl = color
        self.width = width
        self.height = height

    macro = "color"

    @property
    def metadata(self):
        return {"text": str(self.text), "hsl": self.hsl}


class Control(JavaScriptContributor):
    """
    The ``Control`` class provides some kind of controls for the participant,
    with which they will provide their response.

    Parameters
    ----------

    bot_response :
        Defines how bots respond to this page.
        Can be a single value, in which case this is interpreted as the participant's (formatted) answer.
        Alternatively, it can be an instance of class ``BotResponse``, which can accept more detailed
        information, for example:

        raw_answer :
            The raw_answer returned from the page.

        answer :
            The (formatted) answer, as would ordinarily be computed by ``format_answer``.

        metadata :
            A dictionary of metadata.

        blobs :
            A dictionary of blobs returned from the front-end.

        client_ip_address :
            The client's IP address.

    buttons :
        An optional list of additional buttons to include on the page.
        Normally these will be created by calls to :class:`psynet.modular_page.Button`.


    show_next_button :
        Determines whether a 'next' button is shown on the page.
        This button is used to submit the response to the present page.
        If this is not set to ``True``, then the response must be submitted another way,
        for example by triggering the event ``manualSubmit``.

    Attributes
    ----------

    macro : str
        The name of the Jinja2 macro as defined within the respective template file.

    metadata : Object
        Metadata to save about the prompt; can take arbitrary form,
        but must be serialisable to JSON.

    media : MediaSpec
        Optional object of class :class:`~psynet.timeline.MediaSpec`
        that provisions media resources for the controls.

    external_template : Optional[str]
        Optionally specifies a custom Jinja2 template from which the
        control macro should be sourced.
        If not provided, the control macro will be assumed to be located
        in PsyNet's built-in ``control.html`` file.
    """

    external_template = None

    def __init__(
        self,
        bot_response=NoArgumentProvided,
        buttons: Optional[List] = None,
        show_next_button: Optional[bool] = True,
    ):
        self.page = None
        self._bot_response = bot_response

        if buttons is None:
            buttons = []

        self.buttons = buttons
        self.show_next_button = show_next_button

    @property
    def macro(self):
        raise NotImplementedError

    @property
    def metadata(self):
        return {}

    def get_js_vars(self):
        """Page-local JavaScript variables this control contributes.

        See :meth:`Prompt.get_js_vars`.
        """
        return {}

    @property
    def media(self):
        return MediaSpec()

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

            5. ``trial``:
               An instantiation of :class:`psynet.trial.main.Trial`,
               corresponding to the participant's current trial,
               or ``None`` if the participant is not currently taking a trial.

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
        return None

    def visualize_response(self, answer, response, trial):
        return ""

    def pre_render(self):
        pass

    def update_events(self, events):
        pass

    def call__get_bot_response(self, experiment, bot, page, prompt):
        if self._bot_response == NoArgumentProvided:
            res = self.get_bot_response(experiment, bot, page, prompt)
        elif callable(self._bot_response):
            res = call_function_with_context(
                self._bot_response,
                experiment=experiment,
                bot=bot,
                participant=bot,
                page=page,
                prompt=prompt,
            )
        else:
            res = self._bot_response

        if not isinstance(res, BotResponse):
            res = BotResponse(answer=res)

        return res

    def get_bot_response(self, experiment, bot, page, prompt):
        """
        This function is used when a bot simulates a participant responding to a given page.
        In the simplest form, the function just returns the value of the
        answer that the bot returns.
        For more sophisticated treatment, the function can return a
        ``BotResponse`` object which contains other parameters
        such as ``blobs`` and ``metadata``.
        """
        raise NotImplementedError(
            f"The get_bot_response method for class {self.__class__.__name__} has yet to be implemented."
            "You will want to implement it yourself, or otherwise pass a bot_response argument to your page's constructor."
        )

    @property
    def plain_text(self) -> Optional[str]:
        return None


class NullControl(Control):
    """
    Here the participant just has a single button that takes them to the next page.
    """

    # The macro is named blank, not null, for back-compatibility reasons
    macro = "blank"
    metadata = {}

    def get_bot_response(self, experiment, bot, page, prompt):
        return None


class OptionControl(Control):
    """
    The OptionControl class provides four kinds of controls for the participant in its subclasses
    ``CheckboxControl``, ``DropdownControl``, ``PushButtonControl``, and ``RadioButtonControl``.
    """

    def __init__(
        self,
        choices: List[str],
        labels: Optional[List[str]] = None,
        style: str = "",
        bot_response=NoArgumentProvided,
        **kwargs,
    ):
        super().__init__(bot_response=bot_response, **kwargs)
        self.choices = choices
        self.labels = choices if labels is None else labels
        self.style = style

        assert isinstance(self.labels, list)
        assert len(self.choices) == len(self.labels)

    def validate_name(self, name):
        if not isinstance(name, str):
            raise ValueError("name must be a string")
        if not is_valid_html5_id(name):
            raise ValueError("name must be a valid HTML5 id")

    @property
    def input_type(self):
        raise NotImplementedError

    @property
    def metadata(self):
        return {
            "name": self.name,
            "choices": self.choices,
            "labels": self.labels,
            "force_selection": self.force_selection,
        }

    def get_bot_response(self, experiment, bot, page, prompt):
        return BotResponse(
            raw_answer=random.choice(self.choices),
            metadata=self.metadata,
        )

    @property
    def plain_text(self) -> Optional[str]:
        bullet_points = []

        for label in self.labels:
            if _is_html_markup(label):
                text = as_plain_text(label)
            else:
                text = label
            bullet_points.append(f"- {text}")

        return "\n".join(bullet_points)


def _is_html_markup(x):
    return isinstance(x, Markup) or isinstance(x, tags.html_tag)


class CheckboxControl(OptionControl):
    """
    This control interface solicits a multiple-choice response from the participant using checkboxes.

    Parameters
    ----------

    name:
        Name of the checkbox group.

    choices:
        The different options the participant has to choose from.

    labels:
        An optional list of textual labels to apply to the checkboxes,
        which the participant will see instead of ``choices``. Default: ``None``.

    arrange_vertically:
        Whether to arrange the checkboxes vertically. Default: ``True``.

    style:
        CSS style attributes to apply to the checkboxes. Default: ``""``.

    force_selection:
        Determines if at least checkbox has to be ticked. Default: False.

    show_reset_button
        Whether to display a 'Reset' button to allow for unsetting ticked checkboxes. Possible values are: `never`, `always`, and `on_selection`, the latter meaning that the button is displayed only when at least one checkbox is ticked. Default: ``never``.
    """

    input_type = "checkbox"

    def __init__(
        self,
        choices: List[str],
        labels: Optional[List[str]] = None,
        style: str = "",
        name: str = "checkboxes",
        arrange_vertically: bool = True,
        force_selection: bool = False,
        show_reset_button: str = "never",
    ):
        if show_reset_button != "never":
            buttons = [ResetButton()]
        else:
            buttons = []
        super().__init__(choices, labels, style, buttons=buttons)
        self.validate_name(name)
        self.name = name
        self.arrange_vertically = arrange_vertically
        self.force_selection = force_selection
        self.show_reset_button = show_reset_button

        self.checkboxes = [
            Checkbox(
                name=self.name,
                id_=choice,
                label=label,
                style=self.style,
            )
            for choice, label in zip(self.choices, self.labels)
        ]

    macro = "checkboxes"

    def visualize_response(self, answer, response, trial):
        html = tags.div()
        with html:
            for choice, label in zip(self.choices, self.labels):
                tags.input_(
                    type="checkbox",
                    id=choice,
                    name=self.name,
                    value=choice,
                    checked=(
                        True if answer is not None and choice in answer else False
                    ),
                )
                tags.span(label)
                tags.br()
        return html.render()

    def validate(self, response, **kwargs):
        _p = get_translator(context=True)
        if self.force_selection and len(response.answer) == 0:
            return FailedValidation(
                _p("validation", "You need to check at least one answer!")
            )
        return None


class Checkbox:
    def __init__(self, id_, *, name, label, start_disabled=False, style=""):
        self.id = id_
        self.name = name
        self.label = label
        self.start_disabled = start_disabled
        self.style = style


class DropdownControl(OptionControl):
    """
    This control interface solicits a multiple-choice response from the participant using a dropdown selectbox.

    Parameters
    ----------

    choices:
        The different options the participant has to choose from.

    labels:
        An optional list of textual labels to apply to the dropdown options,
        which the participant will see instead of ``choices``.

    style:
        CSS style attributes to apply to the dropdown. Default: ``""``.

    name:
        Name of the dropdown selectbox.

    force_selection
        Determines if an answer has to be selected. Default: True.
    """

    def __init__(
        self,
        choices: List[str],
        labels: Optional[List[str]] = None,
        style: str = "",
        name: str = "dropdown",
        force_selection: bool = True,
        default_text="Select an option",
    ):
        super().__init__(choices, labels, style)
        self.validate_name(name)
        self.name = name
        self.force_selection = force_selection
        self.default_text = default_text

        self.dropdown = [
            DropdownOption(value=value, text=text)
            for value, text in zip(self.choices, self.labels)
        ]

    macro = "dropdown"

    def visualize_response(self, answer, response, trial):
        html = tags.div(_class="dropdown-container")
        with html:
            tags.style(".dropdown-container { margin: 0 auto; width: fit-content; }")
            with tags.select(
                id=self.name,
                _class="form-control response",
                name=self.name,
                style="cursor: pointer;",
            ):
                for choice, label in zip(self.choices, self.labels):
                    if answer == choice:
                        tags.option(value=choice, selected=True).add(label)
                    else:
                        tags.option(value=choice).add(label)
        return html.render()

    def validate(self, response, **kwargs):
        _p = get_translator(context=True)
        if self.force_selection and response.answer == "":
            return FailedValidation(_p("validation", "You need to select an answer!"))
        return None


class DropdownOption:
    def __init__(self, value, text):
        self.value = value
        self.text = text


class PushButtonControl(OptionControl):
    """
    This control interface solicits a multiple-choice response from the participant.

    Parameters
    ----------

    choices:
        The different options the participant has to choose from.

    labels:
        An optional list of textual labels to apply to the buttons,
        which the participant will see instead of ``choices``. Default: ``None``.

    style:
        CSS styles to apply to the buttons. Default: ``"min-width: 100px; margin: 10px"``.

    arrange_vertically:
        Whether to arrange the buttons vertically. Default: ``True``.
    """

    def __init__(
        self,
        choices: List[Union[str, float, int]],
        labels: Optional[List[str]] = None,
        style: str = "min-width: 100px; margin: 10px",
        arrange_vertically: bool = True,
        show_next_button: bool = False,
        **kwargs,
    ):
        super().__init__(
            choices, labels, style, show_next_button=show_next_button, **kwargs
        )
        self.arrange_vertically = arrange_vertically

        self.push_buttons = [
            PushButton(
                button_id=choice,
                label=label,
                style=self.style,
                arrange_vertically=self.arrange_vertically,
                timed=self.timed,
            )
            for choice, label in zip(self.choices, self.labels)
        ]

    macro = "push_buttons"
    timed = False

    @property
    def metadata(self):
        return {"choices": self.choices, "labels": self.labels}

    def visualize_response(self, answer, response, trial):
        html = tags.div()
        with html:
            for choice, label in zip(self.choices, self.labels):
                response_string = response.response.replace('"', "")
                _class = "btn push-button btn-primary response submit"
                _class = (
                    _class.replace("btn-primary", "btn-success")
                    if response_string == choice
                    else _class
                )
                tags.button(
                    type="button",
                    id=choice,
                    _class=_class,
                    style=self.style,
                ).add(label)
                tags.br()
        return html.render()


def _validate_keycode(code):
    valid_prefixes = ["Key", "Digit", "F"]
    for prefix in valid_prefixes:
        if code.startswith(prefix) and len(code) == len(prefix) + 1:
            return True
    return False


class KeyboardPushButtonControl(PushButtonControl):
    """
    This extends the PushButtonControl to allow for keyboard input.

    Parameters
    ----------

    choices:
        The different options the participant has to choose from.

    keys:
        The keycodes corresponding to the choices. Need to be valid keycodes.

    validate_keycode:
        Validation function for the keycodes. Default: _validate_keycode, which allows letter, digit and F keys.

    kwargs:
        Other arguments to pass to :class:`~psynet.modular_page.PushButtonControl`.
    """

    macro = "keyboard_push_buttons"

    def __init__(
        self,
        choices: List[str],
        keys: List[str],
        validate_keycode: Callable[[str], str] = _validate_keycode,
        labels: Optional[List[str]] = None,
        **kwargs,
    ):
        assert len(choices) == len(keys)
        assert all([validate_keycode(key) for key in keys])
        assert all([len(keys) == len(set(keys))])

        super().__init__(
            choices=choices,
            labels=labels,
            **kwargs,
        )
        self.keys = keys

    @property
    def metadata(self):
        return {
            **super().metadata,
            "keys": self.keys,
        }


class TimedPushButtonControl(PushButtonControl):
    """
    This presents a multiple-choice push-button interface to the participant.
    The participant can press as many buttons as they like,
    and the timing of each press will be recorded.
    They advance to the next page by pressing a 'Next' button.

    Parameters
    ----------

    choices:
        The different options the participant has to choose from.

    labels:
        An optional list of textual labels to apply to the buttons,
        which the participant will see instead of ``choices``. Default: ``None``.

    button_highlight_duration:
        How long to highlight the button for once it has been clicked (seconds).
        Defaults to 0.75 s.

    style:
        CSS styles to apply to the buttons. Default: ``"min-width: 100px; margin: 10px"``.

    arrange_vertically:
        Whether to arrange the buttons vertically. Default: ``True``.

    **kwargs
        Other arguments to pass to :class:`~psynet.modular_page.PushButtonControl`.
    """

    timed = True

    def __init__(
        self,
        choices: List[str],
        labels: Optional[List[str]] = None,
        button_highlight_duration: float = 0.75,
        **kwargs,
    ):
        super().__init__(
            choices=choices, labels=labels, show_next_button=True, **kwargs
        )
        self.button_highlight_duration = button_highlight_duration

    def format_answer(self, raw_answer, **kwargs):
        return {**kwargs}["metadata"]["event_log"]

    def visualize_response(self, answer, response, trial):
        html = tags.div()
        with html:
            for choice, label in zip(self.choices, self.labels):
                response_string = response.response.replace('"', "")
                _class = "btn push-button btn-primary response timed"
                _class = (
                    _class.replace("btn-primary", "btn-success")
                    if response_string == choice
                    else _class
                )
                tags.button(
                    type="button",
                    id=choice,
                    _class=_class,
                    style=self.style,
                ).add(label)
                tags.br()
        return html.render()

    def get_bot_response(self, experiment, bot, page, prompt):
        event_log = [
            {
                "eventType": "trialConstruct",
                "localTime": "2025-07-29T14:50:04.301Z",
                "info": None,
            },
            {
                "eventType": "trialPrepare",
                "localTime": "2025-07-29T14:50:04.304Z",
                "info": None,
            },
            {
                "eventType": "trialStart",
                "localTime": "2025-07-29T14:50:04.304Z",
                "info": None,
            },
            {
                "eventType": "responseEnable",
                "localTime": "2025-07-29T14:50:04.309Z",
                "info": None,
            },
            {
                "eventType": "submitEnable",
                "localTime": "2025-07-29T14:50:04.309Z",
                "info": None,
            },
            {
                "eventType": "pushButtonClicked",
                "localTime": "2025-07-29T14:50:05.367Z",
                "info": {"buttonId": "A"},
            },
            {
                "eventType": "pushButtonClicked",
                "localTime": "2025-07-29T14:50:05.897Z",
                "info": {"buttonId": "B"},
            },
            {
                "eventType": "pushButtonClicked",
                "localTime": "2025-07-29T14:50:06.432Z",
                "info": {"buttonId": "C"},
            },
            {
                "eventType": "pushButtonClicked",
                "localTime": "2025-07-29T14:50:06.781Z",
                "info": {"buttonId": "B"},
            },
        ]
        return BotResponse(raw_answer=None, metadata={"event_log": event_log})


class PushButton:
    def __init__(
        self,
        button_id,
        *,
        label,
        style,
        arrange_vertically,
        start_disabled=False,
        timed=False,
    ):
        self.id = button_id
        self.label = label
        self.style = style
        self.start_disabled = start_disabled
        self.display = "block" if arrange_vertically else "inline"
        self.timed = timed


class RadioButtonControl(OptionControl):
    """
    This control interface solicits a multiple-choice response from the participant using radiobuttons.

    Parameters
    ----------

    choices:
        The different options the participant has to choose from.

    labels:
        An optional list of textual labels to apply to the radiobuttons,
        which the participant will see instead of ``choices``.

    style:
        CSS style attributes to apply to the radiobuttons. Default: ``"cursor: pointer"``.

    name:
        Name of the radiobutton group.

    arrange_vertically:
        Whether to arrange the radiobuttons vertically.

    force_selection
        Determines if an answer has to be selected. Default: ``True``.

    show_reset_button
        Whether to display a 'Reset' button to allow for unsetting a ticked radiobutton. Possible values are: `never`, `always`, and `on_selection`, the latter meaning that the button is displayed only when a radiobutton is ticked. Default: ``never``.

    show_free_text_option
        Appends a free text option to the radiobuttons. Default: ``False``.
    """

    input_type = "radio"

    def __init__(
        self,
        choices: List[str],
        labels: Optional[List[str]] = None,
        style: str = "cursor: pointer;",
        name: str = "radiobuttons",
        arrange_vertically: bool = True,
        force_selection: bool = True,
        show_reset_button: str = "never",
        show_free_text_option: bool = False,
        placeholder_text_free_text: str = None,
    ):
        if show_reset_button != "never":
            buttons = [ResetButton()]
        else:
            buttons = []
        super().__init__(choices, labels, style, buttons=buttons)
        self.validate_name(name)
        self.name = name
        self.arrange_vertically = arrange_vertically
        self.force_selection = force_selection
        self.show_reset_button = show_reset_button
        self.show_free_text_option = show_free_text_option
        self.placeholder_text_free_text = placeholder_text_free_text

        self.radiobuttons = [
            RadioButton(name=self.name, id_=choice, label=label, style=self.style)
            for choice, label in zip(self.choices, self.labels)
        ]
        if self.show_free_text_option:
            placeholder_text = (
                ""
                if self.placeholder_text_free_text is None
                else f'placeholder="{self.placeholder_text_free_text}"'
            )
            self.radiobuttons.append(
                RadioButton(
                    name=self.name,
                    id_="free_text",
                    label=Markup(
                        f"<input id='free_text_input' {placeholder_text} type='text'>"
                    ),
                    style=self.style,
                )
            )

    macro = "radiobuttons"

    def visualize_response(self, answer, response, trial):
        html = tags.div()
        with html:
            for choice, label in zip(self.choices, self.labels):
                tags.input_(
                    type="radio",
                    id=choice,
                    name=self.name,
                    value=choice,
                    checked=(True if choice == answer else False),
                )
                tags.span(label)
                tags.br()
        return html.render()

    def validate(self, response, **kwargs):
        _p = get_translator(context=True)
        if self.force_selection and response.answer is None:
            return FailedValidation(_p("validation", "You need to select an answer!"))
        return None


class RadioButton:
    def __init__(
        self, id_, *, name, label, start_disabled=False, style="cursor: pointer"
    ):
        self.id = id_
        self.name = name
        self.label = label
        self.start_disabled = start_disabled
        self.style = style


class NumberControl(Control):
    """
    This control interface solicits number input from the participant.

    Parameters
    ----------

    width:
        CSS width property for the text box. Default: `"120px"`.

    text_align:
        CSS width property for the alignment of the text inside the number input field. Default: `"right"`.
    """

    def __init__(
        self,
        width: Optional[str] = "120px",
        text_align: Optional[str] = "right",
        bot_response=NoArgumentProvided,
    ):
        super().__init__(bot_response=bot_response)
        self.width = width
        self.text_align = text_align

    macro = "number"

    @property
    def metadata(self):
        return {"width": self.width, "text_align": self.text_align}

    def validate(self, response, **kwargs):
        _p = get_translator(context=True)
        try:
            float(response.answer)
        except ValueError:
            return FailedValidation(_p("validation", "You need to provide a number!"))
        return None

    def get_bot_response(self, experiment, bot, page, prompt):
        return random.randint(20, 100)


class TextControl(Control):
    """
    This control interface solicits free text from the participant.

    Parameters
    ----------

    one_line:
        Whether the text box should comprise solely one line.

    width:
        CSS width property for the text box.

    height:
        CSS height property for the text box.

    text_align:
        CSS width property for the alignment of the text inside the text input field. Default: `"left"`.

    block_copy_paste:
        Whether to block the copy, cut and paste options in the text input box.
    """

    def __init__(
        self,
        one_line: bool = True,
        width: Optional[str] = None,  # e.g. "100px"
        height: Optional[str] = None,
        text_align: str = "left",
        block_copy_paste: bool = False,
        bot_response=NoArgumentProvided,
    ):
        super().__init__(bot_response)
        if one_line and height is not None:
            raise ValueError("If <one_line> is True, then <height> must be None.")

        self.one_line = one_line
        self.width = width
        self.height = height
        self.text_align = text_align
        self.block_copy_paste = block_copy_paste

    macro = "text"

    @property
    def metadata(self):
        return {
            "one_line": self.one_line,
            "width": self.width,
            "height": self.height,
            "text_align": self.text_align,
            "block_copy_paste": self.block_copy_paste,
        }

    def get_bot_response(self, experiment, bot, page, prompt):
        return "Hello, I am a bot!"


class MonitorControl(Control):
    """
    This Control records information about the participant's computer screen configuration. The participant just needs
    to press 'Next', and respond positively to a permissions request, then the information will be recorded
    automatically.
    """

    macro = "monitor"

    def get_bot_response(self, experiment, bot, page, prompt):
        return json.loads(
            """
{
    "currentScreen": {
        "left": -959,
        "top": -1440,
        "isPrimary": false,
        "isInternal": false,
        "devicePixelRatio": 1,
        "label": "VX3418-2KPC",
        "availHeight": 1415,
        "availLeft": -959,
        "availTop": -1415,
        "availWidth": 3440,
        "colorDepth": 24,
        "height": 1440,
        "width": 3440,
        "isExtended": true,
        "pixelDepth": 24
    },
    "screens": [
        {
            "left": -959,
            "top": -1440,
            "isPrimary": false,
            "isInternal": false,
            "devicePixelRatio": 1,
            "label": "VX3418-2KPC",
            "availHeight": 1415,
            "availLeft": -959,
            "availTop": -1415,
            "availWidth": 3440,
            "colorDepth": 24,
            "height": 1440,
            "width": 3440,
            "isExtended": true,
            "pixelDepth": 24
        },
        {
            "left": 0,
            "top": 0,
            "isPrimary": true,
            "isInternal": true,
            "devicePixelRatio": 2,
            "label": "Built-in Retina Display",
            "availHeight": 880,
            "availLeft": 0,
            "availTop": 38,
            "availWidth": 1512,
            "colorDepth": 30,
            "height": 982,
            "width": 1512,
            "isExtended": true,
            "pixelDepth": 30
        }
    ],
    "currentWindow": {
        "width": 1200,
        "height": 1284,
        "left": -937,
        "top": -1393
    }
}
"""
        )


class BaseButton:
    def render(self):
        raise NotImplementedError


class NextButton(BaseButton):
    def render(self):
        return "{{ psynet_controls.next_button(button_params) }}"


class ResetButton(BaseButton):
    def render(self):
        return "{{ psynet_controls.reset_button(control_config) }}"


class Button(BaseButton):
    """
    Buttons can be included into modular pages via the page's ``buttons`` argument.
    These buttons can be used to trigger custom events.

    Parameters
    ----------

    id_ :
        The button's ID. This must be written in camelCase.
        When the button is pressed, an event is triggered with this exact ID.

    text :
        Text to display on the button.

    style :
        Optional CSS styling for the button.

    is_response_button :
        If set to ``True``, then the button is treated as a 'response' button and is only enabled once
        the PsyNet responseEnable event is triggered.

    start_disabled :
        If set to ``True``, then the button starts disabled.

    disable_on_click :
        If set to ``True``, then the button is disabled when it is clicked, typically to avoid redundant clicks.
    """

    def __init__(
        self,
        id_: str,
        text: Union[str, dom_tag],
        style: str = "",
        is_response_button=False,
        start_disabled=False,
        disable_on_click=False,
    ):
        if not id_.startswith("button"):
            raise ValueError(
                "Button IDs must be in camelCase and start with the text 'button'."
            )

        if "_" in id_ or "-" in id_:
            raise ValueError(
                f"Invalid button ID '{id_}': button IDs must be written in camelCase."
            )

        self.id = id_
        self.text = text
        self.style = style
        self.is_response_button = is_response_button
        self.start_disabled = start_disabled
        self.disable_on_click = disable_on_click

    def render(self):
        return "{{ psynet_controls.generic_button(button_params) }}"

    @property
    def classes(self):
        classes = ["btn", "btn-primary", "btn-lg"]
        if self.is_response_button:
            classes.append("response")
        return " ".join(classes)


class StartButton(Button):
    def __init__(self):
        super().__init__(
            id_="buttonStart", text="Start", start_disabled=True, disable_on_click=True
        )


class ModularPage(Page):
    """
    The :class:`~psynet.modular_page.ModularPage`
    class provides a way of defining pages in terms
    of two primary components: the
    :class:`~psynet.modular_page.Prompt`
    and the
    :class:`~psynet.modular_page.Control`.
    The former determines what is presented to the participant;
    the latter determines how they may respond.

    Parameters
    ----------

    label
        Internal label to give the page, used for example in results saving.

    prompt
        A :class:`~psynet.modular_page.Prompt` object that
        determines the prompt to be displayed to the participant.
        Alternatively, you can also provide text or a ``markupsafe.Markup`` object,
        which will then be automatically wrapped in a :class:`~psynet.modular_page.Prompt` object.

    control
        A :class:`~psynet.modular_page.Control` object that
        determines the participant's response controls.

    time_estimate
        Time estimated for the page.

    media
        Optional specification of media assets to preload
        (see the documentation for :class:`psynet.timeline.MediaSpec`).
        Typically this field can be left blank, as media will be passed through the
        :class:`~psynet.modular_page.Prompt` or
        :class:`~psynet.modular_page.Control`
        objects instead.

    js_vars
        Optional dictionary of page-scoped values exposed to JavaScript through
        ``psynet.var``.

    start_trial_automatically
        If ``True`` (default), the trial starts automatically, e.g. by the playing
        of a queued audio file. Otherwise the trial will wait for the
        trialPrepare event to be triggered (e.g. by clicking a 'Play' button,
        or by calling `psynet.trial.registerEvent("trialPrepare")` in JS).

    buttons
        An optional list of additional buttons to include on the page.
        Normally these will be created by calls to :class:`psynet.modular_page.Button`.

    show_start_button
        Determines whether a 'start' button is shown on the page.
        The default is ``False``, but one might consider setting this to ``True`` if ``start_trial_automatically``
        is set to ``False``.

    show_next_button
        Determines whether a 'next' button is shown on the page.
        The default is ``None``, which means that the decision is deferred to the selected Control.
        If set to ``True`` or ``False``, the default from the Control is overridden.

    validate
        Optional validation function to use for the participant's response.
        If left blank, then the validation function will instead be read from the provided Control.
        Alternatively, the validation function can be set by overriding this class's ``validate`` method.
        If no validation function is found, no validation is performed.

        Validation functions provided via the present route may contain various optional arguments.
        Most typically the function will be of the form ``lambda answer: ...` or ``lambda answer, participant: ...``,
        but it is also possible to include the arguments ``raw_answer``, ``response``, ``page``, and ``experiment``.
        Note that ``raw_answer`` is the answer before applying ``format_answer``, and ``answer`` is the answer
        after applying ``format_answer``.

        Validation functions should return ``None`` if the validation passes,
        or if it fails a string corresponding to a message to pass to the participant.

        For example, a validation function testing that the answer contains exactly 3 characters might look like this:
        ``lambda answer: "Answer must contain exactly 3 characters!" if len(answer) != 3 else None``.

    layout
        Determines the layout of elements in the page.
        Should take the form of a list that enumerates the page elements in order of appearance.
        If left blank, defaults to ``.default_layout``.

    **kwargs
        Further arguments to be passed to :class:`psynet.timeline.Page`,
        including ``js_dependencies`` and ``js_page_modules``.
    """

    default_layout = ["prompt", "media", "progress", "control", "chatroom", "buttons"]

    def __init__(
        self,
        label: str,
        prompt: Union[str, dom_tag, Prompt],
        control: Optional[Control] = None,
        chatroom: Optional[ChatRoom] = None,
        time_estimate: Optional[float] = None,
        media: Optional[MediaSpec] = None,
        events: Optional[dict] = None,
        js_vars: Optional[dict] = None,
        start_trial_automatically: bool = True,
        buttons: Optional[List] = None,
        show_start_button: Optional[bool] = False,
        show_next_button: Optional[bool] = None,
        validate: Optional[callable] = None,
        layout=NoArgumentProvided,
        **kwargs,
    ):
        if control is None:
            control = NullControl()

        if media is None:
            media = MediaSpec()

        if js_vars is None:
            js_vars = {}

        if buttons is None:
            buttons = []

        if not isinstance(prompt, Prompt):
            prompt = Prompt(prompt)

        self.prompt = prompt
        self.control = control
        self.chatroom = chatroom

        if show_start_button:
            buttons.append(StartButton())

        buttons += prompt.buttons
        buttons += control.buttons

        if show_next_button or (show_next_button is None and control.show_next_button):
            buttons.append(NextButton())

        self.buttons = buttons

        if self.control.page is not None:
            raise ValueError(
                "This `Control` object already belongs to another `ModularPage` object. "
                "This usually happens if you create a single `Control` object and assign it "
                "to multiple modular pages. This pattern is not supported. Please instead "
                "create a fresh `Control` object to pass to this modular page. "
                "Hint: try replacing your original `Control` definition with a function that returns "
                "a fresh `Control` object each time."
            )
        self.control.page = self

        self._validate_function = validate

        if layout == NoArgumentProvided:
            layout = self.default_layout

        self.layout = layout

        template_str = f"""
        {{% extends "timeline-page.html" %}}

        {self.import_templates}

        {{% block main_body %}}
            {self.render_layout()}
        {{% endblock %}}
        """
        all_media = MediaSpec.merge(media, prompt.media, control.media)

        # Reusable components contribute page-local assets through hooks so they
        # do not need inline <style>/<script> (forbidden by the SPA contract).
        components = list(self._iter_layout_components())
        assets = self._collect_component_assets(components, kwargs)

        active_roles = {role: component for role, component in components}
        modular_page_components = {
            "prompt": (
                active_roles["prompt"].macro if "prompt" in active_roles else None
            ),
            "control": (
                active_roles["control"].macro if "control" in active_roles else None
            ),
            "chatroom": (
                active_roles["chatroom"].macro if "chatroom" in active_roles else None
            ),
        }
        js_var_sources = [
            (
                f"{role} {type(component).__name__}",
                component.get_js_vars(),
            )
            for role, component in components
        ]
        js_var_sources.extend(
            [
                ("ModularPage js_vars", js_vars),
                (
                    "PsyNet internals",
                    {"modular_page_components": modular_page_components},
                ),
            ]
        )

        super().__init__(
            label=label,
            time_estimate=time_estimate,
            template_str=template_str,
            template_arg={
                "prompt_config": prompt,
                "control_config": control,
                "chatroom_config": chatroom,
                "buttons": buttons,
            },
            media=all_media,
            events=events,
            js_vars=_merge_js_var_sources(*js_var_sources),
            start_trial_automatically=start_trial_automatically,
            validate=validate,
            framework_owned_template=True,
            **assets,
            **kwargs,
        )

    def _iter_layout_components(self):
        """Yield layout-active components that contribute page assets."""
        if "prompt" in self.layout:
            yield "prompt", self.prompt
        if "control" in self.layout:
            yield "control", self.control
        if self.chatroom is not None and "chatroom" in self.layout:
            yield "chatroom", self.chatroom

    @staticmethod
    def _collect_component_assets(components, kwargs):
        """Collect component assets and merge any matching caller kwargs."""
        css = [c for _, component in components for c in component.get_css()]
        css_links = [
            link for _, component in components for link in component.get_css_links()
        ]
        js_dependencies = [
            dependency
            for _, component in components
            for dependency in component.get_js_dependencies()
        ]
        js_page_modules = [
            module
            for _, component in components
            for module in component.get_js_page_modules()
        ]
        js_page_code = [
            code for _, component in components for code in component.get_js_page_code()
        ]

        assets = {
            "css": css,
            "css_links": css_links,
            "js_dependencies": js_dependencies,
            "js_page_code": js_page_code,
            "js_page_modules": js_page_modules,
        }
        for key, collected in assets.items():
            if key in kwargs:
                extra = kwargs.pop(key)
                collected.extend(extra if isinstance(extra, (list, tuple)) else [extra])
        return assets

    def _collect_spa_incompatibility_codes(self):
        codes = super()._collect_spa_incompatibility_codes()
        if "prompt" in self.layout:
            codes.extend(self.prompt._collect_spa_markup_contract_codes())
        codes.extend(self._collect_external_template_contract_codes())
        return list(dict.fromkeys(codes))

    def _collect_external_template_contract_codes(self):
        codes = []

        for role, template_name in self._external_template_sources:
            try:
                template_source = self._load_external_template_source(template_name)
            except RuntimeError as exc:
                # External templates need a Jinja app context. Skip only that
                # source so non-template SPA codes (legacy_*, js_page_code) still
                # surface during static checks without an app context.
                if "application context" in str(exc).lower():
                    continue
                raise
            codes.extend(Page._collect_spa_markup_contract_codes(template_source))

        return codes

    @property
    def _external_template_sources(self):
        # Match _iter_layout_components: only check templates that can render.
        seen = set()
        for role, component in self._iter_layout_components():
            template_name = component.external_template
            if template_name is None or template_name in seen:
                continue
            seen.add(template_name)
            yield role, template_name

    @staticmethod
    def _load_external_template_source(template_name):
        loader = current_app.jinja_env.loader
        source, _, _ = loader.get_source(current_app.jinja_env, template_name)
        return source

    def get_renderers(self, **kwargs):
        return {
            "prompt": "{{ %s(prompt_config) }}" % self.prompt_macro,
            "media": "{{ media.media_container() }}",
            "control": "{{ %s(control_config) }}" % self.control_macro,
            "buttons": self.render_buttons(),
            "progress": "{{ progress.trial_progress_display(trial_progress_display_config) }}",
            "chatroom": (
                "{{ %s(chatroom_config) }}" % self.chatroom_macro
                if self.chatroom is not None
                else ""
            ),
        }

    def render_layout(self, **kwargs):
        renderers = self.get_renderers()

        return "\n".join([renderers[key] for key in self.layout])

    def validate(self, response, **kwargs):
        if self._validate_function is None:
            return self.control.validate(response, **kwargs)
        else:
            return super().validate(response, **kwargs)

    def prepare_default_events(self):
        events = super().prepare_default_events()
        if "prompt" in self.layout:
            self.prompt.update_events(events)
        if "control" in self.layout:
            self.control.update_events(events)
        return events

    @property
    def prompt_macro(self):
        if self.prompt.external_template is None:
            location = "psynet_prompts"
        else:
            location = "custom_prompt"
        return f"{location}.{self.prompt.macro}"

    @property
    def control_macro(self):
        if self.control.external_template is None:
            location = "psynet_controls"
        else:
            location = "custom_control"
        return f"{location}.{self.control.macro}"

    @property
    def chatroom_macro(self):
        if self.chatroom.external_template is None:
            location = "psynet_chatroom"
        else:
            location = "custom_chatroom"
        return f"{location}.{self.chatroom.macro}"

    @property
    def import_templates(self):
        return self.import_internal_templates + self.import_external_templates

    def render_buttons(self):
        logic = []
        for i, button in enumerate(self.buttons):
            logic.append(f"{{% set button_params = buttons[{i}] %}}")
            logic.append(button.render())

        return "\n".join(logic)

    @property
    def import_internal_templates(self):
        # We explicitly import these internal templates here to ensure
        # they're imported by the time we try to call them.

        return """
        {% import "macros/prompt.html" as psynet_prompts %}
        {% import "macros/control.html" as psynet_controls %}
        {% import "macros/chatroom.html" as psynet_chatroom %}
        """

    @property
    def import_external_templates(self):
        return " ".join(
            [
                f'{{% import "{path}" as {name} with context %}}'
                for path, name in zip(
                    [
                        self.prompt.external_template,
                        self.control.external_template,
                        (
                            self.chatroom.external_template
                            if self.chatroom is not None
                            else None
                        ),
                    ],
                    ["custom_prompt", "custom_control", "custom_chatroom"],
                )
                if path is not None
            ]
        )

    def visualize(self, trial):
        prompt = self.prompt.visualize(trial)
        response = self.control.visualize_response(
            answer=trial.answer, response=trial.response, trial=trial
        )
        div = tags.div(id="trial-visualization")
        div_style = (
            "background-color: white; padding: 10px; "
            "margin-top: 10px; margin-bottom: 10px; "
            "border-style: solid; border-width: 1px;"
        )
        with div:
            if prompt != "":
                (tags.h3("Prompt"),)
                tags.div(raw(prompt), id="prompt-visualization", style=div_style)
            if prompt != "" and response != "":
                tags.br()
            if response != "":
                (tags.h3("Response"),)
                tags.div(raw(response), id="response-visualization", style=div_style)
        return div.render()

    def format_answer(self, raw_answer, **kwargs):
        """
        By default, the ``format_answer`` method is extracted from the
        page's :class:`~psynet.page.Control` member.
        """
        return self.control.format_answer(raw_answer=raw_answer, **kwargs)

    def metadata(self, **kwargs):
        """
        By default, the metadata attribute combines the metadata
        of the :class:`~psynet.page.Prompt` member.
        and the :class:`~psynet.page.Control` members.
        """
        return {"prompt": self.prompt.metadata, "control": self.control.metadata}

    def pre_render(self):
        """
        This method is called immediately prior to rendering the page for
        the participant. It will be called again each time the participant
        refreshes the page.
        """
        self.prompt.pre_render()
        self.control.pre_render()

    def get_bot_response(self, experiment, bot):
        page = self
        prompt = self.prompt
        return self.control.call__get_bot_response(experiment, bot, page, prompt)

    @property
    def plain_text(self) -> Optional[str]:
        prompt = self.prompt.plain_text
        control = self.control.plain_text
        text = []
        if prompt is not None:
            text.append(prompt)
        if control is not None:
            text.append(control)
        return "\n".join(text)


class AudioMeterControl(Control):
    macro = "audio_meter"

    def __init__(
        self,
        calibrate: bool = False,
        show_next_button: bool = True,
        min_time: float = 0.0,
        bot_response=NoArgumentProvided,
        **kwargs,
    ):
        if "submit_button" in kwargs:
            raise ValueError(
                "The 'submit_button' argument in AudioMeterControl has been renamed to 'show_next_button'."
            )
        super().__init__(bot_response, show_next_button=show_next_button, **kwargs)
        self.calibrate = calibrate
        self.min_time = min_time
        if calibrate:
            self.sliders = MultiSliderControl(
                [
                    Slider(
                        "decay-display",
                        "Decay (display)",
                        self.decay["display"],
                        0,
                        3,
                        0.001,
                    ),
                    Slider(
                        "decay-high",
                        "Decay (too high)",
                        self.decay["high"],
                        0,
                        3,
                        0.001,
                    ),
                    Slider(
                        "decay-low", "Decay (too low)", self.decay["low"], 0, 3, 0.001
                    ),
                    Slider(
                        "threshold-high",
                        "Threshold (high)",
                        self.threshold["high"],
                        -60,
                        0,
                        0.01,
                    ),
                    Slider(
                        "threshold-low",
                        "Threshold (low)",
                        self.threshold["low"],
                        -60,
                        0,
                        0.01,
                    ),
                    Slider(
                        "grace-high",
                        "Grace period (too high)",
                        self.grace["high"],
                        0,
                        5,
                        0.001,
                    ),
                    Slider(
                        "grace-low",
                        "Grace period (too low)",
                        self.grace["low"],
                        0,
                        5,
                        0.001,
                    ),
                    Slider(
                        "warn-on-clip", "Warn on clip?", int(self.warn_on_clip), 0, 1, 1
                    ),
                    Slider(
                        "msg-duration-high",
                        "Message duration (high)",
                        self.msg_duration["high"],
                        0,
                        10,
                        0.1,
                    ),
                    Slider(
                        "msg-duration-low",
                        "Message duration (low)",
                        self.msg_duration["low"],
                        0,
                        10,
                        0.1,
                    ),
                ]
            )
        else:
            self.slider = None

    display_range = {"min": -60, "max": 0}

    decay = {"display": 0.1, "high": 0.1, "low": 0.1}

    threshold = {"high": -2, "low": -20}

    grace = {"high": 0.0, "low": 1.5}

    warn_on_clip = True

    msg_duration = {"high": 0.25, "low": 0.25}

    def to_json(self):
        return Markup(
            json.dumps(
                {
                    "display_range": self.display_range,
                    "decay": self.decay,
                    "threshold": self.threshold,
                    "grace": self.grace,
                    "warn_on_clip": self.warn_on_clip,
                    "msg_duration": self.msg_duration,
                }
            )
        )

    def update_events(self, events):
        events["audioMeterMinimalTime"] = Event(
            is_triggered_by="trialStart", delay=self.min_time
        )
        events["submitEnable"].add_trigger("audioMeterMinimalTime")

    def get_bot_response(self, experiment, bot, page, prompt):
        return None


class TappingAudioMeterControl(AudioMeterControl):
    decay = {"display": 0.01, "high": 0, "low": 0.01}

    threshold = {"high": -2, "low": -20}

    grace = {"high": 0.2, "low": 1.5}

    warn_on_clip = False

    msg_duration = {"high": 0.25, "low": 0.25}


class SliderControl(Control):
    """
    This control interface displays either a horizontal or circular slider to the participant.

    The control logs all interactions from the participant including:
    - initial location of the slider
    - subsequent release points along with time stamps

    Currently the slider does not display any numbers describing the
    slider's current position. We anticipate adding this feature in
    a future release, if there is interest.

    Parameters
    ----------

    label:
        Internal label for the control (used to store results).

    start_value:
        Initial position of slider.

    min_value:
        Minimum value of the slider.

    max_value:
        Maximum value of the slider.

    n_steps:
        Determines the number of steps that the slider can be dragged through. Default: `10000`.

    snap_values:
        Optional. Determines the values to which the slider will 'snap' to once it is released.
        Can take various forms:

        - ``<None>``: no snapping is performed.

        - ``<int>``: indicating number of equidistant steps between `min_value` and `max_value`.

        - ``<list>``: list of numbers enumerating all possible values, need to be within `min_value` and `max_value`.

    reverse_scale:
        Flip the scale. Default: `False`.

    directional: default: True
        Make the slider appear in either grey/blue color (directional) or all grey color (non-directional).

    slider_id:
        The HTML id attribute value of the slider. Default: `"sliderpage_slider"`.

    input_type:
        Defaults to `"HTML5_range_slider"`, which gives a standard horizontal slider.
        The other option currently is `"circular_slider"`, which gives a circular slider.

    random_wrap:
        Defaults to `False`. If `True` then slider is wrapped twice so that there are no boundary jumps, and
        the phase to initialize the wrapping is randomized each time.

    minimal_interactions:
        Minimal interactions with the slider before the user can go to the next trial. Default: `0`.

    minimal_time:
        Minimum amount of time in seconds that the user must spend on the page before they can continue. Default: `0`.

    continuous_updates:
        If `True`, then the slider continuously calls slider-update events when it is dragged,
        rather than just when it is released. In this case the log is disabled. Default: `False`.

    template_filename:
        Filename of an optional additional template. Default: `None`.

    template_args:
        Arguments for the  optional additional template. Default: `None`.
    """

    def __init__(
        self,
        start_value: float,
        min_value: float,
        max_value: float,
        n_steps: int = 10000,
        reverse_scale: Optional[bool] = False,
        directional: Optional[bool] = True,
        slider_id: Optional[str] = "sliderpage_slider",
        input_type: Optional[str] = "HTML5_range_slider",
        random_wrap: Optional[bool] = False,
        snap_values: Optional[Union[int, list]] = None,
        minimal_interactions: Optional[int] = 0,
        minimal_time: Optional[int] = 0,
        continuous_updates: Optional[bool] = False,
        template_filename: Optional[str] = None,
        template_args: Optional[Dict] = None,
        bot_response=NoArgumentProvided,
    ):
        super().__init__(bot_response)

        if snap_values is not None and input_type == "circular_slider":
            raise ValueError(
                "Snapping values is currently not supported for circular sliders, set snap_values=None"
            )
        if input_type == "circular_slider" and reverse_scale:
            raise NotImplementedError(
                "Reverse scale is currently not supported for circular sliders, set reverse_scale=False"
            )

        self.start_value = start_value
        self.min_value = min_value
        self.max_value = max_value
        self.n_steps = n_steps
        self.step_size = (max_value - min_value) / (n_steps - 1)
        self.reverse_scale = reverse_scale
        self.directional = directional
        self.slider_id = slider_id
        self.input_type = input_type
        self.random_wrap = random_wrap
        self.template_filename = template_filename
        self.template_args = template_args
        self.minimal_time = minimal_time

        self.snap_values = self.format_snap_values(
            snap_values, min_value, max_value, n_steps
        )

        js_vars = {}
        js_vars["snap_values"] = self.snap_values
        js_vars["minimal_interactions"] = minimal_interactions
        js_vars["continuous_updates"] = continuous_updates
        self.js_vars = js_vars

    macro = "slider"

    def format_snap_values(self, snap_values, min_value, max_value, n_steps):
        if snap_values is None:
            return snap_values
            # return linspace(min_value, max_value, n_steps)
        elif isinstance(snap_values, int):
            return linspace(min_value, max_value, snap_values)
        else:
            for x in snap_values:
                assert isinstance(x, (float, int))
                assert x >= min_value
                assert x <= max_value
            return sorted(snap_values)

    def validate(self, response, **kwargs):
        if self.max_value <= self.min_value:
            raise ValueError("`max_value` must be larger than `min_value`")

        if self.start_value > self.max_value or self.start_value < self.min_value:
            raise ValueError(
                "`start_value` (= %f) must be between `min_value` (=%f) and `max_value` (=%f)"
                % (self.start_value, self.min_value, self.max_value)
            )

        if self.js_vars["minimal_interactions"] < 0:
            raise ValueError("`minimal_interactions` cannot be negative!")

    @property
    def metadata(self):
        return {
            "start_value": self.start_value,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "n_steps": self.n_steps,
            "step_size": self.step_size,
            "reverse_scale": self.reverse_scale,
            "directional": self.directional,
            "slider_id": self.slider_id,
            "input_type": self.input_type,
            "random_wrap": self.random_wrap,
            "template_filename": self.template_filename,
            "template_args": self.template_args,
            "js_vars": self.js_vars,
        }

    def update_events(self, events):
        events["sliderMinimalTime"] = Event(
            is_triggered_by="trialStart", delay=self.minimal_time
        )
        events["submitEnable"].add_triggers(
            "sliderMinimalInteractions", "sliderMinimalTime"
        )

    def get_bot_response(self, experiment, bot, page, prompt):
        import numpy as np

        equidistant = not isinstance(self.snap_values, list)
        if equidistant:
            if self.snap_values:
                n_candidates = self.snap_values
            else:
                n_candidates = self.n_steps
            candidates = list(
                np.linspace(self.min_value, self.max_value, num=n_candidates)
            )
        else:
            candidates = self.snap_values
        return random.sample(candidates, 1)[0]


EXTENSIONS = {
    "audio": ["wav", "mp3"],
    "image": ["jpg", "jpeg", "png", "gif", "svg"],
    "html": ["svg", "txt"],
    "video": ["mp4", "ogg"],
}


class MediaSliderControl(SliderControl):
    """
    This control solicits a slider response from the user that results in playing some media.
    The slider can either be horizontal or circular.

    Parameters
    ----------

    start_value:
        Initial position of slider.

    min_value:
        Minimum value of the slider.

    max_value:
        Maximum value of the slider.

    slider_media:
        A dictionary of media assets (image, video, or sound).
        Each item can either be a string,
        corresponding to the URL for a single file (e.g. "/static/audio/test.wav"),
        or a dictionary, corresponding to metadata for a batch of media assets.
        A batch dictionary must contain the field "url", providing the URL to the batch file,
        and the field "ids", providing the list of IDs for the batch's constituent assets.
        A valid audio argument might look like the following:

        ::

            {
                'example': '/static/example.wav',
                'my_batch': {
                    'url': '/static/file_concatenated.mp3',
                    'ids': ['funk_game_loop', 'honey_bee', 'there_it_is'],
                    'type': 'batch'
                }
            }

    modality:
        Either ``"audio"``,  ``"image"`` or ``"video"``.

    media_locations:
        Dictionary with IDs as keys and locations on the slider as values.

    autoplay:
        The media closest to the current slider position is shown once the page is loaded. Default: `False`.

    disable_while_playing : bool
        If `True`, the slider is disabled while the media is playing. Default: `False`.

        .. deprecated:: 11.0.0

            Use ``disable_slider_on_change`` instead.

    disable_slider_on_change:
        - ``<float>``: Duration for which the media slider should be disabled after its value changed, in seconds.

        - ``"while_playing"``: The slider will be disabled after a value change, as long as the related media is playing.

        - ``"never"``: The slider will not be disabled after a value change.

        Default: `never`.

    n_steps:
        - ``<int>``: Number of equidistant steps between `min_value` and `max_value` that the slider
          can be dragged through. This is before any snapping occurs.

        - ``"n_media"``: Sets the number of steps to the number of media. This only makes sense
          if the media locations are distributed equidistant between the `min_value` and `max_value` of the slider.

        Default: `10000`.

    slider_id:
        The HTML id attribute value of the slider. Default: `"sliderpage_slider"`.

    input_type:
        Defaults to `"HTML5_range_slider"`, which gives a standard horizontal slider.
        The other option currently is `"circular_slider"`, which gives a circular slider.

    random_wrap:
        Defaults to `False`. If `True` then original value of the slider is wrapped twice,
        creating a new virtual range between min and min+2(max-min). To avoid boundary issues,
        the phase of the slider is randomised for each slider using the new range. During the
        user interaction with the slider, we use the virtual wrapped value (`output_value`) in the
        new range and with the random phase, but at the end we use the unwrapped value in the original
        range and without random phase (`raw_value`). Both values are stored in the metadata.

    reverse_scale:
        Flip the scale. Default: `False`.

    directional: default: True
        Make the slider appear in either grey/blue color (directional) or all grey color (non-directional).

    snap_values:
        - ``"media_locations"``: slider snaps to nearest media location.

        - ``<int>``: indicates number of possible equidistant steps between `min_value` and `max_value`

        - ``<list>``: enumerates all possible values, need to be within `min_value` and `max_value`.

        - ``None``: don't snap slider.

        Default: `"media_locations"`.

    minimal_interactions:
        Minimal interactions with the slider before the user can go to the next trial. Default: `0`.

    minimal_time:
        Minimum amount of time in seconds that the user must spend on the page before they can continue. Default: `0`.

    continuous_updates:
        If `True`, then the slider continuously calls slider-update events when it is dragged,
        rather than just when it is released. In this case the log is disabled. Default: `False`.

    """

    def __init__(
        self,
        start_value: float,
        min_value: float,
        max_value: float,
        slider_media: dict,
        modality: str,
        media_locations: dict,
        autoplay: Optional[bool] = False,
        disable_while_playing: Optional[bool] = False,
        disable_slider_on_change: Optional[Union[float, str]] = "",
        n_steps: Optional[int] = 10000,
        slider_id: Optional[str] = "sliderpage_slider",
        input_type: Optional[str] = "HTML5_range_slider",
        random_wrap: Optional[bool] = False,
        reverse_scale: Optional[bool] = False,
        directional: bool = True,
        snap_values: Optional[Union[int, list]] = "media_locations",
        minimal_time: Optional[int] = 0,
        minimal_interactions: Optional[int] = 0,
    ):
        if modality not in EXTENSIONS.keys():
            raise NotImplementedError(f"Modality not implemented: {modality}")

        # Deals with the case where the values are numpy numbers
        media_locations = {k: float(v) for k, v in media_locations.items()}

        if isinstance(n_steps, str):
            if n_steps == "n_media":
                n_steps = len(media_locations)
            else:
                raise ValueError(f"Invalid value of n_steps: {n_steps}")

        if isinstance(snap_values, str):
            if snap_values == "media_locations":
                snap_values = list(media_locations.values())
            else:
                raise ValueError(f"Invalid value of snap_values: {snap_values}")

        # Check if all stimuli specified in `media_locations` are
        # also preloaded before the participant can start the trial
        IDs_media_locations = [ID for ID, _ in media_locations.items()]
        IDs_media = []
        for key, value in slider_media.items():
            if isinstance(slider_media[key], dict) and "ids" in slider_media[key]:
                ids = slider_media[key]["ids"]
                assert isinstance(ids, list)
                IDs_media += ids
            elif isinstance(slider_media[key], str):
                assert any(
                    [value.lower().endswith(ext) for ext in EXTENSIONS[modality]]
                ), (
                    f"Unsupported file extension: {value} (available extensions for {modality}: {EXTENSIONS[modality]})"
                )
                IDs_media.append(key)
            else:
                raise NotImplementedError(
                    "Currently we only support batch files or single files"
                )

        missing = [i for i in IDs_media_locations if i not in IDs_media]
        if missing:
            raise ValueError(
                "All stimulus IDs you specify in `media_locations` need to be defined in `media` too. "
                f"Missing: {missing}"
            )

        if disable_while_playing:
            warnings.warn(
                "disable_while_playing is deprecated, please migrate to disable_slider_on_change.",
                DeprecationWarning,
            )

        super().__init__(
            start_value=start_value,
            min_value=min_value,
            max_value=max_value,
            n_steps=n_steps,
            slider_id=slider_id,
            input_type=input_type,
            random_wrap=random_wrap,
            reverse_scale=reverse_scale,
            directional=directional,
            snap_values=snap_values,
            minimal_interactions=minimal_interactions,
            minimal_time=minimal_time,
        )

        self.media_locations = media_locations
        self.modality = modality
        self.autoplay = autoplay
        self.disable_while_playing = disable_while_playing
        self.disable_slider_on_change = disable_slider_on_change
        self.snap_values = snap_values
        self.slider_media = slider_media
        self.js_vars["modality"] = modality
        self.js_vars["media_locations"] = media_locations
        self.js_vars["autoplay"] = autoplay
        self.js_vars["disable_while_playing"] = (
            True
            if (
                disable_while_playing is True
                or type(disable_slider_on_change) is int
                or type(disable_slider_on_change) is float
                or disable_slider_on_change == "while_playing"
            )
            else False
        )
        self.js_vars["disable_duration"] = (
            disable_slider_on_change
            if (
                type(disable_slider_on_change) is int
                or type(disable_slider_on_change) is float
            )
            else 0
        )

    macro = "media_slider"

    @property
    def metadata(self):
        return {
            **super().metadata,
            "media_locations": self.media_locations,
            "modality": self.modality,
            "autoplay": self.autoplay,
            "disable_while_playing": self.disable_while_playing,
            "disable_slider_on_change": self.disable_slider_on_change,
        }


class AudioSliderControl(MediaSliderControl):
    """
    Audio slider control for backwards compatibility with `AudioSliderControl`.
    """

    def __init__(
        self,
        start_value: float,
        min_value: float,
        max_value: float,
        audio: dict,
        sound_locations: dict,
        autoplay: Optional[bool] = False,
        disable_while_playing: Optional[bool] = False,
        disable_slider_on_change: Optional[Union[float, str]] = "",
        n_steps: Optional[int] = 10000,
        slider_id: Optional[str] = "sliderpage_slider",
        input_type: Optional[str] = "HTML5_range_slider",
        random_wrap: Optional[bool] = False,
        reverse_scale: Optional[bool] = False,
        directional: bool = True,
        snap_values: Optional[Union[int, list]] = "sound_locations",
        minimal_interactions: Optional[int] = 0,
        minimal_time: Optional[int] = 0,
    ):
        if snap_values == "sound_locations":
            snap_values = "media_locations"
        if n_steps in ["n_sounds", "num_sounds"]:
            n_steps = "n_media"

        super().__init__(
            start_value=start_value,
            min_value=min_value,
            max_value=max_value,
            slider_media=audio,
            modality="audio",
            media_locations=sound_locations,
            autoplay=autoplay,
            disable_while_playing=disable_while_playing,
            disable_slider_on_change=disable_slider_on_change,
            n_steps=n_steps,
            slider_id=slider_id,
            input_type=input_type,
            random_wrap=random_wrap,
            reverse_scale=reverse_scale,
            directional=directional,
            snap_values=snap_values,
            minimal_interactions=minimal_interactions,
            minimal_time=minimal_time,
        )

    macro = "audio_media_slider"

    @property
    def metadata(self):
        return {
            **super().metadata,
            "sound_locations": self.media_locations,
            "autoplay": self.autoplay,
        }


class ImageSliderControl(MediaSliderControl):
    """
    This control solicits a slider response from the user that results in showing an image.
    The slider can either be horizontal or circular.

    Parameters
    ----------

    start_value:
        Initial position of slider.

    min_value:
        Minimum value of the slider.

    max_value:
        Maximum value of the slider.

    slider_media:
        A dictionary of media assets (image).
        Each item can either be a string,
        corresponding to the URL for a single file (e.g. "/static/image/test.png"),
        or a dictionary, corresponding to metadata for a batch of media assets.
        A batch dictionary must contain the field "url", providing the URL to the batch file,
        and the field "ids", providing the list of IDs for the batch's constituent assets.
        A valid image argument might look like the following:

        ::

            {
                'example': '/static/example.png',
                'my_batch': {
                    'url': '/static/file_concatenated.batch',
                    'ids': ['funk_game_loop', 'honey_bee', 'there_it_is'],
                    'type': 'batch'
                }
            }

    media_locations:
        Dictionary with IDs as keys and locations on the slider as values.

    autoplay:
        The media closest to the current slider position is shown once the page is loaded. Default: `False`.

    disable_slider_on_change:
        - ``<float>``: Duration for which the media slider should be disabled after its value changed, in seconds.

        - ``"while_playing"``: The slider will be disabled after a value change, as long as the related media is playing.

        - ``"never"``: The slider will not be disabled after a value change.

        Default: `never`.

    media_width:
        CSS width specification for the media container. The image will scale to the width of this container.

    media_height:
        CSS height specification for the media container.

    n_steps:
        - ``<int>``: Number of equidistant steps between `min_value` and `max_value` that the slider
          can be dragged through. This is before any snapping occurs.

        - ``"n_media"``: Sets the number of steps to the number of media. This only makes sense
          if the media locations are distributed equidistant between the `min_value` and `max_value` of the slider.

        Default: `10000`.

    slider_id:
        The HTML id attribute value of the slider. Default: `"sliderpage_slider"`.

    input_type:
        Defaults to `"HTML5_range_slider"`, which gives a standard horizontal slider.
        The other option currently is `"circular_slider"`, which gives a circular slider.

    random_wrap:
        Defaults to `False`. If `True` then original value of the slider is wrapped twice,
        creating a new virtual range between min and min+2(max-min). To avoid boundary issues,
        the phase of the slider is randomised for each slider using the new range. During the
        user interaction with the slider, we use the virtual wrapped value (`output_value`) in the
        new range and with the random phase, but at the end we use the unwrapped value in the original
        range and without random phase (`raw_value`). Both values are stored in the metadata.

    reverse_scale:
        Flip the scale. Default: `False`.

    directional: default: True
        Make the slider appear in either grey/blue color (directional) or all grey color (non-directional).

    snap_values:
        - ``"media_locations"``: slider snaps to nearest image location.

        - ``<int>``: indicates number of possible equidistant steps between `min_value` and `max_value`

        - ``<list>``: enumerates all possible values, need to be within `min_value` and `max_value`.

        - ``None``: don't snap slider.

        Default: `"media_locations"`.

    minimal_interactions:
        Minimal interactions with the slider before the user can go to the next trial. Default: `0`.

    minimal_time:
        Minimum amount of time in seconds that the user must spend on the page before they can continue. Default: `0`.

    continuous_updates:
        If `True`, then the slider continuously calls slider-update events when it is dragged,
        rather than just when it is released. In this case the log is disabled. Default: `False`.
    """

    def __init__(
        self,
        start_value: float,
        min_value: float,
        max_value: float,
        slider_media: dict,
        media_locations: dict,
        autoplay: Optional[bool] = False,
        disable_slider_on_change: Optional[Union[float, str]] = "",
        media_width: Optional[str] = "",
        media_height: Optional[str] = "",
        n_steps: Optional[int] = 10000,
        slider_id: Optional[str] = "sliderpage_slider",
        input_type: Optional[str] = "HTML5_range_slider",
        random_wrap: Optional[bool] = False,
        reverse_scale: Optional[bool] = False,
        directional: bool = True,
        snap_values: Optional[Union[int, list]] = "media_locations",
        minimal_time: Optional[int] = 0,
        minimal_interactions: Optional[int] = 0,
        continuous_updates: Optional[bool] = False,
    ):
        super().__init__(
            start_value=start_value,
            min_value=min_value,
            max_value=max_value,
            slider_media=slider_media,
            modality="image",
            media_locations=media_locations,
            autoplay=autoplay,
            disable_slider_on_change=disable_slider_on_change,
            n_steps=n_steps,
            slider_id=slider_id,
            input_type=input_type,
            random_wrap=random_wrap,
            reverse_scale=reverse_scale,
            directional=directional,
            snap_values=snap_values,
            minimal_time=minimal_time,
            minimal_interactions=minimal_interactions,
        )
        self.media_width = media_width
        self.media_height = media_height
        self.continuous_updates = continuous_updates
        self.js_vars["continuous_updates"] = continuous_updates

    macro = "image_media_slider"

    @property
    def metadata(self):
        return {
            **super().metadata,
            "continuous_updates": self.continuous_updates,
        }


class HtmlSliderControl(MediaSliderControl):
    """
    This control solicits a slider response from the user that results in showing an HTML element.
    The slider can either be horizontal or circular.

    Parameters
    ----------

    start_value:
        Initial position of slider.

    min_value:
        Minimum value of the slider.

    max_value:
        Maximum value of the slider.

    slider_media:
        A dictionary of media assets (image).
        Each item can either be a string,
        corresponding to the URL for a single file (e.g. "/static/image/test.svg"),
        or a dictionary, corresponding to metadata for a batch of media assets.
        A batch dictionary must contain the field "url", providing the URL to the batch file,
        and the field "ids", providing the list of IDs for the batch's constituent assets.
        A valid image argument might look like the following:

        ::

            {
                'example': '/static/example.svg',
                'my_batch': {
                    'url': '/static/file_concatenated.batch',
                    'ids': ['funk_game_loop', 'honey_bee', 'there_it_is'],
                    'type': 'batch'
                }
            }

    media_locations:
        Dictionary with IDs as keys and locations on the slider as values.

    autoplay:
        The media closest to the current slider position is shown once the page is loaded. Default: `False`.

    disable_slider_on_change:
        - ``<float>``: Duration for which the media slider should be disabled after its value changed, in seconds.

        - ``"while_playing"``: The slider will be disabled after a value change, as long as the related media is playing.

        - ``"never"``: The slider will not be disabled after a value change.

        Default: `never`.

    media_width:
        CSS width specification for the media container.

    media_height:
        CSS height specification for the media container.

    n_steps:
        - ``<int>``: Number of equidistant steps between `min_value` and `max_value` that the slider
          can be dragged through. This is before any snapping occurs.

        - ``"n_media"``: Sets the number of steps to the number of media. This only makes sense
          if the media locations are distributed equidistant between the `min_value` and `max_value` of the slider.

        Default: `10000`.

    slider_id:
        The HTML id attribute value of the slider. Default: `"sliderpage_slider"`.

    input_type:
        Defaults to `"HTML5_range_slider"`, which gives a standard horizontal slider.
        The other option currently is `"circular_slider"`, which gives a circular slider.

    random_wrap:
        Defaults to `False`. If `True` then original value of the slider is wrapped twice,
        creating a new virtual range between min and min+2(max-min). To avoid boundary issues,
        the phase of the slider is randomised for each slider using the new range. During the
        user interaction with the slider, we use the virtual wrapped value (`output_value`) in the
        new range and with the random phase, but at the end we use the unwrapped value in the original
        range and without random phase (`raw_value`). Both values are stored in the metadata.

    reverse_scale:
        Flip the scale. Default: `False`.

    directional: default: True
        Make the slider appear in either grey/blue color (directional) or all grey color (non-directional).

    snap_values:
        - ``"media_locations"``: slider snaps to nearest image location.

        - ``<int>``: indicates number of possible equidistant steps between `min_value` and `max_value`

        - ``<list>``: enumerates all possible values, need to be within `min_value` and `max_value`.

        - ``None``: don't snap slider.

        Default: `"media_locations"`.

    minimal_interactions:
        Minimal interactions with the slider before the user can go to the next trial. Default: `0`.

    minimal_time:
        Minimum amount of time in seconds that the user must spend on the page before they can continue. Default: `0`.

    continuous_updates:
        If `True`, then the slider continuously calls slider-update events when it is dragged,
        rather than just when it is released. In this case the log is disabled. Default: `False`.
    """

    def __init__(
        self,
        start_value: float,
        min_value: float,
        max_value: float,
        slider_media: dict,
        media_locations: dict,
        autoplay: Optional[bool] = False,
        disable_slider_on_change: Optional[Union[float, str]] = "",
        media_width: Optional[str] = "",
        media_height: Optional[str] = "",
        n_steps: Optional[int] = 10000,
        slider_id: Optional[str] = "sliderpage_slider",
        input_type: Optional[str] = "HTML5_range_slider",
        random_wrap: Optional[bool] = False,
        reverse_scale: Optional[bool] = False,
        directional: bool = True,
        snap_values: Optional[Union[int, list]] = "media_locations",
        minimal_time: Optional[int] = 0,
        minimal_interactions: Optional[int] = 0,
        continuous_updates: Optional[bool] = False,
    ):
        super().__init__(
            start_value=start_value,
            min_value=min_value,
            max_value=max_value,
            slider_media=slider_media,
            modality="image",
            media_locations=media_locations,
            autoplay=autoplay,
            disable_slider_on_change=disable_slider_on_change,
            n_steps=n_steps,
            slider_id=slider_id,
            input_type=input_type,
            random_wrap=random_wrap,
            reverse_scale=reverse_scale,
            directional=directional,
            snap_values=snap_values,
            minimal_time=minimal_time,
            minimal_interactions=minimal_interactions,
        )
        self.media_width = media_width
        self.media_height = media_height
        self.continuous_updates = continuous_updates
        self.js_vars["continuous_updates"] = continuous_updates

    macro = "html_media_slider"

    @property
    def metadata(self):
        return {
            **super().metadata,
            "continuous_updates": self.continuous_updates,
        }


class VideoSliderControl(MediaSliderControl):
    """
    This control solicits a slider response from the user that results in showing a video.
    The slider can either be horizontal or circular.

    Parameters
    ----------

    start_value:
        Initial position of slider.

    min_value:
        Minimum value of the slider.

    max_value:
        Maximum value of the slider.

    slider_media:
        A dictionary of media assets (video).
        Each item can either be a string,
        corresponding to the URL for a single file (e.g. "/static/image/test.mp4"),
        or a dictionary, corresponding to metadata for a batch of media assets.
        A batch dictionary must contain the field "url", providing the URL to the batch file,
        and the field "ids", providing the list of IDs for the batch's constituent assets.
        A valid image argument might look like the following:

        ::

            {
                'example': '/static/example.mp4',
                'my_batch': {
                    'url': '/static/file_concatenated.mp4',
                    'ids': ['funk_game_loop', 'honey_bee', 'there_it_is'],
                    'type': 'batch'
                }
            }

    media_locations:
        Dictionary with IDs as keys and locations on the slider as values.

    autoplay:
        The media closest to the current slider position is shown once the page is loaded. Default: `False`.

    disable_while_playing : bool
        If `True`, the slider is disabled while the media is playing. Default: `False`.

        .. deprecated:: 11.0.0

            Use ``disable_slider_on_change`` instead.

    disable_slider_on_change:
        - ``<float>``: Duration for which the media slider should be disabled after its value changed, in seconds.

        - ``"while_playing"``: The slider will be disabled after a value change, as long as the related media is playing.

        - ``"never"``: The slider will not be disabled after a value change.

        Default: `never`.

    media_width:
        CSS width specification for the media container. The video will scale to the width of this container.

    media_height:
        CSS height specification for the media container.

    n_steps:
        - ``<int>``: Number of equidistant steps between `min_value` and `max_value` that the slider
          can be dragged through. This is before any snapping occurs.

        - ``"n_media"``: Sets the number of steps to the number of media. This only makes sense
          if the media locations are distributed equidistant between the `min_value` and `max_value` of the slider.

        Default: `10000`.

    slider_id:
        The HTML id attribute value of the slider. Default: `"sliderpage_slider"`.

    input_type:
        Defaults to `"HTML5_range_slider"`, which gives a standard horizontal slider.
        The other option currently is `"circular_slider"`, which gives a circular slider.

    random_wrap:
        Defaults to `False`. If `True` then original value of the slider is wrapped twice,
        creating a new virtual range between min and min+2(max-min). To avoid boundary issues,
        the phase of the slider is randomised for each slider using the new range. During the
        user interaction with the slider, we use the virtual wrapped value (`output_value`) in the
        new range and with the random phase, but at the end we use the unwrapped value in the original
        range and without random phase (`raw_value`). Both values are stored in the metadata.

    reverse_scale:
        Flip the scale. Default: `False`.

    directional: default: True
        Make the slider appear in either grey/blue color (directional) or all grey color (non-directional).

    snap_values:
        - ``"media_locations"``: slider snaps to nearest video location.

        - ``<int>``: indicates number of possible equidistant steps between `min_value` and `max_value`

        - ``<list>``: enumerates all possible values, need to be within `min_value` and `max_value`.

        - ``None``: don't snap slider.

        Default: `"media_locations"`.

    minimal_interactions:
        Minimal interactions with the slider before the user can go to the next trial. Default: `0`.

    minimal_time:
        Minimum amount of time in seconds that the user must spend on the page before they can continue. Default: `0`.

    """

    def __init__(
        self,
        start_value: float,
        min_value: float,
        max_value: float,
        slider_media: dict,
        media_locations: dict,
        autoplay: Optional[bool] = False,
        disable_while_playing: Optional[bool] = False,
        disable_slider_on_change: Optional[Union[float, str]] = "never",
        media_width: Optional[str] = "",
        media_height: Optional[str] = "",
        n_steps: Optional[int] = 10000,
        slider_id: Optional[str] = "sliderpage_slider",
        input_type: Optional[str] = "HTML5_range_slider",
        random_wrap: Optional[bool] = False,
        reverse_scale: Optional[bool] = False,
        directional: bool = True,
        snap_values: Optional[Union[int, list]] = "media_locations",
        minimal_time: Optional[int] = 0,
        minimal_interactions: Optional[int] = 0,
        **kwargs,
    ):
        if "url" in kwargs or "file_type" in kwargs:
            raise ValueError(
                "VideoSliderControl has now been replaced with FrameSliderControl when it concerns sliding through the frames of a single video,"
                " please use the latter now. In case you want to slide through a series of videos, you can use VideoSliderControl. In that case, "
                "please specify slider_media and media_locations rather than url or file_type.",
            )
        super().__init__(
            start_value=start_value,
            min_value=min_value,
            max_value=max_value,
            slider_media=slider_media,
            modality="video",
            media_locations=media_locations,
            autoplay=autoplay,
            disable_while_playing=disable_while_playing,
            disable_slider_on_change=disable_slider_on_change,
            n_steps=n_steps,
            slider_id=slider_id,
            input_type=input_type,
            random_wrap=random_wrap,
            reverse_scale=reverse_scale,
            directional=directional,
            snap_values=snap_values,
            minimal_time=minimal_time,
            minimal_interactions=minimal_interactions,
        )
        self.media_width = media_width
        self.media_height = media_height

    macro = "video_media_slider"

    @property
    def metadata(self):
        return {
            **super().metadata,
            "media_locations": self.media_locations,
            "modality": self.modality,
            "autoplay": self.autoplay,
        }


# WIP
class ColorSliderControl(SliderControl):
    def __init__(
        self,
        start_value: float,
        min_value: float,
        max_value: float,
        slider_id: Optional[str] = "sliderpage_slider",
        hidden_inputs: Optional[dict] = {},
    ):
        super().__init__(
            start_value=start_value,
            min_value=min_value,
            max_value=max_value,
            slider_id=slider_id,
            hidden_inputs=hidden_inputs,
        )

    macro = "color_slider"

    @property
    def metadata(self):
        return {
            **super().metadata,
            "hidden_inputs": self.hidden_inputs,
        }


# WIP
class MultiSliderControl(Control):
    def __init__(
        self,
        sliders,
        next_button=True,
        bot_response=NoArgumentProvided,
    ):
        super().__init__(bot_response)
        assert is_list_of(sliders, Slider)
        self.sliders = sliders
        self.next_button = next_button


class Slider:
    def __init__(self, slider_id, label, start_value, min_value, max_value, step_size):
        self.label = label
        self.start_value = start_value
        self.min_value = min_value
        self.max_value = max_value
        self.step_size = step_size
        self.slider_id = slider_id


class RecordControl(Control):
    """
    Generic class for recording controls. Cannot be instantiated directly.
    See :class:`~psynet.modular_page.AudioRecordControl`
    and :class:`~psynet.modular_page.VideoRecordControl`.

    duration
        Duration of the desired recording, in seconds.
        Note: the output recording may not be exactly this length, owing to inaccuracies
        in the Javascript recording process.

    auto_advance
        Whether the page should automatically advance to the next page
        once the audio recording has been uploaded.

    show_meter
        Whether an audio meter should be displayed, so as to help the participant
        to calibrate their volume.
    """

    file_extension = None

    def __init__(
        self,
        duration: float,
        auto_advance: bool = False,
        show_meter: bool = False,
        bot_response=NoArgumentProvided,
        **kwargs,
    ):
        if "s3_bucket" in kwargs or "public_read" in kwargs:
            raise ValueError(
                "s3_bucket and public_read arguments have been removed from RecordControl classes, ",
                "please delete them from your implementation. Your S3 bucket is now determined by your "
                "S3Storage object, for example when you set asset_storage = S3Storage('my-bucket', 'my-root') "
                "within your Experiment class.",
            )
        for arg in kwargs:
            raise ValueError(f"Unexpected argument: {arg}")

        super().__init__(bot_response)
        self.duration = duration
        self.auto_advance = auto_advance

        if show_meter:
            self.meter = AudioMeterControl(show_next_button=False)
        else:
            self.meter = None

    @property
    def metadata(self):
        return {}

    def update_events(self, events):
        events["recordStart"] = Event(Trigger("responseEnable"))
        events["recordEnd"] = Event(Trigger("recordStart", delay=self.duration))
        events["submitEnable"].add_triggers("recordEnd")
        if self.auto_advance:
            events["autoSubmit"] = Event(is_triggered_by="submitEnable")
        # events["uploadEnd"] = Event(is_triggered_by=[])

    def get_bot_response_files(self, experiment, bot, page, prompt):
        if self.bot_response_media is None:
            self.raise_bot_response_not_provided_error()
        elif callable(self.bot_response_media):
            return call_function(
                self.bot_response_media,
                bot=bot,
                experiment=experiment,
                page=page,
                prompt=prompt,
            )
        else:
            return self.bot_response_media

    def raise_bot_response_not_provided_error(self):
        raise NotImplementedError


class AudioRecordControl(RecordControl):
    """
    Records audio from a participant.

    Parameters
    ----------

    controls
        Whether to give the user controls for the recorder (default = ``False``).

    loop_playback
        Whether in-browser playback of the recording should have looping enabled by default
        (default = ``False``). Ignored if ``controls`` is ``False``.

    num_channels
        The number of channels used to record the audio. Default is mono (`num_channels=1`).

    personal
        Whether the recording should be marked as 'personal' and hence excluded from 'scrubbed' data exports.
        Default: `True`.

    **kwargs
        Further arguments passed to :class:`~psynet.modular_page.RecordControl`
    """

    macro = "audio_record"
    file_extension = ".wav"

    def __init__(
        self,
        *,
        controls: bool = False,
        loop_playback: bool = False,
        num_channels: int = 1,
        personal=True,
        bot_response_media: Optional[Union[dict, str]] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)

        self.controls = controls
        self.loop_playback = loop_playback
        self.num_channels = num_channels
        self.personal = personal
        self.bot_response_media = bot_response_media

    def format_answer(self, raw_answer, **kwargs):
        blobs = kwargs["blobs"]
        audio = blobs["audioRecording"]
        trial = kwargs["trial"]
        participant = kwargs["participant"]

        if trial:
            parent = trial
        else:
            parent = participant

        # Need to leave file deletion to the depositing process
        # if we're going to run it asynchronously
        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            audio.save(tmp_file.name)

            from .trial.record import Recording

            label = self.page.label

            asset = Recording(
                local_key=label,
                input_path=tmp_file.name,
                extension=self.file_extension,
                parent=parent,
                personal=self.personal,
            )

            async_ = not isinstance(asset.default_storage, LocalStorage)
            asset.deposit(async_=async_, delete_input=True)

        return {
            "origin": "AudioRecordControl",
            "supports_record_trial": True,
            "asset_id": asset.id,
            "url": asset.url,
            "duration_sec": self.duration,  # TODO - base this on the actual audio file?
        }

    def visualize_response(self, answer, response, trial):
        if answer is None:
            return tags.p("No audio recorded yet.").render()
        else:
            return tags.audio(
                tags.source(src=answer["url"]),
                id="visualize-audio-response",
                controls=True,
            ).render()

    def update_events(self, events):
        super().update_events(events)
        events["trialFinish"].add_trigger("recordEnd")

    def get_bot_response(self, experiment, bot, page, prompt):
        from .bot import BotResponse

        file = self.get_bot_response_files(experiment, bot, page, prompt)

        return BotResponse(
            raw_answer=None,
            blobs={"audioRecording": Blob(file)},
        )

    def raise_bot_response_not_provided_error(self):
        raise NotImplementedError(
            "To use an AudioRecordControl with bots, you should set the bot_response_media argument "
            "to provide a path to an audio file that the bot should 'return'. "
            "This can be provided as a string, or alternatively as a function that returns a string, "
            "taking (optionally) any of the following arguments: bot, experiment, page, prompt."
        )


class VideoRecordControl(RecordControl):
    """
    Records a video either by using the camera or by capturing from the screen. Output format
    for both screen and camera recording is ``.webm``.

    Parameters
    ----------

    recording_source
        Specifies whether to record by using the camera and/or by capturing from the screen.
        Possible values are 'camera', 'screen' and 'both'.
        Default: 'camera'.

    record_audio
        Whether to record audio using the microphone.
        This setting only applies when 'camera' or 'both' is chosen as `recording_source`. Default: `True`.

    audio_n_channels
        The number of channels used to record the audio (if enabled by `record_audio`). Default is
        mono (`audio_n_channels=1`).

    width
        Width of the video frame to be displayed. Default: "560px".

    show_preview
        Whether to show a preview of the video on the page. Default: `False`.

    controls
        Whether to provide controls for manipulating the recording.

    loop_playback
        Whether to loop playback by default (only relevant if ``controls=True``.

    mirrored
        Whether the preview of the video is displayed as if looking into a mirror. Default: `True`.

    personal
        Whether the recording should be marked as 'personal' and hence excluded from 'scrubbed' data exports.
        Default: `True`.
    """

    macro = "video_record"
    file_extension = ".webm"

    def __init__(
        self,
        *,
        recording_source: str = "camera",
        record_audio: bool = True,
        audio_n_channels: int = 1,
        width: str = "300px",
        show_preview: bool = False,
        controls: bool = False,
        loop_playback: bool = False,
        mirrored: bool = True,
        personal: bool = True,
        bot_response_media: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)

        self.recording_source = recording_source
        self.record_audio = record_audio
        self.audio_n_channels = audio_n_channels
        self.width = width
        self.show_preview = show_preview
        self.controls = controls
        self.loop_playback = loop_playback
        self.mirrored = mirrored
        self.personal = personal
        self.bot_response_media = bot_response_media

        if self.record_audio is False:
            self.audio_n_channels = 0

        assert self.recording_source in ["camera", "screen", "both"]

    @property
    def recording_sources(self):
        return dict(camera=["camera"], screen=["screen"], both=["camera", "screen"])[
            self.recording_source
        ]

    def format_answer(self, raw_answer, **kwargs):
        blobs = kwargs["blobs"]
        trial = kwargs["trial"]
        participant = kwargs["participant"]

        if trial:
            parent = trial
        else:
            parent = participant

        summary = {}

        for source in self.recording_sources:
            blob_id = source + "Recording"
            blob = blobs[blob_id]

            with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
                blob.save(tmp_file.name)

                from .trial.record import Recording

                label = self.page.label
                if len(self.recording_sources) > 1:
                    label += "_" + source

                asset = Recording(
                    local_key=label,
                    input_path=tmp_file.name,
                    extension=self.file_extension,
                    parent=parent,
                    personal=self.personal,
                )

                try:
                    asset.deposit(async_=True, delete_input=True)
                except Asset.InconsistentContentError:
                    raise ValueError(
                        f"This participant already has an asset with the label '{label}'. "
                        "You should update your VideoRecordControl labels to make them distinct."
                    )

                summary[source + "_id"] = asset.id
                summary[source + "_url"] = asset.url

        summary.update(
            {
                "duration_sec": self.duration,
                "origin": "VideoRecordControl",
                "supports_record_trial": True,
                "recording_source": self.recording_source,
                "record_audio": self.record_audio,
                "mirrored": self.mirrored,
            }
        )

        return summary

    def visualize_response(self, answer, response, trial):
        if answer is None:
            return tags.p("No video recorded yet.").render()
        else:
            html = tags.div()
            if answer["camera_url"]:
                html += tags.h5("Camera recording")
                html += tags.video(
                    tags.source(src=answer["camera_url"]),
                    id="visualize-camera-video-response",
                    controls=True,
                    style="max-width: 640px;",
                )
            if answer["screen_url"]:
                html += tags.h5("Screen recording")
                html += tags.video(
                    tags.source(src=answer["screen_url"]),
                    id="visualize-screen-video-response",
                    controls=True,
                    style="max-width: 640px;",
                )
            return html.render()

    def update_events(self, events):
        super().update_events(events)
        events["trialFinish"].add_trigger("recordEnd")

    def get_bot_response(self, experiment, bot, page, prompt):
        from .bot import BotResponse

        files = self.get_bot_response_files(experiment, bot, page, prompt)

        return BotResponse(
            raw_answer=None,
            blobs={
                f"{key}Recording": Blob(files[key]) for key in self.recording_sources
            },
        )

    def get_bot_response_files(self, experiment, bot, page, prompt):
        files = super().get_bot_response_files(experiment, bot, page, prompt)

        if isinstance(files, str):
            assert len(self.recording_sources) == 1
            return {self.recording_source: files}
        elif isinstance(files, dict):
            assert set(files) == {"camera", "screen"}
            return files
        else:
            raise ValueError(f"Invalid files value: {files}")

    def raise_bot_response_not_provided_error(self):
        raise NotImplementedError(
            "To use an VideoRecordControl with bots, you should set the bot_response_media argument "
            "to provide a path to an audio file that the bot should 'return'. "
            "This can be provided as a string, or alternatively as a function that returns a string, "
            "taking (optionally) any of the following arguments: bot, experiment, page, prompt. "
            "If the VideoRecordControl is meant to provide both a screen recording and a camera recording, "
            "you should return a dictionary with two file paths, keyed as 'screen' and 'camera'."
        )


class FrameSliderControl(Control):
    macro = "frame_slider"

    def __init__(
        self,
        *,
        url: str,
        file_type: str,
        width: str,
        height: str,
        starting_value: float = 0.5,
        minimal_time: float = 2.0,
        reverse_scale: bool = False,
        directional: bool = True,
        hide_slider: bool = False,
        bot_response=NoArgumentProvided,
    ):
        super().__init__(bot_response)

        assert 0 <= starting_value <= 1

        self.url = url
        self.file_type = file_type
        self.width = width
        self.height = height
        self.starting_value = starting_value
        self.minimal_time = minimal_time
        self.reverse_scale = reverse_scale
        self.directional = directional
        self.hide_slider = hide_slider

    @property
    def metadata(self):
        return {
            "url": self.url,
            "starting_value": self.starting_value,
            "minimal_time": self.minimal_time,
            "reverse_scale": self.reverse_scale,
            "directional": self.directional,
            "hide_slider": self.hide_slider,
        }

    @property
    def media(self):
        return MediaSpec(video={"slider-video": self.url})

    def visualize_response(self, answer, response, trial):
        html = (
            super().visualize_response(answer, response, trial)
            + "\n"
            + tags.div(
                tags.p(f"Answer = {answer}"),
                tags.video(
                    tags.source(src=self.url),
                    id="visualize-video-slider",
                    controls=True,
                    style="max-width: 400px;",
                ),
            ).render()
        )
        return html

    def update_events(self, events):
        events["sliderMinimalTime"] = Event(
            is_triggered_by="trialStart", delay=self.minimal_time
        )
        events["submitEnable"].add_triggers(
            "sliderMinimalTime",
        )

    def get_bot_response(self, experiment, bot, page, prompt):
        return random.uniform(0, 1)


class SurveyJSControl(Control):
    """
    This control exposes the open-source SurveyJS library.
    You can use this library to develop sophisticated questionnaires which
    many different question types.

    When a SurveyJSControl is included in a PsyNet timeline it produces a single
    SurveyJS survey. This survey can have multiple questions and indeed multiple pages.
    Responses to these questions are compiled together as a dictionary and saved
    as the participant's answer, similar to other controls.

    The recommended way to design a SurveyJS survey is to use their free Survey Creator tool.
    This can be accessed from their website: https://surveyjs.io/create-free-survey.
    You design your survey using the interactive editor.
    Once you are done, click the "JSON Editor" tab. Copy and paste the provided JSON
    into the ``design`` argument of your ``SurveyJSControl``. You may need to update a few details
    to match Python syntax, for example replacing ``true`` with ``True``; your syntax highlighter
    should flag up points that need updating. That's it!

    See https://surveyjs.io/ for more details.

    See the survey_js demo for example usage.

    Parameters
    ----------

    design :
        A JSON-style specification for the survey.

    bot_response :
        Used for bot simulations; see demos for example usage.
    """

    def __init__(
        self,
        design,
        bot_response=NoArgumentProvided,
        show_question_numbers: bool = False,
        show_question_titles: bool = True,
    ):
        self.show_question_numbers = show_question_numbers
        self.show_question_titles = show_question_titles

        if not self.show_question_titles:
            design["questionTitleLocation"] = "hidden"

        self.design = design

        super().__init__(
            bot_response,
            show_next_button=self.use_psynet_next_button,
        )

    macro = "survey_js"

    @property
    def use_psynet_next_button(self):
        # We only use the PsyNet next button if the survey only has one page.
        # Otherwise we use the SurveyJS navigation buttons.
        return "pages" not in self.design

    @property
    def show_required_marks(self):
        return True

    def get_bot_response(self, experiment, bot, page, prompt):
        raise NotImplementedError

    def format_answer(self, raw_answer, **kwargs):
        if raw_answer is None:
            return None
        return json.loads(raw_answer)

    def get_css(self):
        css = super().get_css()
        css.append(
            """
            /* A better way to apply styles would be to use SurveyJS's theming functionality.
            However we think we need to upgrade to SurveyJS v2.0.0 to do this.
            For now we instead use CSS selectors for styling.
            */

            /* We tried using CSS variables but this didn't work for some reason.
            :root {
                --sjs-primary-backcolor: #0d6efd !important;
                --sjs-general-backcolor-dim: #FFFFFF !important;
            }
            */

            /* Instead we use class selectors. */
            .sd-btn {
                /* Changing the colors would make sense but it proved complicated what
                with the different button types and the rollover effects.
                It doesn't seem the worst thing to leave it as is though. */
                /* background-color: #0d6efd !important; */
                font-family: Inter, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", "Noto Sans", "Liberation Sans", Arial, sans-serif !important;
                font-size: 20px !important;
                font-weight: 400 !important;
                max-width: 250px !important;
            }
            /* This removes the grey background from the survey container. */
            .sd-container-modern {
                background-color: #FFFFFF !important;
            }
            /* This removes the shadow from the survey elements. */
            .sd-element--with-frame:not(.sd-element--collapsed) {
                box-shadow: 0px 0px 0px !important;
            }
            """
        )
        if self.use_psynet_next_button:
            # We wait to show the next button until the SurveyJS survey has loaded,
            # to avoid content moving around during page load.
            css.append(
                """
                #next-button {
                    visibility: hidden;
                }
                """
            )

        if not self.show_required_marks:
            # We should be able to use design["requiredMark"] but maybe this is not
            # available in our current version of surveyJS (< 2.0.0).
            css.append(
                """
                .sd-question__required-text {
                    display: none !important;
                """
            )
        # We considered programmatically hiding the complete button via CSS,
        # but the problem is that the survey retains a navigation placeholder div
        # that still consumes space on the page.
        # Instead we have set survey.showNavigationButtons = false in the HTML template.
        # This is also imperfect because it prevents us from displaying other navigation
        # buttons in the future. The best next step would be to upgrade to SurveyJS v2.0.0,
        # which will allow us to set survey.showCompleteButton = false.
        # Keeping the code below in case it's useful in the future:
        # if self.use_psynet_next_button:
        #     css.append(
        #         """
        #         .sd-navigation__complete-btn {
        #             display: none !important;
        #         }
        #         """
        #     )
        return css

    def update_events(self, events):
        super().update_events(events)
        if self.use_psynet_next_button:
            events["showNextButton"] = Event(
                is_triggered_by="trialConstruct",
                js="$('#next-button').css('visibility', 'visible');",
            )


class MultiRatingControl(SurveyJSControl):
    """
    A control that allows the participant to rate multiple items at once.

    Parameters
    ----------

    scales :
        One or more RatingScale objects.

    bot_response :
        An optional argument that can be used to specify a response delivered by automatic bots to this page.

    show_question_numbers :
        Whether to show question numbers (default: False).

    show_question_titles :
        Whether to show question titles (default: True).
    """

    def __init__(
        self,
        *scales: "RatingScale",
        bot_response=NoArgumentProvided,
        show_question_numbers: bool = False,
        show_question_titles: bool = True,
    ):
        self.scales = scales

        design = {
            "elements": [scale.design for scale in scales],
            "showQuestionNumbers": "true" if show_question_numbers else "false",
        }

        super().__init__(
            design,
            bot_response,
            show_question_numbers=show_question_numbers,
            show_question_titles=show_question_titles,
        )

    def get_bot_response(self, experiment, bot, page, prompt):
        return {
            scale.name: scale.get_bot_response(experiment, bot, page, prompt)
            for scale in self.scales
        }

    def format_answer(self, raw_answer, **kwargs):
        answer = super().format_answer(raw_answer, **kwargs)
        return {scale.name: answer.get(scale.name, None) for scale in self.scales}

    @property
    def show_required_marks(self):
        """
        We only show required marks (asterisks by questions that are required)
        if only some of the questions in the set are required.
        """
        all_required = all(scale.required for scale in self.scales)
        all_not_required = all(not scale.required for scale in self.scales)
        return not (all_required or all_not_required)


class RatingControl(MultiRatingControl):
    """
    A control that allows the participant to give a rating on a single scale.

    Parameters
    ----------

    values:
        A list of values for the rating scale.
        The values can be provided in a variety of formats:

        - A single integer, in which case the scale will take values ranging from 1 to the integer.
        - A list of strings, in which case the scale will take values ranging from 1 to the length of the list,
          and the labels will be the strings in the list.
        - A list of floats, in which case the scale will take these floats as values.
        - A dictionary of strings to floats, in which case the floats will be used as values
          and the strings will be used as labels.

    min_description :
        An optional description for the minimum value of the scale.

    max_description :
        An optional description for the maximum value of the scale.

    required :
        Whether the question is required (default: True).

    bot_response :
        An optional argument that can be used to specify a response delivered by automatic bots to this page.
    """

    def __init__(
        self,
        values: int | list[float] | list[str] | dict[str, float],
        min_description: Optional[str] = None,
        max_description: Optional[str] = None,
        required: bool = True,
        bot_response=NoArgumentProvided,
    ):
        scale = RatingScale(
            name="rating",
            values=values,
            min_description=min_description,
            max_description=max_description,
            required=required,
        )
        super().__init__(
            scale,
            bot_response=bot_response,
            show_question_titles=False,
        )

    def format_answer(self, raw_answer, **kwargs):
        answer = super().format_answer(raw_answer, **kwargs)
        return answer.get("rating", None)


class RatingScale:
    """
    A class that represents a single rating scale.

    Parameters
    ----------

    name :
        The name of the scale. This will be used as the key in the participant's answer.

    values :
        A list of values for the rating scale.
        The values can be provided in a variety of formats:

        - A single integer, in which case the scale will take values ranging from 1 to the integer.
        - A list of strings, in which case the scale will take values ranging from 1 to the length of the list,
          and the labels will be the strings in the list.
        - A list of floats, in which case the scale will take these floats as values.
        - A dictionary of strings to floats, in which case the floats will be used as values
          and the strings will be used as labels.

    min_description :
        An optional description for the minimum value of the scale.

    max_description :
        An optional description for the maximum value of the scale.

    title :
        An optional title for the scale.

    description :
        An optional description for the scale.

    required :
        Whether the question is required (default: True).
    """

    def __init__(
        self,
        name: str,
        values: int | list[float] | list[str] | dict[str, float],
        min_description: Optional[str] = None,
        max_description: Optional[str] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
        required: bool = True,
    ):
        self.name = name
        self.min_description = min_description
        self.max_description = max_description
        self.title = title
        self.description = description
        self.required = required
        self.values, self.labels = self.get_values_and_labels(values)
        self.design = self.get_design()

    @staticmethod
    def get_values_and_labels(values):
        """
        Unpacks the input values (which has a variety of possible formats)
        into a standard format.

        Returns
        -------

        - values: a list of values for the rating scale
        - labels: a corresponding list of labels
        """
        if isinstance(values, (int, float)):
            assert values > 0
            values = list(range(1, values + 1))

        assert len(values) > 0

        if isinstance(values, dict):
            labels = list(values.keys())
            values = list(values.values())
        elif isinstance(values[0], (int, float)):
            values = values
            labels = [str(value) for value in values]
        elif isinstance(values[0], str):
            labels = values
            values = list(range(1, len(values) + 1))
        else:
            raise ValueError(f"Invalid values: {values}")

        return values, labels

    def get_design(self):
        design = {}

        design["type"] = "rating"
        design["name"] = self.name
        design["isRequired"] = self.required

        if self.min_description:
            design["minRateDescription"] = self.min_description
        if self.max_description:
            design["maxRateDescription"] = self.max_description

        if self.title:
            design["title"] = self.title

        if self.description:
            design["description"] = self.description

        design["rateValues"] = [
            {
                "value": value,
                "text": label,
            }
            for value, label in zip(self.values, self.labels)
        ]

        return design

    def get_bot_response(self, experiment, bot, page, prompt):
        possible_responses = self.values
        if not self.required:
            possible_responses.append(None)
        return random.choice(possible_responses)


class MusicNotationPrompt(Prompt):
    """
    Displays music notation using the abcjs library by Paul Rosen and Gregory Dyke.
    See https://www.abcjs.net/ for information about abcjs.
    See https://abcnotation.com/ for information about ABC notation.

    Parameters
    ----------

    content :
        Content to display, in ABC notation. This will be rendered to an image.
        See https://www.abcjs.net/abcjs-editor.html for an interactive editor.
        See https://abcnotation.com/wiki/abc:standard:v2.1 for a detailed definition of ABC notation.

    text :
        Text to display above the score.

    text_align :
        Alignment instructions for this text.
    """

    def __init__(
        self,
        content: str,
        text: Union[None, str, Markup, dom_tag] = None,
        text_align: str = "left",
    ):
        super().__init__(text=text, text_align=text_align)
        self.content = content

    macro = "abc_notation"

    def get_js_dependencies(self):
        """Load the abcjs rendering library once per browser document."""
        return [package_static_url("psynet", "libraries/abc-js/abcjs-basic.js")]

    def get_js_page_modules(self):
        """Activate score rendering for each hosting page."""
        return [package_static_url("psynet", "scripts/music-notation-prompt.js")]

    def get_js_vars(self):
        """Provide the ABC notation consumed by the page module."""
        return {"music_notation_prompt": {"content": self.content}}

    def update_events(self, events):
        super().update_events(events)

        events["promptStart"] = Event(
            is_triggered_by=[
                Trigger(
                    triggering_event="trialStart",
                    delay=0,
                )
            ]
        )
