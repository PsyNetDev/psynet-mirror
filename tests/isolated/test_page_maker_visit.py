from types import SimpleNamespace
from uuid import uuid4

import pytest
from dallinger import db

from psynet.asset import asset
from psynet.export.database import _export_table_order, copy_database_to_csv_dir
from psynet.page import InfoPage
from psynet.page_maker_visit import PageMakerVisit, PageMakerVisitError
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_demo_feature
from psynet.timeline import CodeBlock, GoTo, PageMaker, Timeline, while_loop

pytestmark = pytest.mark.parametrize(
    "experiment_directory", [path_to_demo_feature("page_maker")], indirect=True
)


def _participant(timeline):
    experiment = SimpleNamespace(timeline=timeline, base_payment=0)
    p = Participant(experiment, "hotair", uuid4().hex, "assignment", "hit", "debug")
    db.session.commit()
    return experiment, p


def _draw(participant):
    owner = participant
    token = uuid4().hex
    page = InfoPage(token, time_estimate=1)

    def validate(response, participant):
        assert owner is participant
        return token, owner.var.round

    page.validate = validate
    return page


def test_visit_lifecycle(db_session, deployment_info, tmp_path):
    def steps(participant):
        participant.var.round = 0
        participant.var.outer_calls = participant.var.get("outer_calls", 0) + 1
        return [
            PageMaker(lambda: [], time_estimate=0),
            while_loop(
                "draw twice",
                lambda participant: participant.var.get("round", 0) < 2,
                [
                    CodeBlock(lambda participant: participant.var.inc("round", 1)),
                    PageMaker(_draw, time_estimate=1),
                ],
                expected_repetitions=2,
            ),
        ]

    timeline = Timeline(
        PageMaker(steps, time_estimate=2), InfoPage("Done", time_estimate=1)
    )
    experiment, p = _participant(timeline)
    pid = p.id
    timeline.advance_page(experiment, p)
    aborted = timeline.get_current_elt(experiment, p).content
    db.session.flush()
    assert db.session.query(PageMakerVisit).count() == 2
    db.session.rollback()
    assert p.elt_id == ["main", -1]
    assert db.session.query(PageMakerVisit).count() == 0

    timeline.advance_page(experiment, p)
    first = timeline.get_current_elt(experiment, p).content
    assert first != aborted
    db.session.commit()
    db.session.remove()
    p = db.session.get(Participant, pid)
    assert timeline.get_current_elt(experiment, p).validate(None, p) == (first, 1)
    assert "page_maker_visit" not in _export_table_order()
    assert (
        copy_database_to_csv_dir(str(tmp_path), table_names=["page_maker_visit"]) == []
    )
    assert not list(tmp_path.iterdir())

    timeline.advance_page(experiment, p)
    second = timeline.get_current_elt(experiment, p)
    assert second.content != first
    assert second.validate(None, p) == (second.content, 2)
    db.session.commit()
    assert p.var.outer_calls == 1
    assert db.session.query(PageMakerVisit).count() == 2
    timeline.advance_page(experiment, p)
    assert timeline.get_current_elt(experiment, p).content == "Done"
    assert db.session.query(PageMakerVisit).count() == 0


def test_redirect_and_corrupt_snapshot(db_session, deployment_info, monkeypatch):
    timeline = Timeline(
        PageMaker(_draw, time_estimate=1),
        other=[InfoPage("Elsewhere", time_estimate=1)],
    )
    experiment, p = _participant(timeline)
    timeline.advance_page(experiment, p)
    visit = next(iter(p._page_maker_visits.values()))
    original = visit.payload
    visit.payload = original + b"corrupt"
    with pytest.raises(PageMakerVisitError, match="Cannot restore"):
        timeline.get_current_elt(experiment, p)
    visit.payload = original
    from psynet import deployment_info as launch

    # A compatible in-place app update keeps the deployment and private key.
    launch.write(git_commit_sha="new-experiment-revision", secret=uuid4())
    assert timeline.get_current_elt(experiment, p).content
    with monkeypatch.context() as changed_worker:
        changed_worker.setenv("FLASK_SECRET_KEY", uuid4().hex)
        with pytest.raises(PageMakerVisitError, match="this deployment"):
            timeline.get_current_elt(experiment, p)
    with monkeypatch.context() as unconfigured_worker:
        launch.write(mode="live")
        unconfigured_worker.delenv("FLASK_SECRET_KEY", raising=False)
        with pytest.raises(PageMakerVisitError, match="private server key"):
            timeline.get_current_elt(experiment, p)
    launch.write(mode="debug")
    launch.write(deployment_id="different deployment")
    with pytest.raises(PageMakerVisitError, match="this deployment"):
        timeline.get_current_elt(experiment, p)
    timeline.redirect_to_branch(experiment, p, "other")
    db.session.flush()
    assert not p._page_maker_visits


def test_live_resource_refused_on_entry(db_session, deployment_info):
    def invalid():
        open_values = (x for x in (1, 2))
        return CodeBlock(lambda: next(open_values))

    timeline = Timeline(PageMaker(invalid, label="invalid", time_estimate=1))
    experiment, p = _participant(timeline)
    with pytest.raises(PageMakerVisitError, match="invalid.*generator"):
        timeline.advance_page(experiment, p)
    db.session.rollback()
    assert p.elt_id == ["main", -1]
    assert not p._page_maker_visits


def test_shared_closures_and_detached_row(db_session, deployment_info):
    _, owner = _participant(Timeline(InfoPage("Other participant", time_estimate=1)))
    owner_id = owner.id
    db.session.expunge(owner)

    def make_page():
        counter = 0

        def increment():
            nonlocal counter
            counter += 1

        page = InfoPage("Saved callbacks", time_estimate=1)
        page.increment = increment
        page.read_counter = lambda: counter
        page.read_owner = lambda: owner
        page.owner_type = type(owner)
        return page

    timeline = Timeline(PageMaker(make_page, time_estimate=1))
    experiment, p = _participant(timeline)
    timeline.advance_page(experiment, p)
    db.session.commit()
    page = timeline.get_current_elt(experiment, p)
    page.increment()
    assert page.read_counter() == 1
    assert timeline.get_current_elt(experiment, p).read_counter() == 0
    live_owner = db.session.get(Participant, owner_id)
    assert page.read_owner() is live_owner
    assert page.owner_type is type(live_owner)
    db.session.delete(live_owner)
    db.session.flush()
    with pytest.raises(PageMakerVisitError, match="Missing Participant row"):
        timeline.get_current_elt(experiment, p)


def test_worker_rebinds_services_and_restores_asset_specification(
    db_session, deployment_info
):
    def steps(experiment):
        recruiter = experiment.recruiter
        audio = asset(str, extension=".wav", on_demand=True)
        page = InfoPage("Services and a new asset", time_estimate=1)
        page.fetch = lambda: (experiment, recruiter, audio)
        return page

    timeline = Timeline(PageMaker(steps, time_estimate=1))
    experiment, p = _participant(timeline)
    experiment.recruiter = object()
    timeline.advance_page(experiment, p)
    db.session.commit()
    worker = SimpleNamespace(timeline=timeline, recruiter=object())
    restored_experiment, recruiter, audio = timeline.get_current_elt(worker, p).fetch()
    assert restored_experiment is worker and recruiter is worker.recruiter
    assert audio.id is None and audio.extension == ".wav"


def test_jump_out_of_nested_makers_discards_both_visits(db_session, deployment_info):
    destination = InfoPage("Outside", time_estimate=1)
    timeline = Timeline(
        PageMaker(
            lambda: PageMaker(
                lambda: [InfoPage("Inside", time_estimate=1), GoTo(destination)],
                time_estimate=1,
            ),
            time_estimate=1,
        ),
        destination,
    )
    experiment = SimpleNamespace(timeline=timeline, base_payment=0)
    p = Participant(experiment, "hotair", uuid4().hex, "assignment", "hit", "debug")
    # Direct callers can advance a participant before its first database flush.
    timeline.advance_page(experiment, p)
    db.session.commit()
    assert timeline.get_current_elt(experiment, p).content == "Inside"
    assert db.session.query(PageMakerVisit).count() == 2
    timeline.advance_page(experiment, p)
    db.session.commit()
    assert timeline.get_current_elt(experiment, p).content == "Outside"
    assert not p._page_maker_visits
