Getting help
============


How to investigate errors?
--------------------------

When programming, it frequently happens that you can get stuck. It is
okay to ask colleagues for help, but you should avoid asking questions
that have been asked before.

If you encounter an error, carefully inspect the stack trace. You can
click on the links to the files to inspect the lines where things break.
Also, scroll up to see if the error here was actually caused by
something else. Quite often the last error is just the ‘symptom’ but the
real error is above.

To get more insight on the issue, put a break point at the position
where your code breaks. This usually gives you more information about
why the error occurs. See the :ref:`development workflow
<development_workflow>` for the recommended editor and debugging setup.

Once you identified where your problem is, try searching for the
substring of error messages on Slack and on Google. Usually the last
line of the trace is the error you want to look for.

For example in this stack trace the last line is most relevant:

.. code:: text

   INFO:root:Compiling translation file on demand
   /Users/experimenter/Documents/projects/color-naming/locales/el/LC_MESSAGES/experiment.po.

   Traceback (most recent call last):
     File "/opt/homebrew/Caskroom/miniforge/base/envs/psynet/bin/psynet", line 8, in <module>
       sys.exit(psynet())
     File "/opt/homebrew/Caskroom/miniforge/base/envs/psynet/lib/python3.10/site-packages/click/core.py", line 1157, in __call__
       return self.main(*args, **kwargs)
     File "/opt/homebrew/Caskroom/miniforge/base/envs/psynet/lib/python3.10/site-packages/click/core.py", line 1078, in main
       rv = self.invoke(ctx)
     File "/opt/homebrew/Caskroom/miniforge/base/envs/psynet/lib/python3.10/site-packages/click/core.py", line 1688, in invoke
       return _process_result(sub_ctx.command.invoke(sub_ctx))
     File "/opt/homebrew/Caskroom/miniforge/base/envs/psynet/lib/python3.10/site-packages/click/core.py", line 1688, in invoke
       return _process_result(sub_ctx.command.invoke(sub_ctx))
     File "/opt/homebrew/Caskroom/miniforge/base/envs/psynet/lib/python3.10/site-packages/click/core.py", line 1434, in invoke
       return ctx.invoke(self.callback, **ctx.params)
     File "/opt/homebrew/Caskroom/miniforge/base/envs/psynet/lib/python3.10/site-packages/click/core.py", line 783, in invoke
       return __callback(*args, **kwargs)
     File "/opt/homebrew/Caskroom/miniforge/base/envs/psynet/lib/python3.10/site-packages/click/decorators.py", line 33, in new_func
       return f(get_current_context(), *args, **kwargs)
     File "/Users/jakobnieder/psynet/psynet/command_line.py", line 755, in deploy__docker_ssh
       _pre_launch(
     File "/Users/jakobnieder/psynet/psynet/command_line.py", line 639, in _pre_launch
       run_pre_checks(mode, local_, heroku, docker, app)
     File "/Users/jakobnieder/psynet/psynet/command_line.py", line 888, in run_pre_checks
       exp = get_experiment()
     File "/Users/jakobnieder/psynet/psynet/experiment.py", line 2509, in get_experiment
       return import_local_experiment()["class"](db.session)
     File "/Users/jakobnieder/psynet/psynet/experiment.py", line 361, in __init__
       config_initial_recruitment_size = self.get_initial_recruitment_size()
     File "/Users/jakobnieder/psynet/psynet/experiment.py", line 731, in get_initial_recruitment_size
       return get_and_load_config().get("initial_recruitment_size")
     File "/Users/jakobnieder/psynet/psynet/experiment.py", line 108, in get_and_load_config
       config.load()
     File "/Users/jakobnieder/Dallinger/dallinger/config.py", line 306, in load
       self.load_defaults()
     File "/Users/jakobnieder/Dallinger/dallinger/config.py", line 303, in load_defaults
       self.load_experiment_config_defaults()
     File "/Users/jakobnieder/Dallinger/dallinger/config.py", line 347, in load_experiment_config_defaults
       self.extend(exp_klass.config_defaults(), strict=True)
     File "/Users/jakobnieder/psynet/psynet/experiment.py", line 848, in config_defaults
       expected_type = config_types[key]
   KeyError: 'show_bonus'

Try searching for show_bonus and KeyError in Slack. While the first
query show_bonus is more specific, nobody encountered the specific error
with this config key. The next step would be to look for the more
generic error message KeyError in Slack. As you can see in the
screenshot, Pol already had the same issue but with a different key.

.. image:: /_static/images/lab_deployments/image37.png
   :width: 8.5in

The solution was to make sure you are on the correct psynet commit hash.
It’s best to start searching Slack. Searching Google is particularly
helpful if the error does not occur in Psynet or Dallinger but in
dependencies (e.g., numpy, or librosa) or 3rd party software (e.g.,
docker). Google usually points to helpful directions. You can also put
the error or parts of it in double quotes, which will give you exact
matches. Also note that all public issues for PsyNet and Dallinger are
public and thus searchable via Google. Some lab members have also used
ChatGPT for debugging, which you can if Google or Slack don’t give you
the answer.

How to ask for help?
^^^^^^^^^^^^^^^^^^^^

Once you identified the cause of the problem, you can ask your
colleagues.

-  **Make sure you write in a public channel** i.e. #psynet-support if
   it concerns psynet, #online-experiments if it considers online
   experiments (including internal deployment tooling), or #programming if
   it is a general question. *Do not send direct messages to people
   to ask for help.* Your replies and solutions cannot be found by
   other lab members. Also, this allows the whole team to respond
   rather than only a handful of people. Clearly indicate if it is an
   error you are facing or if its more a general question or comment.

-  **Be thoughtful about each other’s time.** A core philosophy of the
   lab workflow is that it’s a waste of time to be stuck on something and
   that a small amount of time of other people can get you going.
   However, it’s a thin balance between using colleagues' time
   and being stuck on a problem for too long. As a rule of thumb, if
   you are stuck on the same problem for more than an hour, you need
   help. But make sure you did all possible steps to look for and
   identify the cause of the problem, as described in the previous
   section above.

-  **Be detailed.** Make sure you have identified the location of your
   problem. Avoid making wild claims, e.g. say the error occurs in
   psynet but psynet does never occur in the stack trace. When you
   state your error message, you need to be very specific:

   -  *Give some context:* Describe what you want to do.

   -  *Location of the error:* Tell us which error occurs and where it
      occurs.

   -  *Commit hash:* Tell us which psynet and dallinger commit hash you
      are using locally and which ones you use in the
      requirements.txt

   -  *Docker or virtual environment:* Tell us if you are using docker
      or a virtual environment.

   -  *Stack trace:* Always paste the full stack trace to your problem

   -  *Minimal working example:* If you can provide a minimal working
      example, e.g. a psynet demo where it occurs or a link to a Git
      repository

-  **Post the final solution.** Once you found the solution to the
   problem post it in the thread in Slack so future users (or future
   you :wink:) will remind the solution.

