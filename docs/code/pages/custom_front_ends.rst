Custom front ends
=================

Custom front ends are usually written as custom prompts and controls for
modular pages. A *prompt* displays a stimulus to the participant, and a
*control* gives the participant a way to respond. The
``demos/features/modular_page`` demo defines the custom prompt and control
used on this page.

In-place timeline transitions
-----------------------------

PsyNet uses in-place timeline transitions by default. When a participant
advances from one timeline page to the next, PsyNet swaps the page content
inside the existing browser document instead of reloading the whole page.
Custom pages and components must therefore follow the fragment-template
contract described below.

Experiments that need the old full-page reload behavior can set
``inplace_timeline_transitions = false`` in ``config.txt``. This legacy path is
kept for backwards compatibility; new and migrated custom pages should be
written for in-place transitions. To migrate an existing experiment, follow
:doc:`/whats_new/upgrading_to_psynet_14`. The complete rendering, activation,
cleanup and failure contract is documented in
:doc:`/developer/page_lifecycle`.

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

This style works only with the legacy full-page reload path, where
``inplace_timeline_transitions = false`` is set explicitly.

With the default in-place transitions, custom pages provide only the contents
of the page's ``main_body`` block, using ``template_fragment_path`` or
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
``psynet-template-data``. A fragment template must not include ``{% extends
"timeline-page.html" %}``, ``{% block main_body %}``, ``<html>``, ``<head>``,
or ``<body>``.

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

``DOMContentLoaded`` does not fire for each page activation, because in-place
transitions do not reload the browser document. Put page setup in a
``js_page_modules`` ``activate()`` function or in short ``js_page_code``. Use
trial events such as ``pageReady`` only for timing gates, for example
auto-advance.

Template validation
~~~~~~~~~~~~~~~~~~~

With the default ``inplace_timeline_transitions = true``, PsyNet raises an
error if a custom page uses a complete template or if author-provided template
content includes patterns that are incompatible with the in-place lifecycle.
With ``inplace_timeline_transitions = false``, PsyNet keeps legacy templates
working but may warn about patterns that should be migrated.

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
  ``js_page_modules`` for substantial or reusable behavior.
* Template ``<script src=...>`` tags. Use ``js_dependencies`` (load-once
  libraries) or ``js_page_modules`` (per-page modules) according to the
  intended lifecycle.
* Template ``<style>`` blocks. Prefer a ``static`` stylesheet via ``css_links``
  (or ``get_css_links()``); use ``css`` / ``get_css()`` only for small
  generated snippets.
* Template stylesheet ``<link rel="stylesheet">`` tags. Use the ``css_links``
  argument (or ``get_css_links()``) instead.

A validation error in the default mode means that the page has not yet been
migrated to the fragment-template contract. The same page may still work in
legacy reload mode.

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

The browser imports and caches each module file once. PsyNet calls its exported
``activate()`` function again whenever the behavior is used on a new page, so
library top-level code does not rerun while page state is still initialized
fresh.

Managing static files for custom components
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Experiment-local components**

A component that belongs to one experiment keeps its files in that
experiment's ``static`` directory and uses normal experiment URLs:

.. code-block:: python

    class ColorText(Control):
        def get_js_page_modules(self):
            return ["/static/color-text.js"]

**Components in a Python package**

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
Package layout, entry-point configuration, custom roots, zip-backed
resources, validation, testing, and wheel packaging are covered in
:doc:`/developer/package_static_resources`.

Embedded HTML scripts
^^^^^^^^^^^^^^^^^^^^^

Framework macros and some supported page content may still embed classic
``<script>`` tags. PsyNet replays those across in-place transitions (see
:doc:`/developer/page_lifecycle` for the replay and ordering contract).
Author-owned external templates should contain only markup and use
``js_page_code`` / ``js_page_modules`` instead. Embedded
``<script type="module">`` tags are not supported.

The older ``js_links`` and ``scripts`` page arguments remain supported but are
deprecated. They keep classic linked and inline script semantics and therefore
force a full page reload rather than using ``js_dependencies``,
``js_page_code``, and ``js_page_modules``.
:doc:`/whats_new/upgrading_to_psynet_14` explains how to move them to explicit
dependency, page-code, or page-module lifecycles (in Cursor,
``/upgrade-to-psynet-14`` follows that checklist).

Legacy global ``js_vars``
^^^^^^^^^^^^^^^^^^^^^^^^^

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
global changes only the mirrored value; it does not update ``psynet.var``.

The compatibility accessors are installed only for keys on the active page,
and PsyNet removes them on the next page. PsyNet never replaces a
pre-existing ``window`` property; when a name is already in use, the page value
remains available through ``psynet.var`` and PsyNet logs a warning. Page
construction also warns for well-known colliding names such as ``name``,
``status``, ``event``, and ``history`` (``window.status`` is the browser status
bar string, not your page variable). If another script replaces and locks a
compatibility accessor, PsyNet leaves that property alone and continues the
page transition.

Custom routes
-------------

Pages normally send information to the server by submitting an answer and
moving to the next page, which records the answer in the database. To exchange
data with the server at other times without leaving the page, define a custom
HTTP route in ``experiment.py`` and call it from the page's JavaScript.

Defining a route
~~~~~~~~~~~~~~~~

Decorate a class method of the experiment with ``experiment_route``:

.. code-block:: python

    from datetime import datetime

    from dallinger.experiment import experiment_route

    import psynet.experiment


    class Exp(psynet.experiment.Experiment):
        @experiment_route("/current_date_and_time", methods=["GET"])
        @classmethod
        def current_date_and_time(cls):
            now = datetime.now()
            return {
                "date": now.strftime("%d/%m/%Y"),
                "time": now.strftime("%H:%M:%S"),
            }

In debug mode, this route is available at
``http://localhost:5000/current_date_and_time``. A route can return a string,
a tuple, or a dictionary.

Routes are class methods (or static methods), so they have no experiment
instance. To read or write experiment variables, get one with
:func:`~psynet.experiment.get_experiment`, and call ``db.session.commit()`` to
persist changes:

.. code-block:: python

    import random

    from dallinger import db

    from psynet.experiment import get_experiment


    class Exp(psynet.experiment.Experiment):
        @experiment_route("/random", methods=["GET"])
        @classmethod
        def random_route(cls):
            x = random.randint(1, 100)
            get_experiment().var.random = x
            db.session.commit()
            return {"value": x}

Calling a route from JavaScript
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Call the route from page JavaScript, for example inside an ``activate()``
function, with ``dallinger.get()``:

.. code-block:: javascript

    dallinger.get("/current_date_and_time").done((resp) => {
        console.log(resp.date, resp.time);
    });

The request is asynchronous, so the result is handled in the callback passed to
``.done()``, which runs once the route returns.

Passing input data
~~~~~~~~~~~~~~~~~~

The simplest way to pass input to a route is as URL parameters, as in
``http://localhost:5000/add?x=5&y=3``. Read them with ``request.values``. URL
parameters are always strings, so convert them to numbers where needed:

.. code-block:: python

    from flask import request


    class Exp(psynet.experiment.Experiment):
        @experiment_route("/add", methods=["GET"])
        @classmethod
        def add(cls):
            x = float(request.values["x"])
            y = float(request.values["y"])
            return {"result": x + y}

``dallinger.get()`` takes the parameters as an object:

.. code-block:: javascript

    dallinger.get("/add", {x: 5, y: 3}).done((resp) => {
        console.log(resp.result);
    });

Saving data with POST routes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

By convention, GET routes only retrieve information and do not change the
server's state. Routes that save information use ``methods=["POST"]`` and are
called with ``dallinger.post()``. They must call ``db.session.commit()`` after
changing database objects. Routes are publicly accessible, so check the
participant's ``unique_id`` before changing their data. A route that does not
return data conventionally returns ``success_response()``:

.. code-block:: python

    from dallinger import db
    from dallinger.experiment_server.utils import error_response, success_response
    from flask import request

    from psynet.participant import Participant


    class Exp(psynet.experiment.Experiment):
        @experiment_route("/set_dollars", methods=["POST"])
        @classmethod
        def set_dollars(cls):
            participant = Participant.query.filter_by(
                id=int(request.values["participant_id"])
            ).one()
            if participant.unique_id != request.values["unique_id"]:
                return error_response(error_text="Invalid participant")
            participant.var.dollars = float(request.values["dollars"])
            db.session.commit()
            return success_response()

.. code-block:: javascript

    dallinger.post("/set_dollars", {
        participant_id: psynet.participantId,
        unique_id: psynet.uniqueId,
        dollars: 1.5,
    });

Nested dictionaries and lists, and blobs such as raw media files, can also be
sent to the server. PsyNet's own response submission does this:
``submitGenericResponse`` in ``psynet/resources/scripts/psynet.js`` sends a
JSON field plus blobs as ``FormData``, and ``route_response`` in
``psynet/experiment.py`` reads them on the server.
