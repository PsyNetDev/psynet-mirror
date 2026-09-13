---
name: basic-data
description: Implement basic data export functionality. Use when implementing an experiment to create clean export csv files that are helpful for future analysis.
---

# Overview

By default, the data export of a PsyNet experient involves dumping the database to a collection
of csv files. These csv files are comprehensive but often messy.

The `basic_data` functionality allows one to construct additional export files that are cleaner
and hence more straightforward to analyse. This is accomplished by writing a custom method
on the experiment class, for example:

```py
    @classmethod
    def get_basic_data(cls, context=None, **kwargs):
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
        return {
            "trial": pd.DataFrame.from_records(trials),
            "participant": pd.DataFrame.from_records(participants),
        }
```

The method above results in two exported csv files: trial and participant.

The art here is thinking about (a) what rows should be included and (b) what attributes
should be included. It's worth thinking carefully about the research question when planning this.

Look out for specific basic-data skills for specific experiment types, for example:

- `basic-data-dyadic-experiment`
