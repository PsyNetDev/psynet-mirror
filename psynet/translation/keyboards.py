import json
from importlib import resources
from typing import Union

from dominate.dom_tag import dom_tag
from markupsafe import Markup

from psynet.timeline import Page, get_template

ALL_KEYS = [
    "Digit1",
    "Digit2",
    "Digit3",
    "Digit4",
    "Digit5",
    "Digit6",
    "Digit7",
    "Digit8",
    "Digit9",
    "Digit0",
    "Minus",
    "Equal",
    "KeyQ",
    "KeyW",
    "KeyE",
    "KeyR",
    "KeyT",
    "KeyY",
    "KeyU",
    "KeyI",
    "KeyO",
    "KeyP",
    "BracketLeft",
    "BracketRight",
    "KeyA",
    "KeyS",
    "KeyD",
    "KeyF",
    "KeyG",
    "KeyH",
    "KeyJ",
    "KeyK",
    "KeyL",
    "Semicolon",
    "Quote",
    "Backquote",
    "Backslash",
    "KeyZ",
    "KeyX",
    "KeyC",
    "KeyV",
    "KeyB",
    "KeyN",
    "KeyM",
    "Comma",
    "Period",
    "Slash",
]

overview_path = str(
    resources.files("psynet")
    / "resources/libraries/international-keyboards/overview.json"
)
with open(overview_path, "r") as f:
    ALL_LAYOUTS = [v["name"] for o in json.load(f).values() for v in o["variants"]]


class KeyboardPage(Page):
    """
    Shows a prompt next to an on-screen keyboard that lights up the keys the participant presses.

    Parameters
    ----------
    prompt :
        Content shown beside the keyboard. Plain strings are shown as text;
        pass ``markupsafe.Markup`` or a ``dominate`` tag for HTML.
    """

    def __init__(
        self,
        prompt: Union[str, Markup, dom_tag],
        highlight_keys=None,
        show_keys=None,
        press_keys=None,
        css_style="inverted",
        key_variant="upper",
        time_estimate=5,
    ):

        if highlight_keys is None:
            highlight_keys = []

        if show_keys is None:
            show_keys = ALL_KEYS

        if press_keys is None:
            press_keys = []

        assert css_style in ["inverted", "default", "apple"]
        super().__init__(
            time_estimate=time_estimate,
            template_str=get_template("keyboard.html"),
            framework_owned_template=True,
            js_vars={
                "cssStyle": css_style,
                "highlightKeys": highlight_keys,
                "showKeys": show_keys,
                "pressKeys": press_keys,
                "keyVariant": key_variant,
            },
            template_arg={
                "prompt": prompt,
            },
        )

    def get_bot_response(self, experiment, bot):
        from psynet.bot import BotResponse

        return BotResponse(
            raw_answer=None,
            metadata=self.metadata(),
        )
