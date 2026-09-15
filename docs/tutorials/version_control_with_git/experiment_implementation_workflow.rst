.. |br| raw:: html

   <br />

Experiment implementation workflow
----------------------------------

PsyNet experiments are represented as folders of files, including most importantly:

    * ``config.txt`` (contains configuration parameters);
    * ``experiment.py`` (defines the logic of the experiment);
    * ``requirements.txt`` (lists the Python packages imported by the experiment);
    * ``constraints.txt`` (lists all Python packages to be installed on the server).

The resulting folder might look something like this:

.. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/folder.png
  :width: 500
  :align: center

|br|
Let’s suppose that we’ve just now created this experiment directory for the first time, perhaps by copying it from a demo in the PsyNet source code. Our first task is to **initialize the Git repository**. We do this by navigating to the experiment directory in our Terminal, and entering the ``git init`` command:

.. code-block:: console

    cd ~/path-to-my-experiment
    git init

This creates a hidden folder called ``.git`` in our experiment directory. On a Mac this will be hidden by default, but we can show it by pressing ‘Command + Shift + .’ (note the period at the end).

.. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/folder_with_git.png
  :width: 500
  :align: center

|br|
We can verify that the repository has been initialized successfully with the ``git status`` command.

.. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/git_status.gif
  :width: 800
  :align: center

|br|
Our repository does not have any commits yet. Let’s make our first commit, including all of the files we’ve added so far.

Making a commit in Git comprises two steps. First, we identify which changes we wish to commit: this process is called *staging*. Once we’re happy with our staged changes, we finalize the commit, making sure to provide a descriptive title.

We stage changes using the ``git add`` command. We use this command to select individual files that we want to commit. In particular, we are interested in files that either (a) are new to the repository or (b) have changed since the last commit. Staging a file means that the upcoming commit will record the file in its current state, including any changes since the last commit. Git will not let you stage a file that has not changed since the last commit because this would be a redundant action.

One way to use ``git add`` is to select individual files one-by-one. We write ``git add`` followed by the path to the file that we wish to add. If we run ``git status`` again we can verify that the file has indeed been staged.

.. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/git_add_file.gif
  :width: 800
  :align: center

Alternatively, if we know we want to stage all the remaining files in the directory (listed currently in red), we can write

.. code-block:: console

    git add .

The period is a shorthand for ‘all files in the directory’. This shorthand is useful, but it can encourage people to be reckless in their commits, including files that ought not to be included (e.g. API credentials). It’s good practice to check the file list carefully before running this command.

A related command is ``git add -i`` (no period at the end). This gives a simple interactive interface that allows you to select which files you want to add to the commit.

.. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/git_add_dir.gif
  :width: 800
  :align: center

Suppose we’re happy that we’ve now staged all the files we want to stage. We then finalize the commit by writing a command of the following form:

.. code-block:: console

    git commit -m "Write your commit title here"

.. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/git_commit.gif
  :width: 800
  :align: center

We can verify that this commit has made it into our repository’s history by running ``git log``.

.. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/git_log.gif
  :width: 640
  :align: center

|br|
Currently our repository is only stored on our local computer. This is fine for local work, but usually we’d want to create a remote copy of the repository too, serving both as a useful backup of our code and a portal for other people to contribute modifications.

To create a remote repository, we go to our favorite version-control platform (e.g., GitHub, GitLab, Bitbucket), login to our account, and follow the instructions to create a new ‘repository’ (GitHub     terminology) or ‘project’ (GitLab terminology). There are a few things to think about here:

    * You will need to decide on a name for the repository (GitLab calls this the *project slug*). It is useful to make this name self-descriptive, not too long, and without capital letters, for example *stroop-implementation*.

    .. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/repository_name.png
      :width: 320
      :align: center

    * If you are working as part of a team (e.g. the MPIEA Computational Auditory Perception group), you may want to make sure that the repository is created as part of your shared group.

    For example, on the GitHub interface:

    .. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/github_interface.png
      :width: 600
      :align: center

    |br|
    On the GitLab interface:

    .. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/gitlab_interface.png
      :width: 540
      :align: center

    |br|
        * These two components (group and slug name) are combined together to produce the repository’s URL, for example `https://gitlab.com/computational-audition-lab/stroop-implementation`.

        * Think carefully about whether to make your repository *public* or *private*. Public repositories can be viewed by the general public, whereas private repositories can only be viewed by yourself or your team. If you make the repository public, you must be very careful about accidentally leaking sensitive information (e.g., API keys, or participant data; note that it’s best practice not to commit these files to Git in the first place!). Remember that the repository stores its own full version history, so once you commit something sensitive it’ll be accessible forever, even if you subsequently delete it from the repository and commit that deletion.

Once you’ve created your remote repository your version-control framework will typically display you some instructions about how to link it to your local repository. On GitHub the instructions look like this:

.. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/github_instructions.png
  :width: 800
  :align: center

|br|
We’ve created our local repository already, so we can follow the instructions titled ‘push an existing repository from the command line:

.. code-block:: console

    git remote add origin git@github.com:pmcharrison/stroop-implementation.git
    git branch -M main
    git push -u origin main

There are three commands here:

    * ``git remote add`` tells the local repository to add a remote repository called ‘origin’ at the specified URL.
    * ``git branch -M main`` tells Git to rename the current branch to main (since by default it might be called master, and GitHub is trying to push back against this).
    * ``git push -u origin main`` tells Git to push the local branch (called ``main``) to the remote repository (called ``origin``).

You don’t need to remember these commands, because you can just copy them from your version-control framework, but it’s useful to cast your eye over them to make sure you’re aware of what they’re doing.

If we now refresh the page on our version-control framework, we should see our files uploaded.

.. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/github_main_branch.png
  :width: 800
  :align: center

|br|
Now, suppose we continue working on our experiment by adding a couple of lines of content to ``requirements.txt``. We make our changes locally via our chosen text editor, then once we’re happy with our changes we perform three steps:

    * Stage the file;
    * Commit the file;
    * Push the changes to the remote repository.

This is achieved using the following commands:

.. code-block:: console

    git add requirements.txt
    git commit -m "Adding content to requirements.txt"
    git push

Once the push command has completed, we should be able to see our new changes reflected in the version-control framework. Version-control frameworks like GitHub provide a handy way to explore the status and history of a repository. For example, we can explore the content of a given file:

.. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/github_file.png
  :width: 720
  :align: center

We can also explore the commit history:

.. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/github_commit_history.png
  :width: 800
  :align: center

and view individual commits:

.. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/github_diff.png
  :width: 800
  :align: center

|br|
These kinds of displays can provide a useful substitute for Git command-line actions such as ``git log``.

We can continue to develop our experiment by repeating this cycle of making changes, staging, committing, and pushing. We will build up a coherent and interpretable version-control history for our repository that describes the series of steps that we took to write our code.

Let’s consider a few situations that might come up during this process.

Deleting files
##############

Suppose we committed a file to Git, but now we want to delete it. How do we achieve this? One way is to use the ``git rm`` command:

.. code-block:: console

    git rm accident.txt

This will delete the offending file and stage the deletion in Git, so that next time we commit the deletion will be logged.

Alternatively, we can delete the file outside of Git (e.g. in Finder), and then run

.. code-block:: console

    git add .

which will have the same effect, namely staging the deletion of the file.

Ignoring files
##############

Git is designed for tracking *text* files, typically source code files. The evolution of a source-code file can typically be expressed efficiently in terms of line-by-line diffs, and does not take much space to capture on disk.

It is also possible to store other kinds of files in Git, for example images, videos, or executable files. It is usually fine to store a small number of such files in a repository. However, if the number or size of such files gets big, it becomes a problem, with Git repositories becoming slow to download and Git actions becoming slow to run.

In such cases it is often useful to instruct Git *not* to track certain files. Perhaps we tell the software to download these files by a separate mechanism instead, or to generate them from scratch when running the code for the first time on a new machine.

There are other situations too where it is useful to tell Git to ignore certain files. Some software generates certain cache files which are generated automatically from the code and do not need to be tracked. For example, Python often generates cache files with the extension ``.pyc.`` Some software also generates log files, which are useful for debugging, but aren’t useful to keep long-term. For example, PsyNet generates log files called ``server.log``.

The way we tell Git to ignore certain files is using a ‘.gitignore’ file. We create a file with the name ‘.gitignore’ (note the leading period) in a folder containing files we want Git to ignore. This would often be the top-level directory of the repository, but it’s equally possible to place the files in subdirectories. On each line of the ‘.gitignore’ file we provide a path specification that tells Git what files to ignore. It’s possible to use wildcards to ignore all files that match a certain specification. For example, the following ‘.gitignore’ file instructs Git to ignore the file called ``secret-api-key.txt``, as well as all files with the extension ‘.wav’.

.. code-block:: console

    secret-api-key.txt
    \*.wav

If we commit a file to Git, and only later add the file to ‘.gitignore’, then Git will by default continue to track the file. To stop tracking the file, you can write a command like the following:

.. code-block:: console

    git rm --cached secret-api-key.txt

As discussed above, though, this won’t necessarily save you from hackers mining repositories for API keys. It also won’t undo the damage wrought by accidentally committing a massive file to Git; even if you subsequently stop tracking the file, it will still be stored somewhere in the Git repository’s version history, and this will make the Git repository very slow to download in the future.

One solution for pruning away big files is to use a service like `BFG Repo-Cleaner <https://rtyley.github.io/bfg-repo-cleaner/>`_. This can be instructed to strip away any files bigger than a certain size.

If you know what you’re doing, there are likewise methods for removing individual files containing sensitive data from the commit history (see for example `GitHub’s documentation on removing sensitive files <https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository>`_). The stakes here are high if you don’t know what you’re doing, though; you might accidentally leave some sensitive data anyway.

In many situations, the simplest situation might simply be to start a new repository from scratch. This is not really an option on big collaborative repositories, but it can be fine if you’re the only person working on the current repository.

.. code-block:: console

    rm -rf .git
    git init
    git add .
    git commit -m "Initial commit"

The ‘.gitignore’ file has a dual function in PsyNet experiment implementations. In addition to telling Git which files to track, it also tells PsyNet which files should be uploaded to the remote server when deploying an experiment. This functionality is particularly important in the context of large media files (coming to a total size of > 100 MB). Such files should generally not be uploaded as part of the experiment directory, but should instead be accessed through separate web-hosting services such as AWS S3. In fact, if you try to launch an experiment containing too many files in the experiment directory, PsyNet will throw an error that can only be disabled by removing the files or alternatively adding them to ‘.gitignore’.

Tagging commits
###############

Sometimes it is useful to *tag* particular commits that represent special moments in a repository’s history. For example, each time we deploy our experiment online, it’s good practice to tag the current commit, so that it’s easy to look back in the future and see exactly what form the code took at that particular point in time. The tag name you choose can then be used in Git commands as an alternative to the commit checksum.

We achieve this using the ``git tag`` command. This command creates a tag for the currently active commit in your Git repository, which will normally just be the last commit you made.

.. code-block:: console

    git tag -a deploy-pilot -m "Deploying the pilot experiment"

Here the ``-a`` flag means that the tag is a so-called *annotated* tag. Annotated tags are able to carry useful metadata like the message above, ‘Deploying the pilot experiment’. Immediately following the ``-a`` flag, we write the name of the tag, in this case ``deploy-pilot``. The ``-m`` option is then used to specify the message to include with the tag.

The default ``git push`` command does *not* push tags, it only pushes commits. To push tags as well, you need the following command:

.. code-block:: console

    git push --tags

Once you’ve pushed your tags, you can view them in your version-control framework:

.. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/git_gui_tags.png
  :width: 800
  :align: center

|br|
You can also list all tags via the Git command-line:

.. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/git_tag.gif
  :width: 600
  :align: center

Undoing uncommitted changes
###########################

Sometimes we will make changes to the files in our local repository and then decide we don’t want to keep or commit them. We can undo changes to a specific file using the ``git checkout``  command, passing it the filename of the file we want to revert.

.. code-block:: console

    git checkout my-file.txt

If we want to undo all changes to files in the repository, including any changes already staged for committing, we can use the ``git stash`` command.

.. code-block:: console

    git stash

The useful thing about ``git stash`` is that it remembers the changes you’ve undone, just in case you decide later you want to reinstate them. You can reinstate the latest set of stashed changes using the following command:

.. code-block:: console

    git stash apply

It is also possible via this command to access previous stashes if necessary. In particular, you can run the command

.. code-block:: console

    git stash list

which lists your previous stashes. Stashes are saved and applied in a last-in-first-out pattern.

Temporarily visiting a historic commit or tag
#############################################

Git makes it easy to visit arbitrary points in a repository’s history. To visit a given commit, we refer to its *checksum*. The checksum is a pseudorandom alphanumeric string listed alongside each commit in a repository’s commit history. We can find these checksums either through the Git command line (``git log``) or through our version-control framework (e.g., GitHub):

.. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/github_commit_history.png
  :width: 800
  :align: center

|br|
In the example above, GitHub displays the starting seven characters of each commit’s checksum; ‘39ece5b’ for the first commit, and ‘a329717’ for the second commit. These starting characters can be used as shorthand for the full 40-character checksum, assuming that there are no two commits that share the same starting characters.

Let’s suppose we want to explore the historic state of the repository at the point of ‘Initial commit’. There are two ways of doing this. One is to explore the files via the GitHub/GitLab interface, using an option labeled something like ‘Browse files’ or ‘View files’:

.. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/git_gui_browse.gif
  :width: 700
  :align: center

|br|
Alternatively, we can take the files in our local repository back to their historic states. We do this using the ``git checkout`` command.

Before using ``git checkout``, your current local repository should be *clean*, that is, containing no changes from its parent commit. If you do have changes (staged or unstaged) you could consider using the *stash* command described above to stash them temporarily and re-*apply* them afterwards.

We pass ``git checkout`` the commit’s checksum, or alternatively just the first few characters of it (as long as they uniquely identify that commit).

.. code-block:: console

    git checkout 39ece5b

This recreates the historic status of the repository as snapshotted in commit 39ece5b, while still preserving in the version history the commits that were logged since then. We can then explore the files at our leisure, run the code they contain, etcetera.

If we run ``git checkout`` like this, we’ll get a message from Git notifying us that we are in ‘detached HEAD’ state:

.. code-block:: console

    You are in 'detached HEAD' state. You can look around, make experimental
    changes and commit them, and you can discard any commits you make in this
    state without impacting any branches by switching back to a branch.

It sounds a bit scary to have a ‘detached head’ but don’t worry, there’s nothing wrong here. All this means is that, if you make commits now, they *won’t* be added to the end of the current branch as they normally would. In most workflows you won’t need to make commits now anyway.  Just take the opportunity to look around and gather the information you need. Once you’re done, you can ‘reattach’ your head (that’s not the technical term) by checking out the branch again, for example:

.. code-block:: console

    git checkout master

Then, if you run ``git status`` again, you can confirm that everything looks like it normally does.
In the above example we checked out a particular commit using its checksum. We can also check out particular tags using their names. For example, above we created a tag called ``deploy-pilot``. We can check out that tag as follows:

.. code-block:: console

    git checkout deploy-pilot

The process behaves exactly the same otherwise as checking out a tag by its checksum.

Undoing a historic commit
#########################

Sometimes you will look through your commit history and decide that you want to undo a particular commit. Perhaps this commit renamed a particular variable in a way you don’t like, or introduced some kind of bug that you don’t want to do with.

The ``git revert`` command is designed for this kind of situation. Its job is to work out what the repository would look like if that historic commit had never occurred. Make sure first you are on your branch HEAD by running ``git checkout`` plus your branch name. You then refer to the historic command using its checksum, and write something like this:

.. code-block:: console

    git revert 39ece5b

Git will then display you a window like this:

.. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/git_revert_vim.png
  :width: 700
  :align: center

This is the Vim text editor. It is famously frustrating for people who don’t know how to use it but for some reason it is the default text editor that comes up with people’s Git installations. At the time of writing, the simple question of ‘how do I exit Vim?’ has been viewed 2.5 million times on Stack Overflow (``https://stackoverflow.com/questions/11828270/how-do-i-exit-the-vim-editor``):

.. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/stackoverflow_exit_vim.png
  :width: 600
  :align: center

|br|
These people are the lucky ones -- at least they realized that they were using Vim and knew what to Google. Others have just met with a lot of frustration.

.. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/twitter_exit_vim.png
  :width: 400
  :align: center

|br|
When Git throws you into Vim, it gives you the opportunity to modify the pregenerated commit message. By default it’s given the new commit the title ‘Revert “Add content to requirements.txt”’, but you could customize this if you wanted by typing your own commit title.

Once you’re happy, you need to ‘save and quit’ Vim. The way you do this is as follows:

    * Quit ‘edit mode’ by pressing ESC.
    * Press ‘:’ to enter the menu.
    * Type ‘wq’, short for ‘write and quit’.
    * Press ‘enter’.

.. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/git_revert_status.gif
  :width: 800
  :align: center

|br|
You will do well to memorize these few commands. If you really hate Vim, though, you can configure Git to use a more intuitive text editor (‘Nano’) by default using the following command:

.. code-block:: console

    git config --global core.editor "nano"

Now that you’ve completed your ``git revert`` command, Git will have created a new commit that undoes the historic commit you chose, something like the inverse of what you had originally. For example, if your original commit looked like this:

.. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/git_original_commit.png
  :width: 700
  :align: center

|br|
Then your ‘revert’ commit will look like this:

.. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/git_revert_commit.png
  :width: 700
  :align: center

|br|
An important feature of the ‘revert’ command is that it preserves history -- the old commit stays in the commit log. We can see it for example in our GitHub history:

.. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/git_revert_history.png
  :width: 700
  :align: center

|br|
This is a useful feature because it protects us from ever doing anything truly disastrous and losing data. There is an alternative Git command that allows destructive deletion like this, called ``git reset``. We’re not going to talk about that here precisely because of its dangerous nature; it’s best to save that until you really know what you’re doing.

Reverting to a historic commit or tag
#####################################

Sometimes things will have gone so poorly that you want to permanently revert the status of your repository to its snapshot from a previous commit. This means setting all the files to their historic states at a particular point in time.

One way of doing this in Git is with the ``git reset`` command. However, this by default is a *destructive* operation, in that it rewrites history. This is dangerous and we’re not going to recommend it here.

Another way of doing it in Git is with the ``git revert`` command. However, the standard use of ``git revert`` is to undo individual commits, not to revert the whole repository to the snapshot from a particular commit. There are ways that you can customize the ``git revert`` command to work in the way that we want, but they’re hard to remember and the common ones fail in certain applications (e.g., if your history contains a merge commit).

Instead, we recommend a slightly hacky workflow which is actually rather simple and robust. It works as follows. Suppose we are on our master branch, and we want to revert back to the repository’s status at the time of commit 39ece5b. We do the following:

    1. Open your repository in the GUI from your operating system (e.g. Finder).
    2. Make sure that ‘view hidden files’ is disabled. In particular, you should NOT be able to see the ‘.git’ folder in your repository. In Mac you can toggle this with CMD + Shift + ‘.’.
    3. Check out the historic commit of interest:

      .. code-block:: console

          git checkout 39ece5b

    4. Using your GUI from your operating system (e.g. Finder), copy all files/folders in your repository to the clipboard.
    5. Check out the branch you’re wanting to perform the edits for (e.g., ‘master’):

      .. code-block:: console

          git checkout master

    6. Stage the changes and commit them:

      .. code-block:: console

          git add .
          git commit -m "Reverting to commit 39ece5b"

This workflow should work fine except for cases where your version-controlled changes include hidden files. In such cases you’ll need to perform the same procedure, except enabling hidden file viewing in the GUI, and copying all files/folders EXCEPT the ‘.git’ folder.

Undoing commits accidentally committed to the wrong branch
##########################################################

Sometimes we might accidentally make some commits to the wrong branch. As long as we realize this before pushing our commits, the problem is relatively straightforward to fix.

The most efficient process here depends on the precise state of the repository. Here we will describe a process that should work well for any state, but in particular use cases there will be slightly more efficient methods.

Start out on the branch where you committed the erroneous commits (this is often the ``master`` branch). If you have uncommitted changes in your working directory that you want to keep but moved to the new branch, commit them using ``git commit``.

Now ``git log`` to work out exactly how many commits you need to undo (the ``--oneline`` flag instructs Git to print each commit on just one line):

.. code-block:: console

    git log --oneline

Count the number of commits that you want to undo and make a note of this number. Also make a note of the checksum corresponding to the last valid commit (i.e., the commit immediately before your first erroneous commit). Lastly, make a note of the checksums for the commits you want to take to your new branch, **in order from oldest to newest**.

If the branch you want to commit doesn’t exist yet, proceed by following these instructions:

    Check out the last valid commit using the checksum you copied earlier, for example:

    .. code-block:: console

        git checkout 6ad7c7d3

    Create a branch from this commit:

    .. code-block:: console

        git checkout -b my-branch

    Then continue with the next instructions.

Now check out the branch you want to commit to:

.. code-block:: console

    git checkout -b my-branch

Now *cherry-pick* the commits you want to move to this branch in order from oldest to newest.

.. code-block:: console

    git cherry-pick my-commit-hash-1
    git cherry-pick my-commit-hash-2
    git cherry-pick my-commit-hash-3
    ...

``my-branch`` should now contain all the commits we wished to port. Lastly, we need to remove these commits from the original branch, which was ``master`` in our example. First we check out that branch:

.. code-block:: console

    git checkout master

Run ``git status`` to verify that the erroneous commits are actually present in the current branch (they might not be if you checked out the wrong branch!).

If so, run the following command to roll the branch to its last valid commit:

.. code-block:: console

    git reset f265hfr --hard

replacing ``f265hfr`` with the checksum of your last valid commit.

Verify that the commits have been appropriately using ``git status``. If so, you can consider your problem fixed.

.. note::
    The ``cherry-pick`` command works by taking a historic commit and applying it to the current branch. It is useful whenever you want to copy commits to a new branch without going through the process of merging branches.

Using the Git GUI in your IDE
#############################

So far we’ve been interacting with Git primarily using the command-line. This is a useful skill to have because the command-line will be available in almost all Git development contexts, and it provides a huge amount of flexibility.

However, it can be rather slow to explore changes to the codebase using command-line. For example, when examining precisely what changes are going to be introduced by a staged commit, it’s useful to be able to skim quickly through the diffs for all the altered files and verify that they look correct.

We therefore recommend taking advantage of the Git GUI in your IDE. Most IDEs do provide some kind of Git GUI. Here we’re going to provide some screenshots from the Git GUI in PyCharm, the recommended IDE for PsyNet, but most IDEs should offer similar functionalities. [#]_

When using the PyCharm Git GUI we typically open a PyCharm ‘project’ corresponding to the Git repository. For example, when working with the PsyNet codebase, we open the ‘psynet’ folder that we get when downloading our repository from Git.

Suppose we have been working on our code in PyCharm. We can open PyCharm’s Git GUI by clicking the ‘Commit’ tab, typically located on the left-hand side of the screen:

.. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/pycharm_commit_tab.png
  :width: 340
  :align: center

|br|
This panel lists the files that have been changed so far. If we double-click on a particular file, we are then given a familiar diff visualization that efficiently summarizes the changes to this file:

.. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/pycharm_panel.png
  :width: 700
  :align: center

|br|
We can use the interface to stage changes to particular files or regions of files. This is generally done by clicking checkboxes. For example, we can stage the particular implementation of the ‘subtract’ function by clicking the checkbox next to it:

.. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/pycharm_panel_subtract.png
  :width: 340
  :align: center

|br|
We can alternatively stage changes to the entire file by clicking the checkbox next to that file in the commit pane:

.. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/pycharm_changes.png
  :width: 340
  :align: center

|br|
We can type a commit message in the box below, and we can commit and optionally push at the click of a button:

.. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/pycharm_commit_message.png
  :width: 340
  :align: center

|br|
This GUI also becomes particularly handy when resolving merge conflicts, which we will talk about later.

Carrying out experimental work on a development branch
######################################################

When we’re implementing an experiment or data analysis on our local machine, it’s often useful to experiment with some code modifications on a separate branch to our main branch. This allows us to be a bit more radical with our changes without worrying about breaking the stable version of our experiment.

Let’s talk through the workflow for this. First, we make sure we’re on the HEAD of our main branch:

.. code-block:: console

    git checkout master

or if you’ve named your branch ‘main’:

.. code-block:: console

    git checkout main

Then, we create and checkout a new branch with a descriptive name (here ‘new-feature’):

.. code-block:: console

    git checkout -b new-feature

We can now work on this branch as normal, making code edits and committing them using the ``git add`` and ``git commit`` commands.

In some cases, we might have already made some local changes before realizing that we want to make a new branch. That’s fine too -- you can run ``git checkout -b new-feature`` even if you have uncommitted local changes.

When we try and push our new branch the first time, Git will throw us an error message:


.. code-block:: console

    fatal: The current branch new-feature has no upstream branch.
    To push the current branch and set the remote as upstream, use

        git push --set-upstream origin new-feature

All we need to do is copy and paste the suggested command into our terminal and run it again.

.. code-block:: console

    git push --set-upstream origin new-feature

Suppose we need to switch back temporarily to the ``master`` branch. We can do this using the ``git checkout`` command.

.. code-block:: console

    git checkout master

We can then keep working on the master branch as usual. When we’re ready, we can switch back to the ``new-feature`` branch.

.. code-block:: console

    git checkout new-feature

Version-control frameworks like GitHub and GitLab make it easy to compare different branches. We do this by creating a draft *pull request* (GitHub terminology) or *merge request* (GitLab terminology). Pull requests and merge requests are created through the GitHub/GitLab websites. The idea behind a pull/merge request is specifically that you are planning (eventually) to merge the new branch (e.g., ``new-feature``) into the branch it came from (e.g., ``master``). The GitHub/GitLab interface correspondingly provides you with a diff explaining how the ``master`` branch will be updated once you complete this merge. For example, the following screenshot summarizes a very simple work-in-progress merge request in the PsyNet repository:

.. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/psynet_merge_request.png
  :width: 700
  :align: center

|br|
This view is particularly useful for code review processes in collaborative projects, but it’s also rather useful when evaluating changes in one’s own code.

At some point you may decide you wish to merge your feature branch back into the master branch. To achieve this in Git, you do the following:

1. Check out the master branch (or main, if you called it main):

  .. code-block:: console

      git checkout master

2. Merge in your feature branch:

  .. code-block:: console

      git merge new-feature

Git will ask you at this point to provide a merge commit message. Here’s an opportunity for you to use your new-found Vim skills (or simply do what most of us do and type “:wq” in order to save the default merge commit message and quit Vim).

Alternatively, it’s possible to perform the merge using the version-control interface (e.g. GitHub, GitLab). The ‘overview’ page for the corresponding pull/merge request will generally contain some kind of ‘Merge’ button which, if you click it, will perform the merge for you.

Some people delete branches once they’re merged in order to keep the branch list clean. This is perfectly acceptable and generally quite safe. However, if you find yourself deleting branches a lot, you may want to consider instead thinking up a better branch naming convention that makes your branch list easier to navigate.

Resolving merge conflicts
#########################

Sometimes when performing a merge you will run into a so-called *merge conflict*. A merge conflict happens when two different branches try to modify overlapping bits of the same code, and Git can’t work out how to resolve it. This most commonly happens on collaborative projects where multiple developers are working on the same codebase, but it is also possible when working on one’s own project.

You will see that a merge conflict has occurred when Git spits out an error message that looks something like this:

.. code-block:: console

    $ git merge feature
    Auto-merging main.py
    CONFLICT (content): Merge conflict in main.py
    Automatic merge failed; fix conflicts and then commit the result.

If you were to open main.py in a text editor, you’d see something like this:

.. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/git_merge_conflict.png
  :width: 700
  :align: center

|br|
Note how Git has inserted various lines with symbols like ‘<<<<<<<<<<’ and ‘=========’. These demarcate parts of the code where conflicts have occurred that need to be resolved manually.

It is possible to deal with these merge conflicts directly in the text file. However, it is much easier to work instead with the Git GUI in (e.g. PyCharm). We can do this by heading to our Git GUI pain and clicking the text marked ‘Resolve’ next to ‘Merge Conflicts’.

.. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/pycharm_merge_commit_resolve.png
  :width: 340
  :align: center

|br|
This opens a pane listing all the files with merge conflicts.

.. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/pycharm_merge_conflicts_pane.png
  :width: 700
  :align: center

|br|
We select the file we wish to address first, and click the ‘Merge’ button. This gives us an interface like the following:

.. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/pycharm_merge_conflict_interface.png
  :width: 700
  :align: center

|br|
On the left we have the diff for the main branch; on the right we have the diff for our feature branch; in the middle we are meant to construct our ‘solution’ to the merge conflict.

There are different ways that we can construct our solution. One of the most natural ways is as follows: start at the top of all three files, and work down gradually, looking at the changes that have been implemented in both branches. Before doing anything, look at the diff for that section on that particular branch, and try to summarize mentally what that change is doing conceptually. Then look to the other branch; has the other branch tried to edit this part of the code too? If not, you can simply accept the change on the other branch (use the ‘>>’ button in the PyCharm interface). If it has, again try to summarize mentally what the change is doing conceptually. Then look to the centre column, and try to write down a solution that combines both modifications. Once you are done, make sure the diffs for the corresponding code section on both sides are marked complete, either by pressing the corresponding ‘>>’ button (which ports the diff to the centre) or pressing the corresponding ‘X’ button (which ignores the diff).

Once you have resolved all the conflicts, you should see a green error message reporting that all conflicts have been resolved successfully:

.. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/pycharm_merge_conflict_resolved.png
  :width: 340
  :align: center

|br|
You are then free to press the ‘Apply’ button, which will conclude this manual resolution process. To finalise the merge, you can then simply type the following command into the Git terminal:

.. code-block:: console

    git commit

Alternatively you can stage the relevant files via the Git GUI:

.. figure:: ../../_static/images/version_control_with_git/experiment_implementation_workflow/git_gui.png
  :width: 400
  :align: center

|br|
To try this merge conflict resolution yourself, you can clone the following repository: `https://github.com/pmcharrison/Merge-conflict-demo/pull/1 <https://github.com/pmcharrison/Merge-conflict-demo/pull/1>`_ Once you’ve cloned the repository, you should try to merge the feature branch into the main branch, and resolve the resulting conflict.

Resolving merge conflicts is a bit of an art, and like all arts it takes practice. Don’t be disillusioned if you find it difficult the first few times.

When working on collaborative projects it is difficult to avoid merge conflicts entirely. However, there are strategies for making them as painless as possible. One important strategy is to avoid letting branches diverge for too long. Try to keep feature branches limited in scope, so that they can be merged to the main branch before they accumulate too many changes.  If you know that you are working on the same branch as someone else, make sure to ``git pull`` regularly so that any changes they make are quickly integrated into your local branch. When working on a particular feature branch, if you notice that changes are accumulating meanwhile in the main branch, it’s worth regularly merging those changes in the main branch back into your feature branch. This follows a similar pattern to the merge commands described above:

.. code-block:: console

    git checkout master
    git pull # this ensures you have the latest changes to master
    git checkout new-feature
    git merge master

.. note::
    Some software projects use ‘rebasing’ instead of merging in this context. We do not recommend that in general, because rebasing is a destructive operation that can cause difficult-to-resolve problems down the road.

Recap of concepts we covered
############################

    #. Initialize a local repository
    #. Adding files
    #. Deleting files
    #. Making commits
    #. Creating a corresponding remote repository (on GitHub, GitLab, or similar), and linking it to the local repository
    #. Ignoring files
    #. Creating tags
    #. Undoing uncommitted changes
    #. Temporarily visiting a historic commit or tag
    #. Undoing a historic commit
    #. Reverting to a historic commit or tag
    #. Staging commits using the PyCharm GUI
    #. Creating a branch
    #. Merging a branch
    #. Resolving merge conflicts (see `https://github.com/pmcharrison/Merge-conflict-demo/pull/1 <https://github.com/pmcharrison/Merge-conflict-demo/pull/1>`_ for an example; to get the merge conflict, you should clone it and then run ``git merge feature``)

.. rubric:: Footnotes

.. [#] In particular, a recommended free alternative to PyCharm is VSCode.
