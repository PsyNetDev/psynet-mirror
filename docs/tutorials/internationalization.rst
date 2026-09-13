====================
Internationalization
====================

Finally, you created an amazing experiment! How cool would it be to run it with participants from all over the world?

Luckily, PsyNet makes it easy to run experiments in different languages. Here's what you need to do:

- mark which strings need to be translated
- perform automatic translation and optionally manually check them

Selecting a language
=====================

We use the technical term 'locale' to refer to the language of your experiment.
Locales are denoted by `ISO 639-1 codes <https://www.gnu.org/software/gettext/manual/html_node/Usual-Language-Codes.html>`__,
e.g. ``en`` for English, ``de`` for German, ``nl`` for Dutch, etc.

You can specify the locale by adding the line ``locale = de`` to your ``config.txt`` file.
If you do not specify a locale, the experiment will default to English.


Mark which strings need to be translated
========================================
Let's say you have the following info page in your experiment:


.. code-block:: python

    from dominate.tags import h1, hr, div
    from psynet.page import InfoPage

    my_info_page = InfoPage(
        div(
            h1("Instructions"),
            hr(),
            p("In this experiment, you will listen to different music clips."),
            p("You have to select the music you like most."),
            p('Press "Next" to continue.')
        ),
        time_estimate=5
    )

You can easily translate it by marking the strings that need to be translated with the ``_`` function from ``gettext``.


.. code-block:: python

    import os

    from dominate.tags import h1, hr, div
    from psynet.page import InfoPage
    from psynet.utils import get_translator

    _ = get_translator()

    my_info_page = InfoPage(
        div(
            h1(_("Instructions")),
            hr(),
            p(_("In this experiment, you will listen to different music clips.")),
            p(_("You have to select the music you like most.")),
            p(_('Press "Next" to continue.'))
        ),
        time_estimate=5
    )


.. warning::
    Under the hood PsyNet searches for strings that are marked with ``_``. If you use other functions to mark strings for translation
    (e.g., ``my_wrapper = get_translator()``), they will not be recognized (e.g., ``my_wrapper("Instructions")``) and not translated. So, make sure to use ``_ = get_translator()``.


Variables
---------
To replace variables in the translation, you have to write the variable in capital letters (underscores are also allowed) and use curly brackets around them.
To resolve the variable, you have to use the ``.format`` method, like here:

.. code-block:: python

    next_button_name = _("Next")
    next_button_text = _('press "{NEXT_BUTTON_NAME}" to continue.').format(NEXT_BUTTON_NAME=next_button_name)

.. warning::
    You have to use the ``.format`` method to replace the variables in the translation. F-strings are not allowed, as it would first replace the variable in the English string and then tries to lookup the translation which would fail.

Summary of best practices
-------------------------
- Use ``_`` for most strings
- Keep the strings short and simple
- Avoid HTML tags in the strings as they might get translated or will lead to word order issues
- Keep the use of inline variables to a minimum, e.g. instead of writing
  ``_("Make the stimulus as {TARGET} as possible using the slider").format(TARGET=_("happy"))``,
  write ``_("Adjust the slider to match the target:") + _("happy")``.

To see the translation in action, have a look at the ``translation`` demo.


Perform automatic translation
=============================

Open a terminal in your experiment folder and run the following command:

.. code-block:: console

    psynet translate

By default this will translate your experiment to the locale specified in your ``config.txt`` file.

.. note::
    You can instruct PsyNet to create translations in multiple languages via the config variable ``supported_locales``,
    for example ``supported_locales = ["de", "nl"]``.
    Alternatively, you can specify the locales on the command line, e.g. ``psynet translate de nl``.

To see all supported locales, run:

.. code-block:: console

    psynet locales

This displays locales with their names. For a compact single-line output (useful for scripting), use:

.. code-block:: console

    psynet locales --codes-only

Each locale's translation will be stored in a file of the form ``locales/<iso_code>/LC_MESSAGES/experiment.po``.

PsyNet currently supports two translators:

- OpenAI ChatGPT (``chat_gpt``, which is PsyNet's default) and
- Google Translator (``google_translate``)

You can set the default translator in your ``config.txt`` or ``.dallingerconfig`` with the following line:

.. code-block:: text

    [Translator]
    default_translator = <translator_name>

OpenAI ChatGPT
--------------
To use OpenAI ChatGPT, you need to have an OpenAI API key. You can set it in your ``.dallingerconfig`` file with the following line:

.. code-block:: text

    [Translator]
    openai_api_key = <your_openai_api_key>


Also you need to install the ``openai`` package by running:

.. code-block:: console

    pip install openai


Google Translator
-----------------
To use Google Translator, you need to do the following steps

- Create a project in the Google Cloud Console
- Enable the Cloud Translation API
- Create a service account
- In the service account and go to the keys tab. Now create a new key as JSON and store it to your computer (home folder is recommended). Now store the path to your ``.dallingerconfig`` file:

.. code-block:: text

    [Translator]
    google_translate_json_path = <path_to_your_json_file>


Also you need to install the ``google-cloud-translate`` package by running:

.. code-block:: console

    pip install google-cloud-translate==2.0.1

The translation process
-----------------------
Both ChatGPT and Google Translate batch their translations on a file basis. This means that they can intelligently
infer the context of the strings in the file. ChatGPT also sees the source code of the file, which can provide
additional information for disambiguation.


Manual checking
---------------
You can manually inspect the machine translation by opening the ``locales/<iso_code>/LC_MESSAGES/experiment.po`` file using
`POedit editor <https://poedit.net>`__ and check if strings that you marked with ``_`` are translated properly.

Machine translations are by default marked as 'fuzzy' in POedit. Once you have reviewed and confirmed a translation,
you can remove this flag in POEdit. When you subsequently run ``psynet translate``, non-fuzzy translations will
not be overwritten unless their input text changes. They will still however be used as context for the other
translations in the same file.


Revising translations
---------------------

When you run ``psynet translate``, all fuzzy (i.e. machine-translated) translations will be overwritten.
Non-fuzzy translations will not be overwritten unless their input text changes.
Texts that no longer occur in the source code will be removed from the translation files.
PsyNet does not make any backup of your translations, so make sure you include your experiments `locales`
directory in your experiment's git repository and commit your changes regularly.


Advanced usage
==============

Contexts
--------
``_`` assumes the same string is always translated the same way, regardless of the context.
However, sometimes you want to disambiguate the meaning of a string. For example, the word "bank" can mean a financial institution or the side of a river.
To do this you can use ``_p``:

.. code-block:: python

    from psynet.utils import get_translator

    _p = get_translator(context=True)

    bank_of_river = _p("river", "bank")
    financial_institution = _p("financial", "bank")


.. note::
    However, this use-case is quite rare. In most cases, you can use ``_`` and it will work just fine.

Translating a package
---------------------

You can translate an arbitrary Python package for use in PsyNet by navigating to the root of
the package and running ``psynet translate``. This will create a ``locales`` directory in the package's
source directory and populate it with the translations for the supported locales.
If you do not specify which locales to translate it to, it will default to PsyNet's own list of supported locales.


Contributing to PsyNet
----------------------

Merge requests that change PsyNet source should not update ``psynet/locales``.
Package catalogs are refreshed on the release branch with ``psynet translate``,
where :func:`~psynet.translation.check.check_translations` also runs. Until
then, a missing PsyNet catalog entry raises under ``psynet debug`` and on
release-branch tests. Non-release test runs show the English source text and
log a warning instead. Live experiments report the error and show English.
Tests that pin translated PsyNet copy should therefore run only on release
branches. Experiment catalogs are unaffected: a missing experiment translation
still raises outside live mode, whether you are running ``psynet debug`` or
``psynet test local``.

To contribute to PsyNet you need to:
- have a local version of psynet on your computer e.g.: ``cd ~ && git clone https://gitlab.com/PsyNetDev/PsyNet``
- go to the master branch and pull the latest changes: ``cd ~/PsyNet && git checkout master && git pull``
- create a new branch for your changes: ``git checkout -b my_new_translations``
- optionally translate to the new language: ``psynet translate <new_locale>``
- go to the locale folder and your new locale: ``cd ~/PsyNet/tests/experiments/translation/locales/<new_locale>/LC_MESSAGES``
- open the ``experiment.po`` file with PoEdit, go through each entry and validate it or change it
- save the file, commit your changes, and push them
- create a merge request on the GitLab page of PsyNet
- thank you for your contribution!
