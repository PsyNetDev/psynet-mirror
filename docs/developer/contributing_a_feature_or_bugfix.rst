.. _developer:
.. highlight:: shell

.. |br| raw:: html

   <br />

=============================
Contributing a feature/bugfix
=============================

Step 1: Creating an issue
+++++++++++++++++++++++++

The process begins with identifying a particular *issue* that deserves to be fixed in PsyNet. This issue could be a problem with existing functionality (a *bug*) or a lack of desirable functionality (a missing *feature* ). Most version-control platforms (e.g., GitHub, GitLab) provide pages where project developers and user can file issues. For example, the PsyNet issues page can be found `here <https://gitlab.com/PsyNetDev/PsyNet/-/work_items>`__, and looks something like this:

.. figure:: ../_static/images/developer/workflow/psynet_issues.png
  :width: 700
  :align: center

|br|
Let's suppose that we want to address issue #288, 'Add Node.participant and Network.participant attributes'.
We click on the issue for more detail:

.. figure:: ../_static/images/developer/workflow/psynet_issue_details.png
  :width: 700
  :align: center

|br|

Step 2: Creating a merge request
+++++++++++++++++++++++++++++++++

GitLab provides a useful button on the issue page for us to click: 'Create merge request'.
Go ahead and click it.
It presents us with some options, specifically to choose the 'source' for our merge request,
and to choose a name for the corresponding branch.
We can leave the 'source' as the default, 'master', and we can leave the name as the default,
which will be generated from the issue name.
Click 'Create merge request' to continue.

You will now see a page with some further options for your merge request.
Take a note of the template 'Changelog' in the Description section;
you will need to fill this out after you have implemented the feature.

Scroll down and ensure that you are listed as the Assignee (the person who will do the implementation)
and the Reviewer is left unassigned. The Reviewer will stay unassigned until you have finished your implementation.
The 'delete source branch' option should be unticked;
if we have good naming conventions for our branches there's no problem in keeping them for posterity.
The 'squash commits' option should also be ticked;
this means that when the branch is ultimately merged its changes will be squashed into one commit,
ensuring the readability and interpretability of PsyNet's version history.

.. figure:: ../_static/images/developer/workflow/gitlab_edit_merge_request-3.png
  :width: 600
  :align: center

We then need to get this branch into our local repository.
GitLab provides a handy button for this labeled 'Check out branch',
which will display the required commands automatically for us to copy and paste.

.. figure:: ../_static/images/developer/workflow/gitlab_edit_merge_request-4.png
  :width: 400
  :align: center

|br|

.. note::
    Other version-control systems (e.g., GitHub) do not necessarily provide these helper buttons.
    In such cases we can instead create the branch and the merge request using the following code,
    and create the pull/merge request via the version-control system's web interface:

    .. code-block:: console

      git checkout master
      git pull
      git checkout -b issue-288-network-participant
      git push -u origin issue-288-network-participant

Once we've checked out the code locally, we should make sure that our Python is using this local version of PsyNet.
Make sure you're in the right virtual environment, then run:

.. code-block:: console

  pip3 install -e .  # installs PsyNet in local editable mode

Try running ``which psynet`` in your terminal; it should return a path to your local PsyNet source code.

Step 3: Implementing the feature
++++++++++++++++++++++++++++++++

Now that we've checked out the branch, our task is to implement our proposed feature or bugfix. To make the example more concrete, I'll share some details about this specific implementation, but the key thing to focus on here is the general approach to Git usage and version control.

Our task is to add a 'participant' attribute to the 'Network' class used in PsyNet. The base 'Network' class used in PsyNet is called 'TrialNetwork', so we'll be working on that. This class is defined in main.py:

.. figure:: ../_static/images/developer/workflow/psynet_class_trial_network.png
  :width: 700
  :align: center

|br|
Currently ``TrialNetwork`` doesn't have a participant attribute. This information is instead stored *implicitly* in the nodes that the network contains. We could look at any of the network's nodes, but the most natural to look at is the 'source' node, which is created when the network is created. We therefore define the following property within the ``TrialNetwork``:

.. code-block:: python

  @property
  def participant(self):
      source = self.source
      assert source is not None
      return source.participant

It turns out that ``TrialNetwork.source`` isn't defined yet either. Let's define it:

.. code-block:: python

  @property
  def source(self):
      sources = TrialSource.query.filter_by(
          network_id=self.id, failed=False)
      if len(sources) == 0:
          return None
      if len(sources) > 1:
          raise RuntimeError(
              f"Network {self.id} has more than one source!")
      return sources[0]

We commit our changes as usual using git commit.

Something to note here is that PsyNet contains pre-commit hooks that run various automated processes including `ruff <https://docs.astral.sh/ruff/>`__. These pre-commit hooks run every time we make a commit in Git. They are designed to check the code for certain errors, sort imports, and enforce standardized formatting. If a given commit fails then this is usually due to one of the pre-commit routines. Often simply restaging the files and retrying the commit will work, because the restaging will now include the standardized formatting enforced by *ruff format*. In other cases (e.g. lint errors) simple retrying will not work. In this case the next step is to run the ``git commit`` command in the terminal (instead of a Git GUI) and study the error message that comes out.

Step 4: Adding documentation
++++++++++++++++++++++++++++

So that future people can benefit from these new properties, we'd better add some documentation. It is conventional to document Python code using docstrings, which can be found at the top of class/function/method definitions. These follow standardized formatting conventions; Python follows in particular the `NumPy Docstring Style <https://numpydoc.readthedocs.io/en/stable/format.html>`_ convention. The main thing though is simply to be consistent, and follow the formatting style of the neighboring parts of PsyNet.

In the present case, we need to edit the docstring for the ``TrialNetwork`` definition. This docstring already contains documentation for lots of other attributes, so we'll just add our new attribute definitions to the list.

.. code-block:: console

  source : Optional[TrialSource]
      Returns the network's :class:`~psynet.trial.main.TrialSource`,
      or ``None`` if none can be found.

  participant : Optional[Participant]
      Returns the network's :class:`~psynet.participant.Participant`,
      or ``None`` if none can be found.
      Implementation note:
      The network's participant corresponds to the participant
      listed in the network's :class:`~psynet.trial.main.TrialSource`.
      If the network has no such :class:`~psynet.trial.main.TrialSource`
      then an error is thrown.

More extensive documentation files can be found in the ``docs``  directory of PsyNet. This contains lots of ``rst`` files that are compiled to HTML files when PsyNet generates its documentation website. Here is a `brief introduction <https://learnxinyminutes.com/docs/rst/>`_ to RST formatting. For Sphinx-specific syntax, see the `reStructuredText primer <https://www.sphinx-doc.org/en/master/usage/restructuredtext/basics.html>`_.

Step 5: Adding tests
++++++++++++++++++++

Automated testing is an important part of software development.
Most mature software packages include a collection of automated tests that are
run regularly as part of the development process.

Testing is not just about making sure that the code works *now*,
but that it continues to work in the *future*.
If you write a particular test now and commit it to the PsyNet codebase,
then every future developer who wants to make a contribution to PsyNet will be forced to make sure that their changes do not stop your test from working.
If you can design your tests to capture all the important aspects of your new feature, then you can (mostly) guarantee that the feature is going to keep working indefinitely.
This is very helpful if you expect to rely on the feature yourself in the future.
There's a cost-benefit analysis to be done, though. Complete coverage of a particular feature could require many many tests, and these could be slower to write than the feature itself. Moreover, some features are relatively hard to write tests for, for example those that concern the visual appearance of the user interface, or those that concern the behavior of database objects that cannot exist in isolation (e.g., a ``Trial`` object cannot exist without corresponding ``Participant`` and ``Node`` objects, and a Node object cannot exist without a corresponding ``Network`` object).

A couple of observations are useful to bear in mind for this cost-benefit analysis.

#. **A simple test is better than no test.** We don't necessarily have to test every aspect of a new feature. It's surprising how effective very basic 'sanity checks' can be for catching problems.
#. **Complex tests can be made simpler by reusing testing infrastructure.** Tests involving the database or the user interface are hard to implement from scratch because they involve time-consuming setup procedures (e.g., spinning up a webserver and simulating a participant interacting with the web page, or populating a database with objects representing fictional participants, trials, and networks). However, we don't need to write this code from scratch each time we implement a new test. Instead, we can try wherever possible to insert our code in PsyNet test files that already provide this functionality.

Bearing all this in mind, we will write a simple test for this new ``Network.participant`` attribute. We won't worry about testing ``Network.source`` because we know that Network.source will have to work in order for ``Network.participant`` to work anyway.

We can see the pre-existing tests within PsyNet's ``tests/`` folder. There are quite a few of them already:

.. figure:: ../_static/images/developer/workflow/psynet_tests.png
  :width: 540
  :align: center

|br|
All test files must begin with the prefix ``test_``. The ``tests`` folder additionally contains a file called ``conftest.py``, which is used to provide additional helper materials; we won't worry about that here.

This folder contains a special collection of tests with the prefix ``test_demo_``. These tests work by running particular demos within PsyNet (stored in the ``demos`` folder) and checking that they behave as expected. These tests are particularly good for testing things to do with the user interface and the database. However, they have the disadvantage of being relatively slow to run, because each test file requires PsyNet to spin up an experiment debugging session. To keep the process efficient, we therefore try and pack lots of different tests into a particular demo test file.

We'll add our test to the test for the MCMCP demo (``test_demo_mcmcp.py``). This is a good one to choose because each network in the MCMCP demo is the property of a particular participant, which means that the ``network.participant`` call should return a meaningful value.

For these browser-based tests to work we must make sure we have an appropriate version of the ChromeDriver software installed. This is a piece of software for programmatically running Chrome sessions. It can be downloaded from the `ChromeDriver website <https://chromedriver.chromium.org/downloads>`_; once you've downloaded the appropriate version for your Chrome browser and your operating system/processor (you can check your Chrome browser's version by clicking 'Chrome' then 'About Chrome'), you should unzip the file and copy the resulting executable file to the ``/usr/local/bin/`` folder. You should only have to do this once in a while (occasionally Chrome updates will require you to get a new version of ChromeDriver).

Once you've downloaded ChromeDriver, verify that it works by running the following terminal command:

.. code-block:: console

  chromedriver --version

If running your test on Mac, you may be faced with a security message like the one below:

.. figure:: ../_static/images/developer/workflow/macos_security_message.png
  :width: 340
  :align: center

|br|
To bypass this message, you will need to go to System Preferences, Security & Privacy, and find the dialog below which allows you to enable chromedriver to run:

.. figure:: ../_static/images/developer/workflow/macos_security_dialog-1.png
  :width: 500
  :align: center

.. figure:: ../_static/images/developer/workflow/macos_security_dialog-2.png
  :width: 340
  :align: center

|br|
To run this test, we execute the following code from the PsyNet root directory:

.. code-block:: console

  pytest tests/test_demo_mcmcp.py --chrome

The ``--chrome`` flag is required whenever we run a demo test (i.e., any test file beginning with ``test_demo_``). This instructs pytest to run the test using the Chrome browser; if we don't have this flag, pytest will skip the test entirely. Otherwise we can just write '``pytest``' followed by the path to the test file we want to run.

These browser-based tests are a little fragile when run on local machines, often getting stuck at the point of opening the browser. This most often happens when running tests repeatedly. This seems to be caused by zombie ChromeDriver processes that aren't shut down properly when tests finish. The problem seems to be solved by running the following command in between tests:

.. code-block:: console

  killall chromedriver

If we run the pytest command described above, we should see PsyNet spin up a browser window and progress through the experiment. Once the experiment is completed, the browser window should be automatically closed, and we should see a collection of green success messages in the computer terminal.

So, having replicated the MCMCP demo test locally, the next step is to incorporate a test of our new ``network.participant`` feature. To work out exactly what to do here, I inserted a breakpoint into the main part of ``test_demo_mcmcp.py``:

.. code-block:: python

  @pytest.mark.usefixtures("demo_mcmcp")
  class TestExp:
      def test_exp(self, bot_recruits, db_session):
          for participant, bot in enumerate(bot_recruits):
              driver = bot.driver
              time.sleep(1)

              driver.execute_script(
                  "$('html').animate({ scrollTop: $(document).height() }, 0);"
              )
              next_page(driver, "standard-consent")

              breakpoint()

Rerunning the pytest command, we see PsyNet spin up a browser window and navigate through the consent form. After this point it freezes because it has hit the breakpoint. At this point we can enter custom code into the Python terminal and see what happens when we execute it. On this basis I replaced the breakpoint with the following lines of code:

.. code-block:: python

  # Testing that network.participant works correctly
  # (we are in a within-participant experiment, so each chain
  # should be associated with a single participant).
  from psynet.trial.mcmcp import MCMCPNetwork
  from psynet.participant import Participant

  # SQLAlchemy uses 1-indexing, Python uses 0-indexing...
  participant_id = participant + 1

  network = MCMCPNetwork.query.all()[0]
  assert isinstance(network.participant, Participant)
  assert network.participant.id == participant_id

The ``assert`` keyword is crucial in test construction. When we write ``assert [XYZ]``, Python evaluates ``[XYZ]`` and checks that it returns ``True``. If yes, then pytest logs a success; if no, then pytest logs a failure. Any unexpected errors will also be logged as a failure.

Here I implemented two assertions. We're asserting that ``network.participant`` returns an object of class ``Participant``, and we're asserting that this participant has the same ID as the participant who's currently taking the experiment. This is very basic stuff; nonetheless, I claim that it's enough to provide some basic reassurance that the new feature works.

Once we've learned all we want to from this breakpoint, we can quit the test early by typing 'q' into the breakpoint terminal. We can now restart the test by running the same pytest command from before. If everything goes well, we should again see PsyNet running through the experiment and delivering lots of green success messages. If not, we can try killing the ChromeDriver process as described above…

Step 6: Push the draft code
+++++++++++++++++++++++++++

We've just finalized our draft implementation, including code, documentation, and tests. We should now ensure that your proposed changes are all pushed to the remote repository. First we run ``git status`` to verify that we have no uncommitted file changes and that we're on the right branch (in our example, the branch was called ``288-network-participant``). If we had uncommitted changes we could fix them with ``git commit``; if we weren't on the right branch we could fix this using ``git checkout``. Lastly, we make sure that all our local changes are pushed to the remote repository by running one final ``git push``.

Step 7: Verify that the automated tests run successfully
++++++++++++++++++++++++++++++++++++++++++++++++++++++++

Pushing your draft code should trigger the remote server to run the full suite of automated tests. You can tell that the tests have started by seeing a notice like this in the merge request's 'Overview' tab.

.. figure:: ../_static/images/developer/workflow/gitlab_pipeline.png
  :width: 600
  :align: center

|br|
We need to wait for these tests to proceed successfully before continuing to the next step. They can take a while to complete (~ 20 minutes), so it's best to find something else to do in the meantime. You should receive an email from GitLab when the tests complete notifying you of their success status.

If the tests ran successfully, congratulations! You can proceed to the next step. If not, you need to work out how to fix the problem. You can see an error log by clicking on the pipeline ID, then on 'tests'.

.. figure:: ../_static/images/developer/workflow/gitlab_pipeline_tests.gif
  :width: 700
  :align: center

|br|
You should have a skim through these error logs to work out what went wrong. Sometimes the solution will be obvious and you can fix it immediately by making and pushing a new commit. Other times the solution will be harder to find. In this cases the next step is typically to rerun the offending test locally (using the pytest command described earlier) to see if you can reproduce it, and thereby debug it more efficiently.

Step 8: Populating the CHANGELOG entry
++++++++++++++++++++++++++++++++++++++

The next step is to add a CHANGELOG entry to the merge-request description. The CHANGELOG entry summarizes the changes that have been made in the merge request;
t will later be compiled into the CHANGELOG.md file situated in PsyNet's root directory.
This process is very important for helping PsyNet users to keep abreast of new features.

We have some conventions about how to format the CHANGELOG entry. It should be organized into sections, with the sections drawn from the following options:

* Added (corresponding to new features);
* Fixed (corresponding to bugfixes);
* Changed (corresponding to changed functionality);
* Updated (corresponding to updated versions, e.g. for dependencies).

Here are some examples of CHANGELOG entries from PsyNet's history:

.. code-block:: markdown

  #### Added
  - Added 'Edit on GitLab' button to documentation pages.
  - Added `FreeTappingRecordTest` to prescreens.

  #### Fixed
  - Renamed `clickedObject` to `clicked_object` in the graph experiment demo's
    `format_answer` method.

  #### Updated
  - Updated Dallinger to v9.3.0.
  - Updated google-chrome and chromedriver to version 109.x in .gitlab-ci.yml.

Step 9: Dealing with merge conflicts
++++++++++++++++++++++++++++++++++++

If you spend a long time working on your feature branch, other changes might happen to the PsyNet codebase in the meantime.
If you are lucky, these changes happen to parts of the code that don't interact with your own changes, and you don't have to think about it. If you're unlucky, the changes do interact, potentially causing a so-called merge conflict. You will have to resolve this merge conflict before releasing your feature. Resolving merge conflicts is covered elsewhere in this documentation.
Merge conflicts get increasingly painful the more and more changes accumulate to the branch that you branched off.
The best way to protect yourself from painful merge conflict resolution is to regularly update your feature branch with changes
that have subsequently happened to the master branch. The way I normally do this is as follows:

.. code-block:: console

  git checkout dev
  git pull
  git checkout my-feature-branch
  git merge dev

The more regularly you do this, the less divergence can occur, and the easier it is to resolve the conflicts.

Step 10: Code review
++++++++++++++++++++

The contribution is now ready for *code review* [#]_. Code review is a process whereby other members of the PsyNet developer team examine your proposed changes and give you feedback. Sometimes they might detect a bug or unforeseen limitation of your contribution; other times they might instead make suggestions about how to make your code more elegant, readable, or maintainable.

It's tempting to assume that code review is only useful when the reviewer has significantly more experience than the code author. This is not the case. An important goal in software design is to write code that looks maximally simple and transparent, and hence understandable by novices. If a novice finds a code segment impossible to understand, this is useful feedback in itself, because it suggests that the code might benefit from refactoring into something more understandable.

Nonetheless, it is true that code review plays a critical role in protecting the integrity and quality of the codebase. In this sense it is important to ensure that every PsyNet contribution does at some point get reviewed by one of the core PsyNet developers, which currently number just two: Frank Höger and Peter Harrison. An important goal of the coming months is to try and increase this number of core PsyNet developers, either through the appointment of additional employees, or through the training of advanced PsyNet users such as yourself.

How do we ensure that every contribution passes through the core PsyNet developers without creating adverse load on Frank and Peter? My proposal is that contributions from non-core PsyNet developers should undergo an initial round of code review from another non-core PsyNet developer. The reviewer will provide some suggested revisions, with the idea that these should be enacted directly by the original submitter. Once the reviewer is satisfied with the enacted revisions, the contribution is then allocated to one of the core PsyNet developers for a final review. This review may introduce further required revisions that need to be addressed by the original submitter. Once the final reviewer is satisfied, they give final approval to the contribution, and merge it into PsyNet's master branch, so that the contribution will be made available in PsyNet's next official release.

Let's now talk about the specifics of the process. If we navigate to the corresponding merge request in GitLab/GitHub, we should see evidence of our recent activity. In particular, if we navigate to the 'Changes' tab, we should see a diff representation of the changes that we have introduced. At this point take a few minutes to read through this diff representation line-by-line to verify the correctness of the changes. It's surprising how many mistakes this process can catch, even if it feels unnecessary.

The next task is to pass your merge request to the first reviewer listed in your merge request's Description. If you yourself are a non-core PsyNet developer, then your first reviewer will generally also be a non-core PsyNet developer.

.. figure:: ../_static/images/developer/workflow/gitlab_reviewer.gif
  :width: 300
  :align: center

|br|
This will send an automatic email to the reviewer telling them that the code is ready for review. If you like you can additionally send a personal message via Slack or via the GitLab merge request comments section.

To review a given merge request, the reviewer will go to the 'Changes' panel on the merge request to view a diff representation of the merge request. It will look something like this:

.. figure:: ../_static/images/developer/workflow/gitlab_merge_request_diff.png
  :width: 700
  :align: center

|br|
The reviewer's task is to go through this diff line-by-line, file-by-file, thinking about whether each change is correct. This process has two main purposes. The first (and obvious purpose) is to catch unanticipated limitations or errors with the contributed code. The second purpose, often neglected, is to help the reviewer to become familiar with this newly changed part of the codebase. This will help them in the future if they want to interact with this part of the codebase again.

To query a given change, the reviewer moves the mouse over to the respective line and clicks the 'Comment' icon. They then write a text message summarizing their query, which will typically take the form of a question, a suggested change, or both.

.. figure:: ../_static/images/developer/workflow/gitlab_merge_request_comment.gif
  :width: 700
  :align: center

|br|
Once the comment is completed, the reviewer clicks the 'Start review' button (or 'Add to review' for the second comment onwards. If we were to click 'Add comment now', this would immediately send an email to the contributor. This is fine if we know that we have just one comment to make, but typically we'll have multiple, and it's awkward to send separate emails for each one. We therefore recommend clicking 'Start a review' for the first comment, clicking 'Add to review' for subsequent comments, and then 'Submit review' once all the comments are complete.

Once we've finished examining a given file, we click the 'Viewed' checkbox to log the fact that we've finished.

.. note::
    Sometimes the reviewer might want to try the code on their own machine, rather than just reading it online. To do this they will need to run some Git commands on their local repository:

    .. code-block:: console

      git fetch  # fetches the current state of all branches, including the feature branch
      git checkout my-feature-branch  # replace my-feature-branch with the branch name

.. figure:: ../_static/images/developer/workflow/gitlab_merge_request_collapse.gif
  :width: 700
  :align: center

|br|
This collapses the diff for that file, helping us to focus on files that we haven't examined yet. If the contributor subsequently edits that file, that diff will be expanded again, making sure that we don't miss these subsequent changes. Otherwise the diff will stay collapsed.

It's important to have a balanced reviewing strategy. One tends to be biased towards one's own coding styles, and it's tempting to feel an obligation to make the code resemble exactly how you'd do it. [#]_ This can be time-consuming for the reviewer, frustrating for the contributor, and not necessarily so valuable in the long run. On the other hand, a lax approach to reviewing is dangerous too because it allows the quality of the codebase to be degraded over the long-term. The main principle to remember though is to be nice: both contributors and reviewers are often working out of goodness of will, and we should try our best to preserve that.

Once the review is completed, the reviewer submits it by pressing the 'Submit review' button. This triggers an automatic email to be sent to the contributor; it wouldn't hurt to send a personal follow-up Slack message or GitHub comment too.

The contributor's task is then to go through the reviewer's comments and address them one-by-one. This will typically involve making various further changes to the current branch, which should be committed and pushed as usual.

Once the contributor has addressed a given comment, they should write a textual response to the reviewer
explaining their actions. This could be as simple as writing 'Fixed'; alternatively it could be the beginning of a longer debate about the right way to go forward.

If the reviewer is satisfied with the response, they should click the 'Resolve thread button'. This hides the commit from the diff view.

.. note::
    Contributors should *not* resolve reviewer comments! This runs the risk of the reviewer missing the response and hence not being able to verify it.

If the reviewer is not satisfied with the response, they are welcome to discuss it further with the contributor to achieve a consensus. If this proves impossible, then they are encouraged to raise the issue to a core PsyNet developer (tagging the developer in that conversation should be sufficient).
Eventually the conversation between the contributor and the first reviewer will come to an end, usually with all conversations resolved. If there is a second reviewer listed on the reviewer list, this is the point when the merge request should be passed onto that second reviewer. This is achieved similarly to how the first reviewer was selected, but this time we begin by deselecting the first reviewer and only then selecting the second reviewer. This second reviewer will then be sent an email notification and the review process will repeat with this new reviewer.

Step 11: Merging
++++++++++++++++

The final reviewer has the job of signing off on the merge request. This is done by clicking the 'Approve' button in the GitLab interface (which removes the 'Draft:' prefix from the merge request's title) and then clicking 'Merge' (or 'Merge when pipeline success' in the case when the automated tests are still running).

Congratulations! Your merge request has been successfully processed. It should become available in PsyNet once the next public release is created by the PsyNet core developers.

.. rubric:: Footnotes

.. [#] Note: It is also possible to request code review at an earlier stage of the project if you feel you would benefit from it. Simply get in touch with the reviewer and ask if they'd be willing to look at the code early.
.. [#] This phenomenon is related to the well-documented phenomenon that people prefer the smell of their own farts. For follow-up reading, see `Code Smells (via Wikipedia) <https://en.wikipedia.org/wiki/Code_smell>`_.

Further considerations
++++++++++++++++++++++

Depending on a custom branch of Dallinger
-----------------------------------------

Sometimes you may need to use a custom branch of Dallinger in a feature you are contributing to PsyNet.
In order to do this, you will need to update the Dallinger entry in ``pyproject.toml`` to point to your branch.
You should write something like this: ``"dallinger @ git+https://github.com/Dallinger/Dallinger.git@2350v82u38ud3unwoiunec8un3c"``
where the string after ``.git@`` is the commit hash for the commit you want to use.

You can find the commit hash by clicking the "Copy" button next to the commit hash on the GitLab page for the branch you want to use.
