.. |br| raw:: html

   <br />

PsyNet's classes and SQLAlchemy
===============================

Object orientation
------------------

PsyNet is an *object-oriented* framework. A *class* defines an abstract
category of objects, for example users, transactions, or events, and the
program creates and manipulates instances of these classes, called *objects*.
In Python, classes are defined like this:

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


    class FrenchPerson(Person):
        def greet(self):
            print("Salut!")

``Person`` is a base class, and ``EnglishPerson`` and ``FrenchPerson`` are
subclasses. Subclasses inherit the structure of their parent class and can add
custom logic: here both share forenames and surnames, but each has its own
greeting. Instances are created like this:

.. code-block:: python

    jeff = EnglishPerson(forename="Jeff", surname="Stevens")
    madeleine = FrenchPerson(forename="Madeleine", surname="de la Coeur")

    print(jeff.surname)  # prints "Stevens"

    jeff.greet()  # prints "Hi!"
    madeleine.greet()  # prints "Salut!"

Working with PsyNet requires familiarity with these Python concepts:

- Defining classes
- Defining subclasses
- Defining methods
- Using the ``@property`` decorator
- Using ``super()``
- Creating instances
- Class attributes versus instance attributes

If some of these are new to you, work through a few online tutorials before
continuing.

PsyNet classes in experiment.py
-------------------------------

An ``experiment.py`` imports classes from PsyNet modules, for example:

.. code-block:: python

    from psynet.page import InfoPage

Some are used directly, like ``InfoPage`` in the timeline. Others are
subclassed to add experiment-specific logic while inheriting PsyNet's, for
example a trial class that displays a particular stimulus within PsyNet's
Markov Chain Monte Carlo with People (MCMCP) procedure:

.. code-block:: python

    from psynet.trial.mcmcp import MCMCPTrial

    class CustomTrial(MCMCPTrial):
        def show_trial(self, experiment, participant):
            ...

The main classes are:

- :class:`~psynet.experiment.Experiment`: every experiment defines one
  subclass of it in ``experiment.py``, with at least a ``timeline``
  attribute. See :doc:`/code/writing_a_timeline`.
- :class:`~psynet.timeline.Elt` and its subclasses, the building blocks of
  the timeline: pages, page makers, code blocks, and modules, combined with
  control flow functions. See :doc:`/code/writing_a_timeline` and
  :doc:`/code/writing_pages`.
- :class:`~psynet.participant.Participant`, described below.
- :class:`~psynet.trial.main.Trial`, :class:`~psynet.trial.Node`, and
  :class:`~psynet.trial.main.TrialMaker`, which define and administer
  trials. See :doc:`/code/writing_a_trial_maker`.
- :class:`~psynet.asset.Asset`, for files used or collected during the
  experiment. See :doc:`/code/using_stimuli` and :doc:`/code/trials/assets`.

Participant
^^^^^^^^^^^

A :class:`~psynet.participant.Participant` object has built-in attributes that
PsyNet fills in during the experiment, for example ``participant.id`` (a
unique integer), ``participant.creation_time`` (when the participant started),
and ``participant.failed``. See the class documentation for the full list.

Experiment code mostly uses custom participant variables instead, stored in
``participant.var`` under any name:

.. code-block:: python

    print(participant.var.custom_variable)
    participant.var.custom_variable = 3

Python does not allow assignments inside a lambda, so there use
``participant.var.set("custom_variable", 3)``.

Variables in ``participant.var`` are shared across the whole timeline. To keep
a variable local to the current module, so that it cannot clash with a
variable of the same name elsewhere, store it on the module state instead:

.. code-block:: python

    participant.module_state.var.custom_variable = 3

Database-backed classes
-----------------------

Several PsyNet classes are database-backed: their objects are rows in a
database, so their state is shared across server processes and persists for
the whole experiment. They include participants, trials, nodes, networks,
assets, error logs, and asynchronous processes. The mapping between Python
objects and database rows is implemented with SQLAlchemy.

As long as you work with existing attributes and variable stores (for example
``participant.var.my_variable``), changes propagate and persist without extra
work. The rest of this page covers what you need for more advanced use:
querying, custom columns, and updating or creating objects directly.

PsyNet is built on an earlier platform, Dallinger, which handles much of the
server management and deployment. Dallinger has its own database-backed
classes, designed for cultural-evolution experiments, with names such as
Info, Vector, Transmission, Node, and Network. PsyNet's participants, nodes,
and networks are built on the corresponding Dallinger classes, which lets
PsyNet reuse Dallinger features such as the network visualizations in the
dashboard. PsyNet also supports creating and manipulating Dallinger objects
directly; see the
`Dallinger documentation <https://dallinger.readthedocs.io/latest/classes.html>`_.

Tables and objects
------------------

PsyNet stores its data in a PostgreSQL database
(`about PostgreSQL <https://www.postgresql.org/about/>`_). SQL databases store
data in *tables*, each like a spreadsheet, with columns (*fields*) and rows
(*records*). Each record represents an object, and each column is an
attribute of those objects, with a name and a data type such as integer,
string, or float. Tables usually have an integer ID column that indexes the
records. For example:

================================ =================  ====================   ===================
person_id (integer, primary key) forename (string)  family_name (string)   occupation (string)
================================ =================  ====================   ===================
1                                James              Edwards                Forestry manager
2                                Edwards            Tolley                 IT consultant
3                                Laura              Harrison               Handyman
4                                Eleanor            Ashby                  Sales assistant
================================ =================  ====================   ===================

SQLAlchemy maps each record to a Python object, so fields can be read and
written as attributes:

.. code-block:: python

    james = Person.query.filter_by(forename="James").one()

    # Reading fields
    assert james.id == 1
    assert james.family_name == "Edwards"

    # Writing fields
    james.occupation = "unemployed"

To browse the tables, use a database viewer such as Postico:

.. figure:: /_static/images/developer/sql_alchemy/postico.png
  :width: 800
  :align: center

|br|

Defining SQLAlchemy classes
---------------------------

Subclassing a database-backed PsyNet class, such as a trial class, defines a
new SQLAlchemy class:

.. code-block:: python

    from psynet.trial.gibbs import GibbsTrial

    class CustomTrial(GibbsTrial):
        def show_trial(self, experiment, participant):
            ...

All class names within an experiment must be unique, including classes
imported from other packages. Unique names also make data analysis easier.

Querying objects
----------------

A query loads objects from the database, like an SQL ``SELECT`` statement.
This returns all ``CustomTrial`` objects:

.. code-block:: python

    trials = CustomTrial.query.all()

The result can be processed like any list, for example to sum the performance
rewards of trials from participants called James:

.. code-block:: python

    james_trials = [t for t in trials if t.participant.var.name == "James"]
    james_performance_reward = sum(t.performance_reward for t in james_trials)

This is fine for small numbers of objects, but two costs grow quickly:

#. **Each query has a significant fixed overhead.** SQLAlchemy compiles an SQL
   command, sends it to the database, waits for the response, and parses the
   result. Loading 200 records in one query is much faster than loading them
   in 200 queries.
#. **Filtering in Python is slow.** The first access to an attribute of an
   SQLAlchemy object takes a few milliseconds. Filtering more than a few
   hundred objects in Python is prohibitively slow, so filter in the query
   instead.

``filter_by`` filters in the query. This finds all trials from participant 5:

.. code-block:: python

    CustomTrial.query.filter_by(participant_id=5).all()

``.all()`` always returns a list. ``.one()`` returns a single object, and
raises an error unless exactly one object matches:

.. code-block:: python

    from psynet.participant import Participant

    Participant.query.filter_by(id=5).one()

``.count()`` returns the number of matches:

.. code-block:: python

    Participant.query.filter_by(status="approved").count()

Filter fields
^^^^^^^^^^^^^

Queries can filter on the columns of the class's table, which you can see in
the dashboard's database view or a viewer such as Postico. The
``participant`` table, for example, has columns such as ``recruiter_id``,
``worker_id``, ``assignment_id``, ``base_pay``, and ``bonus``.

.. figure:: /_static/images/developer/sql_alchemy/postico-2.png
  :width: 800
  :align: center

|br|
Variables stored in ``var`` are not columns: they are stored together as JSON,
so queries cannot filter on them. To filter on a value, define it as a column
with standard SQLAlchemy syntax:

.. code-block:: python

    import random

    from sqlalchemy import Column, Integer

    class CustomTrial(GibbsTrial):
        random_integer = Column(Integer)

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.random_integer = random.randint(0, 10)

.. note::

    All trial classes share one ``trial`` table, so two trial classes that
    declare the same column name share one column. Prefer a plain ``Column``
    on the trial class. PsyNet reuses the existing column when the name is
    already present, which also lets PsyNet reimport ``experiment.py`` from
    its staging copy during debug and deployment. The same reuse applies to
    other classes that share a table. The declarations must agree on type
    options, nullability, uniqueness, indexing, primary keys, foreign keys,
    defaults, update values, constraints, autoincrement behavior, system
    columns, and comments. PsyNet raises an error asking you to rename the
    column when these definitions differ.

Queries can then filter on the column:

.. code-block:: python

    CustomTrial.query.filter_by(random_integer=3).all()

SQLAlchemy provides column types that map to PostgreSQL types, such as
``Integer``, ``DateTime``, ``Float``, ``Text``, and ``String``; see the
`SQLAlchemy type documentation <https://docs.sqlalchemy.org/en/14/core/types.html>`_.
:mod:`psynet.field` adds more, most importantly ``PythonObject``, a
general-purpose column that stores arbitrary data, including database
objects, serialized with ``jsonpickle``.

More general filters
^^^^^^^^^^^^^^^^^^^^

``filter`` takes comparison expressions, so it is more flexible than
``filter_by``:

.. code-block:: python

    CustomTrial.query.filter(CustomTrial.random_integer >= 5).all()
    CustomTrial.query.filter(CustomTrial.random_integer != 5).all()

To filter on fields of *another* class, join the two tables on a related
column. The trial table's ``participant_id`` column refers to the
participant table's ``id`` column, so joining them links each trial to its
participant, and the query can then filter on participant fields. This
selects all trials from approved participants:

.. code-block:: python

    from dallinger import db
    from psynet.participant import Participant

    (
        db.session.query(CustomTrial)
        .join(Participant, CustomTrial.participant_id == Participant.id)
        .filter(Participant.status == "approved")
        .all()
    )

Updating objects
----------------

Attributes of SQLAlchemy objects are updated like ordinary attributes, but the
change reaches the database only when ``db.session.commit()`` is called:

.. code-block:: python

    from dallinger import db
    from psynet.participant import Participant

    participant = Participant.query.filter_by(id=1).one()
    participant.status = "approved"
    db.session.commit()

PsyNet commits automatically after most experiment code, such as code blocks,
``show_trial``, and ``analyze_recording``. Code that PsyNet does not call
itself, such as a custom route defined with ``@experiment_route``, should call
``db.session.commit()``.

Objects loaded by separate queries do not see each other's changes:

.. code-block:: python

    from psynet.trial.main import Trial

    trial = Trial.query.filter_by(id=1).one()
    trial_copy = Trial.query.filter_by(id=1).one()

Changes to ``trial`` are not reflected in ``trial_copy``. To see them, commit
and query again.

SQLAlchemy does not track in-place changes to a ``PythonObject`` column's
value, such as updating a dictionary or appending to a list:

.. code-block:: python

    trial.my_dictionary["value"] = 3
    trial.my_list.append(3)

Mark the column as changed so the change is saved on commit:

.. code-block:: python

    from sqlalchemy.orm.attributes import flag_modified

    trial.my_list.append(3)
    flag_modified(trial, "my_list")

``var`` stores track assignments to top-level variables, but not in-place
changes to a stored dictionary or list. Assign a new value instead:

.. code-block:: python

    trial.var.my_dict = {**trial.var.my_dict, "value": 3}

Creating objects
----------------

SQLAlchemy objects are created like ordinary Python objects, then added to the
database session:

.. code-block:: python

    from dallinger import db

    trial = CustomTrial(
        experiment=experiment,
        node=node,
        participant=participant,
        propagate_failure=False,
        is_repeat_trial=False,
    )
    db.session.add(trial)
    db.session.commit()

``db.session.add`` registers the object with the database, and
``db.session.commit`` saves it. Trial makers and
:meth:`~psynet.trial.main.Trial.cue` normally create trials for you; creating
objects directly is mainly needed for custom network architectures, as in
classic Dallinger experiments.

Logging SQL commands
--------------------

To see the SQL commands that SQLAlchemy generates, enable statement logging on
the PostgreSQL server. In ``postgresql.conf``, find the line:

.. code-block:: console

    # log_statement = 'none'

and replace it with:

.. code-block:: console

    log_statement = 'all'

The file's location depends on your installation; with Homebrew on an Intel
Mac it is in ``/usr/local/var/postgres/``. Restart PostgreSQL, for example
with Homebrew:

.. code-block:: console

    brew services restart postgresql

All SQL commands are then written to the server log, for example
``/usr/local/var/log/postgres.log``, ``/usr/local/var/log/postgresql@14.log``,
or ``/opt/homebrew/var/log/postgres.log``. Follow it live with:

.. code-block:: console

    tail -f /usr/local/var/log/postgres.log

.. warning::

    Logging every statement slows the database down. Restore the original
    ``log_statement`` line when you are done.
