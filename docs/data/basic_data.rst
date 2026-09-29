Basic data
==========

Basic data is a summary of the experiment's data that you define yourself,
by implementing ``get_basic_data`` on the experiment class with SQLAlchemy
queries. It appears in exports, in the dashboard's **Basic data** tab and at
the ``/basic_data`` endpoint.

As a dictionary
---------------

Return a dictionary of data, and it is saved as a JSON file:

.. code:: python

    @classmethod
    def get_basic_data(cls, context=None, **kwargs):
        return {
            "trials": [
                {
                    "id": trial.id,
                    "question": trial.definition.get("question"),
                    "answer": trial.answer,
                }
                for trial in Trial.query.all()
            ]
        }

As data frames
--------------

In exports, a dictionary of data frames also works, and each is saved as a
CSV file. The dashboard tab, the ``/basic_data`` endpoint and backups need
JSON data, so check ``context`` and return data frames only when it is
``"export"``:

.. code:: python

    @classmethod
    def get_basic_data(cls, context=None, **kwargs):
        import pandas as pd

        trials = [
            {
                "id": trial.id,
                "participant_id": trial.participant_id,
                "animal": trial.definition.get("animal"),
                "block": trial.block,
                "answer": trial.answer,
                "score": trial.score,
            }
            for trial in StaticTrial.query.all()
        ]
        participants = [
            {
                "id": participant.id,
                "status": participant.status,
                "bonus": participant.bonus,
            }
            for participant in Participant.query.all()
        ]
        if context != "export":
            return {"trial": trials, "participant": participants}
        return {
            "trial": pd.DataFrame.from_records(trials),
            "participant": pd.DataFrame.from_records(participants),
        }

PsyNet doesn't anonymize basic data. If a public release must omit
identifiers, leave them out in ``get_basic_data``.

Over HTTP
---------

A running experiment serves basic data at ``/basic_data``, so you can fetch it
without exporting. The endpoint requires the dashboard credentials as query
parameters, ``dashboard_user`` and ``dashboard_password``. The
``basic_data_url`` property builds the full URL:

.. code:: python

    from psynet.experiment import Experiment

    url = Experiment.basic_data_url
    # https://your-experiment-url.com/basic_data?dashboard_user=...&dashboard_password=...

.. code:: bash

    curl "https://your-experiment-url.com/basic_data?dashboard_user=USER&dashboard_password=PASSWORD"

All query parameters, including the credentials, are passed to
``get_basic_data`` as keyword arguments, so one method can serve several
views:

.. code:: python

    @classmethod
    def get_basic_data(cls, context=None, **kwargs):
        sheet = kwargs.get("sheet", "participant")
        if sheet == "participant":
            return [...]
        elif sheet == "trial":
            return [...]

The endpoint returns JSON, which Python reads with ``requests.get(url).json()``
and R with ``jsonlite::fromJSON(url)``. Because the credentials are part of the
URL, keep sensitive information out of basic data.
