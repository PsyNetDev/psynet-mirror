import psynet.experiment
from psynet.async_job import LocalAsyncJob, WorkerAsyncJob
from psynet.page import InfoPage
from psynet.participant import Participant
from psynet.timeline import CodeBlock, Timeline, switch
from psynet.utils import get_logger

logger = get_logger()


class ErrorOnSubmitResponse(InfoPage):
    def __init__(self, error_code, *args, **kwargs):
        self.error_code = error_code
        super().__init__(*args, **kwargs)

    def format_answer(self, raw_answer, **kwargs):
        raise ValueError(f"Error code {self.error_code}")


class ErrorOnGetPage(InfoPage):
    def __init__(self, error_code, *args, **kwargs):
        self.error_code = error_code
        super().__init__(*args, **kwargs)

    def render(self, experiment, participant):
        raise RuntimeError(f"Error code {self.error_code}")


def worker_function(error_code):
    raise AssertionError(f"Error code {error_code}")


def worker_async_job_error(error_code):
    return CodeBlock(
        lambda participant: WorkerAsyncJob(
            worker_function,
            arguments={"error_code": error_code},
            participant=participant,
        ).enqueue()
    )


def local_async_job_error(error_code):
    return CodeBlock(
        lambda participant: LocalAsyncJob(
            worker_function,
            arguments={"error_code": error_code},
            participant=participant,
        ).enqueue()
    )


class Exp(psynet.experiment.Experiment):
    label = "Error handling demo"

    def need_more_participants(self):
        return Participant.query.count() < 4

    timeline = Timeline(
        InfoPage("Welcome to the experiment!", time_estimate=5),
        switch(
            "switch",
            # lambda participant: 3,
            lambda participant: (participant.id - 1) % 4,
            {
                0: ErrorOnSubmitResponse(38574, "Lorem ipsum", time_estimate=5),
                1: ErrorOnGetPage(82626, "Lorem ipsum", time_estimate=5),
                2: worker_async_job_error(48473),
                3: local_async_job_error(73722),
            },
        ),
    )

    def test_experiment(self):
        pass
