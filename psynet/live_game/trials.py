"""Present prepared static trials in a live session."""

from copy import deepcopy

from .game import LiveGame


class LiveTrialGame(LiveGame):
    """A live game that presents a fixed plan to each player, in seat order.

    Play this game inside a StaticTrialMaker. PlayLiveGame loads each player's
    trial plan when the session starts. For LocalGame tests, pass the plans directly.
    Optionally set ``stop`` to an exclusive position in the full deck. The next
    session resumes at the first unanswered trial. Define the response message
    and participant interface for your experiment.

    The default view exposes the player's deck, current definition, and progress.
    The game ends when everyone reaches their own segment boundary. If overriding
    ``on_start``, call ``super().on_start(state)`` to open the response clocks.
    """

    @staticmethod
    def _session_settings(participants, settings):
        from ..experiment import get_trial_maker
        from ..trial.main import TrialMakerState
        from ..trial.static import StaticTrialMaker

        if settings is not None and not isinstance(settings, dict):
            raise ValueError("LiveTrialGame settings must be a dictionary.")
        if settings and "plans" in settings:
            raise ValueError("LiveTrialGame loads plans from the active trial maker.")
        plans = []
        for participant in participants:
            run = participant.module_state
            maker = (
                get_trial_maker(run.module_id)
                if isinstance(run, TrialMakerState)
                else None
            )
            if not isinstance(maker, StaticTrialMaker):
                raise ValueError("Play a LiveTrialGame inside a StaticTrialMaker.")
            plans.append(maker.trial_plan(participant))
        return {**(settings or {}), "plans": plans}

    def initial_state(self, players, settings=None):
        if not isinstance(settings, dict) or "plans" not in settings:
            raise ValueError("Supply trial plans in the game settings.")
        state = deepcopy(settings)
        plans = state["plans"]
        if len(plans) != len(players):
            raise ValueError("Supply one trial plan for each player in seat order.")
        stop = state.pop("stop", None)
        for plan in plans:
            ids = plan["_trial_ids"]
            if stop is not None:
                if type(stop) is not int or not 0 <= stop <= len(ids):
                    raise ValueError(
                        "stop must be an exclusive position within each deck."
                    )
                plan["_trial_ids"] = ids[:stop]
            if len(plan["answers"]) > len(plan["_trial_ids"]):
                raise ValueError("The player has already answered beyond this segment.")
        return state

    def on_start(self, state):
        self.start_trials(state["plans"])

    def current_definition(self, state, player):
        """Return the player's current definition, or None at the segment boundary."""
        plan = state["plans"][player]
        index = len(plan["answers"])
        if index >= len(plan["_trial_ids"]):
            return None
        return plan["definitions"][index]

    def is_over(self, state):
        return all(
            self.current_definition(state, i) is None
            for i in range(len(state["plans"]))
        )

    def outcome(self, state, reason):
        """Trial rows hold the responses. Override for a separate game result."""
        return {}

    def view(self, state, player):
        plan = state["plans"][player]
        return {
            "definition": self.current_definition(state, player),
            "deck": plan["definitions"],
            "completed": len(plan["answers"]),
            "total": len(plan["definitions"]),
            "stop": len(plan["_trial_ids"]),
        }
