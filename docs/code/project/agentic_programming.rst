Working with a coding agent
===========================

Coding agents such as Cursor, Claude Code and Codex can plan, write, test and
debug a PsyNet experiment. The researcher stays responsible for the
scientific design and for deciding whether the experiment implements it
faithfully.

What PsyNet gives the agent
---------------------------

``psynet setup`` installs PsyNet's **Agent Skills** into
``.cursor/skills/psynet/`` and an ``AGENTS.md`` file into the experiment
directory. Compatible agents read them from the project directory. They
tell the agent how to plan an experiment, choose PsyNet components, test with
simulated participants, and debug.

The skills also tell the agent to keep an **experiment audit**: a record of
the original request, the implementation plan, the development timeline,
validation results, evidence and remaining blockers. You review the rendered
audit when the agent hands over. :doc:`/reference/audit` describes the format
and commands.

Implement an experiment with an agent
-------------------------------------

#. Set up an experiment folder and start the local services as in
   :doc:`/quickstart`, then open the folder as the workspace in your agent.
   On Windows, run the commands in the Ubuntu (WSL) terminal.

#. Describe the experiment with the same information you would give a
   human developer:

   * the scientific design;
   * the participant procedure;
   * the stimuli and response formats;
   * randomization and condition assignment;
   * the data that must be recorded;
   * practical or deployment constraints.

   For example::

       Implement a PsyNet experiment from the specification below. Start by
       agreeing a plan with me. Once the plan is agreed, implement and test
       it, then hand over to me for review.

   You don't need to mention audits, commands or skill paths; the skills
   cover them.

#. Review the agent's plan before it starts implementing. This is the point
   at which misunderstandings about the science or the participant
   experience are cheapest to correct.

#. Let the agent implement the experiment and test it, including taking part
   as a participant and checking the resulting data.

#. When the agent hands over, it offers to open the rendered audit in a
   browser. Review the plan, implementation summary, timeline, evidence and
   blockers, and ask for changes where needed. Then run
   ``psynet debug local`` and take part yourself.

Debug with an agent
-------------------

Give the agent the failing command and its output, what you expected, and
how to reach the failing behavior. Let it run the command, read the output
and the PsyNet source, apply a fix, and rerun the command to check it.

For a deployed experiment, describe the problem and let the agent connect to
the server over SSH, using the same connection details as the deployment
commands, to investigate the running system.
