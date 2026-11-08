"""Pairs that lose a member, as a model for testing dropouts with bots.

In the first pair, one member returns the study mid-game. In the second, one
member stops responding and is removed for being late. With
``below_quorum="leave_group"``, the partner who stayed carries on alone in
both cases and is told why on their next page.
"""

import psynet.experiment
from psynet.bot import BotDriver, advance_past_wait_pages
from psynet.consent import MainConsent
from psynet.page import InfoPage
from psynet.sync import GroupBarrier, SimpleGrouper
from psynet.timeline import Timeline, conditional

LATE_AFTER = 5


class Exp(psynet.experiment.Experiment):
    label = "Pair dropout"

    test_n_bots = 4

    timeline = Timeline(
        MainConsent(),
        SimpleGrouper("pair", initial_group_size=2, below_quorum="leave_group"),
        InfoPage("Round 1.", time_estimate=5),
        GroupBarrier(
            id_="round_1",
            group_type="pair",
            late_after=LATE_AFTER,
            late_action="leave_group",
        ),
        conditional(
            "still_paired",
            lambda participant: participant.in_sync_group("pair"),
            InfoPage("Round 2 with your partner.", time_estimate=5),
            InfoPage("Round 2 on your own.", time_estimate=5),
        ),
        GroupBarrier(id_="round_2", group_type="pair"),
        InfoPage("Done.", time_estimate=5),
    )

    def test_serial_run_bots(self, bots: list[BotDriver]):
        quitter, stayer, on_time, silent = bots
        for pair in [(quitter, stayer), (on_time, silent)]:
            for bot in pair:
                bot.take_page()
            advance_past_wait_pages(list(pair))
            assert all(bot.current_page_text == "Round 1." for bot in pair)

        quitter.drop_out()
        assert quitter.failed
        stayer.take_page()
        advance_past_wait_pages([stayer])
        self._assert_carries_on_alone(stayer)

        on_time.take_page()
        advance_past_wait_pages([on_time], timeout=LATE_AFTER + 10)
        self._assert_carries_on_alone(on_time)

        silent.take_page()
        self._assert_carries_on_alone(silent)

        for bot in [stayer, on_time, silent]:
            bot.run_to_completion()
            assert not bot.failed

    @staticmethod
    def _assert_carries_on_alone(bot):
        assert bot.current_page_text == "Round 2 on your own."
        assert bot.current_notice == (
            "Your partner is no longer in your group. Please continue."
        )
