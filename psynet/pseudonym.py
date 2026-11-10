"""Short, friendly names such as "Blue fox" for showing participants to each other.

Multiplayer pages (chat rooms, group displays) need to tell participants
apart without revealing recruitment IDs. This module gives every participant
a pseudonym made of a colour and an animal, shown as the animal in that colour.

Design constraints:

- Page rendering is read-only, so the default pseudonym is a pure function
  of the participant ID and the deployment ID stored in the database, and
  is never written. Each deployment shuffles the colours and animals
  differently, so participant 10 gets a different pseudonym in each
  deployment, and a loaded export gives the same pseudonyms that
  participants saw, as long as it is loaded with the same PsyNet version,
  pseudonym scheme and locale, and not launched again. Colour and animal
  indices cycle with coprime periods (8 and 11), so any 88 consecutive
  participants get different pseudonyms, and neighbours differ in both
  colour and animal, which helps colour-blind participants.
  Participants whose IDs differ by a multiple of 88 share a pseudonym.
- Only keys are stored when an experiment overrides a pseudonym, in the
  participant's ``pseudonym_color`` and ``pseudonym_animal`` columns; labels
  are translated when shown.
- Experiments customize pseudonyms by subclassing :class:`PseudonymScheme`
  and setting :attr:`psynet.experiment.Experiment.pseudonym_scheme`.
"""

import random
from dataclasses import dataclass
from typing import Dict, Optional, Tuple
from urllib.parse import quote

from markupsafe import Markup

from .static_resources import package_static_url
from .utils import get_translator

_COLORS = {
    "orange": "#E69F00",
    "light_blue": "#56B4E9",
    "green": "#009E73",
    "yellow": "#F0E442",
    "blue": "#0072B2",
    "red": "#D55E00",
    "pink": "#CC79A7",
    "black": "#000000",
}

_ANIMALS = {
    "fox": "🦊",
    "owl": "🦉",
    "otter": "🦦",
    "panda": "🐼",
    "tiger": "🐯",
    "frog": "🐸",
    "koala": "🐨",
    "penguin": "🐧",
    "rabbit": "🐰",
    "whale": "🐳",
    "cat": "🐱",
}


# One message per name, so that translators can make the colour agree with
# the animal. The lambdas keep the literals extractable while translating
# only the name that is shown.
_BUILTIN_NAMES = {
    ("orange", "fox"): lambda _p: _p("pseudonym", "Orange fox"),
    ("orange", "owl"): lambda _p: _p("pseudonym", "Orange owl"),
    ("orange", "otter"): lambda _p: _p("pseudonym", "Orange otter"),
    ("orange", "panda"): lambda _p: _p("pseudonym", "Orange panda"),
    ("orange", "tiger"): lambda _p: _p("pseudonym", "Orange tiger"),
    ("orange", "frog"): lambda _p: _p("pseudonym", "Orange frog"),
    ("orange", "koala"): lambda _p: _p("pseudonym", "Orange koala"),
    ("orange", "penguin"): lambda _p: _p("pseudonym", "Orange penguin"),
    ("orange", "rabbit"): lambda _p: _p("pseudonym", "Orange rabbit"),
    ("orange", "whale"): lambda _p: _p("pseudonym", "Orange whale"),
    ("orange", "cat"): lambda _p: _p("pseudonym", "Orange cat"),
    ("light_blue", "fox"): lambda _p: _p("pseudonym", "Light blue fox"),
    ("light_blue", "owl"): lambda _p: _p("pseudonym", "Light blue owl"),
    ("light_blue", "otter"): lambda _p: _p("pseudonym", "Light blue otter"),
    ("light_blue", "panda"): lambda _p: _p("pseudonym", "Light blue panda"),
    ("light_blue", "tiger"): lambda _p: _p("pseudonym", "Light blue tiger"),
    ("light_blue", "frog"): lambda _p: _p("pseudonym", "Light blue frog"),
    ("light_blue", "koala"): lambda _p: _p("pseudonym", "Light blue koala"),
    ("light_blue", "penguin"): lambda _p: _p("pseudonym", "Light blue penguin"),
    ("light_blue", "rabbit"): lambda _p: _p("pseudonym", "Light blue rabbit"),
    ("light_blue", "whale"): lambda _p: _p("pseudonym", "Light blue whale"),
    ("light_blue", "cat"): lambda _p: _p("pseudonym", "Light blue cat"),
    ("green", "fox"): lambda _p: _p("pseudonym", "Green fox"),
    ("green", "owl"): lambda _p: _p("pseudonym", "Green owl"),
    ("green", "otter"): lambda _p: _p("pseudonym", "Green otter"),
    ("green", "panda"): lambda _p: _p("pseudonym", "Green panda"),
    ("green", "tiger"): lambda _p: _p("pseudonym", "Green tiger"),
    ("green", "frog"): lambda _p: _p("pseudonym", "Green frog"),
    ("green", "koala"): lambda _p: _p("pseudonym", "Green koala"),
    ("green", "penguin"): lambda _p: _p("pseudonym", "Green penguin"),
    ("green", "rabbit"): lambda _p: _p("pseudonym", "Green rabbit"),
    ("green", "whale"): lambda _p: _p("pseudonym", "Green whale"),
    ("green", "cat"): lambda _p: _p("pseudonym", "Green cat"),
    ("yellow", "fox"): lambda _p: _p("pseudonym", "Yellow fox"),
    ("yellow", "owl"): lambda _p: _p("pseudonym", "Yellow owl"),
    ("yellow", "otter"): lambda _p: _p("pseudonym", "Yellow otter"),
    ("yellow", "panda"): lambda _p: _p("pseudonym", "Yellow panda"),
    ("yellow", "tiger"): lambda _p: _p("pseudonym", "Yellow tiger"),
    ("yellow", "frog"): lambda _p: _p("pseudonym", "Yellow frog"),
    ("yellow", "koala"): lambda _p: _p("pseudonym", "Yellow koala"),
    ("yellow", "penguin"): lambda _p: _p("pseudonym", "Yellow penguin"),
    ("yellow", "rabbit"): lambda _p: _p("pseudonym", "Yellow rabbit"),
    ("yellow", "whale"): lambda _p: _p("pseudonym", "Yellow whale"),
    ("yellow", "cat"): lambda _p: _p("pseudonym", "Yellow cat"),
    ("blue", "fox"): lambda _p: _p("pseudonym", "Blue fox"),
    ("blue", "owl"): lambda _p: _p("pseudonym", "Blue owl"),
    ("blue", "otter"): lambda _p: _p("pseudonym", "Blue otter"),
    ("blue", "panda"): lambda _p: _p("pseudonym", "Blue panda"),
    ("blue", "tiger"): lambda _p: _p("pseudonym", "Blue tiger"),
    ("blue", "frog"): lambda _p: _p("pseudonym", "Blue frog"),
    ("blue", "koala"): lambda _p: _p("pseudonym", "Blue koala"),
    ("blue", "penguin"): lambda _p: _p("pseudonym", "Blue penguin"),
    ("blue", "rabbit"): lambda _p: _p("pseudonym", "Blue rabbit"),
    ("blue", "whale"): lambda _p: _p("pseudonym", "Blue whale"),
    ("blue", "cat"): lambda _p: _p("pseudonym", "Blue cat"),
    ("red", "fox"): lambda _p: _p("pseudonym", "Red fox"),
    ("red", "owl"): lambda _p: _p("pseudonym", "Red owl"),
    ("red", "otter"): lambda _p: _p("pseudonym", "Red otter"),
    ("red", "panda"): lambda _p: _p("pseudonym", "Red panda"),
    ("red", "tiger"): lambda _p: _p("pseudonym", "Red tiger"),
    ("red", "frog"): lambda _p: _p("pseudonym", "Red frog"),
    ("red", "koala"): lambda _p: _p("pseudonym", "Red koala"),
    ("red", "penguin"): lambda _p: _p("pseudonym", "Red penguin"),
    ("red", "rabbit"): lambda _p: _p("pseudonym", "Red rabbit"),
    ("red", "whale"): lambda _p: _p("pseudonym", "Red whale"),
    ("red", "cat"): lambda _p: _p("pseudonym", "Red cat"),
    ("pink", "fox"): lambda _p: _p("pseudonym", "Pink fox"),
    ("pink", "owl"): lambda _p: _p("pseudonym", "Pink owl"),
    ("pink", "otter"): lambda _p: _p("pseudonym", "Pink otter"),
    ("pink", "panda"): lambda _p: _p("pseudonym", "Pink panda"),
    ("pink", "tiger"): lambda _p: _p("pseudonym", "Pink tiger"),
    ("pink", "frog"): lambda _p: _p("pseudonym", "Pink frog"),
    ("pink", "koala"): lambda _p: _p("pseudonym", "Pink koala"),
    ("pink", "penguin"): lambda _p: _p("pseudonym", "Pink penguin"),
    ("pink", "rabbit"): lambda _p: _p("pseudonym", "Pink rabbit"),
    ("pink", "whale"): lambda _p: _p("pseudonym", "Pink whale"),
    ("pink", "cat"): lambda _p: _p("pseudonym", "Pink cat"),
    ("black", "fox"): lambda _p: _p("pseudonym", "Black fox"),
    ("black", "owl"): lambda _p: _p("pseudonym", "Black owl"),
    ("black", "otter"): lambda _p: _p("pseudonym", "Black otter"),
    ("black", "panda"): lambda _p: _p("pseudonym", "Black panda"),
    ("black", "tiger"): lambda _p: _p("pseudonym", "Black tiger"),
    ("black", "frog"): lambda _p: _p("pseudonym", "Black frog"),
    ("black", "koala"): lambda _p: _p("pseudonym", "Black koala"),
    ("black", "penguin"): lambda _p: _p("pseudonym", "Black penguin"),
    ("black", "rabbit"): lambda _p: _p("pseudonym", "Black rabbit"),
    ("black", "whale"): lambda _p: _p("pseudonym", "Black whale"),
    ("black", "cat"): lambda _p: _p("pseudonym", "Black cat"),
}


@dataclass(frozen=True)
class Pseudonym:
    """A participant's pseudonym, ready to show.

    Attributes
    ----------
    color, animal
        Keys into the scheme's colours and animals, as stored.
    name
        Translated name, for example ``"Blue fox"``.
    css_color
        CSS colour for the participant's animal.
    emoji
        The animal's emoji.
    sticker_html
        HTML for a picture of the animal in the participant's colour, as in
        :class:`~psynet.group_prompt.GroupPrompt` and chat rooms. Its size
        follows the font size.
    """

    color: str
    animal: str
    name: str
    css_color: str
    emoji: str
    sticker_html: Markup

    def to_dict(self) -> dict:
        """Return the fields as JSON-serializable values."""
        return {
            "color": self.color,
            "animal": self.animal,
            "name": self.name,
            "css_color": self.css_color,
            "emoji": self.emoji,
            "sticker_html": str(self.sticker_html),
        }


class PseudonymScheme:
    """Chooses and displays participants' pseudonyms.

    Set an instance on your experiment to change the defaults::

        _ = get_translator()

        class TeamScheme(PseudonymScheme):
            def animals(self):
                return {"lion": (_("lion"), "🦁"), "bear": (_("bear"), "🐻")}

        class Exp(psynet.experiment.Experiment):
            pseudonym_scheme = TeamScheme()

    Override :meth:`colors` and :meth:`animals` to change the vocabulary,
    :meth:`assign` to change who gets which pseudonym, :meth:`name` to name
    the pairs of a custom vocabulary in full, and :meth:`sticker_html` or
    :meth:`artwork` for the pictures. Call
    :meth:`~psynet.participant.Participant.set_pseudonym` to give one
    participant a particular pseudonym.
    """

    def colors(self) -> Dict[str, Tuple[str, str]]:
        """Return ``{key: (label, css_color)}``; labels are translated here."""
        _p = get_translator(context=True)
        labels = {
            "orange": _p("pseudonym color", "orange"),
            "light_blue": _p("pseudonym color", "light blue"),
            "green": _p("pseudonym color", "green"),
            "yellow": _p("pseudonym color", "yellow"),
            "blue": _p("pseudonym color", "blue"),
            "red": _p("pseudonym color", "red"),
            "pink": _p("pseudonym color", "pink"),
            "black": _p("pseudonym color", "black"),
        }
        return {key: (labels[key], css) for key, css in _COLORS.items()}

    def animals(self) -> Dict[str, Tuple[str, str]]:
        """Return ``{key: (label, emoji)}``; labels are translated here."""
        _p = get_translator(context=True)
        labels = {
            "fox": _p("pseudonym animal", "fox"),
            "owl": _p("pseudonym animal", "owl"),
            "otter": _p("pseudonym animal", "otter"),
            "panda": _p("pseudonym animal", "panda"),
            "tiger": _p("pseudonym animal", "tiger"),
            "frog": _p("pseudonym animal", "frog"),
            "koala": _p("pseudonym animal", "koala"),
            "penguin": _p("pseudonym animal", "penguin"),
            "rabbit": _p("pseudonym animal", "rabbit"),
            "whale": _p("pseudonym animal", "whale"),
            "cat": _p("pseudonym animal", "cat"),
        }
        return {key: (labels[key], emoji) for key, emoji in _ANIMALS.items()}

    def assign(self, participant) -> Tuple[str, str]:
        """Return the ``(color, animal)`` keys for a participant without a stored pseudonym.

        The default shuffles the colours and animals using :meth:`seed`, then
        cycles through them by participant ID. If the two lists' lengths
        share no factor, every pair recurs only after
        ``len(colors) * len(animals)`` participants.
        """
        rng = random.Random(self.seed())
        colors, animals = sorted(self.colors()), sorted(self.animals())
        rng.shuffle(colors)
        rng.shuffle(animals)
        return (
            colors[participant.id % len(colors)],
            animals[participant.id % len(animals)],
        )

    def seed(self) -> str:
        """Return the seed for :meth:`assign`'s shuffle: by default, the deployment ID.

        It is read from the database, so it is the same in every server
        process and in exports, and differs between deployments. Before
        launch there is none yet, and the order is fixed.
        """
        if getattr(self, "_deployment_seed", None) is None:
            from .experiment import get_experiment

            deployment_id = get_experiment().var.get("deployment_id", None)
            if deployment_id is None:
                return ""
            self._deployment_seed = str(deployment_id)
        return self._deployment_seed

    def name(self, color: str, animal: str) -> str:
        """Return the translated name for a pair of colour and animal keys.

        Each pair of built-in keys has its own translated message, such as
        ``"Blue fox"``, so that languages can make the colour agree with the
        animal. Other pairs get their labels joined by a translatable
        ``"{COLOR} {ANIMAL}"``, which can't agree; override this method to
        name such pairs in full. Give new words new keys, since a built-in
        key keeps its built-in name.
        """
        if (color, animal) in _BUILTIN_NAMES:
            return _BUILTIN_NAMES[(color, animal)](get_translator(context=True))
        _p = get_translator(context=True)
        name = _p("pseudonym", "{COLOR} {ANIMAL}").format(
            COLOR=self.colors()[color][0], ANIMAL=self.animals()[animal][0]
        )
        return name[:1].upper() + name[1:]

    def artwork(self, animal: str, emoji: str) -> Optional[Tuple[str, str]]:
        """Return URLs of an animal's ``(shape, lines)`` SVGs, or ``None`` to use its emoji.

        :meth:`sticker_html` fills the shape's outline with the participant's
        colour and draws the lines on top. The built-in animals use Microsoft
        Fluent Emoji artwork (MIT licence); animals added by an override, or
        given a different emoji, get ``None``.
        """
        if _ANIMALS.get(animal) != emoji:
            return None
        folder = "images/pseudonym-animals"
        return (
            package_static_url("psynet", f"{folder}/{animal}.svg"),
            package_static_url("psynet", f"{folder}/{animal}-lines.svg"),
        )

    def sticker_html(
        self, css_color: str, animal: str, emoji: str, name: str
    ) -> Markup:
        """Return HTML for the animal drawn in the participant's colour.

        Uses :meth:`artwork` when there is some, and otherwise tints the
        emoji. Lines turn light on dark colours. The picture is hidden from
        screen readers, because pages show the name next to it. Pages insert
        this HTML as it is, so an override must return
        :class:`~markupsafe.Markup` and escape its arguments, as
        :meth:`Markup.format <markupsafe.Markup.format>` does.
        """
        classes = "psynet-pseudonym-sticker"
        if _is_dark(css_color):
            classes += " psynet-pseudonym-sticker--dark"
        artwork = self.artwork(animal, emoji)
        if artwork is None:
            return Markup(
                '<span class="{} psynet-pseudonym-sticker--emoji" aria-hidden="true"'
                ' title="{}" style="--psynet-pseudonym-color: {}">'
                '<span class="psynet-pseudonym-sticker-shape">{}</span>'
                '<span class="psynet-pseudonym-sticker-detail">{}</span></span>'
            ).format(classes, name, css_color, emoji, emoji)
        return _artwork_sticker(classes, css_color, *artwork, name)

    def replacement(self, taken, participant) -> Optional[Tuple[str, str]]:
        """Return ``(color, animal)`` keys that nobody in ``taken`` has, or ``None`` if all are used.

        Used to give a new group member a pseudonym that differs from the
        others'. ``taken`` is a collection of ``(color, animal)`` pairs. The
        default prefers a pair whose colour and animal are both unused, and
        picks among those using :meth:`seed` and the participant's ID, so
        that participants renamed in different groups get different names.
        """
        taken = set(taken)
        used_colors = {color for color, _ in taken}
        used_animals = {animal for _, animal in taken}
        free = [
            (color, animal)
            for color in self.colors()
            for animal in self.animals()
            if (color, animal) not in taken
        ]
        distinct = [
            pair
            for pair in free
            if pair[0] not in used_colors and pair[1] not in used_animals
        ]
        candidates = distinct or free
        if not candidates:
            return None
        return random.Random(f"{self.seed()}:{participant.id}").choice(candidates)

    def pseudonym(self, participant) -> Pseudonym:
        """Return this participant's pseudonym."""
        color, animal = participant.pseudonym_color, participant.pseudonym_animal
        if color is None or animal is None:
            color, animal = self.assign(participant)
        return self.make(color, animal)

    def make(self, color: str, animal: str) -> Pseudonym:
        """Return the :class:`Pseudonym` for a pair of keys."""
        colors, animals = self.colors(), self.animals()
        if color not in colors:
            raise ValueError(f"Unknown pseudonym color {color!r}.")
        if animal not in animals:
            raise ValueError(f"Unknown pseudonym animal {animal!r}.")
        css_color, emoji = colors[color][1], animals[animal][1]
        name = self.name(color, animal)
        return Pseudonym(
            color=color,
            animal=animal,
            name=name,
            css_color=css_color,
            emoji=emoji,
            sticker_html=self.sticker_html(css_color, animal, emoji, name),
        )


def anonymous_sticker_html() -> Markup:
    """Return HTML for a grey person silhouette, used where members must not be recognisable."""
    return _artwork_sticker(
        "psynet-pseudonym-sticker psynet-pseudonym-sticker--anonymous",
        "#adb5bd",
        package_static_url("psynet", "images/pseudonym-animals/person.svg"),
        None,
        "",
    )


def _artwork_sticker(classes, css_color, shape, lines, name) -> Markup:
    detail = (
        Markup('<img class="psynet-pseudonym-sticker-detail" src="{}" alt="">').format(
            lines
        )
        if lines
        else Markup("")
    )
    title = Markup(' title="{}"').format(name) if name else Markup("")
    return Markup(
        '<span class="{}" aria-hidden="true"{}'
        ' style="--psynet-pseudonym-color: {}; --psynet-pseudonym-shape: url(&#39;{}&#39;)">'
        "{}</span>"
    ).format(classes, title, css_color, quote(shape, safe="/:._-~%?=&#"), detail)


def _is_dark(css_color: str) -> bool:
    """Return whether a ``#rgb`` or ``#rrggbb`` colour is too dark for dark lines on it.

    Other colour formats count as light.
    """
    digits = css_color[1:] if css_color.startswith("#") else ""
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    try:
        r, g, b = (int(digits[i : i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return False
    return 0.2126 * r + 0.7152 * g + 0.0722 * b < 0.2
