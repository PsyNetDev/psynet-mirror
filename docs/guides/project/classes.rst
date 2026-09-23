=================
Classes in PsyNet
=================

Introduction to object-orientation
----------------------------------

PsyNet is an *object-oriented* framework. Object-oriented programming is a popular pattern in Python and many other
programming languages. In object-oriented programming, one defines a collection of *classes*, where a class defines
an abstract category of objects, for example 'users', 'transactions', or 'events'. The programmer then creates and
manipulates instances of these classes, called *objects*. In Python, one can create classes as follows:

.. code-block:: python

    class Person:
        def __init__(self, forename, surname):
            self.forename = forename
            self.surname = surname

        def greet(self):
            raise NotImplementedError


    class EnglishPerson(Person):
        def greet(self):
            print("Hi!")


    class FrenchPerson(Person)
        def greet(self):
            print("Salut!")


Here we created a base class called ``Person``, and two subclasses called ``EnglishPerson`` and ``FrenchPerson``.
Subclasses inherit the structure of their parent class, but also can have additional custom logic.
Here the ``EnglishPerson`` and ``FrenchPerson`` subclasses share the parent concept of forenames and surnames,
but they have customized greeting methods corresponding to their respective languages.

We can then create instances of these classes as follows:

.. code-block:: python

        jeff = EnglishPerson(forename="Jeff", surname="Stevens")
        madeleine = FrenchPerson(forename="Madeleine", surname="de la Coeur")

        print(jeff.surname)  # yields "Stevens"

        jeff.greet()  # yields "Hi!"
        madeleine.greet()  # yields "Salut!"


Working with PsyNet requires fluency in object-oriented programming in Python.
You should aim to be familiar with the following concepts:

- Defining classes
- Defining subclasses
- Defining methods
- Using the ``@property`` decorator
- Using ``super()``
- Creating instances
- Class attributes versus instance attributes

If some of these concepts are new to you, we recommend doing a few relevant online tutorials before proceeding.

PsyNet classes in experiment.py
-------------------------------

If you open a given PsyNet experiment (e.g. ``demos/experiments/mcmcp/experiment.py``) you will typically see a variety of
PsyNet classes. These will be imported from particular PsyNet modules, for example:

.. code-block:: python

    from psynet.page import InfoPage


Page classes like ``InfoPage`` are particularly important for defining the experiment's timeline;
you'll see logic for instructions using this class, for example.

Many PsyNet experiments also include some custom subclasses that inherit from particular PsyNet classes.
For example, you might see something like this:

.. code-block:: python

    from psynet.trial.mcmcp import MCMCPTrial

    class CustomTrial(MCMCPTrial):
        def show_trial(self, ...):
            ...

This allows the experimenter to define a particular kind of trial for their experiment, that inherits certain
functionality from core PsyNet (e.g. the logic of a Markov Chain Monte Carlo with People [MCMCP] experiment)
but also adds custom logic (e.g. displaying a particular kind of stimulus to the participant).

In the next section we'll introduce the core PsyNet classes in proper detail so that you understand how
they all fit together and how they are used in practice.


Overview of key PsyNet classes
------------------------------

Experiment
^^^^^^^^^^

The ``Experiment`` class is the most central class in the PsyNet experiment.
It is defined in ``experiment.py``, the main Python file in your experiment directory.
You define your ``Experiment`` class by subclassing PsyNet's built-in
:class:`~psynet.experiment.Experiment` class. Your custom ``Experiment`` class
must include a definition of the experiment's timeline:

.. code-block:: python

    import psynet.experiment

    class Exp(psynet.experiment.Experiment):
        timeline = join(
            InfoPage(...)
            ...
        )
    )

The ``timeline`` attribute should receive a series of ``Elt`` objects (see below),
with these Elts joined together using the :func:`~psynet.timeline.join` function.

There are various other customizations that can be applied to the experiment via this experiment class,
see the :class:`~psynet.experiment.Experiment` documentation for details.

Participant
^^^^^^^^^^^

The :class:`~psynet.participant.Participant` class is used to represent participants.
Each Participant object has various attributes that are populated during the experiment,
carrying useful information for identifying the participant and recording their experience
during the experiment. For example, ``Participant.id`` gives a unique integer ID for the Participant;
``Participant.creation_time`` tells you when the Participant started the experiment;
``Participant.failed`` tells you if the Participant has been failed, and so on.
For a full list of attributes see the :class:`~psynet.participant.Participant` class documentation.

Most PsyNet experimenters do not interact much with built-in Participant attributes.
Instead, they define custom Participant variables which are used to track state during the experiment.
Participant variables are defined via ``Participant.var``, and can take any name, for example
``Participant.var.custom_variable``. For example, one might write
``print(participant.var.custom_variable)`` to print the current value of ``custom_variable``,
or write ``participant.var.custom_variable = 3`` to set ``custom_variable`` to 3.
For setting Participant variables in lambda functions (see below),
Python syntax doesn't allow you to write expressions like ``participant.var.custom_variable = 3`` directly;
instead we write ``participant.var.set("custom_variable", 3)``.

Elt
^^^

:class:`~psynet.timeline.Elt` objects define the logic of the experiment.
They determine what materials are shown to the participant, how the participant responds to
those materials, how the server processes those responses, and so on.

There are several main types of :class:`~psynet.timeline.Elt` objects:

- :class:`psynet.timeline.Page` objects determine the web pages that are presented to the participant;
- :class:`psynet.timeline.PageMaker` objects generate Pages on-demand;
- :class:`psynet.timeline.CodeBlock` objects define code that runs in between Pages;
- Control flow functions determine how these elements are sequenced within the timeline.

We will now introduce each of these concepts in a little more detail.
See their dedicated documentation for full information.

Page
""""

:class:`psynet.timeline.Page` objects determine the web pages that are presented to the participant.
The base :class:`psynet.timeline.Page` class allows you to define a Page using a custom Jinja template.
Jinja is a templating engine that is popular for creating websites with a Python back-end.
For example, here's what the template for :class:`psynet.timeline.SuccessfulEndPage` currently
looks like:

.. code-block:: html

    {% extends "timeline-page.html" %}

    {% block main_body %}
        That's the end!
        {% if experiment.show_reward %}
            {% include "final-page-rewards.html" %}
        {% endif %}
        Thank you for taking part.

        <p class="vspace"></p>
        <p>
            Click Finish to finalize the session.
        </p>
        <p class="vspace"></p>

        <button type="button" id="next-button" class="btn btn-primary btn-lg" onClick="dallinger.submitAssignment();">Finish</button>
    {% endblock %}

Most PsyNet users don't work with these Jinja templates directly. Instead, they use PsyNet helper classes
that create these templates programmatically.

The simplest case is the :class:`~psynet.page.InfoPage`. The Info Page simply displays some information to
the participant, and does not request any response. An Info Page can be created like this:

.. code-block:: python

    from psynet.page import InfoPage

    InfoPage("Welcome to the experiment!", time_estimate=5)

The ``time_estimate`` parameter tells PsyNet how many seconds the participant is expected to spend
on the page. This is a common feature of PsyNet Pages. This time estimate is used to manage
the progress bar and to compensate participants pro rata for their time on the experiment.

More often than not, experimenters eventually end up using the :class:`~psynet.modular_page.ModularPage`
class for their experiment implementations. The Modular Page is a powerful way of defining pages
that combines two basic elements: the :class:`~psynet.modular_page.Prompt` and the
:class:`~psynet.modular_page.Control`. The Prompt defines what is presented to the participant,
whereas the Control defines their interface for responding. The PsyNet library contains many
built-in implementations of Prompts and Controls, but it's perfectly possible to create your own
Prompts or Controls for a given experiment, and then reuse them in future experiment implementations.

Here's an example of a Modular Page which combines an :class:`~psynet.modular_page.AudioPrompt`
with a :class:`~psynet.modular_page.PushButtonControl`:

::

    from psynet.modular_page import ModularPage, AudioPrompt, PushButtonControl

    ModularPage(
        "question_page",
        AudioPrompt("https://my-server.org/stimuli/audio.wav", "Do you like this audio file?"),
        PushButtonControl(["Yes", "No"]),
        time_estimate=self.time_estimate,
    )

The other important kind of page is the :class:`~psynet.page.EndPage`. An EndPage is used to mark
the end of an experiment. There are two commonly used types of End Pages, triggering different
end-of-experiment behavior:
the :class:`~psynet.page.SuccessfulEndPage` and the :class:`~psynet.page.UnsuccessfulEndPage`.
The latter is typically used when the participant fails some kind of performance check
and is made to finish the experiment early.

Page Maker
""""""""""

:class:`psynet.timeline.PageMaker` objects generate Pages on-demand.
The resulting pages can be dynamic, incorporating content that depends on the current
state of the participant or the experiment.

.. code-block:: python

    from psynet.timeline import PageMaker

    PageMaker(lambda participant: InfoPage(
        f"Welcome to the experiment, {participant.var.name}.",
        time_estimate=5
    ))

The Page Maker takes a function as its primary argument. Typically we use a lambda function,
which allows us to define the Page Maker content in-line. However, it's also possible
to pass a named function which is defined or imported earlier in the code.

The Page Maker function can optionally take a variety of arguments, of which ``participant``
is one. To find the full list of available arguments, see the documentation.

Warning: The Page Maker function will be called more than once for a given page,
including whenever the page is refreshed. It is important therefore that the code
is **idempotent**, i.e. calling it multiple times should have the same effect as calling
it just once. It is a bad idea to incorporate random functions in this code.

Code Block
""""""""""

:class:`psynet.timeline.CodeBlock` objects define code that runs in between Pages.
They are similar to Page Makers, but do not return pages. Like Page Makers,
they take a function as the primary argument, which can optionally take a variety of arguments
such as ``participant``.
Unlike Page Makers, they only ever run once, so they're a safe place to put random functions.

.. code-block:: python

    from psynet.timeline import CodeBlock

    CodeBlock(lambda participant: participant.var.seed = random.randint(0, 5))


Control Flow
^^^^^^^^^^^^

Control flow functions determine how these elements are sequenced within the timeline.
They are currently not implemented as classes, but rather as pure functions;
we might change this in the future though to achieve a cleaner syntax.

While Loop
""""""""""

A While Loop repeats a particular series of Elts while a particular condition is
satisfied. The condition is specified as a function that is called with various
optional arguments, most commonly ``participant``.

.. code-block:: python

    while_loop(
        "example_loop",
        lambda participant: participant.answer == "Yes",
        Module(
            "loop",
            ModularPage(
                "loop_nafc",
                Prompt("Would you like to stay in this loop?"),
                control=PushButtonControl(["Yes", "No"], arrange_vertically=False),
                time_estimate=3,
            ),
        ),
        expected_repetitions=3,
    )


For Loop
""""""""

A For Loop instructs PsyNet to loop over the values of a list,
and using these values to dynamically generate Elts in the manner of a Page Maker.
The following example uses a For Loop to create a series of Info Pages
counting from 1 to 3:

.. code-block:: python

    from psynet.timeline import for_loop
    from psynet.page import InfoPage

    for_loop(
        label="for_loop_1",
        iterate_over=lambda: [1, 2, 3],
        logic=lambda number: InfoPage(f"{number} / 3"),
        time_estimate_per_iteration=5,
    )

For Loops can also include random functions to generate their seed lists.
This provides a straightforward way to randomize the order of material
presented to Participants. For example:

.. code-block:: python

    import random
    from psynet.timeline import for_loop
    from psynet.page import InfoPage

    for_loop(
        label="for_loop_2",
        iterate_over=lambda: random.sample(range(10), 3),
        logic=lambda number: InfoPage(f"Stimulus {number}"),
        time_estimate_per_iteration=5,
    )


Conditional
"""""""""""

A Conditional construct is used to branch Timeline logic according to whether or not
a given Condition is satisfied. The Condition is programmed as a function,
analogous to the function for the While Loop,
which should return either True or False.
If the function returns True, then the logic follows the first branch;
if it returns False, the logic follows the second branch (if such a branch
was specified). For example:

.. code-block:: python

    from psynet.timelime import conditional
    from psynet.page import InfoPage

    conditional(
        "like_chocolate",
        lambda participant: participant.answer == "Yes",
        InfoPage("It's nice to hear that you like chocolate!", time_estimate=5),
        InfoPage(
            "I'm sorry to hear that you don't like chocolate...",
            time_estimate=3,
        ),
    )

Switch
""""""

A Switch construct is a more powerful version of the Conditional construct
that supports arbitrary numbers of branches. As before, the experimenter
writes a function that is evaluated once the Participant reaches the Switch,
but this time the function can return an arbitrary Python object
(technically, this object must be 'hashable', which includes things like
strings, integers, and floats).
The experimenter then also provides a dictionary of branches,
where each branch is a piece of Timeline logic,
and the branches are keyed by possible outputs of the function.
PsyNet sends the Participant to the branch that's keyed by the output
of the function. For example:

.. code-block:: python

    from psynet.timeline import switch

    switch(
        "color",
        lambda participant: participant.answer,
        branches={
            "Red": InfoPage("You selected 'red'.", time_estimate=1),
            "Green": InfoPage("You selected 'green'.", time_estimate=1),
            "Blue": InfoPage("You selected 'blue'.", time_estimate=1),
        },
    )

Module
^^^^^^

A :class:`~psynet.timeline.Module` is a construct for organizing Timeline logic
into standalone blocks. For example, if we create a pre-screening test that involves
asking the Participant some spelling questions, we might make this pre-screening test a Module
and then distribute it in a helper package.

Modules are useful for tracking the Participants' journey through the experiment.
For example, the Dashboard contains a useful visualization that shows how many Participants
have started and finished each Module.

Modules are also useful for encapsulating Participant state. This means that variables don't
unintentionally leak from one part of the Experiment to the other, something which otherwise
can produce subtle bugs. To take advantage of this feature, the experimenter avoids setting
participant variables in this way (which sets variables that are 'global' to the entire timeline):

.. code-block:: python

    participant.var.custom_variable = 3

and instead sets participant variables on the current module state:

.. code-block:: python

    participant.module_state.var.custom_variable = 3

Modules can be used as the base class for object-oriented hierarchies of Timeline constructs.
For example, the :class:`~psynet.trial.main.TrialMaker` class is a special kind of Module class
that implements logic for administering Trials to the participant (see below).
One day we might similarly create a PreScreen class for implementing pre-screening tests.

Modules are also useful for managing Assets, as described below.

Asset
^^^^^

An :class:`~psynet.asset.Asset` is some kind of file (or collection of files) that
is referenced during an experiment. These might for example be video files that we play
to the participant, or perhaps audio recordings that we collect from the participant.

The API for Assets is powerful but complex. PsyNet provides many patterns for creating Assets
and for accessing them within an experiment. These are documented in detail in the
Assets chapter. For now, we will just illustrate the simplest of these patterns,
which is to define an Asset at the Module level.

You can create an asset within a Module by passing it to the Module constructor's
``assets`` argument. This argument expects a dictionary. For example:

.. code-block:: python

    import psynet.experiment
    from psynet.asset import CachedAsset

    class Exp(psynet.experiment.Experiment):
        timeline = join(
            Module(
                "my_module",
                my_pages(),
                assets={
                    "logo": CachedAsset("logo.svg"),
                }
            )
        )

You can then access this asset within your module as follows:

.. code-block:: python

    from psynet.timeline import PageMaker

    def my_pages():
        return PageMaker(
            lambda assets: ModularPage(
                "audio_player",
                ImagePrompt(assets["logo"], "Look at this image."),
                time_estimate=5,
            )
        )

Note how the asset must be accessed within a ``PageMaker``,
and is pulled from the optional ``assets`` argument that we included
in the lambda function. This ``assets`` argument is populated with a dictionary
of assets from the current module.


Trial
^^^^^

The :class:`~psynet.trial.main.Trial` class represents a single Trial within the Experiment.
A Trial typically involves administering some kind of stimulus to the Participant
and recording their response.

The PsyNet experimenter typically creates their own Trial subclass as part of the
Experiment implementation. This might look something like this:

.. code-block:: python

    from psynet.trial.main import Trial

    class RateTrial(Trial):
        time_estimate = 3

        def show_trial(self, experiment, participant):
            word = self.definition["word"]

            return ModularPage(
                "rate_trial",
                Markup(f"How happy is the following word: <strong>{word}</strong>"),
                PushButtonControl(
                    ["Not at all", "A little", "Very much"],
                ),
            )

This minimal example of a custom trial class has two important elements:
``time_estimate`` and ``show_trial``.

The ``time_estimate`` attribute tells PsyNet how long an average Trial is expected to last, in seconds.
This is used to construct progress bars and to reward participants for their progress through
the experiment.

The ``show_trial`` method then defines how the Trial is displayed to the Participant.
The ``show_trial`` method method should refer to the Trial's ``definition`` attribute,
which will be a dictionary containing defining information about the Trial,
typically providing all the information required to uniquely determine the stimulus
that will be presented to the Participant.
Ordinarily the ``show_trial`` method should return a single page,
however, it's also possible to construct more complex multi-page Trials by returning
a series of Elts wrapped in a call to :func:`~psynet.timeline.join`.

The simplest way to use a custom Trial class in an experiment is by using the
:meth:`~psynet.trial.main.Trial.cue` method. This inserts a Trial in the timeline with a
given definition, with this definition provided as an argument to ``cue``.
The following example combines ``Trial.cue`` with a ``for_loop`` to deliver three
trials with randomly sampled words:

.. code-block:: python

    for_loop(
        label="Randomly sample three words from the word list",
        iterate_over=lambda: random.sample(WORDS, 3),
        logic=lambda word: RateTrial.cue(
            {
                "word": word,
            }
        ),
        time_estimate_per_iteration=3,
    )

Trials used in this way can also incorporate Assets.
However, this approach is only recommended for
External Assets (i.e. Assets that are hosted externally on a web server)
or for On-Demand Assets (i.e. Assets that are generated on-demand).

.. code-block:: python

    audio_ratings = Module(
        "audio_ratings",
        for_loop(
            label="Deliver 5 trials with randomly sampled parameters",
            iterate_over=lambda: [
                {
                    "frequency_gradient": random.uniform(-100, 100),
                    "start_frequency": random.uniform(-100, 100),
                }
                for _ in range(5)
            ],
            logic=lambda definition: RateTrial.cue(
                definition,
                assets={
                    "audio": OnDemandAsset(
                        function=synth_stimulus,
                        extension=".wav",
                    ),
                },
            ),
            time_estimate_per_iteration=RateTrial.time_estimate,
        ),
    )

Adaptive or generated trials can use ``on_trial_created`` to create related
database records in the same transaction as the cued trial. Pass request-local
provenance through ``creation_context`` and assign ORM relationships in the
callback, because the trial's database ID may not exist until the transaction
flushes:

.. code-block:: python

    from dallinger import db


    def record_decision(trial, creation_context):
        decision = AdaptiveDecision(
            snapshot_id=creation_context["snapshot_id"],
        )
        decision.trial = trial
        db.session.add(decision)

    RateTrial.cue(
        definition={"item_id": "item-1"},
        on_trial_created=record_decision,
        creation_context={"snapshot_id": 12},
    )

See ``demos/features/trial_cue_adaptive`` for a complete participant-level
staircase that uses this pattern with ``while_loop``.


Node
^^^^

If your experiment design requires the Participant session to depend on what happened in previous
Participant sessions (e.g. if you want to ensure that every stimulus receives exactly the same number
of ratings), or if it requires pregenerating Assets (which normally is sensible if your Assets
are slow to generate), then you will likely want to take advantage of Nodes.

A :class:`~psynet.trial.main.Node` is a PsyNet database construct that is used for organizing Trials.
In particular, it can be conceptualized as a *parent* for Trials,
storing important parameters that are used to define its child Trials,
as well as storing Assets that the Trials can make use of.

Nodes are useful for enacting interactions between Participant sessions because they exist
independently of individual Participants.
In a non-adaptive experiment, a Node would typically represent a stimulus that is to be shown
to multiple Participants. PsyNet can then balance stimulus selection by making sure that each
Node ends up receiving the same number of Trials.
In an adaptive experiment (e.g. Gibbs Sampling with People), a Node can instead represent the
current state of the experiment (or, more specifically, the state of a particular chain within an experiment).

Nodes are useful for asset management because they are typically created before the Participant comes along.
This means they can have a headstart with asset generation, meaning that the Participant isn't kept waiting
in the meantime. Moreover, since the same Node can spawn many Trials, the same Assets can be reused
many times, instead of having to be regenerated for each new Trial.

The simplest way to use Nodes in an experiment is to create a collection of Nodes in experiment.py
and use these for your Trials. Here's an example from a PsyNet demo:

.. code-block:: python

    def synth_stimulus(path, frequencies):
        synth_prosody(vector=frequencies, output_path=path)

    NODES = [
        Node(
            definition={
                "frequency_gradient": frequency_gradient,
                "start_frequency": start_frequency,
                "frequencies": [start_frequency + i * frequency_gradient for i in range(5)],
            },
            assets={
                "stimulus": CachedFunctionAsset(
                    function=synth_stimulus,
                    extension=".wav",
                )
            },
        )
        for frequency_gradient in [-100, -50, 0, 50, 100]
        for start_frequency in [-100, 0, 100]
    ]


    class RateTrial(Trial):
        time_estimate = 5

        def show_trial(self, experiment, participant):
            return ModularPage(
                "audio_rating",
                AudioPrompt(
                    self.node.assets["stimulus"],
                    text="How happy is the following word?",
                ),
                PushButtonControl(
                    ["Not at all", "A little", "Very much"],
                ),
            )


    audio_ratings = Module(
        "audio_ratings",
        for_loop(
            label="Deliver 5 random samples from the stimulus set",
            iterate_over=lambda nodes: random.sample(nodes, 5),
            logic=lambda node: RateTrial.cue(node),
            time_estimate_per_iteration=RateTrial.time_estimate,
            expected_repetitions=5,
        ),
        nodes=NODES,
    )

Here the Nodes are used to define a stimulus set that explores a factorial combination of two variables,
``frequency_gradient`` and ``start_frequency``. Each Node has an Asset, specifically a Cached Function Asset,
defined as a function that gets its arguments from the Node's definition. When the experiment is deployed,
PsyNet will automatically generate the full set of Assets if it doesn't find them in its cache.

Note how the Nodes are passed to the ``Module`` call. This ensures that the Nodes are recognized by
the Experiment, and it associates the Nodes with the ``"audio_ratings"`` module. Now code within that module
(e.g. Page Makers, For Loops) can access those Nodes within lambda functions, as in the example above.
These nodes can be used to create Trials by using the ``Trial.cue`` method, as in the example above.
The Trial then inherits the Node's definition (in this case ``frequency_gradient``, ``start_frequency``,
and ``frequencies``); the Node's assets then can be accessed through ``trial.node.assets``.

It is also possible to create Nodes during the Experiment using similar techniques,
but at the time of writing we haven't got a demo for this yet. Watch this space.

Trial maker
^^^^^^^^^^^

The previous sections described how trial-based experiments can be implemented using the ``Trial.cue`` method.
With this approach, the experimenter has to define the logic of choosing Trials themselves
using constructs such as For Loops.
However, such logic can get complex and repetitive. PsyNet therefore provides some built-in constructs
that cover a variety of use cases, including:

- Static experiments, where Trials are generated from a pre-specified collection of Nodes,
  and Node selection is balanced to ensure that Trials accumulate evenly across Nodes;
- Serial reproduction, where a participant imitates a stimulus, another participant imitates that imitation,
  and so on for many generations;
- Markov Chain Monte Carlo with People, a procedure which coordinates many two-alternative forced-choice trials
  into a process which stochastically samples from a (possibly high-dimensional) stimulus space;
- Gibbs Sampling with People, a variant of Markov Chain Monte Carlo with People based on a continuous
  slider-based task.

These constructs are implemented as Trial Makers (:class:`psynet.trial.main.TrialMaker`).
A Trial Maker is a special kind of Module that provides logic for administering Trials within an experiment.
Experiments using a Trial Maker typically implement custom Trial classes, as before.
Complex experiments (e.g. chain-based) experiments will typically also implement a custom Node class.
Then, instead of using some combination of For Loops with ``Trial.cue``, the experimenter instead
inserts a Trial Maker instance into the Timeline. This Trial Maker might look something like this:

.. code-block:: python

    AnimalTrialMaker(
        id_="animals",
        trial_class=AnimalTrial,
        nodes=nodes,
        expected_trials_per_participant=6,
        max_trials_per_block=2,
        allow_repeated_nodes=True,
        balance_across_nodes=True,
        check_performance_at_end=True,
        check_performance_every_trial=False,
        target_n_participants=50,
        target_trials_per_node=None,
        recruit_mode="n_participants",
        n_repeat_trials=3,
    )

This Trial Maker has several features as determined by the options that have been passed to it:

- PsyNet will expect each participant to take about 6 trials;
- Each participant will take no more than 2 trials in each block;
- Each participant is in theory allowed to take multiple Trials from the same Node;
- Node selection will be balanced, meaning that Trials should accumulate evenly across Nodes;
- PsyNet will check the participant's performance at the end of the Trial Maker, and potentially terminate
  their session if they perform too badly;
- The Trial Maker will prompt PsyNet to keep recruiting until 50 participants have been recruited;
- The Trial Maker will administer three Trials at the end that are repeats of three randomly selected
  Trials from earlier in the Trial Maker; the results from these Trials can be used to evaluate the
  participant's test-rest reliability.

Explore documentation for specific Trial Maker classes as well as PsyNet demos for more information.

Connection to SQLAlchemy classes
--------------------------------

Several PsyNet classes are database-backed, which means that their objects are represented as rows
in a database. This enables object states to be communicated across servers and persisted
throughout the duration of the experiment. Examples of database-backed classes include:

- Participants
- Trials
- Nodes
- Assets
- Error Logs
- Asynchronous Processes

This database integration is implemented via SQLAlchemy. SQLAlchemy is a powerful Python package
that creates a mapping between Python objects and database elements.

In most PsyNet usage you do not need to worry much about the mechanics of this database integration.
As long as you work with pre-existing object attributes and variable stores
(e.g. ``participant.var.my_variable``), then your changes should propagate and persist just
as you expect. However in advanced usage you will eventually want to understand more about
how this integration works. We will soon include a tutorial on SQLAlchemy usage into this
documentation website.

Connection to Dallinger classes
-------------------------------

As you may know, PsyNet is built on an earlier platform called Dallinger which deals with many
of the lower-level aspects of server management and experiment deployment.
Dallinger has its own collection of database-backed classes which are designed with a particular
focus on cultural simulation experiments, with names such as
Info, Vector, Transmission, Node, and so on.

Several PsyNet classes are built on some of these pre-existing Dallinger classes.
For example, Trials are built on Infos, PsyNet Nodes are built on Dallinger Nodes,
and PsyNet Nodes are organized into Networks, just like in Dallinger.
The motivation for this inheritance is that it allows PsyNet to share some features
with Dallinger, in particular as regards network visualizations in the dashboard.
However, it does mean that in a few places in the code and the database
you might see the word Info used when you were expecting to see the word Trial. We are
working to eliminate these instances to make the abstraction more intuitive.
