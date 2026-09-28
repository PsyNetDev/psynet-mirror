==================
Translating PsyNet
==================

PsyNet's own translations are stored in
``psynet/locales/<locale>/LC_MESSAGES/psynet.po``. Their progress is shown on
the :doc:`/dashboards/translation`.

Catalogs in merge requests
--------------------------

Merge requests that change PsyNet source code should not also update
``psynet/locales``; translation-only merge requests are the exception.
Package catalogs are refreshed on the release branch with ``psynet translate``,
which also runs ``psynet.translation.check.check_translations``. Until then, a
missing PsyNet catalog entry behaves as follows:

- Under ``psynet debug`` and in tests on release branches, it raises an error.
- In tests on other branches, PsyNet shows the English source text and logs a
  warning.
- In live experiments, PsyNet reports the error and shows the English text.

Tests that pin translated PsyNet copy should therefore run only on release
branches. Use :func:`psynet.utils.is_release_branch` or the
``release_branch_only`` marker from ``psynet.pytest_psynet``.

Experiment catalogs are unaffected: a missing experiment translation still
raises outside live mode, under both ``psynet debug`` and ``psynet test local``.

Contributing a translation
--------------------------

1. Clone PsyNet and create a branch from an up-to-date ``master``:

   .. code-block:: console

       cd ~ && git clone https://gitlab.com/PsyNetDev/PsyNet
       cd ~/PsyNet && git checkout master && git pull
       git checkout -b my_new_translations

2. To add a new language, run ``psynet translate <new_locale>`` from the root
   of the PsyNet checkout. Run from a package root, ``psynet translate`` writes
   to the package's ``locales`` directory.

3. Open ``psynet/locales/<locale>/LC_MESSAGES/psynet.po`` in
   `Poedit <https://poedit.net>`__, and check or correct each entry. Remove
   the fuzzy flag from each translation you confirm.

4. Save the file, commit and push your changes, and open a merge request on
   `GitLab <https://gitlab.com/PsyNetDev/PsyNet>`__.
