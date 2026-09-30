# Design simulation: the method

A **design simulation** runs the planned experiment many times on
computer-generated participants before any real data are collected. Each
simulated experiment is analyzed with the planned analysis, and the results
show how well each candidate design would answer the research question and, if
the experiment pays participants, what each design would cost. Use it to choose
the number of participants, stimuli and trials. A design simulation is
optional; when there is one, it goes in the experiment's audit.

This page explains the ideas and the recommended defaults. The files and code
are in [design-simulation-setup.md](design-simulation-setup.md).

## Designs, assumptions and scenarios

Keep three things apart: what the experimenter chooses, what is assumed about
the world, and what the analysis tries to learn.

- A **design** is an experiment that could be run: the number of participants,
  stimuli and trials per participant, the allocation across conditions, or the
  budget of an adaptive procedure.
- **Assumptions** describe the world the design is tested in: how noisy single
  responses are, how much participants and stimuli differ, how strong an effect
  is, and how many responses go missing. They are uncertain before data
  collection. The number of stimuli is a design choice; the population the
  stimuli are drawn from is an assumption.
- A **scenario** is one design combined with one complete set of assumptions.
  Five participant counts, two trial counts and three noise levels give 30
  scenarios.
- A **replicate** is one complete simulated experiment under a scenario, with
  newly drawn participants and responses. Many replicates per scenario show how
  much the results would vary between repeated real experiments.
- An **analysis target** is one scientific quantity evaluated in each scenario,
  such as a condition effect or a set of stimulus profiles. Several targets are
  analyzed from the same simulated experiments; they don't need separate
  simulated worlds.
- A **decision criterion** is the rule that says whether a design is good
  enough for a target, such as a maximum margin of error.

Test several plausible assumption sets when the choice of design depends on
them. A design that works only under optimistic assumptions is less convincing
than one that stays adequate across a reasonable range.

## Response models

A **response model** generates simulated answers from assumptions about how
participants behave. For a rating task it might say that a rating is the
participant's usual level, plus the effect of the condition, plus random noise,
rounded to the rating scale. Its parameter values come from pilot data, the
literature, or judgment, and the simulation records which.

Use one response model for both the design simulation and the experiment's
bots, so that the bots' practice data and the design simulation describe the
same simulated world. The response model applies the same rounding and limits
as the real response controls. The `participant-response-models` skill builds
it.

Keep the response model separate from two other models that may share its
mathematics:

- the **estimator**, the planned analysis that tries to recover the quantities
  of interest from the responses;
- in an adaptive experiment, the **learner**, which uses its own model of
  participants to choose what to present next.

In a simulation of an adaptive experiment, the response model can match the
learner or deliberately differ from it, to test how the procedure copes when
its assumptions are wrong. In the real experiment, participants supply the
responses.

## Precision and power

A classical **power analysis** asks how often a hypothesis test would reject the
null hypothesis if an effect of a given size were real. The recommended default
is **precision estimation** instead: it asks how precisely the planned analysis
would estimate each quantity of interest. Precision suits experiments that
measure profiles, rankings or many stimulus-specific values, where there is no
single test to power, and it still applies when there is one. The
`precision-estimation` skill implements it.

Use **power** as the decision metric when the question is whether an effect
exists: the experimenter names a smallest effect worth detecting, or asks for
a power analysis. Power is the share of replicates in which the planned test
rejects the null hypothesis at the planned α, with the true effect set to that
smallest size. Its Monte Carlo standard error is √(p(1 − p)/R) for power p over
R replicates. The usual requirement is 80% or 90%; agree it with the
experimenter. Report the margin of error alongside, so readers see what the
study will estimate as well as whether it will detect. If the analysis tests
several effects, report power at any corrected α the analysis will use, and,
when the response model sets some effects to zero, how often those tests
reject (the false-positive rate, which should be close to α).

Each quantity of interest is an **estimand**, such as a mean difference between
conditions, a regression slope, or a stimulus's response profile. Across
replicates, the planned estimator gives a spread of estimates for each
estimand:

- The **sampling standard error** is the standard deviation of these estimates.
  It approximates how much the estimate would vary between repeated real
  experiments.
- The **margin of error** is half the width of an approximate confidence
  interval, about 1.96 sampling standard errors at 95% confidence. State it in
  the estimand's own units: a chord rated 4.7 with a margin of error of 0.2
  rating points is known to lie roughly between 4.5 and 4.9.
- **Bias** is the average difference between the estimates and the true value
  built into the response model. A precise but biased estimator is not
  acceptable.
- **Coverage** is how often the estimator's own confidence intervals contain the
  true value, when the estimator produces intervals.

When the estimand is a set of values, such as each stimulus's mean rating,
also report:

- The **root mean square (RMS) margin of error** across the set, the square
  root of the mean squared margin, and the **largest** margin. With many
  values, the largest of their Monte Carlo estimates is inflated by Monte
  Carlo error, so it is not a stable basis for a decision. If the largest is
  much bigger than the RMS, say which values are least precise.
- The **margin of error of a difference**: how far apart two values must be
  for the study to order them reliably. Compute it from the replicates rather
  than as √2 times the margin of error of a single value. When every participant responds to
  every stimulus, shared variation such as a participant's overall bias cancels
  in differences, so they are more precise than that approximation suggests.
- The **profile correlation**: in each replicate, the correlation between the
  estimated and the true values, averaged over replicates on the Fisher-z
  scale. It answers whether the study can tell the stimuli apart.
- The **smallest spread for a target correlation**: the smallest standard
  deviation of the true values across the set at which the design would still
  reach that correlation (0.9 by default). The expected squared correlation is
  about S² / (S² + SE²), where S is that standard deviation and SE is the root
  mean square sampling standard error of the estimates after subtracting each
  replicate's mean across the set. The smallest spread for a correlation r is
  therefore SE × r / √(1 − r²).

These measures differ in how much they depend on the assumptions. The margin
of error, including the margin of error of a difference, depends on how noisy
responses are, which pilot data or earlier studies with the same scale estimate
well. The profile correlation also depends on how much the stimuli truly
differ, which is what the study sets out to measure and usually the least
certain assumption. The smallest spread for a target correlation depends only
on the noise, so it states the design's resolving power without assuming the
answer.

For example, in a study where 160 participants each rate 40 chords on a 1–7
scale, the design simulation might report that each chord's mean is known to
within about ±0.18 rating points, that chords more than about 0.22 points apart
are reliably ordered, and that the estimated means correlate at least 0.9 with the
true ones whenever the true means have a standard deviation of at least 0.16
points. The response model assumes a spread of 0.71, which gives a profile
correlation of 0.99, but the last conclusion holds for any spread above 0.16.

Because the simulation uses a finite number of replicates, its own summaries are
uncertain too. Report this **Monte Carlo error** alongside each result; if it
could change which design is chosen, run more replicates.

For adaptive experiments, the main measure is often how closely each
participant's final estimate matches their true value, reported as the root
mean squared error (RMSE), with correlation, bias and coverage as diagnostics.

## Choosing the required precision

There is no default threshold: how precise an estimate must be depends on the
research question. Agree the threshold with the experimenter before running the
full simulation, state it in the response's units, and record the reason with
it.

1. Ask what precision the question needs: the smallest difference that would
   matter, or the precision of earlier estimates the study should match or
   improve on.
2. If the experimenter has no view, propose a threshold derived from the
   question and explain the derivation:
   - To detect an effect, use power, as in "Precision and power". A
     margin-of-error requirement is equivalent to a power requirement: 80%
     power at two-sided α = 0.05 needs a margin of error of about 0.7 times
     the smallest effect worth detecting, and 90% power about 0.6 times.
     Requiring half the effect amounts to about 97.5% power, which is much
     stricter than usual.
   - To rank or profile stimuli, choose the smallest difference between two
     stimuli that the study should order reliably, and apply it to the margin
     of error of a difference. The smallest spread for a 0.9 correlation
     shows whether that also separates the stimuli as a whole.
3. If no value can be justified, make no pass/fail decision. Show precision and
   cost against the design, point out where more participants or trials bring
   little gain, and let the experimenter choose.

Keep the threshold fixed across scenarios. Deriving it from each scenario's own
noise would relax the requirement as responses get noisier, so the noisiest
assumptions would appear to need the fewest participants. For a set of values,
apply it to the RMS margin across the set, of single values or of differences,
and report the largest alongside.

Choose the design under the reference assumptions, and report the smallest
design that meets the threshold under each alternative assumption set. If the
chosen design fails under an alternative that the experimenter considers
plausible, say so and give the design that alternative would need.

## What to simulate

Each replicate simulates every trial of the complete experiment: the planned
allocation to conditions and stimuli, missing responses, the response scale and
its rounding, and differences between participants and stimuli. The planned
analysis then runs on each simulated dataset. Shortcuts such as analytical
formulas or rejection rates of a simpler test are not substitutes for the
planned analysis.

Draw participants afresh for each replicate. Draw stimuli afresh too when the
study aims to generalize beyond the particular stimuli used; keep them fixed
when the claim is only about that set. The same reasoning applies to items,
groups and networks.

The experimenter may state the effect on the observed scale, such as a
correlation of 0.15 between a questionnaire score and behaviour, while the
response model generates it from latent quantities, measurement error and
interaction. Calibrate the model's parameter so that the observed effect, as
the planned analysis measures it on a very large simulated sample, equals the
stated size. Calibrate separately for each assumption set, and report the
calibrated values.

Run the design simulation as standalone code on the experimenter's computer,
not through PsyNet's server, so that it can run thousands of replicates. In an
adaptive experiment, simulate the full cycle of choosing a stimulus, generating
a response and updating the estimates, and treat the adaptive procedure as one
of the design factors compared.

Make the set of candidate designs fine enough to show where the criterion is
first met and where further participants or trials bring little gain.

## Adaptive stopping

An adaptive procedure that can stop early does not use its maximum number of
trials, so comparing it with a fixed design at that maximum overstates its
efficiency. First find a suitable fixed number of trials with stopping switched
off, then report what the stopping rule saves against that baseline: the
average number of trials, the saving in time and money, and the change in
precision. Fewer trials are only a saving if the precision cost is shown
alongside.

## Participant costs

If the experiment pays participants, compare each design's precision with its
cost. `psynet estimate` gives the payment per participant from the timeline's
time estimates and the hourly wage, and the cost of other designs follows from
the number of participants and trials. Before the timeline exists, take costs
from planned page and trial durations and label them provisional. State the
currency and whether the total includes performance bonuses, recruiter fees,
or extra recruitment to replace participants who drop out.

## Reporting the results

Write the report for someone who knows the study but not the statistics, such
as the experimenter's supervisor. Give the answer first, then the assumptions
behind it, and keep the statistical detail for the end:

1. **Summary.** A few plain sentences: the chosen design and what it achieves,
   in the response's units; the required precision and why; the smallest
   design that meets it under the reference assumptions and under each
   alternative; and what those designs cost.
2. **Assumptions** in everyday words, with the numbers in brackets: what the
   response model says, where its values come from and which are judgment,
   what each alternative assumption set represents, missing data, and the
   costs left out. For example: "a single rating varies by about 1 point
   around its typical value (standard deviation 1.0); the noisier-raters
   scenario assumes 1.3".
3. **What the results would look like.** One simulated dataset at the chosen
   design, analyzed as planned: for example, each stimulus's estimate with its
   interval. This shows what the precision means before any statistic is
   defined.
4. **One section per question**, headed by the question in plain words, such
   as "How many participants do we need?" or "How much does the ranking depend
   on our assumptions?". Give each one figure with the required precision
   marked, and a sentence saying what it shows. Show the smallest adequate
   design under each assumption set, with its cost, in a small table.
5. **Details for reviewers**: definitions of the statistics, the numbers of
   replicates, Monte Carlo intervals, bias, coverage, failed fits, and a table
   of every metric with readable column names.

Follow "Writing notebooks for readers" in
`produce-experiment-audit/references/populating-an-audit.md`: compute the summary, and give numbers with
the plain words, such as "noisier raters (rating noise SD 1.3)". Plot only the
factors that change the answer: if two assumption levels give the same result,
show one and say so.

## After data collection

The real data can check the design simulation's predictions without knowing
the true values. Report, in the analysis:

- the achieved margin of error of each primary estimand, from the planned
  estimator's own standard errors;
- for a profile, the **split-half reliability**: split the participants
  randomly into two halves, correlate the two halves' estimates, apply the
  Spearman–Brown correction 2r / (1 + r), and average over many random
  splits. Its square root estimates the profile correlation.

Put these beside the values the design simulation predicted for the chosen
design. Before launch, the same code runs on the simulated export, so it has
been tested when the real data arrive.

## Review checklist

Use these questions when you review a design simulation, whether you wrote it
or an agent did:

- [ ] Are the estimands the quantities the research question is about, and is
      every primary estimand evaluated?
- [ ] Does the required precision follow from the research question, and did
      the experimenter confirm it and its rationale?
- [ ] Is the estimator the analysis that will be run on the real data?
- [ ] Where do the response model's parameter values come from, and are values
      based on judgment identified as such?
- [ ] Do the alternative assumption sets cover the plausible range, and does
      the report give the smallest adequate design under each of them?
- [ ] Are margins of error stated in the response's units, and, for a
      profile, are the difference margin, the profile correlation and the
      smallest spread for the target correlation reported?
- [ ] Are stimuli drawn afresh between replicates when the claim generalizes
      beyond the sampled stimuli?
- [ ] Is bias reported next to precision, and is the Monte Carlo error small
      enough not to change the chosen design?
- [ ] Were failed model fits counted rather than dropped?
- [ ] For an adaptive procedure that stops early, is it compared at its actual
      average number of trials?
- [ ] Are costs based on the current timeline, and does the report say what
      they include?
- [ ] Does the analysis report the achieved margin of error and, for a
      profile, the split-half reliability?
