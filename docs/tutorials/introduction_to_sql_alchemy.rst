.. |br| raw:: html

   <br />

Introduction to SQLAlchemy
==========================

SQLAlchemy is a Python package for interacting with SQL databases. PsyNet uses a particular kind of SQL database called PostgreSQL, which you can read about `here <https://www.postgresql.org/about/>`_.

SQL databases store data in *tables*. Each table looks something like a spreadsheet. It has multiple columns (termed *fields*) and multiple rows (termed *records*). Each record may be interpreted conceptually as some kind of object. The columns then provide attributes of those objects. Each attribute will have a name and an associated data type, for example integer, string, or float.

It is common practice for SQL tables to include an ID column comprising positive integers. This ID column indexes the different records in the table.

Here is a simple example of what an SQL table might look like:

================================ =================  ====================   ===================
person_id (integer, primary key) forename (string)  family_name (string)   occupation (string)
================================ =================  ====================   ===================
1                                James              Edwards                Forestry manager
2                                Edwards            Tolley                 IT consultant
3                                Laura              Harrison               Handyman
4                                Eleanor            Ashby                  Sales assistant
================================ =================  ====================   ===================

SQLAlchemy provides an elegant way of accessing and interacting with records within SQL tables. Each record in the table is aliased to a Python object. We’d then be able to write things like:

.. code-block:: python

    james = person.query.filter_by(forename="James").one()

    # Reading fields
    assert james.id == 1
    assert james.family_name == "Edwards"

    # Writing fields
    james.occupation = "unemployed"

This is quite exciting because it allows us to work with SQL tables in a very Pythonic way. Here we’re interacting with ‘``james``’ just like an ordinary Python object, so we get to use all of our standard Python tools like object oriented programming, list comprehensions, etcetera.

PsyNet relies heavily on SQLAlchemy. Many of the fundamental objects in PsyNet (participants, trials, nodes, chains) are stored in SQL databases and aliased to Python objects using SQLAlchemy. We can view the SQL representations of these objects through Postico, an SQL database viewer which we recommend as a default to PsyNet programmers (see installation instructions):

.. figure:: ../_static/images/developer/sql_alchemy/postico.png
  :width: 800
  :align: center

|br|
It is possible to program many PsyNet experiments without any knowledge of SQLAlchemy. However, a little SQLAlchemy knowledge can open many exciting doors. The purpose of this chapter is to give you this knowledge.

Defining SQLAlchemy classes
---------------------------

Anyone who has used a PsyNet trial maker has already had to define their own SQLAlchemy classes. This works just like subclassing ordinary Python classes:

.. code-block:: python

    class CustomTrial(GibbsTrial):
        def show_trial(self, experiment, participant):
            ...

An important thing to know is that all class names within an experiment must be unique, even if you are importing some of those classes from different packages. This is a good idea anyway for the sake of data analysis.

PsyNet’s trial makers make heavy use of SQLAlchemy objects. Each trial is represented as a distinct SQLAlchemy object, and each trial is connected to a node in a network, with nodes and networks also being represented as SQLAlchemy objects.

The underlying Dallinger framework also makes heavy use of SQLAlchemy objects. Dallinger experiments typically involve constructing various kinds of networks which develop according to participant behavior during the course of the experiment. PsyNet fully supports the creation and manipulation of Dallinger SQLAlchemy objects. For more information about Dallinger’s network infrastructure, see the `official Dallinger documentation <https://dallinger.readthedocs.io/latest/classes.html>`_ (which is unfortunately very limited).

Querying SQLAlchemy objects
---------------------------

Querying means loading SQLAlchemy objects into the workspace. It is equivalent to what would be called a SELECT statement in SQL. The simplest kind of SQLAlchemy looks something like this:

.. code-block:: python

    trials = CustomTrial.query.all()

This query returns a list of all the ``CustomTrial`` objects in the database. We can then filter and read these objects as we like. For example, we could filter the trials to only keep trials from participants called James:

.. code-block:: python

    james_trials = [
        t for t in trials
        if t.participant.var.name == "James"
    ]

We could then sum the performance rewards from each of these trials:

.. code-block:: python

    james_performance_reward = sum([t.performance_reward for t in james_trials])

We have to be careful, though, about certain performance questions when using SQLAlchemy. There are a couple of things that are particularly important to be aware of:

#. **Each query has a significant overhead.** Every time you run a query statement in SQLAlchemy, Python must compile an SQL command, send it to the database, wait for the response, and parse it into Python objects. There is a fixed overhead to this process; consequently, if you need to load 200 records, it is much better to load them in one 200-record query than to load them in 200 1-record queries.
#. **Filtering objects on the Python side is slow.** The first time we access an attribute of an SQLAlchemy object, there is a processing overhead that takes a few milliseconds. This is barely noticeable for individual objects, but it quickly becomes important if we are iterating over thousands of objects. A consequence is that filtering SQLAlchemy objects in Python is prohibitively slow once we have more than a few hundred objects. Instead, we need to perform the filtering within the SQLAlchemy query itself.

SQLAlchemy filtering can be achieved by inserting a call to ``filter_by`` in your query. For example, to find all trials from participant 5, I could write the following:

.. code-block:: python

    CustomTrial.query.filter_by(participant_id=5).all()

The ``.all()`` method always returns a list. If we know that we only are expecting one object, we can use ``.one()`` instead. This will return the object directly, and will throw an error if the number of matching objects proves to be less or more than one.

.. code-block:: python

    from psynet.participant import Participant

    Participant.query.filter_by(id=5).one()

If we only want to count the number of matching objects, we can use ``.count()``:

.. code-block:: python

    from psynet.participant import Participant

    Participant.query.filter_by(status="approved").count()

Filter variables
################

What variables might we filter on? The simplest way to find out is to inspect the SQL table for your class (e.g. in Postico), and see what columns are defined there. For example, in the ``Participant`` table we see variables like ``recruiter_id``, ``worker_id``, ``assignment_id``, ``base_pay``, ``bonus``, etcetera.

.. figure:: ../_static/images/developer/sql_alchemy/postico-2.png
  :width: 800
  :align: center

|br|
You may find that this list is missing some variables that you want to use. In particular, if you’ve been storing custom variables in ``CustomTrial.var``, you won’t see them as SQL columns and you won’t be able to filter on them. This is because these var objects are stored in JSON in the database, and are hence difficult to filter on in SQL.

Fortunately, it’s quite straightforward to define your own columns manually using standard SQLAlchemy syntax. See the following example:

.. code-block:: python

    from sqlalchemy import Column, Integer

    class CustomTrial(GibbsTrial):
        random_integer = Column(Integer)

        def __init__(*args, **kwargs):
            super().__init__(*args, **kwargs)
            self.random_integer = random.randint(0, 10)

.. note::

    Trial classes share Dallinger's ``info`` table, so two trial classes that
    declare the same column name share one column. Prefer a plain ``Column`` on
    the trial class. PsyNet reuses the existing column when the name is already
    present, which also lets PsyNet reimport ``experiment.py`` from its staging
    copy during debug and deployment. The same reuse applies to other
    Dallinger-backed classes that share a table. The declarations must agree on
    type options, nullability, uniqueness, indexing, primary keys, foreign
    keys, defaults, update values, constraints, autoincrement behavior, system
    columns, and comments. PsyNet raises an error asking you to rename the
    column when these definitions differ.

Having defined the class in this way, we can then run queries for ``CustomTrial`` objects that filter on the value of ``random_integer``:

.. code-block:: python

    CustomTrial.query.filter_by(random_integer=3).all()

SQLAlchemy provides a variety of built-in datatypes that map to PostgreSQL column types. For example:

  - Integer
  - DateTime
  - Float
  - Text
  - String

See the `SQLAlchemy documentation <https://docs.sqlalchemy.org/en/14/core/types.html>`_ for more possibilities.

PsyNet additionally defines a few more that can be useful for experiment implementations. The most important is ``PythonObject``, a general-purpose column that can store arbitrary data types, even including database objects. These are serialized using the powerful ``jsonpickle`` package. This class can be imported from ``psynet.field``.

More general filters
####################

We previously used ``filter_by`` to return objects whose fields matched a certain value. We can perform more general filtering using the ``filter`` method, which is slightly more verbose but more flexible. For example:


.. code-block:: python

    CustomTrial.query.filter(CustomTrial.random_integer >= 5).all()
    CustomTrial.query.filter(CustomTrial.random_integer != 5).all()

What if we want to filter on fields from *another class*? For example, suppose we want to select all trials from ‘approved’ participants? In this case we perform a join operation. A *join* operation combines two tables together on a related column. In this case, the ``Trial`` table has a column ``participant_id``, which maps to the *id* column of the ``Participant`` table. When we ask SQLAlchemy to join the ``Trial`` table with the ``Participant`` table, it uses this special relationship to link each Trial with its parent Participant. This then enables us to filter by fields of the ``Participant`` class, as if they were fields in the original ``Trial`` class.

.. code-block:: python

    from dallinger import db
    from psynet.participant import Participant

     db.session.query(CustomTrial)
        .join(Participant, CustomTrial.participant_id == Participant.id)
        .filter(Participant.status == "approved")
        .all()

Updating SQLAlchemy objects
---------------------------

We can update the attributes of SQLAlchemy objects just like the attributes of ordinary Python objects.

.. code-block:: python

    participant.status = "approved"

These attributes will not be immediately propagated to the database, however. This only happens when someone calls ``db.session.commit()``.

.. code-block:: python

    from dallinger import db
    from psynet.participant import Participant

    participant = Participant.query.filter_by(id=1)
    participant.status = "approved"
    db.session.commit()

If you are writing code within most standard PsyNet contexts (e.g. ``CodeBlock``, ``show_trial``, ``analyze_recording``), you do not need to worry about calling ``db.session.commit()``, as PsyNet calls it automatically for you. However, there are more advanced contexts (e.g., custom experiment routes made using the ``@experiment_route`` decorator) where this does not happen (yet). In these kinds of cases it’s worth putting in a ``db.session.commit()`` just to be sure.

It’s worth noting also that attribute updates do not propagate between Python objects once they are instantiated. For example, if I were to write the following:

.. code-block:: python

    from psynet trial import Trial


    trial = Trial.query.filter_by(id=1).one()
    trial_copy = Trial.query.filter_by(id=1).one()

then any alterations I make to ``trial`` would *not* be reflected in ``trial_copy``. If I wanted to see the updated trial, I’d have to commit first, then query the database again.

Another important thing to know is that SQLAlchemy does not track in-place modifications by default. For example, suppose that we update a dictionary:

.. code-block:: python

    trial.my_dictionary["value"] = 3

or append to a list:

.. code-block:: python

    trial.my_list.append(3)

By default, SQLAlchemy won’t realize that these alterations have been performed, and so they won’t be persisted to the database when you commit. You have to tell SQLAlchemy explicitly that these fields have been changed:

.. code-block:: python

    from sqlalchemy.orm.attributes import flag_modified

    trial.my_list.append(3)
    flag_modified(trial, "my_list")

It is more awkward to modify variables stored in the ‘var’ attribute. I don’t think the following works at all:

.. code-block:: python

    trial.var.my_dict["value"] = 3

For now, I think one must use a somewhat inelegant pattern like the following:

.. code-block:: python

    my_dict = trial.var.my_dict
    my_dict["value"] = 3
    trial.var.my_dict = my_dict
    flag_modified(trial, "vars")

Or alternatively:

.. code-block:: python

    my_dict = trial.var.my_dict
    my_dict["value"] = 3
    trial.var.my_dict = my_dict.copy()

Creating SQLAlchemy objects
---------------------------

SQLAlchemy objects are created just like ordinary Python objects, but need an extra step before they are registered in the database. This is how one might create a ``Trial`` object:

.. code-block:: python

    from dallinger import db
    trial = CustomTrial(
       experiment=experiment,
       node=node,
       participant=participant,
    )
    db.session.add(trial)
    db.session.commit()
    return trial

The crucial line here is ``db.session.add(trial)``, which adds the trial object to the database. We finalize the commit as before with ``db.session.commit()``.

Most experimenters will never need to create SQLAlchemy objects directly like this. The main application would be when designing a highly customized network architecture, as with the classic Dallinger experiment.

SQLAlchemy debugging
--------------------

In extreme cases when SQLAlchemy is misbehaving you may wish to inspect the actual SQL commands that it is generating behind the scenes. One way to do this is to enable query logging on the Postgres server and follow the logs in real time.

Use a text editor to open your ``pg_hba.conf`` file, which on my Intel Mac with Homebrew Postgres is located at ``/usr/local/var/postgres/``. If you can’t find this file you might have to Google where this file might be located on your operating system.

Find the line that says

.. code-block:: console

    # log_statement = 'none'

Replace it with the following (note how the # has been removed)

.. code-block:: console

    log_statement = 'all'

In the terminal, restart Postgres:

.. code-block:: console

    brew services restart postgresql

Now all SQL commands will be streamed to a log file; on my computer this log file is located at ``/usr/local/var/log/postgres.log``, but I’ve also seen it at ``/usr/local/var/log/postgresql@14.log`` and ``/opt/homebrew/var/log/postgres.log``.

Open a live preview of this log file using the following command:

.. code-block:: console

    tail -f /usr/local/var/log/postgres.log

Now you can see what commands are being run in real-time.

.. warning::

    Continuous logging like this might have performance implications. Once you’re done you should probably disable logging by replacing that line in ``postgresql.conf`` with its initial value.

Exercise
--------

Design a PsyNet experiment where each participant starts with a randomly generated number of dollars (saved in an SQL field called ``dollars``). Write a ``while_loop`` in the timeline, containing a page where the participant is shown a collection of push buttons (``PushButtonControl``), one for each participant in the study, labeled with participant name and current dollar amount. Pushing a button should donate $1 to that person. Can you generalize these mechanics to make an interesting behavioral economics game?

**Tasks:**
    * Make the ``PushButton`` choices correspond to the participants who are actually in the database.

        * We’ll need to query for participants.
        * We want to display their money on the button.
        * (it’s good to avoid using weird symbols in the ``choices`` parameter in ``PushButtonControl``, better to put them in the ``labels`` parameter)

    * When we click a button, we want to assign money to that participant.

        * We take $1 from ourselves, we give it to the other participant.
        * This logic is going to go in ``process_response``.
