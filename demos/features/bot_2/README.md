# README

When you need bots to keep feeding a live experiment — not just exercise a page
once — schedule them with `@scheduled_task` and `WorkerAsyncProcess`. This clone
of the imitation-chain number-memory demo launches a bot every 10 seconds, marks
each as a good or bad rememberer in `initialize_bot`, and lets those answers
propagate through the chain.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).
