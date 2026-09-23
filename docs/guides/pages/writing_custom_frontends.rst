.. |br| raw:: html

   <br />

Writing custom frontends
=========================

PsyNet provides a library of built-in user interface components, including text boxes, audio recorders, video players, vector animations, and so on. It is possible to design many experiments using these built-in components, but for true flexibility, one needs the ability to program one’s own front-end components from scratch.

The recommended way to do this is by creating custom modular page components. As a reminder, modular pages combine together two types of elements: a *prompt*, which displays some kind of stimulus to the user, and a *control*, which gives the user some mechanism for responding to the prompt.

The built-in ‘``modular_page``’ demo demonstrates how one can write custom prompts and controls in PsyNet.

In-place timeline transitions
-----------------------------

PsyNet uses in-place timeline transitions by default. This means that when a
participant advances from one timeline page to the next, PsyNet swaps the
timeline page content inside the existing browser document instead of reloading
the whole page. Custom pages and components should therefore follow the
fragment-template contract described below.

Experiments that explicitly need the old full-page reload behavior can set
``inplace_timeline_transitions = false`` in ``config.txt``. This legacy path is
kept for backwards compatibility, but new and migrated custom pages should be
written for in-place transitions.

If you are upgrading an existing experiment, start with
:doc:`/whats_new/upgrading_to_psynet_14`. Maintainers extending PsyNet's Page,
Prompt, or Control internals should also read
:doc:`/developer/page_lifecycle`, which documents the complete rendering,
activation, cleanup, and failure contract.

Custom page templates
~~~~~~~~~~~~~~~~~~~~~

PsyNet supports two styles of custom page templates.

The legacy style is a complete Jinja template that extends ``timeline-page.html``
and overrides blocks such as ``main_body``:

.. code-block:: html

    {% extends "timeline-page.html" %}

    {% block main_body %}
        <p>Custom page content</p>
    {% endblock %}

This complete-template style remains supported for the legacy full-page reload
path, where ``inplace_timeline_transitions = false`` is set explicitly. It
should not be used for custom pages that inherit the default in-place
transition behavior.

For the default in-place timeline transitions, custom pages should provide only
the contents of the page's ``main_body`` block by using ``template_fragment_path`` or
``template_fragment_str``:

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
``psynet-template-data``. Authors should not include ``{% extends
"timeline-page.html" %}``, ``{% block main_body %}``, ``<html>``, ``<head>``,
or ``<body>`` in a fragment template.

Page-local CSS and JavaScript should be supplied through explicit page
arguments:

* Prefer ``template_fragment_path`` for experiment templates stored in
  ``templates/``. ``template_fragment_str`` is useful for small generated
  fragments, but file-based fragments are usually clearer for authored pages.
* Use ``css_links`` for authored page-local CSS files stored in ``static/``.
  Prefer this over embedding non-trivial CSS in Python.
* Use ``js_dependencies`` for JavaScript libraries that are loaded once per
  browser document.
* Use ``js_page_code`` for short inline activation snippets.
* Use ``js_page_modules`` for JavaScript behavior activated for each page.
  Each file exports ``activate(context)`` and may return a cleanup function.
* Use ``css`` only for small generated or one-off style snippets when a file
  would be less clear.

Custom prompts and controls supply the equivalent assets from Python through
``get_css()``, ``get_css_links()``, ``get_js_dependencies()``, ``get_js_page_code()``,
``get_js_page_modules()`` and ``get_js_vars()``, which are described below.

Do not rely on ``DOMContentLoaded`` for page setup when using in-place
transitions. In-place transitions do not reload the browser document for every
timeline page, so ``DOMContentLoaded`` will not fire for each page activation.
Put ordinary page setup in a ``js_page_modules`` ``activate()`` function (or
short ``js_page_code``). Use trial events such as ``pageReady`` only for
timing gates (for example auto-advance).

Template validation
~~~~~~~~~~~~~~~~~~~

With the default ``inplace_timeline_transitions = true`` behavior, PsyNet raises
an error if a custom page uses a complete template or if author-provided
template content includes patterns that are incompatible with the in-place
lifecycle. When ``inplace_timeline_transitions = false`` is set explicitly,
PsyNet keeps legacy templates working but may warn about patterns that should be
migrated before returning to the default mode.

The validation checks only author-provided template content, not PsyNet's own
timeline shell or assets supplied through supported page arguments. The checked
patterns are:

* ``document.addEventListener("DOMContentLoaded", ...)``. Move page setup into
  a ``js_page_modules`` ``activate()`` function (or ``js_page_code``). Use
  ``pageReady`` / ``trialConstruct`` only for timing gates.
* ``window.addEventListener(...)`` without evidence of PsyNet cleanup. Prefer
  returning cleanup from ``activate()``, or use
  ``psynet.addPageEventListener(...)`` /
  ``psynet.addPageCleanupCallback(...)``.
* Raw template ``<script>`` blocks. Use ``js_page_code`` for short snippets or
  ``js_page_modules`` for substantial / reusable behavior.
* Template ``<script src=...>`` tags. Use ``js_dependencies`` (load-once
  libraries) or ``js_page_modules`` (per-page modules) according to the
  intended lifecycle.
* Template ``<style>`` blocks. Prefer a ``static`` stylesheet via ``css_links``
  (or ``get_css_links()``); use ``css`` / ``get_css()`` only for small
  generated snippets.
* Template stylesheet ``<link rel="stylesheet">`` tags. Use the ``css_links``
  argument (or ``get_css_links()``) instead.

Existing experiments may therefore be legacy-only, SPA-ready, or incidentally
compatible with both modes. A validation error in the default mode means that
the page has not yet been migrated to the fragment-template contract; it does
not imply that the same page should stop working in legacy reload mode.

Custom prompts
--------------

Let’s see first how the user defines a custom prompt. Looking at ``experiment.py``, we see the following Python code:

.. code-block:: python

    class HelloPrompt(Prompt):
        macro = "with_hello"
        external_template = "custom-prompts.html"

        def __init__(
                self,
                username: str,
                text: Union[None, str, Markup] = None,
                text_align: str = "left",
        ):
            super().__init__(text=text, text_align=text_align)
            self.username = username

There are three important components here.

First, we tell PsyNet that our ``HelloPrompt`` prompt is going to be associated with a macro called ‘``with_hello``’.

Second, we tell PsyNet that this macro is going to be defined in an external template, and that external template is going to be called ``custom-prompts.html``. External templates are stored in a folder called ``templates`` located in the experiment directory; we’ll have a look at ``templates/custom-prompts.html`` in just a moment.

Third, we write a custom constructor function. This function inherits from the superclass ``Prompt``, but adds an extra argument, ``username``, which is saved as an instance attribute (``self.username = username``).

Let’s have a look at ``templates/custom-prompts.html``.

.. code-block:: html

    {% macro with_hello(config) %}
       <h1>Hello, {{ config.username }}!</h1>

       {{ psynet_prompts.simple(config) }}

    {% endmacro %}

The curly braces and percent sign notation comes from `Jinja <https://jinja.palletsprojects.com/en/3.0.x/>`_. Jinja is a templating language used for programmatically generating HTML. An important feature of Jinja is the use of *macros*, which are functions responsible for generating code. Everything else is HTML code.

Here we are defining a macro called ``with_hello``. This macro follows a standard form for all PsyNet prompt/control macros. In particular, it takes a single argument, ‘``config``’, which is used to bring configuration information from Python into Jinja. Note that this variable ‘``config``’ has nothing to do with config.txt, it is simply a way for psynet to transfer information to Jinja as we will explain below. We can access information from this config object by writing expressions of the following form:

.. code-block:: html

    {{ config.username }}

The double brackets is special Jinja syntax that means ‘evaluate the contents of these brackets as a Python expression’. The config object is a Python object, and we can access its attributes (for example ``username``) just like normal Python object attributes, using ‘.’ notation.

When Jinja evaluates an expression surrounded with double brackets, it takes the results and writes it into the HTML file. So, suppose ``config.username`` was equal to ‘Jeff’, then the following Jinja passage

.. code-block:: html

    <h1>Hello, {{ config.username }}!</h1>

would evaluate to the following HTML passage:

.. code-block:: html

    <h1>Hello, Jeff!</h1>

So what exactly *is* the ``config`` object? It corresponds directly to the ``Prompt`` or ``Control`` object that has been inserted into the modular page. Any attributes (or indeed methods) of these objects are directly accessible within the Jinja macro. Look again at the definition of ``HelloPrompt``:

.. code-block:: python

    class HelloPrompt(Prompt):
        macro = "with_hello"
        external_template = "custom-prompts.html"

        def __init__(
                self,
                username: str,
                text: Union[None, str, Markup] = None,
                text_align: str = "left",
        ):
            super().__init__(text=text, text_align=text_align)
            self.username = username

See how the ``username`` attribute was set within the ``__init__`` function, making it an instance attribute, i.e. an attribute that varies between ``HelloPrompt`` instances.

We can also define prompts with *class attributes*; these attributes are fixed for all instances of a given class. In the below example, ``background_color`` is a class attribute:

.. code-block:: python

    class HelloPrompt(Prompt):
        macro = "with_hello"
        external_template = "custom-prompts.html"
        background_color = "red"

As before, we can access them using Jinja curly brackets:

.. code-block:: html

    <h1 style="background-color: {{ config.background_color }}">
        Hello, {{ config.username }}!
    </h1>

We can even access methods within Jinja:

.. code-block:: python

    class HelloPrompt(Prompt):
        macro = "with_hello"
        external_template = "custom-prompts.html"

        def get_message(self):
            return f"Today's date is { self.print_date() }"

Accessed in Jinja as follows:

.. code-block:: html

    <p> {{ config.get_message() }} </p>

Let’s look once more at the definition of the ``with_hello`` macro:

.. code-block:: html

    {% macro with_hello(config) %}
       <h1>Hello, {{ config.username }}!</h1>

       {{ psynet_prompts.simple(config) }}

    {% endmacro %}

We have already talked about the first part, which pulls information from ``config.username``. The second part calls a macro called ‘``simple``’ from PsyNet’s built-in library of prompts. The source code for PsyNet’s prompt library can be seen in ``psynet/templates/macros/prompt.html``. It is possible to reuse any of these macros when writing your own prompt. The ``simple`` macro simply displays some text to the participant, which is what we use here.

Custom controls
---------------

Custom controls are defined in a similar way. Looking in the same demo, we have the following definition for ``ColorText``:

.. code-block:: python

    class ColorText(Control):
        macro = "color_text_area"
        external_template = "custom-controls.html"

        def __init__(self, color):
            super().__init__()
            self.color = color

        def get_js_page_modules(self):
            return ["/static/color-text.js"]

        @property
        def metadata(self):
            return {"color": self.color}

As before, the class has ``macro`` and ``external_template`` attributes, which
tell PsyNet where to find the class’s Jinja macro. It additionally has a
``color`` instance attribute, which is set in the instance’s constructor
function (``__init__()``). ``get_js_page_modules()`` supplies behavior that
PsyNet activates for each hosting page. Lastly, it has a ``metadata`` method,
which generates optional information saved with the participant’s response.

This ``ColorText`` definition is complemented by the following macro definition in ``custom-controls.html``:

.. code-block:: html

    {% macro color_text_area(config) %}

        <textarea id="text-input" type="text" class="form-control" style="background-color: {{ config.color }}; margin-bottom: 40px;"></textarea>

    {% endmacro %}

The macro remains focused on markup. The corresponding ``static/color-text.js``
file contains the behavior:

.. code-block:: javascript

    export async function activate({root, psynet}) {
        const input = root.querySelector("#text-input");

        function stageResponse() {
            psynet.response.staged.rawAnswer = input.value;
        }

        psynet.setStageResponseHandler(stageResponse);
    }

The ``textarea`` is a standard HTML element corresponding to a text box. Its
customizable background color comes from ``config.color``. The JavaScript
handler extracts the current contents and stages them so that the response is
submitted when the page is exited. PsyNet loads the file as a JavaScript module,
calls ``activate()`` for each hosting page, and resets the response handler
automatically when the page ends.

In some cases we might want to postprocess this response in Python before we save it. This can be achieved by writing a custom ``format_answer`` method for the custom ``Control`` class. For example, if we wanted to capitalize all the responses, we could write something like this:

.. code-block:: python

    def format_answer(self, raw_answer, **kwargs):
        return raw_answer.capitalize()

The ``raw_answer`` argument here corresponds to the data that was saved in ``psynet.stageResponse``. In this example, this data will be a string, corresponding to the contents of the textbox; however, more complex forms of data are supported, for example lists and dictionaries.

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

``js_vars`` should contain data, not functions. If, for example, a prompt needs
to provide a function that its control can call, expose the function through
the page-scoped ``psynet.page`` namespace:

.. code-block:: javascript

    // Prompt setup
    psynet.page.prompt.playStimulus = function () {
        // ...
    };

The control can then call the prompt-owned function:

.. code-block:: javascript

    psynet.page.prompt.playStimulus();

PsyNet resets ``psynet.page`` when the participant moves to another page, so
this does not leave stale functions behind. If the function is not naturally
owned by the prompt or control, use a descriptive shared namespace such as
``psynet.page.myTask`` instead. This makes the dependency explicit without
creating a global function on ``window``.

Managing JavaScript lifecycles
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

PsyNet distinguishes loading code from activating page behavior:

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
common cases requiring cleanup.

The module file itself is imported once and cached by the browser. PsyNet calls
its exported ``activate()`` function again whenever the behavior is used on a
new page. This separation avoids rerunning library top-level code while still
initializing fresh page state.

Managing static files for custom components
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Where a custom Prompt or Control keeps its static files depends on who owns the
component.

**Experiment-local components**

If the component belongs to one experiment, put its files in that experiment's
``static`` directory and use normal experiment URLs:

.. code-block:: python

    class ColorText(Control):
        def get_js_page_modules(self):
            return ["/static/color-text.js"]

This is the simplest workflow for experiment-specific components.

**Components contributed to PsyNet**

Reusable components added to the PsyNet library should own their resources
inside ``psynet/static``. Construct their namespaced URLs with
:func:`psynet.static_resources.package_static_url`:

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

PsyNet already registers this package root, so experiment authors do not need
to copy these files or modify their own ``static`` directories. New built-in
components should use namespaced package URLs rather than adding individual
entries to ``Experiment.extra_files()``.

**Third-party component packages**

Third-party Prompt and Control packages register one static root through the
``psynet.static`` Python entry-point group. PsyNet publishes it under
``/static/packages/<namespace>/`` before dynamic pages are created.

Third-party components also use
:func:`psynet.static_resources.package_static_url` in their resource hooks.
Package authors must include the static root in their wheel and source
distribution.

See :doc:`/developer/package_static_resources` for package layout, entry-point
configuration, custom roots, zip-backed resources, validation, testing, and
wheel-packaging requirements.

Embedded HTML scripts
^^^^^^^^^^^^^^^^^^^^^

Framework macros and some supported page content may still embed classic
``<script>`` tags. PsyNet replays those across in-place transitions; author-owned
external templates should remain markup-only and use ``js_page_code`` /
``js_page_modules`` instead. Embedded ``<script type="module">`` tags are not
supported.

For the full replay/ordering contract, see :doc:`/developer/page_lifecycle`.

The older ``js_links`` and ``scripts`` Page arguments remain supported but are
deprecated. They keep classic linked/inline script semantics and therefore
force a full page reload rather than participating in the managed SPA
JavaScript path (``js_dependencies``, ``js_page_code``, and
``js_page_modules``). Follow :doc:`/whats_new/upgrading_to_psynet_14` to move
them to explicit dependency, page-code, or page-module lifecycles (in Cursor,
``/upgrade-to-psynet-14`` follows that checklist).

Historically, PsyNet also copied each ``js_vars`` key onto ``window``. This
global access is deprecated because in-place timeline transitions reuse the
same browser window across pages. The ``legacy_js_var_globals`` configuration
controls the compatibility behavior:

* ``warn`` (default) keeps legacy access working and warns once for each key.
* ``error`` throws a ``ReferenceError`` that identifies the key and recommends
  the corresponding ``psynet.var`` expression.
* ``off`` does not install legacy global properties.

In ``error`` mode the compatibility property remains present so that reads and
writes can produce the informative error. Consequently, ``typeof legacy_name``
also throws and ``"legacy_name" in window`` remains true. Test availability
with ``"name" in psynet.var`` instead. In ``warn`` mode, assigning the legacy
global preserves historical behavior by changing only the mirrored value; it
does not update ``psynet.var``.

The compatibility accessors are installed only for keys on the active page,
and PsyNet removes them on the next page. PsyNet never replaces a
pre-existing ``window`` property; when a name is already in use, the page value
remains available through ``psynet.var`` and PsyNet logs a warning. Common
colliding names include ``name``, ``status``, ``event``, and ``history`` —
legacy ``window.status`` is the browser status bar string, not your page
variable. Page construction also warns for these well-known collisions.
If another
script replaces and locks a compatibility accessor, PsyNet leaves that property
alone and continues the page transition rather than allowing deprecated
compatibility behavior to interrupt the canonical ``psynet.var`` update.
