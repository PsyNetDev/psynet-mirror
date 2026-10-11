---
name: plan-server-resources
description: Measure how much CPU each async job of a PsyNet experiment uses with psynet test local, tell CPU-heavy jobs from I/O-bound ones, and confirm worker capacity with psynet performance-test. Use before a performance test, or when choosing worker processes or server size for an experiment that runs async jobs.
---

# Plan server resources

## Read first

Read these pages before acting. The "Documentation" section of the experiment's `AGENTS.md` explains how to find and search them.

- `test/scalability` — `psynet performance-test` and how to read its report
- `reference/api/async_job` — job priority, and async job columns including `cpu_time`

## Measure async job CPU

Run the bots locally from the experiment directory:

```bash
psynet test local
```

When the bots finish, the log shows one row per async job label and
priority, for jobs that finished:

```text
Async job CPU time (CPU-heavy: mean CPU >= 50% of mean wall time):
  Label           Priority  Count  Mean CPU (s)  Max CPU (s)  Mean wall (s)  CPU-heavy
  AsyncCodeBlock  high          2         0.027        0.052          0.085         no
```

If the log says `No async jobs finished.` and the experiment doesn't use async
jobs, it puts no load on the workers; go straight to the performance test. If
it does use them, look for failed jobs in the log first.

For per-job values, export the data (`psynet export local`) and read the
`cpu_time`, `time_taken` and `queue_delay` columns of
`database/async_job.csv`.

## Interpret the numbers

A **CPU-heavy** job, such as audio analysis or model fitting, keeps a CPU core
busy while it runs. A worker process uses one core, so these jobs queue
behind each other unless there are more worker processes. Set the number of
worker processes with `num_dynos_worker` in `config.txt`; on an SSH
deployment each one is a separate worker container. Estimate the cores the
jobs keep busy at peak:

```text
CPU seconds per participant = sum of (Count × Mean CPU) over CPU-heavy labels / number of bots
busy cores at peak          = CPU seconds per participant × participants starting per second
```

For example, 2 bots that ran 6 `analyse_audio` jobs averaging 1.5 CPU
seconds need 4.5 CPU seconds per participant. With 40 participants starting
per minute, 4.5 × 40 / 60 = 3 cores are busy, so leave headroom with
`num_dynos_worker = 4` on a server with a core for each worker plus one for
the web process.

An **I/O-bound** job, such as an API call or an upload, mostly waits, so more
cores do not help it.

**Priority** says whether a participant waits for the job (`high`) or not
(`low`); workers start `high` jobs first. A long CPU-heavy `low` job, such
as analysing every main tapping trial, still occupies a worker until it
finishes, so size the workers so that `high` jobs, such as calibration or
feedback analyses, find a free one at peak. If a label has the wrong
priority, override it as described in `reference/api/async_job`.

In a worker that runs several jobs at once, `cpu_time` also counts the other
jobs that ran while this one waited on I/O. With a few bots in
`psynet test local` the jobs mostly run alone, so the numbers are close to
exact; under load they are an upper bound. Your computer may also be faster
or slower than the server.

## Confirm with a performance test

Run `psynet performance-test local` at the expected peak load, as described
in `test/scalability`, then on the real server with
`psynet performance-test ssh`. In the "Async job times" section, a high queue
share means jobs wait for a free worker: add worker processes, or make the
CPU-heavy jobs cheaper.
