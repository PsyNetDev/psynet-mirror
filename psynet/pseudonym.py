"""Short, friendly names such as "Blue fox" for showing participants to each other.

Multiplayer pages (chat rooms, group displays) need to tell participants
apart without revealing recruitment IDs. This module gives every participant
a pseudonym made of a colour and an animal, with an icon combining the two.

Design constraints:

- Page rendering is read-only, so the default pseudonym is a pure function
  of the participant ID and the deployment, and is never written to the
  database. Each deployment shuffles the colours and animals differently,
  so participant 10 gets a different pseudonym in each deployment. Colour
  and animal indices cycle with coprime periods (8 and 11), so any 88
  consecutive participants get different pseudonyms, and neighbours differ
  in both colour and animal, which helps colour-blind participants.
- Only keys are stored when an experiment overrides a pseudonym
  (``participant.var.pseudonym``); labels are translated when shown.
- Experiments customize pseudonyms by subclassing :class:`PseudonymScheme`
  and setting :attr:`psynet.experiment.Experiment.pseudonym_scheme`.
"""

import random
from dataclasses import dataclass
from typing import Dict, Tuple

from markupsafe import Markup

from .utils import get_logger, get_translator

logger = get_logger()

_COLORS = {
    "orange": "#E69F00",
    "sky": "#56B4E9",
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
    "turtle": "🐢",
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
        CSS colour for the participant's icon.
    emoji
        The animal's emoji.
    icon_html
        HTML for the participant's icon.
    """

    color: str
    animal: str
    name: str
    css_color: str
    emoji: str
    icon_html: Markup

    def to_dict(self) -> dict:
        """Return the fields that pages need, as JSON-serializable values."""
        return {
            "name": self.name,
            "color": self.css_color,
            "emoji": self.emoji,
            "icon_html": str(self.icon_html),
        }


class PseudonymScheme:
    """Chooses and displays participants' pseudonyms.

    Set an instance on your experiment to change the defaults::

        class TeamScheme(PseudonymScheme):
            def animals(self):
                return {"lion": ("Lion", "🦁"), "bear": ("Bear", "🐻")}

        class Exp(psynet.experiment.Experiment):
            pseudonym_scheme = TeamScheme()

    Override :meth:`colors` and :meth:`animals` to change the vocabulary,
    :meth:`assign` to change who gets which pseudonym, :meth:`name` for the
    word order, and :meth:`icon_html` for the icon. Call
    :meth:`~psynet.participant.Participant.set_pseudonym` to give one
    participant a particular pseudonym.
    """

    def colors(self) -> Dict[str, Tuple[str, str]]:
        """Return ``{key: (label, css_color)}``; labels are translated here."""
        _p = get_translator(context=True)
        labels = {
            "orange": _p("pseudonym color", "orange"),
            "sky": _p("pseudonym color", "sky"),
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
            "turtle": _p("pseudonym animal", "turtle"),
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

        The same within a deployment, across all its server processes, and
        different between deployments.
        """
        from .experiment import Experiment

        try:
            return str(Experiment.deployment_id)
        except (FileNotFoundError, KeyError):
            logger.debug("No deployment ID yet; using a fixed pseudonym order.")
            return ""

    def name(self, color_label: str, animal_label: str) -> str:
        """Combine translated colour and animal labels into a name, capitalizing its first letter."""
        _p = get_translator(context=True)
        name = _p("pseudonym", "{COLOR} {ANIMAL}").format(
            COLOR=color_label, ANIMAL=animal_label
        )
        return name[:1].upper() + name[1:]

    def icon_html(self, css_color: str, emoji: str, name: str) -> Markup:
        """Return HTML for a participant's icon: the animal on a coloured disc."""
        return Markup(
            '<span class="psynet-pseudonym-icon" role="img" aria-label="{}"'
            ' style="--psynet-pseudonym-color: {}">{}</span>'
        ).format(name, css_color, emoji)

    def pseudonym(self, participant) -> Pseudonym:
        """Return this participant's pseudonym."""
        stored = participant.var.get("pseudonym", None)
        if stored is None:
            color, animal = self.assign(participant)
        else:
            color, animal = stored["color"], stored["animal"]
        return self.make(color, animal)

    def make(self, color: str, animal: str) -> Pseudonym:
        """Return the :class:`Pseudonym` for a pair of keys."""
        colors, animals = self.colors(), self.animals()
        if color not in colors:
            raise ValueError(f"Unknown pseudonym color {color!r}.")
        if animal not in animals:
            raise ValueError(f"Unknown pseudonym animal {animal!r}.")
        color_label, css_color = colors[color]
        animal_label, emoji = animals[animal]
        name = self.name(color_label, animal_label)
        return Pseudonym(
            color=color,
            animal=animal,
            name=name,
            css_color=css_color,
            emoji=emoji,
            icon_html=self.icon_html(css_color, emoji, name),
        )
