Agentic programming with PsyNet
===============================

What is agentic programming?
----------------------------

Agentic programming uses an AI coding agent to carry out software-development
tasks on your behalf. A coding agent can inspect a project, edit files, run
commands, observe the results, and refine its implementation in response.

Popular tools include Cursor, Claude Code, and OpenAI Codex. They differ in
interface and capabilities, but share the same basic model: you describe the
desired outcome, give the agent access to the development environment, and
review the work it produces.

The most effective agents work directly inside the project directory. This
gives them access to the source code, documentation, dependencies,
command-line tools, and runtime feedback needed to make informed changes.

Why PsyNet works well with coding agents
----------------------------------------

PsyNet experiments are represented almost entirely in code. The experiment
structure, participant flow, stimuli, configuration, browser behavior, tests,
simulations, and deployment setup are all available for an agent to inspect
and modify.

PsyNet itself is open source. When an agent needs to understand an API or
diagnose unexpected behavior, it can inspect the installed PsyNet source and
run the experiment directly. This supports a complete implementation loop
within the development environment.

The researcher remains responsible for the scientific design and for deciding
whether the resulting experiment faithfully implements it.

How PsyNet supports coding agents
---------------------------------

PsyNet provides two main forms of support for agentic programming.

Agent Skills
^^^^^^^^^^^^

Running ``psynet setup`` installs a collection of PsyNet Agent Skills into the
experiment directory. These skills give coding agents structured guidance for
planning experiments, selecting PsyNet components, implementing participant
flows, testing behavior, debugging problems, and preparing results for review.

Compatible tools discover these skills from the project directory. This
supplies agents with PsyNet-specific working practices alongside their
general programming capabilities.

Experiment audits
^^^^^^^^^^^^^^^^^

PsyNet's audit workflow gives the agent a structured way to present its work
for human review. An audit records the original request, implementation plan,
development timeline, validation results, evidence, and any remaining
blockers.

The agent prepares the audit as it works. The researcher then reviews the
rendered audit, checks the evidence, and requests further changes where
necessary. See :doc:`audit` for the packet format and CLI.

Implementing an experiment with an agent
----------------------------------------

1. Open a project directory
^^^^^^^^^^^^^^^^^^^^^^^^^^^

Create an empty directory for the experiment and open it as the workspace in
your AI-assisted IDE. Open a terminal in that directory.

2. Install PsyNet
^^^^^^^^^^^^^^^^^

Paste the following:

.. code-block:: bash

    uv venv --python 3.13
    source .venv/bin/activate
    uv pip install psynet
    psynet setup

``psynet setup`` prepares the experiment directory, initializes Git, installs
the full experiment environment, and adds the PsyNet Agent Skills.

This assumes PsyNet's system prerequisites are already available (Python 3.13,
Git, uv, PostgreSQL, Redis, Chrome). See the
:doc:`/installation/index` documentation if you are setting up a machine for
the first time. On Windows, use WSL (Ubuntu) and paste these same commands in
the Ubuntu terminal; see
:doc:`/installation/virtual_environment_installation/windows`. Native Windows
is not supported.

3. Describe the experiment
^^^^^^^^^^^^^^^^^^^^^^^^^^

Ask the agent to implement the experiment, giving it the same information you
would give a human developer:

* the scientific design;
* the participant procedure;
* the stimuli and response formats;
* randomization and condition assignment;
* data that must be recorded;
* practical or deployment constraints.

For example::

    Implement a PsyNet experiment from the specification below. Let's start
    by agreeing a plan. Once the plan is agreed, you can do the
    implementation and testing, and then handover to me for review.

The PsyNet Agent Skills already tell the agent to use the audit workflow, so
you do not need to mention audits, commands, or skill paths in the prompt.

The agent should turn the specification into a concrete plan before
implementation. Reviewing this plan is an important opportunity to correct
misunderstandings about the science or participant experience.

4. Let the agent implement and test
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Once the plan is agreed, the agent should implement the experiment and test
it itself, including taking the participant flow and checking the resulting
data.

5. Review the result
^^^^^^^^^^^^^^^^^^^^

When the agent is ready to hand over, it should offer to open the rendered
audit in a browser. Accept that offer and review the plan, implementation
summary, timeline, evidence, and blockers. You can then ask the agent to
address specific issues and update the audit.

The researcher decides when the experiment is scientifically and
operationally ready.

If you would rather start from an existing demo and edit it yourself, see
:doc:`/tutorials/creating_a_new_experiment`.

Debugging with coding agents
----------------------------

Coding agents are particularly useful for debugging when they can reproduce
the problem themselves. Give the agent access to the experiment directory and
tell it what you expected, what happened, and how to reach the failing
behavior. Let it run the relevant PsyNet commands, inspect the output and
source code, apply a fix, and verify the result in the same environment.

Give the agent the real failing command and its output whenever you have
them, and let it rerun that command after each attempted fix.

The same approach can be used for deployed experiments. PsyNet deployments
already provide SSH access with the usual connection details. Describe the
observed issue and ask the agent to investigate the running system directly.

See also
--------

* :doc:`/tutorials/creating_a_new_experiment`
* :doc:`development_workflow`
* :doc:`audit`

