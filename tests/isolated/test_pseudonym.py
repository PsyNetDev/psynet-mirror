import itertools
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import psynet.pseudonym
from psynet.experiment import get_experiment
from psynet.pseudonym import PseudonymScheme
from psynet.pytest_psynet import path_to_test_experiment

sys.path.insert(0, str(Path(__file__).resolve().parent))
from timeline_hold_helpers import _working_participants  # noqa: E402


def _participant(id_, stored=None):
    color, animal = stored or (None, None)
    return SimpleNamespace(id=id_, pseudonym_color=color, pseudonym_animal=animal)


class _SeededScheme(PseudonymScheme):
    def __init__(self, seed):
        self._seed = seed

    def seed(self):
        return self._seed


def test_neighbours_differ_and_deployments_shuffle_pseudonyms():
    scheme = _SeededScheme("deployment-a")
    pseudonyms = [scheme.pseudonym(_participant(i)) for i in range(1, 89)]

    assert len({p.name for p in pseudonyms}) == 88
    for a, b in zip(pseudonyms, pseudonyms[1:]):
        assert a.color != b.color and a.animal != b.animal
    other = [_SeededScheme("deployment-b").pseudonym(_participant(i)) for i in (1, 2)]
    assert [p.name for p in other] != [p.name for p in pseudonyms[:2]]
    # Participants renamed in different groups get different replacements.
    taken = {("blue", "fox")}
    replacements = {scheme.replacement(taken, _participant(i)) for i in range(5)}
    assert len(replacements) > 1 and not replacements & taken
    blue_fox = scheme.make("blue", "fox")
    assert (blue_fox.name, blue_fox.emoji) == ("Blue fox", "🦊")
    assert "--psynet-pseudonym-color: #0072B2" in blue_fox.icon_html
    assert "pseudonym-animals/fox-lines.svg" in blue_fox.sticker_html
    assert "sticker--dark" in scheme.make("black", "fox").sticker_html

    class Shorthand(_SeededScheme):
        def colors(self):
            return {"navy": ("navy", "#003"), "named": ("named", "rebeccapurple")}

    shorthand = Shorthand("deployment-a")
    assert "sticker--dark" in shorthand.make("navy", "fox").sticker_html
    assert "sticker--dark" not in shorthand.make("named", "fox").sticker_html


def test_schemes_and_stored_pseudonyms_can_be_customized():
    class Teams(_SeededScheme):
        def animals(self):
            return {"lion": ("lion", "🦁"), "bear": ("bear", "🐻")}

    class NamedTeams(Teams):
        def name(self, color, animal):
            return f"{self.animals()[animal][0].title()} ({self.colors()[color][0]})"

    assert Teams("deployment-a").make("red", "bear").name == "Red bear"
    scheme = NamedTeams("deployment-a")
    stored = scheme.pseudonym(_participant(1, ("red", "bear")))

    assert stored.name == "Bear (red)"
    assert "psynet-pseudonym-sticker--emoji" in stored.sticker_html
    half_stored = _participant(1, ("red", None))
    assert scheme.pseudonym(half_stored) == scheme.pseudonym(_participant(1))
    assert scheme.pseudonym(_participant(2)).animal in {"lion", "bear"}
    with pytest.raises(ValueError, match="Unknown pseudonym animal 'fox'"):
        scheme.make("red", "fox")


def test_built_in_names_are_translated_whole(monkeypatch):
    """Translators see "Blue fox" as one message, so the colour can agree with the animal."""
    french = {"Blue fox": "Renard bleu", "{COLOR} {ANIMAL}": "{ANIMAL} {COLOR}"}
    monkeypatch.setattr(
        psynet.pseudonym,
        "get_translator",
        lambda context=True: lambda _context, message: french.get(message, message),
    )

    class Lions(PseudonymScheme):
        def animals(self):
            return {**super().animals(), "lion": ("lion", "🦁")}

    assert set(psynet.pseudonym._BUILTIN_NAMES) == set(
        itertools.product(PseudonymScheme().colors(), PseudonymScheme().animals())
    )
    assert Lions().make("blue", "fox").name == "Renard bleu"
    assert Lions().make("blue", "lion").name == "Lion blue"


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_stored_deployment_id_and_overrides_decide_pseudonyms(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    exp.setup_experiment_config()
    participants = _working_participants(exp, 3)

    def names(deployment_id):
        exp.var.deployment_id = deployment_id
        return [PseudonymScheme().pseudonym(p).name for p in participants]

    assert names("deployment-a") == names("deployment-a") != names("deployment-b")

    participants[0].set_pseudonym("red", "whale")
    assert participants[0].pseudonym.name == "Red whale"
    assert "pseudonym_color" not in participants[0].to_dict()
    rows = exp.table_data(0, 10, table="participant")["data"]
    assert {row["id"]: row["pseudonym"] for row in rows}[participants[0].id] == (
        "Red whale"
    )
    (column,) = [
        c for c in exp.table_columns("participant") if c["data"] == "pseudonym"
    ]
    assert not column["orderable"] and not column["searchable"]
    with pytest.raises(ValueError, match="Unknown pseudonym color"):
        participants[0].set_pseudonym("teal", "whale")
