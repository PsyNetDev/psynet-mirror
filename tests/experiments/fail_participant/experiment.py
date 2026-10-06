import psynet.experiment
from psynet.bot import Bot
from psynet.consent import MainConsent
from psynet.db import transaction
from psynet.page import InfoPage, UnsuccessfulEndPage
from psynet.participant import Participant
from psynet.timeline import CodeBlock, ParticipantFailRoutine, Timeline, switch
from psynet.utils import get_logger

logger = get_logger()


class Exp(psynet.experiment.Experiment):
    label = "Failing a participant"

    test_n_bots = 4

    timeline = Timeline(
        MainConsent(),
        CodeBlock(
            lambda participant: participant.var.set("fail_routine_executed", False)
        ),
        switch(
            "switch",
            lambda participant: participant.id,
            {
                1: InfoPage("Nothing to see here...", time_estimate=5),
                2: UnsuccessfulEndPage(),
                3: CodeBlock(lambda participant: participant.fail("CodeBlock")),
                4: [
                    InfoPage("Page before external fail", time_estimate=5),
                    InfoPage("Should not reach this page", time_estimate=5),
                ],
            },
        ),
        ParticipantFailRoutine(
            "var",
            lambda participant: participant.var.set("fail_routine_executed", True),
        ),
    )

    def test_serial_run_bots(self, bots):
        for bot in bots:
            if bot.id == 2:
                while bot.take_page():
                    pass
                assert bot.current_page_label is None
            elif bot.id == 4:
                # Advance bot 4 past consent (and the var-init CodeBlock,
                # which is consumed silently) to the InfoPage.
                bot.take_page()
                assert "before external fail" in bot.current_page_text

                # Simulate a background process calling fail() outside advance_page.
                with transaction():
                    participant = Participant.query.get(bot.id)
                    participant.fail("BackgroundFail")

                # Bot submits response to the current page; the pending redirect
                # should send it to the unsuccessful_end branch.
                bot.run_to_completion()
            else:
                self.run_bot(bot, time_factor=self.test_time_factor)

    def test_check_bot(self, bot: Bot, **kwargs):
        if bot.id == 1:
            assert not bot.failed
            assert not bot.var.fail_routine_executed
            assert bot.complete

        elif bot.id == 2:
            assert bot.failed
            assert bot.var.fail_routine_executed
            assert bot.failed_reason == "UnsuccessfulEndPage"
            assert not bot.complete

        elif bot.id == 3:
            assert bot.failed
            assert bot.var.fail_routine_executed
            assert bot.failed_reason == "CodeBlock"
            assert not bot.complete

        elif bot.id == 4:
            assert bot.failed
            assert bot.var.fail_routine_executed
            assert bot.failed_reason == "BackgroundFail"
            assert not bot.complete
            assert bot.pending_redirect is None

        else:
            raise ValueError(f"Unexpected bot id: {bot.id}")
