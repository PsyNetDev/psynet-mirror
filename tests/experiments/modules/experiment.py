import psynet.experiment
from psynet.page import InfoPage
from psynet.timeline import CodeBlock, Module, PageMaker, Timeline, for_loop, join


def check_module_b(participant):
    module_a_state = participant.module_states["module_a"][-1]
    module_b_state = participant.module_states["module_b"][-1]

    assert module_a_state.var.animal == "dog"
    assert not module_b_state.var.has("animal")
    assert module_b_state.var.color == "blue"

    export = participant.to_dict()
    flattened_keys = [k for k in export if k.startswith(("module_a__", "module_b__"))]
    assert flattened_keys == [], (
        f"participant.to_dict() should no longer contain module locals, but found: {flattened_keys}"
    )


class Exp(psynet.experiment.Experiment):
    label = "Module demo"

    timeline = Timeline(
        Module(
            "module_a",
            for_loop(
                label="module_a_loop",
                iterate_over=lambda: ["cat", "dog"],
                logic=lambda animal: join(
                    CodeBlock(
                        lambda participant: participant.module_state.var.set(
                            "animal", animal
                        )
                    ),
                    PageMaker(
                        lambda participant: InfoPage(
                            f"Animal = {participant.module_state.var.animal}",
                        ),
                        time_estimate=5,
                    ),
                ),
                time_estimate_per_iteration=5,
            ),
        ),
        Module(
            "module_b",
            CodeBlock(
                lambda participant: participant.module_state.var.set("color", "blue")
            ),
            PageMaker(
                lambda participant: InfoPage(
                    f"Color = {participant.module_state.var.color}",
                ),
                time_estimate=5,
            ),
        ),
    )

    def test_check_bot(self, participant, **kwargs):
        check_module_b(participant)
