.. |br| raw:: html

   <br />

Essential concepts
------------------

Repositories
############

Git is based on the manipulation of *repositories*. A Git repository is a collection of files that makes up a software project. Git relies on the assumption that most of the files in a repository will be text files; this assumption is important for the way that Git tracks file histories and merges changes from different developers on the same file.

When we work with Git, we typically maintain multiple copies of the same repository. One of these copies is typically stored on an Internet server, and is called the *remote repository*. The remote repository will typically be shared by all the programmers working on a particular project, and will often be hosted on a website such as `GitHub <https://github.com/>`_ or `GitLab <https://gitlab.com/>`_. Both GitHub and GitLab have generous free tiers, allowing users with free accounts to host an unlimited number of their own repositories via their services. Many research groups have their own ‘groups’ on GitHub or GitLab which allow different lab members to host their repositories in the same space; for example, the Computational Auditory Perception group at the Max Planck Institute for Empirical Aesthetics has a private group at the following URL, accessible only to lab members: ``https://gitlab.com/computational-audition-lab``.


The other copies of a Git repository are typically stored on the programmer’s own machines. The programmer works by making edits to their local Git repository. When they are happy with their contributions, they ‘push’ (``git push``) these contributions to the remote repository, where they can be accessed by other users.

A Git repository on your local computer looks very similar to an ordinary folder of files. The main difference is that it contains a folder, hidden by default, called ``.git``. This folder contains all the essential information for defining the Git repository. The crucial thing to know, in particular, is that this includes **the repository’s entire version history**. You can peek at a repository’s version history using the ``git log`` command.

.. figure:: ../../_static/images/version_control_with_git/essential_concepts/git_log.gif
  :width: 600
  :align: center

|br|

Commits
#######

The history of a Git repository is split into discrete elements called *commits*. A simple repository history might look something like this:

    #. Commit a7dfh3z2 (22 Sep 2021, 9:15AM): Initialize repository
    #. Commit h4djsn4k (22 Sep 2021, 9:37AM): Prototype data structures
    #. Commit dj57djs2 (22 Sep 2021, 10:10AM): Add unit tests
    #. Commit dj57du30 (22 Sep 2021, 11:20AM): Add documentation

Each commit is labeled by a *checksum*. The checksum is a pseudorandom string of letters and numbers that uniquely identifies the commit. The full checksum is 40 characters long, but is often abbreviated to the first 8 characters, as in the above display.

Each commit also possesses a title. This title is typically by the programmer and provides some useful information about the nature of the commit. It is conventional (and encouraged!) to follow the following rules:

   * Begin with a capital letter;
   * Use the ‘imperative’ verb form, as if you’re telling someone to do something, e.g. ‘Initialize repository’ rather than ‘Initialized repository’;
   * Keep it short, minimize redundant words (e.g. ‘the’);
   * Don’t include a period at the end.

Commits have dual interpretations: (a) as *snapshots*, and (b) as *diffs*. Let’s explore each interpretation in turn.

**Commits as snapshots**. A commit provides a snapshot of the contents of all files tracked in the repository at a particular point in time on a particular machine. Git stores this information in an intelligent way, saving storage space by avoiding duplicating data that hasn’t changed since the last commit. These snapshots allow us to ‘go back in time’ by ‘checking out’ (``git checkout``) a particular commit in the repository’s history. This feature provides an invaluable safety net, allowing you to recover previous versions of a project in a simple and transparent manner.

**Commits as diffs**. Every commit has a *parent* commit. [#]_ This parent commit corresponds to the state of the repository *before* the new commit was added. This allows us to view each commit as a *diff* (short for ‘difference’) between the parent commit and the new commit. A simple diff might look something like this:

.. figure:: ../../_static/images/version_control_with_git/essential_concepts/git_diff.png
  :width: 800
  :align: center

|br|
This particular screenshot comes from the GitLab web interface, but you can find similar functionality in other version-control platforms such as GitHub. Additionally, many IDEs (e.g. PyCharm) provide similar diff visualizations.

The diff representation highlights the precise region of the code that has changed between the parent commit and the new commit. It is normally expressed in terms of a combination of (a) lines that have been *deleted* from the parent commit (highlighted in red) and (b) lines that have been *added* in the new commit (highlighted in green). In the example above, a particular line (l. 156) has been deleted from the parent commit, and replaced with a new line that is identical in every way, except that the text ‘clickedObject’ has been replaced with the text ‘clicked_object’. These diff representations provide a very natural way for humans to understand the version history of a particular repository, and they have a particularly important role in the process of *code review*, which we will discuss shortly.

There are no strict rules about how big a commit can be, but there are certain conventions. Ideally a commit should be limited to a precise and well-defined change in the code, perhaps corresponding to 1-30 lines of code alterations. This means that you can give it a clear title. If you find the commit changes to be too complicated to describe with a short title, this means you probably could have benefited from splitting your commit into multiple smaller commits.

Branches
########

In a collaborative software project, different programmers will often be working on different software features at the same time. While working on a given feature, the programmer will need their own local version of the repository where they can trial their work-in-progress implementations. Since new features often take a while to implement, the programmer will want to make commits at various points in the process. However, they will probably not want to integrate these commits with the main codebase right away. They’ll instead want to keep these commits to themselves for the time being, only integrating the commits to the main codebase once the code has been properly tested and reviewed.

This is what *branches* are for. A branch can be interpreted as a particular ‘stream’ of commits that can be incrementally added to by the programmer without affecting the other branches in the software project.
Every Git repository has a default branch. Traditionally this was called the ‘master’ branch, but more recently it has become common to name this the ‘main’ branch to avoid the negative connotations of ‘master-slave’ terminology. This is the branch that will be used by default when you download a Git repository onto your local computer.

Most Git repositories have other additional branches. A recommended practice in collaborative software projects is to make a new branch every time you start implementing a new ‘feature’, where a feature might be fixing a particular bug or implementing some new functionality in your software. It is common to call such branches ‘feature branches’.

Some Git repositories (including PsyNet) additionally have a ‘staging’ branch. In PsyNet this branch is named ‘dev’. The staging branch is where the programmers prepare upcoming software versions, which would typically combine together multiple new features.

Git branches are created by *branching* (``git branch``) off pre-existing branches (or commits). For example, when starting to implement a new feature, one might create a new feature branch that branches off the current staging branch.

Once a new feature is complete, the feature branch needs to be *merged* back to more central branches, typically either the staging branch (if it exists) or the main branch. The goal of a merge is to take the modifications implemented in the feature branch and apply them to the target branch. This is simple if the target branch is a direct historical predecessor of the feature branch; all that needs to be done is to update the history of the target branch to include the new commits made in the feature branch. This simple process is called a *fast-forward merge*.

Merging is more complicated if the target branch has in the meantime accumulated some more commits of its own. In this context, Git works by representing each commit as a diff and then combining these diffs together. As long as each branch works on separate parts of the code, this combination process is straightforward enough for Git to perform automatically.

Let’s look at a simple example. Suppose I start on my main branch with a simple file (``main.py``) containing a single function called ``add``.

.. figure:: ../../_static/images/version_control_with_git/essential_concepts/python_add.png
  :width: 800
  :align: center

|br|
Suppose I create a new feature branch where I implement a function called ``multiply``. The resulting ``main.py`` file looks like this:

.. figure:: ../../_static/images/version_control_with_git/essential_concepts/python_multiply.png
  :width: 800
  :align: center

|br|
Let’s suppose I want to merge my new ``multiply`` implementation back into the master branch. Furthermore, let’s suppose that in the meantime someone has merged their own changes to the main branch, so that the ``main.py`` file now looks like this:

.. figure:: ../../_static/images/version_control_with_git/essential_concepts/python_subtract.png
  :width: 800
  :align: center

|br|
How does Git merge these two branches together? It begins by expressing the commits on the feature branch as a series of diffs. In our case, there is just one commit on the feature branch, whose diff looks like this:

.. figure:: ../../_static/images/version_control_with_git/essential_concepts/git_diff_multiply.png
  :width: 800
  :align: center

|br|
Git then simply adds this diff to the commit history of the target branch. The combined diff sequence is then

.. figure:: ../../_static/images/version_control_with_git/essential_concepts/git_diff_subtract.png
  :width: 800
  :align: center

.. figure:: ../../_static/images/version_control_with_git/essential_concepts/git_diff_multiply.png
  :width: 800
  :align: center

|br|
and if we add them together, we get a ``main.py`` file that looks like this:

.. figure:: ../../_static/images/version_control_with_git/essential_concepts/python_add_multiply_subtract.png
  :width: 800
  :align: center

|br|
Merging gets more complicated when the two branches both edit the same lines of code. For example, suppose I have one branch that renames ``subtract`` to ``minus``, and another branch that renames the variables from ``x, y`` to ``a, b``:

.. figure:: ../../_static/images/version_control_with_git/essential_concepts/git_merge-1.png
  :width: 800
  :align: center

.. figure:: ../../_static/images/version_control_with_git/essential_concepts/git_merge-2.png
  :width: 800
  :align: center

|br|
If we look closely, it becomes clear that these two diffs cannot be combined as they stand. In particular, once we’ve renamed ``subtract`` to ``minus``, the second diff doesn’t make sense, because the line ``subtract(x, y)`` no longer exists. This situation is called a *merge conflict*. Git will not resolve a merge conflict automatically; it instead leaves it up to us. Our job in resolving the merge conflict is essentially to create a modified version of the second diff that ‘makes sense’ in the context of the first diff. In our example above, our revised second diff looks like this:

.. figure:: ../../_static/images/version_control_with_git/essential_concepts/git_merge-3.png
  :width: 800
  :align: center

|br|
Merge conflicts are one of the least pleasant parts of working with Git, and it’s good to avoid them where possible. The longer two branches spend diverged, the more likely it is that a complex and difficult-to-resolve merge conflict will occur. This is one reason why it’s helpful to keep the scope of a feature branch small and merge it sooner rather than later.

Synchronizing with the remote repository
########################################

It is possible to do many Git operations without any internet connection, with the resulting actions solely affecting the local repository. Eventually, however, one will want to propagate these changes to the remote repository. This process is called *pushing* (``git push``). We generally push to one branch at a time; pushing to a branch means uploading new commits in our local branch to the corresponding branch in the remote repository.

Conversely, when working with multiple programmers on the same project, we will want to download new commits from the remote repository to our local repository. This process is called *pulling* (``git pull``). We generally pull to one branch at a time; pulling to a branch means downloading new commits in the remote branch to the corresponding branch of our local repository.

.. note::
  You may also come across the related command ``git fetch``. This command is similar to ``git pull``, but it does a bit less. Like ``git pull``, it downloads the state of the remote repository onto your local machine; however, unlike ``git pull``, it doesn’t integrate these changes with your current branch, but instead leaves it as it is. The main situation I find myself using ``git fetch`` is when I want to check out a branch that has been added by another user to the remote repository that I haven’t yet loaded onto my local machine.

One thing to note is that you can’t push to the remote repository if the remote repository contains commits that you are missing from your local repository. So, it is often necessary to first pull, so that you’re sure that you’re not missing anything from the remote repository, and only then push your new commits.

There are no strict rules about how often you push or pull. Ordinarily one might push to the remote repository after every commit, but it’s perfectly possible to wait longer and only push after every few commits. The main rule is that once you’ve finished your working session you should make sure to push your local changes, so that the remote repository can act as a backup, and so that collaborators will see the most up-to-date version of your code.

Cloning
#######

Sometimes we want to work with a repository that someone else created. We achieve this by ‘cloning’ their repository to our local machine. This is achieved using the ``git clone`` command. Running this command creates a directory on our local machine corresponding to the remote repository. We can then run our other Git commands as usual within this repository.

Forking
#######

Forking is a related concept to branching. When we create a branch in Git, this branch is kept as part of the original repository. People who work with that repository can switch to our branch, assuming that we’ve pushed our local changes. Forking is like branching, except the branch is kept in a new, separate repository. It’s most commonly used when someone wants to work with a codebase when they’re not one of the project’s main developers. They can work on their fork of the codebase and not worry about harming anyone else’s work. By default, the forked repository is completely independent from the original repository; however, online version-control systems (e.g. GitHub) do make it possible to eventually merge a fork back into the original repository, if for example the programmer wants to contribute some changes back to the original codebase.

Summary
#######

Let’s recap the essential concepts we’ve covered. When we work with Git, we work with particular *repositories*, which store the code for a given software project. These repositories are typically hosted on remote servers, for example on the GitHub/GitLab platforms, with individual programmers keeping their own copies on their local machines. These repositories are kept synchronized by *pulling* changes from the remote repository to the local repository, and *pushing* changes in the local repository to the remote repository. The repositories have tracked *version history*, which makes it easy to go back in time to previous versions of a given project. This version history is expressed in terms of a series of atomic *commits*, which can be represented either as *snapshots* of the repository at particular points in time, or *diffs* that capture the sense in which particular regions of the code have been edited from one snapshot to the next. Each repository may contain multiple *branches*, which represent different streams of commits that typically correspond to different ongoing feature implementations or developer workflows. After completing implementation of a given feature, the programmer will typically *merge* the relevant feature branch into a more central repository branch. In some cases, Git can perform this merge automatically, but in other cases (*merge conflicts*) it needs help from the programmer.

.. rubric:: Footnotes

.. [#] Some commits, in particular *merge commits*, actually have more than one parent.
