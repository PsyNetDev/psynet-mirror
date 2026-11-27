"""Keep the generated timeline for each open PageMaker visit in the participant transaction.

A visit can contain callbacks and shared jump targets, so serialize its elements
together. Store compressed bytes in a private table, outside research exports
and imports. Only the deployment which created a visit should execute it.
"""

import hashlib
import io
import os
import pickle
import secrets
import socket
import sys
import zlib
from functools import cached_property

import dill
from dallinger import db
from itsdangerous import BadSignature, Signer
from sqlalchemy import (
    JSON,
    Column,
    ForeignKey,
    Integer,
    LargeBinary,
    UniqueConstraint,
    inspect,
)
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapper, Session, scoped_session
from sqlalchemy.orm.state import InstanceState

from . import deployment_info
from .version import psynet_version


class PageMakerVisitError(ValueError):
    """A generated sequence cannot be saved or restored for this visit."""


def _model_name(mapper):
    model = mapper.class_
    if mapper.registry is not db.Base.registry:
        raise PageMakerVisitError(
            f"{model.__name__} must use the experiment's database registry."
        )
    return model.__module__, model.__qualname__


class _Pickler(dill.Pickler):
    def __init__(self, stream, experiment):
        super().__init__(stream, protocol=pickle.HIGHEST_PROTOCOL)
        self.resources = {}
        if experiment is not None:
            self.resources[id(experiment)] = ("experiment", None)
            # Dallinger's recruiter is a cached property. A bound callback
            # already materialized it; avoid constructing a recruiter for other pages.
            recruiter = vars(experiment).get("recruiter")
            if recruiter is not None:
                self.resources[id(recruiter)] = ("recruiter", None)
            for name, maker in experiment.timeline.trial_makers.items():
                self.resources[id(maker)] = ("trial_maker", name)

    def persistent_id(self, obj):
        resource = self.resources.get(id(obj))
        if resource:
            return resource
        if isinstance(
            obj, (Session, scoped_session, Connection, io.IOBase, socket.socket)
        ):
            raise PageMakerVisitError(
                f"A page maker captured a live {type(obj).__name__}."
            )
        state = inspect(obj, raiseerr=False)
        if isinstance(state, Mapper) and state.class_ is obj:
            return _model_name(state), None
        if isinstance(state, InstanceState) and state is not obj:
            if state.transient:
                from .asset import Asset

                # Trial.cue can carry an asset specification that becomes a
                # new row only when its registration code block runs.
                if isinstance(obj, Asset):
                    return None
            if (
                state.identity is None
                or state.was_deleted
                or (state.session is not None and obj in state.session.deleted)
            ):
                raise PageMakerVisitError(
                    f"A page maker captured an unsaved or deleted {type(obj).__name__}."
                )
            return _model_name(state.mapper), state.identity
        return None


class _Unpickler(dill.Unpickler):
    def __init__(self, stream, experiment):
        super().__init__(stream)
        self.experiment = experiment

    @cached_property
    def models(self):
        # Experiment modules can be loaded directly from their source path.
        # Importing one again to unpickle a class would register its tables twice.
        models = {}
        for mapper in db.Base.registry.mappers:
            # Staging can redeclare a trial. SQLAlchemy uses the current
            # polymorphic mapper when loading its rows, so use that one here too.
            if (
                mapper.polymorphic_map.get(mapper.polymorphic_identity, mapper)
                is mapper
            ):
                name = _model_name(mapper)
                models[name] = None if name in models else mapper.class_
        return models

    def persistent_load(self, reference):
        name, key = reference
        if name == "experiment":
            return self.experiment
        if name == "recruiter":
            return self.experiment.recruiter
        if name == "trial_maker":
            return self.experiment.timeline.get_trial_maker(key)
        model = self.models.get(name)
        if model is None:
            raise PageMakerVisitError(
                f"Cannot identify a unique registered database model {name}."
            )
        if key is None:
            return model
        row = db.session.get(model, key)
        if row is None:
            raise PageMakerVisitError(
                f"Missing {model.__name__} row {key} while restoring a page maker."
            )
        return row


# A timeline can also run directly in a Python process, outside a deployed
# experiment. Its snapshots are private to that interpreter.
_standalone_key = secrets.token_bytes(32)


def _signer(participant_id, path):
    # Dallinger provisions the same private Flask key for its web and background
    # workers. Deployment metadata is visible on the dashboard; it is context,
    # never key material. Standalone timelines have only a process-local key.
    launch = deployment_info.read_all() if deployment_info.is_available() else {}
    key = os.environ.get("FLASK_SECRET_KEY")
    if not key and launch.get("mode") in ("live", "sandbox"):
        raise PageMakerVisitError(
            "The deployment needs its private server key to use PageMaker."
        )
    context = (
        "psynet.page-maker.v1",
        psynet_version,
        sys.implementation.cache_tag,
        dill.__version__,
        launch.get("deployment_id"),
        participant_id,
        path,
    )
    return Signer(
        key or _standalone_key,
        salt=repr(context),
        key_derivation="hmac",
        digest_method=hashlib.sha256,
    )


class PageMakerVisit(db.Base):
    """Private execution state. One row per active nesting level, removed on exit."""

    __tablename__ = "page_maker_visit"
    __table_args__ = (
        UniqueConstraint(
            "participant_id", "depth", deferrable=True, initially="DEFERRED"
        ),
    )
    id = Column(Integer, primary_key=True)
    participant_id = Column(
        Integer, ForeignKey("participant.id", ondelete="CASCADE"), nullable=False
    )
    depth = Column(Integer, nullable=False)
    path = Column(JSON, nullable=False)
    payload = Column(LargeBinary, nullable=False)

    @classmethod
    def enter(cls, maker, experiment, participant):
        """Resolve once in the transaction which moves the participant into the maker."""
        if participant.id is None:
            db.session.flush()  # The signature and captured row references need its key.
        path = list(participant.elt_id)
        elements = maker.resolve(experiment, participant, path)
        stream = io.BytesIO()
        try:
            _Pickler(stream, experiment).dump(elements)
        except (
            pickle.PicklingError,
            TypeError,
            RecursionError,
            PageMakerVisitError,
        ) as exc:
            raise PageMakerVisitError(
                f"Cannot save PageMaker {maker.label!r} at {path}: {exc}"
            ) from exc
        payload = _signer(participant.id, path).sign(
            zlib.compress(stream.getvalue(), level=1)
        )
        participant._page_maker_visits[len(path)] = cls(
            depth=len(path), path=path, payload=payload
        )

    @staticmethod
    def read(experiment, participant, path):
        """Reconstruct a fresh graph for rendering, validation or scoring."""
        visit = participant._page_maker_visits.get(len(path))
        if visit is None or visit.path != path:
            raise PageMakerVisitError(
                f"No active PageMaker visit at {path} for participant {participant.id}."
            )
        try:
            compressed = _signer(participant.id, path).unsign(visit.payload)
        except BadSignature as exc:
            raise PageMakerVisitError(
                f"Cannot restore PageMaker at {path} with this deployment and runtime."
            ) from exc
        return _Unpickler(io.BytesIO(zlib.decompress(compressed)), experiment).load()
