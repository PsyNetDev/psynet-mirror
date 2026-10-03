"""Network monitor payload includes PsyNet trials after Trial left Info."""

from psynet.experiment import _trials_as_network_monitor_infos


def test_trials_as_network_monitor_infos_aliases_origin_id():
    rows = [
        {
            "id": 7,
            "node_id": 3,
            "participant_id": 1,
            "failed": False,
            "type": "StaticTrial",
        }
    ]
    infos = _trials_as_network_monitor_infos(rows)
    assert len(infos) == 1
    assert infos[0]["id"] == 7
    assert infos[0]["origin_id"] == 3
    assert infos[0]["node_id"] == 3
    # Input row is not mutated.
    assert "origin_id" not in rows[0]


def test_experiment_network_structure_puts_trials_in_infos_slot(monkeypatch):
    from dallinger.experiment import Experiment as DallingerExperiment

    from psynet.experiment import Experiment

    def fake_parent_network_structure(
        self,
        network_roles=None,
        network_ids=None,
        collapsed=False,
        transformations=False,
    ):
        return {
            "networks": [{"id": 1}],
            "nodes": [{"id": 3}],
            "vectors": [],
            "infos": [{"id": 99, "origin_id": 3, "type": "Info"}],
            "participants": [],
            "trans": [{"id": 1}],
        }

    monkeypatch.setattr(
        DallingerExperiment, "network_structure", fake_parent_network_structure
    )

    exp = Experiment.__new__(Experiment)

    def fake_summarize_table(
        table, network_roles=None, network_ids=None, cls_filter=None
    ):
        assert table == "trial"
        return [
            {
                "id": 7,
                "node_id": 3,
                "participant_id": 1,
                "failed": False,
                "type": "StaticTrial",
            }
        ]

    exp.summarize_table = fake_summarize_table
    structure = Experiment.network_structure(exp)

    assert structure["networks"] == [{"id": 1}]
    assert structure["nodes"] == [{"id": 3}]
    assert len(structure["infos"]) == 1
    assert structure["infos"][0]["id"] == 7
    assert structure["infos"][0]["origin_id"] == 3
    assert structure["infos"][0]["type"] == "StaticTrial"


def test_experiment_network_structure_collapsed_skips_trials(monkeypatch):
    from dallinger.experiment import Experiment as DallingerExperiment

    from psynet.experiment import Experiment

    def fake_parent_network_structure(self, **kwargs):
        return {
            "networks": [],
            "nodes": [],
            "vectors": [],
            "infos": [],
            "participants": [],
            "trans": [],
        }

    monkeypatch.setattr(
        DallingerExperiment, "network_structure", fake_parent_network_structure
    )

    exp = Experiment.__new__(Experiment)
    called = []

    def fake_summarize_table(table, *args, **kwargs):
        called.append(table)
        return []

    exp.summarize_table = fake_summarize_table
    structure = Experiment.network_structure(exp, collapsed=True)
    assert structure["infos"] == []
    assert called == []


def test_json_clean_tolerates_missing_details_and_contents():
    from psynet.field import json_clean

    row = {"id": 1, "type": "AnimalTrial", "property1": "x"}
    json_clean(row, details=True, contents=True)
    assert "property1" not in row
    assert "details" not in row
    assert "contents" not in row
    assert row["id"] == 1
