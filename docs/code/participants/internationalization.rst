====================
Internationalization
====================

A **locale** is the language an experiment is shown in, written as an
`ISO 639-1 code <https://www.gnu.org/software/gettext/manual/html_node/Usual-Language-Codes.html>`__,
such as ``en`` for English, ``de`` for German or ``nl`` for Dutch.

Setting locales
---------------

Two configuration keys control the locales, in ``config.txt`` or the
experiment's ``config`` dictionary:

``locale`` (default ``en``)
    The locale participants see. Every participant in a deployment sees the
    same locale.

``supported_locales`` (default ``[]``)
    Further locales to translate the experiment into. ``psynet translate``
    produces translations for these and for ``locale``, and PsyNet checks that
    the translation files exist before the experiment starts.

.. code-block:: text

    locale = de
    supported_locales = ["nl"]

To run the same experiment in several languages, deploy it once per locale,
changing ``locale`` each time. ``psynet locales`` lists the locales PsyNet
supports; ``psynet locales --codes-only`` prints just the codes on one line.

Marking strings
---------------

Mark each participant-facing string with ``_``, which
:func:`~psynet.utils.get_translator` returns. The ``translation`` demo is shown
in German and has a Dutch translation:

.. literalinclude:: ../../../demos/experiments/translation/experiment.py
   :start-at: _ = get_translator()

The unmarked strings on the second page stay in English.

.. warning::

    ``psynet translate`` finds strings by searching the source code for
    calls to ``_`` and ``_p``. Keep these names (``my_wrapper =
    get_translator()`` is not recognized), and pass the text as a literal
    string, not as a variable.

``psynet translate`` also extracts strings marked with ``_``, ``_p``,
``gettext`` or ``pgettext`` from the experiment's ``.html`` templates.

Variables
~~~~~~~~~

Write variables in capital letters (underscores are allowed) inside curly
brackets, and fill them in with ``.format``:

.. code-block:: python

    next_button_name = _("Next")
    next_button_text = _('Press "{NEXT_BUTTON_NAME}" to continue.').format(
        NEXT_BUTTON_NAME=next_button_name
    )

.. warning::

    Do not use f-strings. An f-string fills in the variable before the
    translation is looked up, so no translation is found.

Contexts
~~~~~~~~

``_`` translates a string the same way wherever it appears. When one English
string needs different translations, such as "bank" for a riverbank and for a
financial institution, use ``_p`` and give each use a context:

.. code-block:: python

    from psynet.utils import get_translator

    _p = get_translator(context=True)

    bank_of_river = _p("river", "bank")
    financial_institution = _p("financial", "bank")

The demo uses ``_p`` to group the button labels under the context
``"button"``. In most cases ``_`` is enough.

Best practices
~~~~~~~~~~~~~~

- Use ``_`` for most strings.
- Keep the strings short and simple.
- Leave HTML tags out of the strings; translators may translate them, and
  they make word order hard to change.
- Keep inline variables to a minimum. Instead of
  ``_("Make the stimulus as {TARGET} as possible using the slider").format(TARGET=_("happy"))``,
  write ``_("Adjust the slider to match the target:") + _("happy")``.

Translating
-----------

Run ``psynet translate`` in the experiment directory:

.. code-block:: console

    psynet translate

This translates the experiment into ``locale`` and ``supported_locales``. To
choose the locales on the command line instead, list them:

.. code-block:: console

    psynet translate de nl

Each locale's translations are stored in
``locales/<iso_code>/LC_MESSAGES/experiment.po``.

Translators
~~~~~~~~~~~

PsyNet supports two machine translators:

- OpenAI ChatGPT (``chat_gpt``, the default)
- Google Translate (``google_translate``)

Set the default in ``config.txt`` or ``~/.dallingerconfig``, or pass
``--translator`` to ``psynet translate``:

.. code-block:: text

    [Translator]
    default_translator = <translator_name>

Both translators send one file at a time, so they can use the other strings in
the file as context. ChatGPT also sees the file's source code.

**OpenAI ChatGPT** needs an OpenAI API key in ``~/.dallingerconfig``:

.. code-block:: text

    [Translator]
    openai_api_key = <your_openai_api_key>

It also needs the ``openai`` package:

.. code-block:: console

    pip install openai

**Google Translate** needs a Google Cloud service account:

1. Create a project in the Google Cloud Console.
2. Enable the Cloud Translation API.
3. Create a service account.
4. On the service account's **Keys** tab, create a JSON key and save it on
   your computer, for example in your home directory.
5. Add the key's path to ``~/.dallingerconfig``:

   .. code-block:: text

       [Translator]
       google_translate_json_path = <path_to_your_json_file>

It also needs the ``google-cloud-translate`` package:

.. code-block:: console

    pip install google-cloud-translate

Reviewing and revising
----------------------

Manual checking
~~~~~~~~~~~~~~~

Open ``locales/<iso_code>/LC_MESSAGES/experiment.po`` in
`Poedit <https://poedit.net>`__ to check the machine translations. Poedit
shows them as "fuzzy". When you have checked a translation, remove the fuzzy
flag in Poedit.

Revising translations
~~~~~~~~~~~~~~~~~~~~~

When you run ``psynet translate`` again:

- fuzzy (machine) translations are overwritten;
- checked translations are kept unless their English text has changed, and
  are used as context for the other translations in the file;
- translations of strings that no longer occur in the source code are
  removed.

PsyNet keeps no backup of the translations, so commit the experiment's
``locales`` directory to Git regularly.

Missing translations
~~~~~~~~~~~~~~~~~~~~

If a marked string has no translation in the experiment's catalog,
``psynet debug`` and ``psynet test local`` raise an error. A live experiment
reports the error and shows the English text instead.

Translating a package
---------------------

To translate a Python package for use with PsyNet, run ``psynet translate``
in the root of the package. This creates a ``locales`` directory in the
package's source directory with translations for the locales you list, or
for all locales PsyNet supports if you list none.
