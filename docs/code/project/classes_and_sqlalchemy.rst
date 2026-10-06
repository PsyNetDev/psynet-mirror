Querying and storing database objects
=====================================

Participants, trials, nodes, networks, assets, error logs and asynchronous
processes are **database-backed**: each object is a row in PsyNet's
PostgreSQL database, so its state is shared across server processes and
persists for the whole experiment. The mapping between Python objects and
database rows is implemented with `SQLAlchemy <https://www.sqlalchemy.org/>`_.

As long as you use existing attributes and variable stores, such as
``participant.var.my_variable``, changes are saved without extra work. This
page covers querying, custom columns, updating or creating objects directly,
and custom tables. It assumes familiarity with Python classes, subclasses
and ``super()``; the
`Python tutorial on classes <https://docs.python.org/3/tutorial/classes.html>`_
covers them.

Tables and objects
------------------

Each database-backed class has a table. Each row is an object, and each
column is an attribute with a name and a data type such as integer, string or
float. The ``participant`` table, for example, has columns such as ``id``,
``status``, ``worker_id``, ``base_pay`` and ``bonus``. SQLAlchemy exposes the
columns as attributes:

.. code-block:: python

    from psynet.participant import Participant

    participant = Participant.query.filter_by(id=1).one()

    participant.status  # read a column
    participant.status = "approved"  # write a column

The dashboard's database tab shows the tables and their contents. A
database viewer such as `Postico <https://eggerapps.at/postico2/>`_ shows
the columns too:

.. figure:: /_static/images/developer/sql_alchemy/postico-2.png
  :width: 800
  :align: center

Subclassing a database-backed class, such as a trial class, defines a new
SQLAlchemy class. All class names within an experiment must be unique,
including classes imported from other packages.

PsyNet's participants, nodes and networks are built on the corresponding
classes of `Dallinger <https://dallinger.readthedocs.io/latest/classes.html>`_,
the platform PsyNet runs on.

Query objects
-------------

A query loads objects from the database, like an SQL ``SELECT`` statement.
This returns all ``CustomTrial`` objects:

.. code-block:: python

    trials = CustomTrial.query.all()

The result is a list. Filtering it in Python is fine for small numbers of
objects, but two costs grow quickly:

#. **Each query has a significant fixed overhead.** SQLAlchemy compiles an SQL
   command, sends it to the database, waits for the response, and parses the
   result. Loading 200 records in one query is much faster than loading them
   in 200 queries.
#. **Filtering in Python is slow.** The first access to an attribute of an
   SQLAlchemy object takes a few milliseconds, so filtering more than a few
   hundred objects in Python is prohibitively slow.

Filter in the query instead. ``filter_by`` finds all trials from
participant 5:

.. code-block:: python

    CustomTrial.query.filter_by(participant_id=5).all()

``.all()`` always returns a list. ``.one()`` returns a single object, and
raises an error unless exactly one object matches. ``.count()`` returns the
number of matches:

.. code-block:: python

    Participant.query.filter_by(status="approved").count()

Add a column to filter on
^^^^^^^^^^^^^^^^^^^^^^^^^

Queries can filter only on columns. Variables stored in ``var`` are stored
together as JSON, so queries can't filter on them. To filter on a value,
define it as a column:

.. code-block:: python

    import random

    from sqlalchemy import Column, Integer

    class CustomTrial(GibbsTrial):
        random_integer = Column(Integer)

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.random_integer = random.randint(0, 10)

Queries can then filter on the column:

.. code-block:: python

    CustomTrial.query.filter_by(random_integer=3).all()

.. note::

    All trial classes share one ``trial`` table, and the same applies to other
    classes that share a table. Two classes that declare a column with the
    same name share that column, so the declarations must match exactly;
    PsyNet raises an error asking you to rename the column otherwise.

SQLAlchemy provides column types that map to PostgreSQL types, such as
``Integer``, ``DateTime``, ``Float``, ``Text``, and ``String``; see the
`SQLAlchemy type documentation <https://docs.sqlalchemy.org/en/14/core/types.html>`_.
:mod:`psynet.field` adds more, most importantly ``PythonObject``, a
general-purpose column that stores arbitrary data, including database
objects, serialized with ``jsonpickle``.

Filter with comparisons and joins
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

``filter`` takes comparison expressions, so it is more flexible than
``filter_by``:

.. code-block:: python

    CustomTrial.query.filter(CustomTrial.random_integer >= 5).all()
    CustomTrial.query.filter(CustomTrial.random_integer != 5).all()

To filter on the columns of another class, join the two tables on a related
column. The trial table's ``participant_id`` column refers to the
participant table's ``id`` column, so this selects all trials from approved
participants:

.. code-block:: python

    from dallinger import db
    from psynet.participant import Participant

    (
        db.session.query(CustomTrial)
        .join(Participant, CustomTrial.participant_id == Participant.id)
        .filter(Participant.status == "approved")
        .all()
    )

Update objects
--------------

Change an object by assigning to its attributes. PsyNet saves the change to
the database when it commits the transaction (see `Saving changes`_):

.. code-block:: python

    from psynet.participant import Participant

    participant = Participant.query.filter_by(id=1).one()
    participant.status = "approved"

SQLAlchemy does not track in-place changes to a ``PythonObject`` column's
value, such as updating a dictionary or appending to a list. Mark the column
as changed so the change is saved on commit:

.. code-block:: python

    from sqlalchemy.orm.attributes import flag_modified

    trial.my_list.append(3)
    flag_modified(trial, "my_list")

``var`` stores track assignments to top-level variables, but not in-place
changes to a stored dictionary or list. Assign a new value instead:

.. code-block:: python

    trial.var.my_dict = {**trial.var.my_dict, "value": 3}

Create objects
--------------

Database objects are created like ordinary Python objects, then added to the
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
    db.session.flush()

``db.session.add`` registers the object with the database, and
``db.session.flush`` sends it to the database so that it gets an ``id``.
PsyNet saves it when it commits the transaction. Trial makers and
:meth:`~psynet.trial.main.Trial.cue` normally create trials for you;
creating trials directly is mainly needed for custom network architectures.

.. _saving_changes:

Saving changes
--------------

PsyNet runs experiment code inside a database transaction and commits it
once the step has finished. This includes code blocks, page makers, page
methods such as ``format_answer``, ``validate``, ``on_complete`` and
``pre_render``, trial methods such as ``show_trial`` and
``finalize_definition``, and trial maker hooks such as ``grow_network``,
``finalize_trial`` and ``select_node``. While this code runs, the
transaction holds a lock on the participant's database row.

Do not call ``db.session.commit()`` or ``db.session.rollback()`` in this
code. Committing early releases the participant's lock, so a second request
from the same participant can interleave with this one, and it saves
half-finished changes if a later step fails. PsyNet raises a
``RuntimeError`` that names the offending code if it commits or rolls back.

Call ``db.session.flush()`` when you need a new object's ``id`` straight
away. Flushing sends pending changes to the database within the current
transaction, without committing them:

.. code-block:: python

    def create_pet(participant):
        pet = Dog(participant)
        db.session.add(pet)
        db.session.flush()
        participant.var.current_pet = pet.id

The same applies to helper code called from these places, including custom
recruiter methods such as ``release_participant``. A helper should leave
committing to the code that started the transaction, and flush if it needs
database-generated values. The
exception is saving payment state just before a recruiter posts a payment, so
a crash cannot repeat the payment: call ``experiment.commit_payment_state()``,
which is allowed in these places.

Code that does not run as part of a participant's progress through the
timeline manages its own transaction. For example, POST routes defined with
``@experiment_route`` must call ``db.session.commit()``; see
:doc:`/code/pages/custom_routes`.

Define a custom table
---------------------

To store objects that don't fit PsyNet's classes, define a new table. The
class inherits from ``SQLBase`` and :class:`~psynet.data.SQLMixin`, both
imported from :mod:`psynet.data`, sets ``__tablename__``, and is decorated
with :func:`~psynet.data.register_table`, which adds the table to the
dashboard's database tab and to data exports. ``SQLMixin`` provides the
standard columns, such as ``id``, ``creation_time`` and ``failed``.

``demos/features/custom_table_simple`` stores a coin each time the
participant chooses to collect one. The ``relationship`` with a ``backref``
gives each participant an ``all_coins`` attribute:

.. literalinclude:: ../../../demos/features/custom_table_simple/experiment.py
   :start-at: @register_table
   :end-before: def check_continue

Subclasses of a custom table class share its table, and each subclass can
add its own columns. ``demos/features/custom_table_complex`` stores dogs and
cats in one ``pet`` table:

.. literalinclude:: ../../../demos/features/custom_table_complex/experiment.py
   :start-at: @register_table
   :end-at: self.participant_id = participant.id

.. literalinclude:: ../../../demos/features/custom_table_complex/experiment.py
   :pyobject: Dog

The demo's timeline creates a pet with ``db.session.add`` and
``db.session.flush``, stores its ``id`` in a participant variable, and
queries it again with ``Pet.query.filter_by(id=...)`` on later pages.

Find slow queries
-----------------

``psynet test local --sql-profile`` reports the SQL queries that the
experiment runs and how long they take; see :doc:`/test/sqlalchemy_profiling`.
