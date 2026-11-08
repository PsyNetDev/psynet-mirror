"""Pairs that lose a member, as a model for testing dropouts with bots.

In the first pair, one member returns the study mid-game. In the second, one
member stops responding and is removed for being late. In the third, one member
fails, as after a failed check. With
``below_quorum="continue_without_group"``, the partner who stayed carries on
alone in each case and is told why on their next page. The member removed for
being late is told on the page they are on.
"""

import psynet.experiment
from psynet.bot import BotDriver, advance_past_wait_pages, run_bots_to_completion
from psynet.consent import MainConsent
from psynet.page import InfoPage
from psynet.sync import GroupBarrier, SimpleGrouper, only_in_group
from psynet.timeline import Timeline

LATE_AFTER = 5


def _finish_round_1(participants):
    for participant in participants:
        participant.var.finished_round_1 = True


class Exp(psynet.experiment.Experiment):
    label = "Pair dropout"

    test_n_bots = 6

    timeline = Timeline(
        MainConsent(),
        SimpleGrouper(
            "pair", initial_group_size=2, below_quorum="continue_without_group"
        ),
        InfoPage("Round 1.", time_estimate=5),
        GroupBarrier(
            id_="round_1",
            group_type="pair",
            late_after=LATE_AFTER,
            late_action="leave_group",
            on_release=_finish_round_1,
            on_dissolve=_finish_round_1,
        ),
        only_in_group(
            "pair",
            InfoPage("Round 2 with your partner.", time_estimate=5),
            otherwise=InfoPage("Round 2 on your own.", time_estimate=5),
        ),
        GroupBarrier(id_="round_2", group_type="pair"),
        only_in_group(
            "pair", InfoPage("Thanks for playing together.", time_estimate=5)
        ),
        InfoPage("Done.", time_estimate=5),
    )

    def test_serial_run_bots(self, bots: list[BotDriver]):
        quitter, stayer, on_time, silent, failer, survivor = bots
        for pair in [(quitter, stayer), (on_time, silent), (failer, survivor)]:
            for bot in pair:
                bot.take_page()
            advance_past_wait_pages(list(pair))
            texts = [bot.current_page_text for bot in pair]
            assert texts == ["Round 1."] * 2, texts

        # silent never answers round 1; on_time waits for them at the barrier.
        on_time.take_page()
        assert on_time.current_page_text.startswith("Waiting for"), (
            on_time.current_page_text
        )
        assert silent.current_notice == "Your partner is ready.", silent.current_notice

        quitter.drop_out()
        assert quitter.failed
        stayer.take_page()
        advance_past_wait_pages([stayer])
        self._assert_carries_on_alone(stayer)

        advance_past_wait_pages([on_time], timeout=LATE_AFTER + 10)
        self._assert_carries_on_alone(on_time)
        # Their pair dissolved while they waited, so on_dissolve ended the round
        # for them; the stayer arrived after their pair had gone.
        finished = [
            bot.with_participant(lambda p: p.var.get("finished_round_1", False))
            for bot in (on_time, stayer)
        ]
        assert finished == [True, False]

        assert (
            silent.with_participant(
                lambda participant: participant.sync_group_removal_reason("pair")
            )
            == "late"
        )
        # Told they were too slow on the page they are on, not that their
        # partner left them.
        assert silent.current_notice == (
            "Your partner went on without you. Please continue."
        ), silent.current_notice
        silent.take_page()
        assert silent.current_page_text == "Round 2 on your own.", (
            silent.current_page_text
        )
        assert silent.current_notice is None, silent.current_notice

        failer.allow_failure()
        failer.fail("failed_check")
        survivor.take_page()
        advance_past_wait_pages([survivor])
        self._assert_carries_on_alone(survivor)

        carried_on = [stayer, on_time, silent, survivor]
        for bot in carried_on:
            bot.take_page()
            advance_past_wait_pages([bot])
            assert bot.current_page_text == "Done.", bot.current_page_text
        run_bots_to_completion(carried_on)
        assert not any(bot.failed for bot in carried_on)

    @staticmethod
    def _assert_carries_on_alone(bot):
        assert bot.current_page_text == "Round 2 on your own.", bot.current_page_text
        assert bot.current_notice == (
            "Your partner is no longer in your group. Please continue."
        ), bot.current_notice
