# Prolific auto-recruit deployment test

This experiment tests whether Prolific continues supplying participants when
PsyNet automatically adds places to a running study.

## Expected recruitment sequence

The experiment uses a `StaticTrialMaker` with:

- `recruit_mode="n_participants"`
- `target_n_participants=10`
- `initial_recruitment_size=1`
- `auto_recruit=True`

The study therefore opens with one place. After each of the first nine
completions, PsyNet should add one place through Prolific. Participant 10
reaches the target, so no further place should be added.

Keeping the initial recruitment size at one is intentional: it makes the
automatic top-ups observable and avoids satisfying the target in the initial
batch.

## Run locally

Use the simulated Prolific recruiter, which does not recruit or pay people:

```bash
cp config.txt.devprolific config.txt
psynet test local
```

## Paid Prolific deployment

Immediately before deployment, select the paid variant:

```bash
cp config.txt.prolific config.txt
psynet deploy ssh --app <app-name>
```

`config.txt` is intentionally ignored. Keep the named variants unchanged so
the selected recruiter is always explicit.

## What to verify

1. The Prolific study begins with exactly one available place.
2. After each of the first nine completions, a new participant can enter.
3. No eleventh place is added after participant 10 completes.
4. PsyNet logs request another participant after completions 1 through 9, then
   decline recruitment after completion 10.
5. Prolific shows ten completed submissions and no unexplained pause between
   them.

If PsyNet logs show `Conclusion: recruiting another participant` but Prolific
does not expose a new place, the failure is downstream of the recruitment
criterion and should be investigated in the Prolific API interaction.
