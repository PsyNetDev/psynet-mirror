Custom front ends
=================

Custom front ends are usually written as custom prompts and controls for
modular pages. A *prompt* displays a stimulus to the participant, and a
*control* gives the participant a way to respond. The examples on this page
come from the ``demos/features/modular_page`` demo.

Custom prompts
--------------

The demo defines a custom prompt as follows:

.. literalinclude:: ../../../demos/features/modular_page/experiment.py
   :pyobject: HelloPrompt

``macro`` names the Jinja macro that renders the prompt. ``external_template``
names the file that defines the macro, stored in the experiment's
``templates`` folder. The constructor extends the one from
:class:`~psynet.modular_page.Prompt` with a ``username`` argument, which it
saves as an instance attribute.

``templates/custom-prompts.html`` defines the macro:

.. literalinclude:: ../../../demos/features/modular_page/templates/custom-prompts.html
   :language: html+jinja

The template uses `Jinja <https://jinja.palletsprojects.com/en/3.0.x/>`_, a
templating language for generating HTML. ``{% macro %}`` defines a function
that generates HTML, and ``{{ ... }}`` evaluates a Python expression and writes
the result into the HTML. If ``username`` is ``"Jeff"``, the ``<h1>`` line
renders as ``<h1>Hello, Jeff!</h1>``.

Every prompt and control macro takes a single argument, here called
``params``. It is the :class:`~psynet.modular_page.Prompt` or
:class:`~psynet.modular_page.Control` object inserted into the modular page;
it is unrelated to ``config.txt``. The macro can access any attribute or method
of that object, including instance attributes such as ``username``, class
attributes, and methods:

.. code-block:: python

    class HelloPrompt(Prompt):
        macro = "with_hello"
        external_template = "custom-prompts.html"
        background_color = "red"

        ...  # constructor as above

        def get_message(self):
            return f"Welcome back, {self.username}."

.. code-block:: html+jinja

    <h1 style="background-color: {{ params.background_color }}">
        Hello, {{ params.username }}!
    </h1>
    <p>{{ params.get_message() }}</p>

Custom macros can reuse PsyNet's built-in macros. ``psynet_prompts.simple``
displays the prompt's text. The built-in prompt macros are defined in
``psynet/templates/macros/prompt.html``.

Custom controls
---------------

Custom controls are defined in the same way:

.. literalinclude:: ../../../demos/features/modular_page/experiment.py
   :pyobject: ColorText

``color`` is an instance attribute set in the constructor.
``get_js_page_modules()`` supplies behavior that PsyNet activates for each
page hosting the control. ``metadata`` returns optional information saved with
the participant's response. ``get_bot_response()`` supplies the answer that
bots give in automated tests.

``templates/custom-controls.html`` contains only the markup:

.. literalinclude:: ../../../demos/features/modular_page/templates/custom-controls.html
   :language: html+jinja

``static/color-text.js`` contains the behavior:

.. literalinclude:: ../../../demos/features/modular_page/static/color-text.js
   :language: javascript

The handler stages the text box contents in
``psynet.response.staged.rawAnswer``, which PsyNet submits when the page is
exited. PsyNet loads the file as a JavaScript module, calls ``activate()`` for
each hosting page, and resets the response handler when the page ends.

To postprocess the response in Python before it is saved, override
:meth:`~psynet.modular_page.Control.format_answer`:

.. code-block:: python

    def format_answer(self, raw_answer, **kwargs):
        return raw_answer.capitalize()

``raw_answer`` is the staged ``rawAnswer``. Here it is a string, but lists and
dictionaries are also supported.

Passing configuration to JavaScript
-----------------------------------

Custom prompts and controls can provide page-scoped JavaScript configuration
by implementing ``get_js_vars()``:

.. code-block:: python

    class ColorText(Control):
        def get_js_vars(self):
            return {"color_text_config": {"maximum_length": 200}}

Read these values through ``psynet.var``:

.. code-block:: javascript

    const maximumLength = psynet.var.color_text_config.maximum_length;

Sharing JavaScript functions between components
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``js_vars`` should contain data, not functions. To provide a function that
another component can call, for example a prompt function called by its
control, attach it to the page-scoped ``psynet.page`` namespace:

.. code-block:: javascript

    // Prompt setup
    psynet.page.prompt.playStimulus = function () {
        // ...
    };

The control can then call it:

.. code-block:: javascript

    psynet.page.prompt.playStimulus();

PsyNet resets ``psynet.page`` when the participant moves to another page, so
no stale functions are left behind. If the function is not owned by the prompt
or control, use a descriptive shared namespace such as ``psynet.page.myTask``
instead of a global function on ``window``.

Managing JavaScript lifecycles
------------------------------

PsyNet moves between timeline pages without reloading the browser document,
so it distinguishes loading code from activating page behavior:

* ``js_dependencies`` contains URLs of classic JavaScript files loaded once per
  browser document. Components return the same URLs from
  ``get_js_dependencies()``.
* ``js_page_code`` contains short inline activation bodies. Components return
  equivalent snippets from ``get_js_page_code()``.
* ``js_page_modules`` contains URLs of JavaScript modules whose named export
  ``activate(context)`` runs for each hosting page. Components return the same
  URLs from ``get_js_page_modules()``.

The activation context contains ``root`` (the page's ``#main-body`` element),
``trial``, ``vars`` (the current ``psynet.var``), ``page``, and ``psynet``.
Page code is wrapped in an asynchronous activation function with the same
context. Page code and module ``activate()`` functions may return asynchronous
cleanup. Most do not need one: PsyNet removes the page DOM, stops trial-owned
timers and handlers, and resets page response state automatically.

For example, a short component hook can return activation code directly:

.. code-block:: python

    def get_js_page_code(self):
        return "root.querySelector('#answer').focus();"

Each page-code entry has its own local scope. Use ``vars`` or ``psynet.page`` to
communicate with other behavior rather than relying on local declarations from
another snippet. Page code is compiled in the browser; components with
substantial, reusable, or imported behavior should use a page module instead.

Cleanup is needed for resources that survive normal page teardown. For example,
a listener attached to ``window`` survives removal of the page DOM:

.. code-block:: javascript

    export function activate({root}) {
        function updateWidth() {
            root.querySelector("#width").textContent = window.innerWidth;
        }

        window.addEventListener("resize", updateWidth);
        updateWidth();

        return function cleanup() {
            window.removeEventListener("resize", updateWidth);
        };
    }

PsyNet runs returned cleanup functions in reverse activation order before
leaving the page. WebSockets, workers, observers, and raw timers are other
common cases requiring cleanup. ``psynet.addPageEventListener(...)`` and
``psynet.addPageCleanupCallback(...)`` register listeners and callbacks that
PsyNet removes or runs when the page ends.

The browser imports and caches each module file once. PsyNet calls its exported
``activate()`` function again whenever the behavior is used on a new page, so
library top-level code does not rerun while page state is still initialized
fresh.

``DOMContentLoaded`` does not fire for each page. Put page setup in
``activate()`` or ``js_page_code``, and use
:doc:`trial events <event_management>` such as ``pageReady`` only for timing,
for example auto-advance.

Managing static files for custom components
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A component that belongs to one experiment keeps its files in that
experiment's ``static`` directory and uses normal experiment URLs:

.. code-block:: python

    class ColorText(Control):
        def get_js_page_modules(self):
            return ["/static/color-text.js"]

Reusable components shipped in a Python package keep their resources inside
the package and construct namespaced URLs with
:func:`psynet.static_resources.package_static_url`. PsyNet's built-in
components use the ``psynet`` namespace, whose root is ``psynet/static``:

.. code-block:: python

    from psynet.static_resources import package_static_url


    class MyPrompt(Prompt):
        def get_js_dependencies(self):
            return [
                package_static_url(
                    "psynet",
                    "libraries/my-library/library.js",
                )
            ]

        def get_js_page_modules(self):
            return [
                package_static_url(
                    "psynet",
                    "scripts/my-prompt.js",
                )
            ]

PsyNet already registers its own package root, so experiments using built-in
components do not need to copy files into their ``static`` directories. New
built-in components use namespaced package URLs rather than adding entries to
``Experiment.extra_files()``.

Third-party packages register one static root through the ``psynet.static``
Python entry-point group. PsyNet publishes it under
``/static/packages/<namespace>/`` before dynamic pages are created. Package
authors must include the static root in their wheel and source distribution.
:doc:`/developer/package_static_resources` covers package layout,
entry-point configuration, custom roots, zip-backed resources, validation,
testing, and wheel packaging.

Custom page templates
---------------------

A custom :class:`~psynet.timeline.Page` provides only the contents of the
page body, with ``template_fragment_path`` or ``template_fragment_str``:

.. code-block:: python

    from psynet.timeline import Page


    class MyPage(Page):
        def __init__(self):
            super().__init__(
                label="my_page",
                template_fragment_path="templates/my-page.html",
                css_links=["/static/my-page.css"],
                js_page_modules=["/static/my-page.js"],
                time_estimate=5,
            )

        def get_bot_response(self, experiment, bot):
            return None

PsyNet wraps this fragment in the standard timeline page shell, including the
timeline header, main body container, footer, page asset bundle, and
``psynet-template-data``. A fragment template must not include ``{% extends
"timeline-page.html" %}``, ``{% block main_body %}``, ``<html>``, ``<head>``,
``<body>``, ``<script>``, ``<style>`` or ``<link rel="stylesheet">``.

Supply page-local CSS and JavaScript through explicit page arguments:

* Prefer ``template_fragment_path`` for experiment templates stored in
  ``templates/``. ``template_fragment_str`` is useful for small generated
  fragments.
* Use ``css_links`` for page-local CSS files stored in ``static/``, rather
  than embedding non-trivial CSS in Python.
* Use ``js_dependencies`` for JavaScript libraries that are loaded once per
  browser document.
* Use ``js_page_code`` for short inline activation snippets.
* Use ``js_page_modules`` for JavaScript behavior activated for each page.
  Each file exports ``activate(context)`` and may return a cleanup function.
* Use ``css`` only for small generated or one-off style snippets.

Custom prompts and controls supply the same assets from Python through
``get_css()``, ``get_css_links()``, ``get_js_dependencies()``,
``get_js_page_code()``, ``get_js_page_modules()`` and ``get_js_vars()``.

These rules exist because PsyNet swaps pages in place by default, without
reloading the browser document; :doc:`/developer/page_lifecycle` describes
how. PsyNet raises an error when a page's template breaks them. With the
``inplace_timeline_transitions`` configuration key set to ``false`` (see
:doc:`/reference/configuration`), PsyNet reloads the document for every page
and only warns. :doc:`/whats_new/upgrading_to_psynet_14` explains each error
and how to migrate older templates.
