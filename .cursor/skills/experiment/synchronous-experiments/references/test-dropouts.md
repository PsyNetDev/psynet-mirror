# Testing dropouts: worked example

A worked example for "Decide and test failure cases" in `synchronous-experiments/SKILL.md`.

After each dropout, assert who failed (`bot.failed`), what each remaining bot
sees (`bot.current_page_text`), and that the others carry on. This test
plays two teams of three that can go on with two (`quorum=2`), and drops one
member of each team, one by quitting and one by going silent. The silent
member is failed for being late (`late_action="fail"`); failing isn't a
penalty, it ends a session that can no longer contribute, and the
participant is paid for what they completed:

```python
# Long, so the poller can't remove the silent member before make_late_now.
LATE_AFTER = 60

class Exp(psynet.experiment.Experiment):
    test_n_bots = 6
    timeline = Timeline(
        MainConsent(),
        SimpleGrouper("team", initial_group_size=3, quorum=2, below_quorum="fail"),
        InfoPage("Round 1.", time_estimate=5),
        GroupBarrier(id_="round_1", group_type="team",
                     late_after=LATE_AFTER, late_action="fail"),
        InfoPage("Round 2.", time_estimate=5),
        GroupBarrier(id_="round_2", group_type="team"),
        InfoPage("Done.", time_estimate=5),
    )

    def test_serial_run_bots(self, bots):
        for team in (bots[:3], bots[3:]):
            for bot in team:
                bot.take_page()
            advance_past_wait_pages(team)
        (quitter, *stayers), (silent, *on_time) = bots_by_sync_group(bots, "team")

        quitter.drop_out()
        for bot in stayers:
            bot.take_page()
        advance_past_wait_pages(stayers)
        for bot in stayers:
            assert bot.current_page_text == "Round 2.", bot.current_page_text

        silent.allow_failure()
        for bot in on_time:
            bot.take_page()  # silent never answers round 1
        make_late_now(on_time, "round_1")  # instead of waiting LATE_AFTER
        assert silent.failed
        for bot in on_time:
            assert bot.current_page_text == "Round 2.", bot.current_page_text

        run_bots_to_completion([*stayers, *on_time])
        assert not any(bot.failed for bot in [*stayers, *on_time])
```

If another member of either team left, the last one would be below the
quorum and failed (`below_quorum="fail"`); call `allow_failure()` for them
too, and assert `bot.failed`.

`make_late_now` moves the group's clocks back so that the barrier's next
check removes the silent member as `late_after` would. Bot tests wait out
other timeouts in real time, so pass `advance_past_wait_pages` a `timeout`
longer than the `max_wait_time` being tested. The
default `test_check_bot` accepts bots that called `drop_out()` or
`allow_failure()`; call `allow_failure()` for every bot the design fails on
purpose.

`tests/experiments/pair_dropout` in the PsyNet repository tests the advanced
setup instead, `late_action="leave_group"` with
`below_quorum="continue_without_group"`, where the partner carries on alone
and a member removed for being late is told on the page they are on.
PsyNet rejects `late_action="leave_group"` with `below_quorum="fail"`
at load; it can only log a warning for barriers built in `show_trial`.
