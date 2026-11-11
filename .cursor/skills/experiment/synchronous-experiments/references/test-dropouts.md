# Testing dropouts: worked example

A worked example for "Decide and test failure cases" in `synchronous-experiments/SKILL.md`.

After each dropout, assert who failed (`bot.failed`), what each remaining bot
sees (`bot.current_page_text` and `bot.current_notice`), and that branches on
`participant.in_sync_group(group_type)` lead somewhere sensible. This pair
test drops one member of each pair, one by quitting
and one by going silent:

```python
LATE_AFTER = 5

class Exp(psynet.experiment.Experiment):
    test_n_bots = 4
    timeline = Timeline(
        MainConsent(),
        SimpleGrouper("pair", initial_group_size=2, below_quorum="continue_without_group"),
        InfoPage("Round 1.", time_estimate=5),
        GroupBarrier(id_="round_1", group_type="pair",
                     late_after=LATE_AFTER, late_action="leave_group"),
        conditional(
            "round_2",
            lambda participant: participant.in_sync_group("pair"),
            join(
                InfoPage("Round 2 with your partner.", time_estimate=5),
                GroupBarrier(id_="round_2", group_type="pair"),
            ),
            InfoPage("Round 2 on your own.", time_estimate=5),
        ),
        InfoPage("Done.", time_estimate=5),
    )

    def test_serial_run_bots(self, bots):
        quitter, stayer, on_time, silent = bots
        for pair in [(quitter, stayer), (on_time, silent)]:
            for bot in pair:
                bot.take_page()
            advance_past_wait_pages(list(pair))

        quitter.drop_out()
        stayer.take_page()
        advance_past_wait_pages([stayer])
        assert stayer.current_page_text == "Round 2 on your own.", stayer.current_page_text
        assert stayer.current_notice == (
            "Your partner is no longer in your group. Please continue."
        ), stayer.current_notice

        on_time.take_page()  # silent never answers round 1
        make_late_now([on_time], "round_1")  # instead of waiting LATE_AFTER
        assert on_time.current_page_text == "Round 2 on your own.", on_time.current_page_text

        # silent comes back after being removed, and is told on the page they are on
        assert silent.current_notice == (
            "Your partner went on without you. Please continue."
        ), silent.current_notice
        silent.take_page()
        assert silent.current_page_text == "Round 2 on your own.", silent.current_page_text

        run_bots_to_completion([stayer, on_time, silent])
        assert not any(bot.failed for bot in [stayer, on_time, silent])
```

`tests/experiments/pair_dropout` in the PsyNet repository extends this with
a third pair whose member is failed.

`make_late_now` moves the group's clocks back so that the barrier's next
check removes the silent member as `late_after` would. Bot tests wait out
other timeouts in real time, so pass `advance_past_wait_pages` a `timeout`
longer than the `max_wait_time` being tested. The
default `test_check_bot` accepts bots that called `drop_out()` or
`allow_failure()`; call `allow_failure()` for every bot the design fails on
purpose, such as a partner left behind under the default
`below_quorum="fail"`. If a late member fails the partners who were on time
(PsyNet logs a warning when that happens) and the design didn't mean to,
pass `below_quorum="continue_without_group"` rather than changing the test.
