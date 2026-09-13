# Store study-level adaptive state

Finalized observations are the source data for a study-level adaptive model.
The fitted state is a derived snapshot that makes later selection efficient.
Each adaptive decision records which snapshot it used.

```text
finalized observations -> study-model snapshot -> adaptive decision
```

Use append-only snapshots rather than updating one shared payload in place. A
new fit must be complete and durable before selection can see it.

## Suggested tables

Define custom tables using PsyNet's `SQLBase`, `SQLMixin`, and `register_table`.
The following is a starting point; add domain-specific fields when they need to
be queried or exported directly.

```python
from sqlalchemy import Column, Float, ForeignKey, Integer, String
from sqlalchemy.orm import deferred, relationship

from psynet.data import SQLBase, SQLMixin, register_table
from psynet.field import PythonDict, PythonObject
from psynet.trial.main import Trial


@register_table
class StudyModelSnapshot(SQLBase, SQLMixin):
    __tablename__ = "study_model_snapshot"

    status = Column(String, index=True)
    model_version = Column(String)
    data_version = Column(Integer, unique=True, index=True)
    observation_count = Column(Integer)
    observation_fingerprint = Column(String)

    state = deferred(Column(PythonObject, nullable=True))
    asset_id = Column(Integer, ForeignKey("asset.id"), nullable=True)
    asset_format = Column(String, nullable=True)
    asset_content_id = Column(String, nullable=True)

    diagnostics = Column(PythonDict)
    random_seed = Column(Integer, nullable=True)
    error = Column(String, nullable=True)


@register_table
class AdaptiveDecision(SQLBase, SQLMixin):
    __tablename__ = "adaptive_decision"

    participant_id = Column(
        Integer,
        ForeignKey("participant.id"),
        index=True,
    )
    trial_id = Column(
        Integer,
        ForeignKey("trial.id"),
        nullable=True,
        unique=True,
        index=True,
    )
    study_fit_id = Column(
        Integer,
        ForeignKey("study_model_snapshot.id"),
        nullable=True,
        index=True,
    )
    selected_candidate_id = Column(String)
    participant_history_count = Column(Integer, nullable=True)
    candidate_pool_version = Column(String)
    selected_utility = Column(Float, nullable=True)
    details = Column(PythonDict)
    trial = relationship(Trial, foreign_keys=[trial_id])
```

`status` normally moves from `building` to `ready` or `failed`. Store an error
summary for a failed fit, but keep the previous ready snapshot available. Give
each successful fit a model version and a monotonically increasing data
version.

## Create decisions transactionally

Create the decision row when the assignment is created, in the same
transaction. With `Trial.cue`, pass provenance through `creation_context` and
write the row in an `on_trial_created` callback:

```python
def record_decision(trial, participant, creation_context):
    decision = AdaptiveDecision(
        participant_id=participant.id,
        selected_candidate_id=creation_context["selected_candidate_id"],
        participant_history_count=creation_context["participant_history_count"],
        study_fit_id=creation_context["study_fit_id"],
        candidate_pool_version=creation_context["candidate_pool_version"],
        selected_utility=creation_context["selected_utility"],
        details=creation_context["details"],
    )
    decision.trial = trial
    db.session.add(decision)


AdaptiveTrial.cue(
    definition={"item_id": selected_item_id},
    on_trial_created=record_decision,
    creation_context=creation_context,
)
```

Assigning the relationship lets SQLAlchemy populate `trial_id` when the
transaction flushes; do not flush merely to obtain the trial ID. If the callback
raises, the trial and the decision roll back together, so a decision never
survives an assignment the participant did not receive.

A trial maker's `on_trial_created` method is the same kind of hook. Pass
provenance as the `selection_context` parameter (the `context` attribute of
the returned `Selection`), not `creation_context`. It runs for primary
assignments only: repeat trials and synchronized follower copies do not call it.

Use explicit columns for routine queries and exports. Keep `details` small
unless the complete candidate and utility set is needed to reconstruct the
policy.

## Publish a snapshot

Create and commit the `building` row before starting the expensive fit. Perform
the computation outside a database transaction. Publish the payload and mark
the snapshot `ready` together in a short final transaction.

```python
snapshot = StudyModelSnapshot(
    status="building",
    model_version=MODEL_VERSION,
    data_version=data_version,
    observation_count=len(observations),
    observation_fingerprint=fingerprint_observations(observations),
)
db.session.add(snapshot)
db.session.commit()
snapshot_id = snapshot.id
db.session.remove()

try:
    model_fit = fit_study_model(
        observations=observations,
        participants=participants,
        items=items,
    )
except Exception as error:
    snapshot = StudyModelSnapshot.query.get(snapshot_id)
    snapshot.status = "failed"
    snapshot.error = str(error)
    db.session.commit()
    raise
else:
    snapshot = StudyModelSnapshot.query.get(snapshot_id)
    snapshot.state = state_needed_for_scoring(model_fit)
    snapshot.diagnostics = fit_diagnostics(model_fit)
    snapshot.status = "ready"
    db.session.commit()
```

Removing the scoped session before fitting releases its connection and detaches
the `building` row. Re-query the snapshot in a fresh session only when
publishing success or failure.

Selection queries the newest ready data version. It never reads a `building`
row.

```python
snapshot = (
    StudyModelSnapshot.query
    .filter_by(status="ready")
    .order_by(StudyModelSnapshot.data_version.desc())
    .first()
)
```

Do not rely on a scheduled task's `max_instances=1` when several server
processes might execute it. The unique `data_version` constraint makes
competing claims fail atomically; catch that integrity error and let the
existing claimant continue. A database lock can coordinate more complex claim
rules. Truly incremental updates additionally need a single-writer mechanism
that incorporates every observation exactly once.

## Identify the fitted observations

A maximum trial or response ID is not always a sufficient cutoff because an
older record can become finalized after a newer record was created. Record the
number of included observations and a fingerprint of their sorted stable IDs.
When exact membership must be queryable, store the included IDs or use an
association table between snapshots and observations.

Record the query rule that defines an eligible observation. A snapshot should
be reproducible from the experiment data, model version, random seed, and
recorded observation set.

## Choose the payload representation

For small state, store a portable dictionary in the deferred `PythonObject`
column. Include only what selection needs, such as item estimates, uncertainty
summaries, or population coefficients. Avoid serializing a full fitted-library
object when numerical parameters are sufficient.

For large state, create an `ExperimentAsset` and save its ID, format, and
content ID on the snapshot. The database row remains the authoritative index;
the asset contains the large payload.

Portable numerical formats are preferable where practical. For example:

```python
np.savez_compressed(
    path,
    item_ids=item_ids,
    item_estimates=item_estimates,
    covariance=covariance,
)
```

Pickle is an option when the fitted object cannot usefully be reconstructed
from a portable representation. Treat it as a trusted, version-dependent
format: only unpickle files produced by the experiment, and record the Python,
package, and model-code versions needed to read them. Do not include raw
participant data when fitted parameters are sufficient.

## Store a large fit as an ExperimentAsset

Serialize the fit to a temporary file, deposit it through PsyNet's configured
asset storage, and reference the resulting asset from the snapshot.

```python
import pickle
import tempfile

from dallinger import db
from psynet.asset import ExperimentAsset


with tempfile.NamedTemporaryFile(suffix=".pkl") as file:
    pickle.dump(model_fit, file)
    file.flush()

    asset = ExperimentAsset(
        input_path=file.name,
        local_key=f"study_model_snapshot_{snapshot.id}",
        extension=".pkl",
        description=f"Study model snapshot {snapshot.id}",
        module_id="common",
    )
    asset.deposit()
    db.session.flush()

snapshot.asset_id = asset.id
snapshot.asset_format = "pickle"
snapshot.asset_content_id = asset.content_id
snapshot.status = "ready"
db.session.commit()
```

Mark the snapshot ready only after a synchronous deposit succeeds. If deposit
is asynchronous, its completion path must publish the snapshot. Do not put
secrets or unnecessary participant data in the fitted object.
Depositing an `ExperimentAsset` requires `Experiment.asset_storage` (for local
work, `LocalStorage`). `module_id="common"` scopes the asset to the shared
experiment module rather than a participant.

## Load and cache an asset

Export the asset to a temporary file before deserialization. Cache the loaded
object within each server process so participant requests do not repeatedly
download the same snapshot.

```python
import pickle
import tempfile
from functools import lru_cache

from psynet.asset import ExperimentAsset


@lru_cache
def load_study_fit(asset_id, content_id):
    asset = ExperimentAsset.query.get(asset_id)
    if asset.content_id != content_id:
        raise RuntimeError("Study-model asset content ID does not match.")

    with tempfile.NamedTemporaryFile(suffix=".pkl") as file:
        asset.export(file.name)
        with open(file.name, "rb") as reader:
            return pickle.load(reader)
```

Use immutable asset and content IDs as the cache key. Publishing a new snapshot
therefore creates a new cache entry without mutating the fitted object used by
requests already in progress.

## Validate persistence

Exercise a successful refresh, a failed refresh, and two workers attempting to
claim the same data version. Confirm that selection never observes a partial
fit and that a decision can be traced to the exact snapshot and observation
set. For asset-backed state, load the fit in a fresh process rather than relying
on the process that created it.
