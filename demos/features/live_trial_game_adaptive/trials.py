"""The native trial and its SQL writes. Dallinger calls the writer once per effect."""

from dallinger import db

from psynet.experiment import get_experiment
from psynet.timeline import ModuleState
from psynet.trial.main import GenericTrialNode, LiveGameItemTrial


class ContrastTrial(LiveGameItemTrial):
    time_estimate = 2

    @staticmethod
    def score_answer(answer, definition):
        other = "right" if answer == "left" else "left"
        return int(definition[answer] > definition[other])


def trial_context(participants):
    """Capture the solo player's module run before starting the live session."""
    (participant,) = participants
    node = ContrastTrial.get_default_parent_node(participant, get_experiment())
    db.session.flush()
    return {"run_id": participant.module_state.id, "node_id": node.id}


def write_step(session, step):
    """Complete the answered row and insert the chosen successor in one transaction."""
    experiment = get_experiment()
    (member,) = session.members
    slot = step["completed"]
    if slot:
        previous = ContrastTrial.query.filter_by(
            live_session_id=session.id, participant_id=int(member), live_slot=slot - 1
        ).one()
        previous.time_taken = step["seconds"]
        previous._complete_with_answer(step["answer"], experiment)

    if step["next_pair"] is not None:
        run = ModuleState.query.filter_by(
            id=step["run_id"], participant_id=int(member)
        ).one()
        trial = ContrastTrial(
            experiment=experiment,
            participant=run.participant,
            module_state=run,
            node=GenericTrialNode.query.filter_by(id=step["node_id"]).one(),
            definition=step["next_pair"],
            position=slot,
            propagate_failure=False,
            is_repeat_trial=False,
        )
        trial.live_session_id = session.id
        trial.live_slot = slot
