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

When the bots finish, the log shows one row per place the job runs, async
job label, priority and `cpu_heavy` declaration, for jobs that finished:

```text
Async job CPU time (CPU-heavy: mean CPU >= 50% of mean wall time):
  Runs in  Label           Priority  Count  Mean CPU (s)  Max CPU (s)  Mean wall (s)  CPU-heavy
  worker   AsyncCodeBlock  high          2         0.027        0.052          0.085         no
```

`Runs in` is `worker` for `WorkerAsyncJob` jobs, which run in worker
processes, and `web` for `LocalAsyncJob` jobs, such as asset deposits. These
run in a thread of the process that enqueued them, which is usually the web
process; one enqueued from a worker job runs in that worker. Local jobs skip
the worker queues, so their priority is `-`.

If the log says `No async jobs finished.` and the experiment doesn't use async
jobs, it puts no load on the workers; go straight to the performance test. If
it does use them, look for failed jobs in the log first.

For per-job values, export the data (`psynet export local`) and read the
`cpu_time`, `time_taken` and `queue_delay` columns of
`database/async_job.csv`.

## Interpret the numbers

A **CPU-heavy** job, such as audio analysis or model fitting, keeps a CPU core
busy while it runs, and would stall the other jobs of a worker process, which
runs up to `worker_greenlets_per_process` jobs at once. Every job declares
whether it is CPU-heavy (`cpu_heavy=` on `WorkerAsyncJob` and `AsyncCodeBlock`,
`async_post_trial_cpu_heavy` on a trial class that defines `async_post_trial`,
and likewise `async_post_grow_network_cpu_heavy` and `async_on_deploy_cpu_heavy`;
recording trials declare `True`), and CPU-heavy jobs run in CPU workers. Each
worker process starts `cpu_processes_per_worker` of them (default 1), which run
one job at a time, so CPU-heavy jobs queue behind each other unless there are
more worker processes. Set the number of worker processes with
`worker_processes` in `config.txt`; on an SSH deployment each worker process is
a separate worker container, with its CPU workers. If the log warns that a job
declared `cpu_heavy=False` looks CPU-heavy, check what the job does and fix the
declaration. Before a performance
test, make a first estimate of `worker_processes`, aiming for the CPU workers
70% busy. The performance test summary uses the same formula when the CPU
workers were busy the whole time:

```text
CPU-worker seconds per participant = sum of (Count × Mean wall) over CPU-heavy worker rows / number of bots
worker_processes                   = participants at once × CPU-worker seconds per participant / (session seconds × 0.7 × cpu_processes_per_worker)
```

Count only the rows of the jobs your code declares CPU-heavy (the table's
`CPU-heavy` column is measured, not declared): CPU workers run one of them
at a time, so each is busy for the job's whole run time, which is why the
formula uses Mean wall rather than Mean CPU. The other worker jobs mostly wait
and share a worker process's greenlets; the performance test sizes them
separately and recommends whichever needs more processes, which is rarely
them. With `cpu_processes_per_worker = 0`, CPU-heavy jobs share the worker
processes instead, so sum over all worker rows and drop that factor.

For example, 2 bots that ran 6 `analyse_audio` jobs declared CPU-heavy,
averaging 1.5 seconds, need 4.5 CPU-worker seconds per participant. With 100
participants at once in a 10-minute session and one CPU worker per process,
100 × 4.5 / (600 × 0.7) = 1.1, so start with `worker_processes = 2`, on a
server with a core for each worker process and each CPU worker, plus two for
the web server and database.

Do not count `web` rows toward `worker_processes`: more workers do not help
them. A CPU-heavy `web` row competes with page requests in the web process,
so expect slower responses in the performance test; if they are too slow,
make the job cheaper or move its work into a `WorkerAsyncJob`.

An **I/O-bound** job, such as an API call or an upload, mostly waits, so more
cores do not help it.

**Priority** says whether a participant waits for a worker job (`high`) or
not (`low`); worker processes start `high` jobs first. CPU workers ignore
priority and take CPU-heavy jobs in the order they were enqueued, so a burst of
`low` analyses, such as analysing every main tapping trial, delays the `high`
ones queued behind it, such as calibration or feedback analyses. Size the CPU
workers (through `worker_processes`) so that the CPU queue stays short at
peak. If a label has the wrong priority, override it as described in
`reference/api/async_job`.

While a job waits on I/O, its process runs other work, and `cpu_time` counts
that too: other jobs in a worker, and page requests in the web process. With a
few bots in `psynet test local`, `worker` jobs mostly run alone, so their
numbers are close to exact; under load they are an upper bound. `web` jobs
share the web process with the bots' page requests, so a `web` row that waits
on I/O, such as an upload, can look CPU-heavy when it isn't. Your computer may
also be faster or slower than the server.

`cpu_time` counts only the job's own thread. CPU used by subprocesses (such as
`ffmpeg`) or by library threads (such as NumPy's BLAS) is missing, so a job
that shells out can look I/O-bound. For such jobs, judge from `Mean wall`
and confirm with the performance test.

## Confirm with a performance test

Run `psynet performance-test local` at the expected peak load, as described
in `test/scalability`, then on the real server with
`psynet performance-test ssh`. In the "Async job times" section, a high queue
share means jobs wait for a free worker, and the report says how busy the
worker processes were in the steady state. The capacity summary's
"Recommended settings" paragraph then estimates `worker_processes` for the cap from the
measured utilization, the start-up burst and the server's cores, as
described under "Async workers" in `test/scalability`.
