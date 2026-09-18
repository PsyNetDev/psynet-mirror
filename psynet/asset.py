import os.path
import shutil
import subprocess
import tempfile
import time
import urllib
import urllib.parse
import urllib.request
import uuid
import warnings
from functools import cache, cached_property
from os import environ, makedirs, remove, symlink, unlink, walk
from pathlib import Path
from typing import Callable, Optional, Union

import boto3
import paramiko
import requests
from dallinger import db
from dallinger.utils import classproperty
from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, inspect
from sqlalchemy.exc import NoInspectionAvailable
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import deferred, relationship
from tqdm import tqdm

from psynet.timeline import NullElt

from . import deployment_info
from .data import SQLBase, SQLMixin, ingest_to_model, register_table
from .field import PythonDict, PythonObject  # , register_extra_var
from .media import (
    get_aws_credentials,
    get_s3_bucket,
    get_s3_client,
    get_s3_resource,
)
from .process import LocalAsyncProcess
from .serialize import prepare_function_for_serialization
from .utils import (
    get_args,
    get_extension,
    get_file_size_mb,
    get_folder_size_mb,
    get_from_config,
    get_logger,
    md5_directory,
    md5_file,
    md5_object,
)

logger = get_logger()


def filter_botocore_deprecation_warnings():
    boto3.compat.filter_python_deprecation_warnings()

    # Filter out the datetime.utcnow() deprecation warning
    # (see https://github.com/boto/botocore/issues/3088)
    warnings.filterwarnings(
        "ignore",
        message=r"datetime\.datetime\.utcnow\(\) is deprecated.*",
        category=DeprecationWarning,
        module="botocore.*",
    )


class AssetSpecification(NullElt):
    """
    A base class for asset specifications.
    An asset specification defines some kind of asset or collection or assets.
    It can be included within an experiment timeline.

    Parameters
    ----------

    local_key : str
        A string identifier for the asset, for example ``"stimulus"``. If provided, this string identifier
        should together with ``parent`` and ``module_id`` uniquely identify that asset (i.e. no other asset
        should share that combination of properties).

    description : str
        An optional longer string that provides further documentation about the asset.
    """

    def __init__(
        self, local_key, key_within_module, key_within_experiment, description
    ):
        self.export_path = None
        self.local_key = local_key
        self.key_within_module = key_within_module
        self.key_within_experiment = key_within_experiment
        self.description = description

    def prepare_for_deployment(self, registry):
        raise NotImplementedError

    def generate_export_path(self):
        path = self.key_within_experiment
        if (
            path is not None
            and hasattr(self, "extension")
            and self.extension
            and not path.endswith(self.extension)
        ):
            path += self.extension
        return path


class AssetCollection(AssetSpecification):
    """
    A base class for specifying a collection of assets.
    """

    pass


class InheritedAssets(AssetCollection):
    """
    Experimental: Provides a way to load assets from a previously deployed
    experiment into a new experiment.

    Parameters
    ----------

    path : str
        Path to a CSV file specifying the previous assets. This CSV file should come
        from the ``db/asset.csv`` file of an experiment export. The CSV file can
        optionally be customized by deleting rows corresponding to unneeded assets,
        or it can be merged with analogous CSV files from other experiments.

    key : str
        A string that is used to identify the source of the imported assets
        in the ``Asset.inherited_from`` attribute.
    """

    def __init__(self, path: str, key: str):
        raise NotImplementedError(
            "This code needs revisiting, the implementation has not been updated yet"
        )

    def prepare_for_deployment(self, registry):
        self.ingest_specification_to_db()

    def ingest_specification_to_db(self):
        clear_columns = ["parent"]
        with open(self.path, "r") as file:
            ingest_to_model(
                file,
                Asset,
                clear_columns=clear_columns,
                replace_columns=dict(
                    inherited=True,
                    inherited_from=self.key,
                ),
            )


@register_table
class Asset(AssetSpecification, SQLBase, SQLMixin):
    """
    Assets represent particular files (or sometimes collections of files) that
    are used within an experiment. It is encouraged to register things like
    audio files and video files as assets so that they can be managed
    appropriately by PsyNet's deploy and export mechanisms.

    Parameters
    ----------

    local_key : str
        A string identifier for the asset, for example ``"stimulus"``. If provided, this string identifier
        should together with ``parent`` and ``module_id`` uniquely identify that asset (i.e. no other asset
        should share that combination of properties).

    description : str
        An optional longer string that provides further documentation about the asset.

    is_folder : bool
        Whether the asset is a folder.

    data_type : str
        Experimental: the nature of the asset's data. Could be used to determine visualization methods etc.

    extension : str
        The file extension, if applicable.

    parent : object
        The object that 'owns' the asset, if applicable, for example a Participant or a Node.

    key_within_module : str
        A string that uniquely identifies the asset within a given module. If left unspecified,
        this will be automatically generated with reference to the ``parent`` and the ``local_key`` arguments.

    key_within_experiment : str
        A string that uniquely identifies the asset within a given experiment. If left unspecified,
        this will be automatically generated with reference to the ``key_within_module`` and the ``module_id`` arguments.

    module_id : str
        The module within which the asset is located.

    personal : bool
        Whether the asset is 'personal' and hence omitted from anonymous database exports.


    Attributes
    ----------

    needs_storage_backend : bool
        Whether the asset type needs a storage backend, e.g. a file server, or whether it can do without
        (e.g. in the case of an externally hosted resource accessible by a URL).

    psynet_version : str
        The version of PsyNet used to create the asset.

    deployment_id : str
        A string used to identify the particular experiment deployment.

    deposited: bool
        Whether the asset has been deposited yet.

    inherited : bool
        Whether the asset was inherited from a previous experiment, typically via the
        ``InheritedAssets`` functionality.

    inherited_from : str
        Identifies the source of an inherited asset.

    export_path : str
        A relative path that will be used by default when the asset is exported.

    participant_id : int
        ID of the participant who 'owns' the asset, if applicable.

    content_id : str
        A token used for checking whether the contents of two assets are equivalent.
        This takes various forms depending on the asset type.
        For a file, the ``content_id`` would typically be a hash;
        for an externally hosted asset, it would be the URL, etc.

    host_path : str
        The filepath used to host the asset within the storage repository, if applicable.

    url : str
        The URL that can be used to access the asset from the perspective of the experiment front-end.

    storage : AssetStorage
        The storage backend used for the asset.

    async_processes : list
        Lists all async processes that have been created for the asset, including completed ones.

    participant :
        If the parent is a ``Participant``, returns that participant.

    participants : list
        Lists all participants associated with the asset.

    trial :
        If the parent is a ``trial``, returns that trial.

    trials : list
        Lists all trials associated with the asset.

    node :
        If the parent is a ``Node``, returns that participant.

    nodes : list
        Lists all nodes associated with the asset.

    network :
        If the parent is a ``Network``, returns that participant.

    networks : list
        Lists all networks associated with the asset.

    errors : list
        Lists the errors associated with the asset.


    Linking assets to other database objects
    ----------------------------------------

    PsyNet assets may be linked to other database objects. There are two kinds of links that may be used.
    First, an asset may possess a *parent*. This parental relationship is strict in the sense that an asset
    may not possess more than one parent.

    However, in addition to the parental relationship, it is possible to link the asset to an arbitrary number
    of additional database objects. These latter links have a key-value construction, meaning that one can access
    a given asset by reference to a given key, for example: ``node.assets["response"]``.

    Importantly, the same asset can have different keys for different objects; for example, it might be the ``response``
    for one node, but the ``stimulus`` for another node. These latter relationships are instantiated with logic like
    the following:

    ::

        participant.assets["stimulus"] = my_asset
    """

    # Inheriting from ``SQLBase`` and ``SQLMixin`` means that the ``Asset`` object is stored in the database.
    # Inheriting from ``NullElt`` means that the ``Asset`` object can be placed in the timeline.

    __tablename__ = "asset"
    __extra_vars__ = {}

    id = SQLMixin.id

    # Remove default SQL columns
    failed = None
    failed_reason = None
    time_of_death = None

    needs_storage_backend = True

    psynet_version = Column(String)
    deployment_id = Column(String)
    deposited = Column(Boolean)
    inherited = Column(Boolean, default=False)
    inherited_from = Column(String)
    module_id = Column(String, index=True)
    local_key = Column(String)
    key_within_module = Column(String, index=True)
    key_within_experiment = Column(String, index=True)  # , onupdate="cascade")
    export_path = Column(String, index=True, unique=True)

    is_global = Column(Integer, ForeignKey("experiment.id"), index=True)

    parent = deferred(Column(PythonObject))
    module_state_id = Column(Integer, ForeignKey("module_state.id"), index=True)
    participant_id = Column(Integer, ForeignKey("participant.id"), index=True)
    trial_id = Column(Integer, ForeignKey("info.id"), index=True)
    node_id = Column(Integer, ForeignKey("node.id"), index=True)
    network_id = Column(Integer, ForeignKey("network.id"), index=True)

    description = Column(String)
    personal = Column(Boolean)
    content_id = Column(String)
    host_path = Column(String)
    url = Column(String)
    is_folder = Column(Boolean)
    data_type = Column(String)
    extension = Column(String)
    storage = Column(PythonObject)
    node_definition = Column(PythonObject)

    async_processes = relationship("AsyncProcess")

    module_state_links = relationship(
        "AssetModuleState",
        order_by="AssetModuleState.creation_time",
    )
    module_states = association_proxy("module_state_links", "module_state")

    participant_links = relationship(
        "AssetParticipant",
        order_by="AssetParticipant.creation_time",
    )
    participants = association_proxy("participant_links", "participant")

    trial_links = relationship(
        "AssetTrial",
        order_by="AssetTrial.creation_time",
    )
    trials = association_proxy("trial_links", "trial")

    node_links = relationship(
        "AssetNode",
        order_by="AssetNode.creation_time",
    )
    nodes = association_proxy("node_links", "node")

    network_links = relationship(
        "AssetNetwork",
        order_by="AssetNetwork.creation_time",
    )
    networks = association_proxy("network_links", "network")

    errors = relationship("ErrorRecord")

    @property
    def trial(self):
        from .trial.main import Trial

        self._raise_if_detached()
        if isinstance(self.parent, Trial):
            return self.parent

    @property
    def node(self):
        from .trial.main import Trial, TrialNode

        self._raise_if_detached()
        if isinstance(self.parent, Trial):
            return self.parent.node
        elif isinstance(self.parent, TrialNode):
            return self.parent

    @property
    def network(self):
        from .trial.main import Trial, TrialNetwork, TrialNode

        self._raise_if_detached()
        if isinstance(self.parent, (Trial, TrialNode)):
            return self.parent.network
        elif isinstance(self.parent, TrialNetwork):
            return self.parent

    @property
    def participant(self):
        from .participant import Participant

        self._raise_if_detached()
        if self.parent is None:
            return None
        elif isinstance(self.parent, Participant):
            return self.parent
        else:
            return self.parent.participant

    def _raise_if_detached(self):
        try:
            state = inspect(self)
        except NoInspectionAvailable:
            return
        if getattr(state, "detached", False):
            raise ValueError(
                "Cannot access an Asset attribute because this Asset instance is detached. "
                "Create the asset inside the per-participant timeline function that uses it "
                "(for example, show_trial or a for_loop/PageMaker function that calls Trial.cue), "
                "rather than reusing an Asset instance defined at module import time."
            )

    def update_metadata(
        self,
        parent,
        local_key: str,
        definition: Optional[dict] = None,
        module_id: Optional[str] = None,
    ):
        """
        Update parent-related metadata when linking an asset.

        Parent-related metadata includes the asset's parent object, its link key
        (``local_key``), the parent ``module_id`` used for key generation, and
        any trial/node definition used to parameterize on-demand assets.

        For undeposited assets, this overwrites parent/key/module/definition metadata
        so the asset is bound to the current owner. Deposited assets retain existing
        metadata to preserve their storage identity, but missing parent/link fields
        are filled in so exported paths remain unique.

        Parameters
        ----------
        parent : object
            The parent object to which the asset is linked.
        local_key : str
            The key under which the asset is linked.
        definition : dict, optional
            Trial or node definition used to populate on-demand asset arguments.
        module_id : str, optional
            Module identifier to set when missing.

        Returns
        -------
        Asset
            The updated asset instance.
        """
        self._raise_if_detached()

        if not self.deposited:
            self.parent = parent
            self.local_key = local_key
            if module_id is not None:
                self.module_id = module_id
            else:
                self.module_id = getattr(parent, "module_id", None)
            if definition is not None:
                self.receive_node_definition(definition)
            return self

        if self.parent is None:
            self.parent = parent
        if not self.local_key:
            self.local_key = local_key
        if self.module_id is None:
            if module_id is not None:
                self.module_id = module_id
            else:
                self.module_id = getattr(parent, "module_id", None)

        return self

    @property
    def trial_maker(self):
        from psynet.experiment import get_trial_maker

        return get_trial_maker(self.trial_maker_id)

    @classproperty
    def experiment_class(cls):  # noqa
        from .experiment import import_local_experiment

        return import_local_experiment()["class"]

    @classproperty
    def registry(cls):  # noqa
        return cls.experiment_class.assets

    @classproperty
    def default_storage(cls):  # noqa
        return cls.registry.storage

    def __init__(
        self,
        *,
        local_key=None,
        key_within_module=None,
        key_within_experiment=None,
        description=None,
        is_folder=False,
        data_type=None,
        extension=None,
        parent=None,
        module_id=None,
        personal=False,
    ):
        self.deposit_on_the_fly = True
        self.key_within_module = key_within_module

        from . import __version__ as psynet_version

        self.psynet_version = psynet_version
        self.is_folder = is_folder

        self.extension = extension if extension else self.get_extension()

        if data_type is None:
            data_type = self.infer_data_type()

        self.data_type = data_type
        self.parent = parent

        from psynet.participant import Participant
        from psynet.trial.main import Trial, TrialNetwork, TrialNode

        if isinstance(parent, Participant):
            self.participant_id = parent.id
        elif isinstance(parent, Trial):
            self.trial_id = parent.id
        elif isinstance(parent, TrialNode):
            self.node_id = parent.id
        elif isinstance(parent, TrialNetwork):
            self.network_id = parent.id

        if module_id:
            self.module_id = module_id
        else:
            if self.parent:
                self.module_id = self.parent.module_id

        if self.participant:
            if self.participant.module_state:
                self.module_state = self.participant.module_state

        self.personal = personal

        super().__init__(
            local_key, key_within_module, key_within_experiment, description
        )

    def get_ancestors(self):
        return {
            "network": self.network.id if self.network else None,
            "node": self.node.id if self.node else None,
            "degree": self.node.degree if hasattr(self.node, "degree") else None,
            "trial": self.trial.id if self.trial else None,
            "participant": self.participant.id if self.participant else None,
        }

    def ensure_keys_and_paths(self):
        """
        Fill in missing key fields and derived paths for the asset.

        For deposited assets, this method preserves existing ``host_path``/``url`` values
        (and only fills them if missing) so the storage identity does not change.
        """
        if self.key_within_module is None:
            self.key_within_module = self.generate_key_within_module()

        if self.key_within_experiment is None:
            self.key_within_experiment = self.generate_key_within_experiment()

        if not self.local_key and self.key_within_module:
            self.local_key = self.key_within_module

        if not self.deposited:
            self.host_path = self.generate_host_path()
            self.export_path = self.generate_export_path()
            self.url = self.get_url()
            return

        host_path_was_missing = self.host_path is None
        if host_path_was_missing:
            self.host_path = self.generate_host_path()

        if self.export_path is None:
            self.export_path = self.generate_export_path()

        if self.url is None or host_path_was_missing:
            self.url = self.get_url()

    def set_keys(self):
        """
        Deprecated. Use :meth:`ensure_keys_and_paths` instead.
        """
        warnings.warn(
            "Asset.set_keys is deprecated; use Asset.ensure_keys_and_paths instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.ensure_keys_and_paths()

    def generate_key_within_experiment(self):
        if self.module_id is None:
            base = "common"
        else:
            base = self.module_id

        return base + "/" + self.key_within_module

    def generate_key_within_module(self):
        return os.path.join(
            self.generate_key_within_module_parents(),
            self.generate_key_within_module_child(),
        )

    def generate_key_within_module_parents(self):
        ids = []
        if self.participant:
            ids.append(f"participants/participant_{self.participant.id}")
        elif self.node:
            ids.append("nodes")
        return "/".join(ids)

    def generate_key_within_module_child(self):
        ids = self.generate_key_within_module_child_ids()

        if self.local_key:
            ids.append(f"{self.local_key}")

        return "__".join(ids)

    def generate_key_within_module_child_ids(self):
        from psynet.trial.static import StaticNetwork

        ancestors = self.get_ancestors()

        if self.network and isinstance(self.network, StaticNetwork):
            id_types = ["node", "trial"]
        else:
            id_types = ["network", "degree", "node", "trial"]

        return [
            f"{id_type}_{ancestors[id_type]}"
            for id_type in id_types
            if ancestors[id_type] is not None
        ]

    def consume(self, experiment, participant):
        if not self.module_id:
            self.module_id = participant.module_id
        self.ensure_keys_and_paths()
        if self.deposit_on_the_fly:
            self.deposit()

    def infer_data_type(self):
        if self.extension in ["wav", "mp3"]:
            return "audio"
        elif self.extension in ["mp4", "avi"]:
            return "video"
        else:
            return None

    def get_extension(self):
        raise NotImplementedError

    def prepare_for_deployment(self, registry):
        """Runs in advance of the experiment being deployed to the remote server."""
        self.deposit(self.default_storage)

    def deposit(
        self,
        storage=None,
        async_: bool = False,
        delete_input: bool = False,
    ):
        """

        Parameters
        ----------
        storage :
            If set to an ``AssetStorage`` object, the asset will be deposited to the provided storage location
            rather than defaulting to the Experiment class's storage location.

        async_ :
            If set to ``True``, then the asset deposit will be performed asynchronously and the program's
            execution will continue without waiting for the deposit to complete. It is sensible to
            set this to ``True`` if you see that the participant interface is being held up noticeably by
            waiting for the deposit to complete.

        delete_input :
            If set to ``True``, then the input file will be deleted after it has been deposited.
        """
        try:
            if storage is None:
                storage = self.default_storage
            self.storage = storage

            self.deployment_id = self.registry.deployment_id
            self.content_id = self.get_content_id()

            self.ensure_keys_and_paths()
            db.session.add(self)

            if self.parent:
                assert self.local_key
                _local_key = self.local_key
                self.parent.assets[_local_key] = self

                ancestors = self.get_ancestors()
                self.network_id = ancestors["network"]
                self.node_id = ancestors["node"]
                self.trial_id = ancestors["trial"]
                self.participant_id = ancestors["participant"]

            # Note: performing the deposit cues post-deposit actions as well (e.g. async_post_trial),
            # which may rely on the asset being in its complete state. Any information that may be needed
            # by these post-deposit actions must be saved before this step.
            self._deposit(self.storage, async_, delete_input)

            if not self.content_id:
                self.content_id = self.get_content_id()

            return self

        finally:
            pass

    def _deposit(self, storage: "AssetStorage", async_: bool, delete_input: bool):
        """
        Performs the actual deposit, confident that no duplicates exist.

        Returns
        -------

        Returns ``True`` if the deposit has been completed,
        or ``False`` if the deposit has yet to be completed,
        typically because it is being performed in an asynchronous process
        which will take responsibility for marking the deposit as complete
        in due course.
        """
        raise NotImplementedError

    def delete_input(self):
        """
        Deletes the input file(s) that make(s) up the asset.
        """
        raise NotImplementedError

    def get_content_id(self):
        raise NotImplementedError

    def generate_host_path(self):
        raise NotImplementedError

    def export(self, path, ssh_host=None, ssh_user=None, local=False):
        try:
            self.storage.export(
                self, path, ssh_host=ssh_host, ssh_user=ssh_user, local=local
            )
        except Exception:
            from .command_line import log

            log(f"Failed to export the asset {self.id} to path {path}.")
            raise

    def export_subfile(self, subfile, path):
        assert self.is_folder
        try:
            self.storage.export_subfile(self, subfile, path)
        except Exception:
            from .command_line import log

            log(
                f"Failed to export the subfile {subfile} from asset {self.id} to path {path}."
            )
            raise

    def export_subfolder(self, subfolder, path):
        try:
            self.storage.export_subfolder(self, subfolder, path)
        except Exception:
            from .command_line import log

            log(
                f"Failed to export the subfolder {subfolder} from asset {self.id} to path {path}."
            )
            raise

    def receive_node_definition(self, definition):
        self.node_definition = definition

    def read_text(self):
        assert not self.is_folder
        with tempfile.NamedTemporaryFile() as f:
            self.export(f.name)
            with open(f.name, "r") as reader:
                return reader.read()


class AssetLink:
    """
    These objects define many-to-many mappings between assets and other database objects.
    When we write something like ``participant.assets["stimulus"] = my_asset``,
    this creates an object subclassing ``AssetLink`` to represent that relationship.
    """

    id = None
    failed = None
    failed_reason = None
    time_of_death = None

    local_key = Column(String, primary_key=True)

    @declared_attr
    def asset_id(cls):
        return Column(Integer, ForeignKey("asset.id"), primary_key=True)

    def __init__(self, local_key, asset):
        self.local_key = local_key
        self.asset = asset


@register_table
class AssetModuleState(AssetLink, SQLBase, SQLMixin):
    __tablename__ = "asset_module_state"

    module_state_id = Column(Integer, ForeignKey("module_state.id"), primary_key=True)
    module_state = relationship(
        "psynet.timeline.ModuleState", back_populates="asset_links"
    )

    asset = relationship("Asset", back_populates="module_state_links")


@register_table
class AssetParticipant(AssetLink, SQLBase, SQLMixin):
    __tablename__ = "asset_participant"

    participant_id = Column(Integer, ForeignKey("participant.id"), primary_key=True)
    participant = relationship(
        "psynet.participant.Participant", back_populates="asset_links"
    )

    asset = relationship("Asset", back_populates="participant_links")


@register_table
class AssetTrial(AssetLink, SQLBase, SQLMixin):
    __tablename__ = "asset_trial"

    trial_id = Column(Integer, ForeignKey("info.id"), primary_key=True)
    trial = relationship("psynet.trial.main.Trial", back_populates="asset_links")

    asset = relationship("Asset", back_populates="trial_links")


@register_table
class AssetNode(AssetLink, SQLBase, SQLMixin):
    __tablename__ = "asset_node"

    node_id = Column(Integer, ForeignKey("node.id"), primary_key=True)
    node = relationship("TrialNode", back_populates="asset_links")

    asset = relationship(
        "Asset",
        back_populates="node_links",
    )


@register_table
class AssetNetwork(AssetLink, SQLBase, SQLMixin):
    __tablename__ = "asset_network"

    network_id = Column(Integer, ForeignKey("network.id"), primary_key=True)
    network = relationship("TrialNetwork", back_populates="asset_links")

    asset = relationship(
        "Asset",
        back_populates="network_links",
    )


class ManagedAsset(Asset):
    """
    This is a parent class for assets that are actively 'managed' by PsyNet. Active managing means that PsyNet takes
    responsibility for storing the asset in its own storage repositories. This class is not generally instantiated
    directly, but is instead instantiated via its subclasses.

    Parameters
    ----------

    input_path : str
        Path to the file/folder from which the asset is to be created.

    local_key : str
        A string identifier for the asset, for example ``"stimulus"``. If provided, this string identifier
        should together with ``parent`` and ``module_id`` should uniquely identify that asset (i.e. no other asset
        should share that combination of properties).

    description : str
        An optional longer string that provides further documentation about the asset.

    is_folder : bool
        Whether the asset is a folder.

    data_type : str
        Experimental: the nature of the asset's data. Could be used to determine visualization methods etc.

    extension : str
        The file extension, if applicable.

    parent : object
        The object that 'owns' the asset, if applicable, for example a Participant or a Node.

    key_within_module : str
        An optional key that uniquely identifies the asset within a given module. If left unspecified,
        this will be automatically generated with reference to the ``parent`` and the ``local_key`` arguments.

    key_within_experiment : str
        A string that uniquely identifies the asset within a given experiment. If left unspecified,
        this will be automatically generated with reference to the ``key_within_module`` and the ``module_id`` arguments.

    module_id : str
        Identifies the module with which the asset should be associated. If left blank, PsyNet will attempt to
        infer the ``module_id`` from the ``parent`` parameter, if provided.

    personal : bool
        Whether the asset is 'personal' and hence omitted from anonymous database exports.

    obfuscate : int
        Determines the extent to which the asset's generated URL should be obfuscated. By default, ``obfuscate=1``,
        which means that the URL contains a human-readable component containing useful metadata (e.g the participant
        ID), but also contains a randomly generated string so that malicious agents cannot retrieve arbitrary assets
        by guessing URLs. If ``obfuscate=0``, then the randomly generated string is not added. If ``obfuscate=2``,
        then the human-readable component is omitted, and only the random portion is kept. This might be useful in
        cases where you're worried about participants cheating on the experiment by looking at file URLs.

    Attributes
    ----------

    md5_contents : str
        Contains an automatically generated MD5 hash of the object's contents, where 'contents' is liberally defined;
        it could mean hashing the file itself, or hashing the arguments of the function used to generate that file.

    size_mb : float
        The size of the asset's file(s) (in MB).

    deposit_time_sec : float
        The time it took to deposit the asset.

    needs_storage_backend : bool
        Whether the asset type needs a storage backend, e.g. a file server, or whether it can do without
        (e.g. in the case of an externally hosted resource accessible by a URL).

    psynet_version : str
        The version of PsyNet used to create the asset.

    deployment_id : str
        A string used to identify the particular experiment deployment.

    deposited: bool
        Whether the asset has been deposited yet.

    inherited : bool
        Whether the asset was inherited from a previous experiment, typically via the
        ``InheritedAssets`` functionality.

    inherited_from : str
        Identifies the source of an inherited asset.

    export_path : str
        A relative path constructed from the key that will be used by default when the asset is exported.

    participant_id : int
        ID of the participant who 'owns' the asset, if applicable.

    content_id : str
        A token used for checking whether the contents of two assets are equivalent.
        This takes various forms depending on the asset type.
        For a file, the ``content_id`` would typically be a hash;
        for an externally hosted asset, it would be the URL, etc.

    host_path : str
        The filepath used to host the asset within the storage repository, if applicable.

    url : str
        The URL that can be used to access the asset from the perspective of the experiment front-end.

    storage : AssetStorage
        The storage backend used for the asset.

    async_processes : list
        Lists all async processes that have been created for the asset, including completed ones.

    participant :
        If the parent is a ``Participant``, returns that participant.

    participants : list
        Lists all participants associated with the asset.

    trial :
        If the parent is a ``trial``, returns that trial.

    trials : list
        Lists all trials associated with the asset.

    node :
        If the parent is a ``Node``, returns that participant.

    nodes : list
        Lists all nodes associated with the asset.

    network :
        If the parent is a ``Network``, returns that participant.

    networks : list
        Lists all networks associated with the asset.

    errors : list
        Lists the errors associated with the asset.


    Linking assets to other database objects
    ----------------------------------------

    PsyNet assets may be linked to other database objects. There are two kinds of links that may be used.
    First, an asset may possess a *parent*. This parental relationship is strict in the sense that an asset
    may not possess more than one parent.

    However, in addition to the parental relationship, it is possible to link the asset to an arbitrary number
    of additional database objects. These latter links have a key-value construction, meaning that one can access
    a given asset by reference to a given key, for example: ``node.assets["response"]``.

    Importantly, the same asset can have different keys for different objects; for example, it might be the ``response``
    for one node, but the ``stimulus`` for another node. These latter relationships are instantiated with logic like
    the following:

    ::

        participant.assets["stimulus"] = my_asset
    """

    input_path = Column(String)
    obfuscate = Column(Integer)
    md5_contents = Column(String)
    size_mb = Column(Float)
    deposit_time_sec = Column(Float)

    def __init__(
        self,
        input_path: str,
        *,
        local_key=None,
        key_within_module=None,
        key_within_experiment=None,
        description=None,
        is_folder=None,
        data_type=None,
        extension=None,
        parent=None,
        module_id=None,
        personal=False,
        obfuscate=1,  # 0: no obfuscation; 1: can't guess URL; 2: can't guess content
    ):
        self.deposited = False
        self.input_path = str(input_path)
        self.obfuscate = obfuscate

        if is_folder is None:
            is_folder = os.path.isdir(input_path)

        super().__init__(
            local_key=local_key,
            key_within_module=key_within_module,
            key_within_experiment=key_within_experiment,
            is_folder=is_folder,
            description=description,
            data_type=data_type,
            extension=extension,
            module_id=module_id,
            parent=parent,
            personal=personal,
        )

    def get_content_id(self):
        return self.get_md5_contents()

    def get_md5_contents(self):
        return self._get_md5_contents(self.input_path, self.is_folder)

    @cache
    def _get_md5_contents(self, path, is_folder):
        f = md5_directory if is_folder else md5_file
        return f(path)

    def get_extension(self):
        return get_extension(self.input_path)

    def _deposit(self, storage: "AssetStorage", async_: bool, delete_input: bool):
        if self.needs_storage_backend and isinstance(storage, NoStorage):
            raise RuntimeError(
                "Cannot deposit this asset "
                f"(type = {type(self).__name__}, id = {self.id}) "
                "without an asset storage backend. "
                "Please add one to your experiment class, for example by writing "
                "asset_storage = S3Storage('your-s3-bucket', 'your-subdirectory') "
                "in your experiment class."
            )

        # ensure_keys_and_paths() is called by deposit() before _deposit().
        self.storage.update_asset_metadata(self)

        if self._needs_depositing():
            time_start = time.perf_counter()

            self.prepare_input()

            self.size_mb = self.get_size_mb()
            self.md5_contents = self.get_md5_contents()

            storage.receive_deposit(self, self.host_path, async_, delete_input)

            time_end = time.perf_counter()

            self.deposit_time_sec = time_end - time_start
        else:
            self.deposited = True

    def prepare_input(self):
        pass

    def _needs_depositing(self):
        return True

    def after_deposit(self):
        # logger.info("Calling after_deposit.")
        if self.trial:
            logger.info(
                "Calling check_if_can_run_async_post_trial as part of after_deposit."
            )
            self.trial.check_if_can_run_async_post_trial()
            self.trial.check_if_can_mark_as_finalized()

    def get_url(self):
        return self.storage.get_url(self.host_path)

    def delete_input(self):
        if self.is_folder:
            shutil.rmtree(self.input_path)
        else:
            remove(self.input_path)

    def get_size_mb(self):
        if self.is_folder:
            return get_folder_size_mb(self.input_path)
        else:
            return get_file_size_mb(self.input_path)

    def generate_host_path(self):
        raise NotImplementedError

    @staticmethod
    def generate_uuid():
        return str(uuid.uuid4())


class ExperimentAsset(ManagedAsset):
    """
    The ``ExperimentAsset`` class is one of the most commonly used Asset classes. It refers to assets that are
    specific to the current experiment deployment. This would typically mean assets that are generated *during the
    course* of the experiment, for example recordings from a singer, or stimuli generated on the basis of
    participant responses.

    Examples
    --------

    ::

        import tempfile

        with tempfile.NamedTemporaryFile("w") as file:
            file.write(f"Your message here")
            asset = ExperimentAsset(
                local_key="my_message",
                input_path=file.name,
                extension=".txt",
                parent=participant,
            )
            asset.deposit()

    Parameters
    ----------

    input_path : str
        Path to the file/folder from which the asset is to be created.

    local_key : str
        A string identifier for the asset, for example ``"stimulus"``. If provided, this string identifier
        should together with ``parent`` and ``module_id`` should uniquely identify that asset (i.e. no other asset
        should share that combination of properties).

    description : str
        An optional longer string that provides further documentation about the asset.

    is_folder : bool
        Whether the asset is a folder.

    data_type : str
        Experimental: the nature of the asset's data. Could be used to determine visualization methods etc.

    extension : str
        The file extension, if applicable.

    parent : object
        The object that 'owns' the asset, if applicable, for example a Participant or a Node.

    key_within_module : str
        An optional key that uniquely identifies the asset within a given module. If left unspecified,
        this will be automatically generated with reference to the ``parent`` and the ``local_key`` arguments.

    key_within_experiment : str
        A string that uniquely identifies the asset within a given experiment. If left unspecified,
        this will be automatically generated with reference to the ``key_within_module`` and the ``module_id`` arguments.

    module_id : str
        Identifies the module with which the asset should be associated. If left blank, PsyNet will attempt to
        infer the ``module_id`` from the ``parent`` parameter, if provided.

    personal : bool
        Whether the asset is 'personal' and hence omitted from anonymous database exports.

    obfuscate : int
        Determines the extent to which the asset's generated URL should be obfuscated. By default, ``obfuscate=1``,
        which means that the URL contains a human-readable component containing useful metadata (e.g the participant
        ID), but also contains a randomly generated string so that malicious agents cannot retrieve arbitrary assets
        by guessing URLs. If ``obfuscate=0``, then the randomly generated string is not added. If ``obfuscate=2``,
        then the human-readable component is omitted, and only the random portion is kept. This might be useful in
        cases where you're worried about participants cheating on the experiment by looking at file URLs.

    Attributes
    ----------

    needs_storage_backend : bool
        Whether the asset type needs a storage backend, e.g. a file server, or whether it can do without
        (e.g. in the case of an externally hosted resource accessible by a URL).

    psynet_version : str
        The version of PsyNet used to create the asset.

    deployment_id : str
        A string used to identify the particular experiment deployment.

    deposited: bool
        Whether the asset has been deposited yet.

    inherited : bool
        Whether the asset was inherited from a previous experiment, typically via the
        ``InheritedAssets`` functionality.

    inherited_from : str
        Identifies the source of an inherited asset.

    export_path : str
        A relative path constructed that will be used by default when the asset is exported.

    participant_id : int
        ID of the participant who 'owns' the asset, if applicable.

    content_id : str
        A token used for checking whether the contents of two assets are equivalent.
        This takes various forms depending on the asset type.
        For a file, the ``content_id`` would typically be a hash;
        for an externally hosted asset, it would be the URL, etc.

    host_path : str
        The filepath used to host the asset within the storage repository, if applicable.

    url : str
        The URL that can be used to access the asset from the perspective of the experiment front-end.

    storage : AssetStorage
        The storage backend used for the asset.

    async_processes : list
        Lists all async processes that have been created for the asset, including completed ones.

    participant :
        If the parent is a ``Participant``, returns that participant.

    participants : list
        Lists all participants associated with the asset.

    trial :
        If the parent is a ``trial``, returns that trial.

    trials : list
        Lists all trials associated with the asset.

    node :
        If the parent is a ``Node``, returns that participant.

    nodes : list
        Lists all nodes associated with the asset.

    network :
        If the parent is a ``Network``, returns that participant.

    networks : list
        Lists all networks associated with the asset.

    errors : list
        Lists the errors associated with the asset.


    Linking assets to other database objects
    ----------------------------------------

    PsyNet assets may be linked to other database objects. There are two kinds of links that may be used.
    First, an asset may possess a *parent*. This parental relationship is strict in the sense that an asset
    may not possess more than one parent.

    However, in addition to the parental relationship, it is possible to link the asset to an arbitrary number
    of additional database objects. These latter links have a key-value construction, meaning that one can access
    a given asset by reference to a given key, for example: ``node.assets["response"]``.

    Importantly, the same asset can have different keys for different objects; for example, it might be the ``response``
    for one node, but the ``stimulus`` for another node. These latter relationships are instantiated with logic like
    the following:

    ::

        participant.assets["stimulus"] = my_asset
    """

    folder = "experiments"

    def generate_path(self):
        path = self.obfuscate_key(self.key_within_experiment)
        if self.extension:
            path += self.extension
        return path

    def generate_host_path(self):
        return os.path.join(self.folder, self.deployment_id, self.generate_path())

    def obfuscate_key(self, key):
        random = self.generate_uuid()

        if self.obfuscate == 0:
            return key
        elif self.obfuscate == 1:
            key += "__" + random
        elif self.obfuscate == 2:
            key = "private/" + random
        else:
            raise ValueError(f"Invalid value of obfuscate: {self.obfuscate}")

        return key


class CachedAsset(ManagedAsset):
    """
    The classic use of a ``CachedAsset`` would be to store some kind of stimulus that is pre-defined in advance of
    experiment launch. For example:

    ::

         asset = CachedAsset(
            key_within_module="bier",
            input_path="bier.wav",
            description="A recording of someone saying 'bier'",
         )

    Cached assets are most commonly instantiated by passing them to the ``assets`` arguments of modules or nodes
    when defining the Experiment timeline. PsyNet compiles these assets together before experiment deployment
    and makes sure they are uploaded if necessary.

    In contrast to Experiment Assets, Cached Assets are shared between different experiments, so as to avoid
    duplicating time-consuming file generation or upload routines. The cached assets are stored in the selected
    asset storage back-end, and if PsyNet detects that the requested asset exists already then it will skip
    creating/uploading that asset. Under the hood there is some special logic to ensure that the caches are invalidated
    if the file content has changed.

    Parameters
    ----------

    input_path : str
        Path to the file/folder from which the asset is to be created.

    local_key : str
        A string identifier for the asset, for example ``"stimulus"``. If provided, this string identifier
        should together with ``parent`` and ``module_id`` should uniquely identify that asset (i.e. no other asset
        should share that combination of properties).

    description : str
        An optional longer string that provides further documentation about the asset.

    is_folder : bool
        Whether the asset is a folder.

    data_type : str
        Experimental: the nature of the asset's data. Could be used to determine visualization methods etc.

    extension : str
        The file extension, if applicable.

    parent : object
        The object that 'owns' the asset, if applicable, for example a Participant or a Node.

    key_within_module : str
        An optional key that uniquely identifies the asset within a given module. If left unspecified,
        this will be automatically generated with reference to the ``parent`` and the ``local_key`` arguments.

    key_within_experiment : str
        A string that uniquely identifies the asset within a given experiment. If left unspecified,
        this will be automatically generated with reference to the ``key_within_module`` and the ``module_id`` arguments.

    module_id : str
        Identifies the module with which the asset should be associated. If left blank, PsyNet will attempt to
        infer the ``module_id`` from the ``parent`` parameter, if provided.

    personal : bool
        Whether the asset is 'personal' and hence omitted from anonymous database exports.

    obfuscate : int
        Determines the extent to which the asset's generated URL should be obfuscated. By default, ``obfuscate=1``,
        which means that the URL contains a human-readable component containing useful metadata (e.g the participant
        ID), but also contains a randomly generated string so that malicious agents cannot retrieve arbitrary assets
        by guessing URLs. If ``obfuscate=0``, then the randomly generated string is not added. If ``obfuscate=2``,
        then the human-readable component is omitted, and only the random portion is kept. This might be useful in
        cases where you're worried about participants cheating on the experiment by looking at file URLs.

    Attributes
    ----------

    md5_contents : str
        Contains an automatically generated MD5 hash of the object's contents, where 'contents' is liberally defined;
        it could mean hashing the file itself, or hashing the arguments of the function used to generate that file.

    size_mb : float
        The size of the asset's file(s) (in MB).

    deposit_time_sec : float
        The time it took to deposit the asset.

    needs_storage_backend : bool
        Whether the asset type needs a storage backend, e.g. a file server, or whether it can do without
        (e.g. in the case of an externally hosted resource accessible by a URL).

    psynet_version : str
        The version of PsyNet used to create the asset.

    deployment_id : str
        A string used to identify the particular experiment deployment.

    deposited: bool
        Whether the asset has been deposited yet.

    inherited : bool
        Whether the asset was inherited from a previous experiment, typically via the
        ``InheritedAssets`` functionality.

    inherited_from : str
        Identifies the source of an inherited asset.

    export_path : str
        A relative path that will be used by default when the asset is exported.

    participant_id : int
        ID of the participant who 'owns' the asset, if applicable.

    content_id : str
        A token used for checking whether the contents of two assets are equivalent.
        This takes various forms depending on the asset type.
        For a file, the ``content_id`` would typically be a hash;
        for an externally hosted asset, it would be the URL, etc.

    host_path : str
        The filepath used to host the asset within the storage repository, if applicable.

    url : str
        The URL that can be used to access the asset from the perspective of the experiment front-end.

    storage : AssetStorage
        The storage backend used for the asset.

    async_processes : list
        Lists all async processes that have been created for the asset, including completed ones.

    participant :
        If the parent is a ``Participant``, returns that participant.

    participants : list
        Lists all participants associated with the asset.

    trial :
        If the parent is a ``trial``, returns that trial.

    trials : list
        Lists all trials associated with the asset.

    node :
        If the parent is a ``Node``, returns that participant.

    nodes : list
        Lists all nodes associated with the asset.

    network :
        If the parent is a ``Network``, returns that participant.

    networks : list
        Lists all networks associated with the asset.

    errors : list
        Lists the errors associated with the asset.


    Linking assets to other database objects
    ----------------------------------------

    PsyNet assets may be linked to other database objects. There are two kinds of links that may be used.
    First, an asset may possess a *parent*. This parental relationship is strict in the sense that an asset
    may not possess more than one parent.

    However, in addition to the parental relationship, it is possible to link the asset to an arbitrary number
    of additional database objects. These latter links have a key-value construction, meaning that one can access
    a given asset by reference to a given key, for example: ``node.assets["response"]``.

    Importantly, the same asset can have different keys for different objects; for example, it might be the ``response``
    for one node, but the ``stimulus`` for another node. These latter relationships are instantiated with logic like
    the following:

    ::

        participant.assets["stimulus"] = my_asset
    """

    used_cache = Column(Boolean)

    @cached_property
    def cache_key(self):
        return self.get_md5_contents()

    def generate_host_path(self):
        key = self.key_within_experiment  # e.g. big-audio-file.wav
        cache_key = self.cache_key

        if self.obfuscate == 2:
            base = "private"
        else:
            base = key

        host_path = os.path.join("cached", base, cache_key)

        if self.type != "folder":
            host_path += self.extension

        return host_path

    def _needs_depositing(self):
        exists_in_cache = self.storage.check_cache(
            self.host_path, is_folder=self.is_folder
        )
        self.used_cache = exists_in_cache
        return not exists_in_cache

    def retrieve_contents(self):
        pass

    def delete_input(self):
        pass


class FunctionAssetMixin:
    """
    This Mixin is used to define Asset classes that create their assets not from input files but from functions
    that are called with a specified set of arguments. It is not to be instantiated directly.

    Parameters
    ----------

    function : callable
        A function responsible for generating the asset. The function should receive an argument called ``path``
        and create a file or a folder at that path. It can also receive additional arguments specified via the
        ``arguments`` parameter.

    arguments : dict
        An optional dictionary of arguments that should be passed to the function.

    Attributes
    ----------

    computation_time_sec : float
        The time taken to generate the asset.
    """

    # The following conditional logic in the column definitions is required
    # to prevent column conflict errors, see
    # https://docs.sqlalchemy.org/en/13/orm/extensions/declarative/inheritance.html#resolving-column-conflicts
    @declared_attr
    def function(cls):
        return cls.__table__.c.get("function", Column(PythonObject))

    @declared_attr
    def arguments(cls):
        return cls.__table__.c.get("arguments", deferred(Column(PythonDict)))

    @declared_attr
    def computation_time_sec(cls):
        return cls.__table__.c.get("computation_time_sec", Column(Float))

    def __init__(
        self,
        function,
        *,
        arguments: Optional[dict] = None,
        is_folder=False,
        description=None,
        data_type=None,
        extension=None,
        local_key: Optional[str] = None,
        key_within_module=None,
        key_within_experiment=None,
        module_id=None,
        parent=None,
        personal=False,
        obfuscate=1,  # 0: no obfuscation; 1: can't guess URL; 2: can't guess content
    ):
        if arguments is None:
            arguments = {}

        function, arguments = prepare_function_for_serialization(function, arguments)

        self.function = function
        self.arguments = arguments
        self.temp_dir = None
        self.input_path = None

        super().__init__(
            local_key=local_key,
            key_within_module=key_within_module,
            key_within_experiment=key_within_experiment,
            input_path=self.input_path,
            is_folder=is_folder,
            description=description,
            data_type=data_type,
            extension=extension,
            parent=parent,
            module_id=module_id,
            personal=personal,
            obfuscate=obfuscate,
        )

    def __del__(self):
        if hasattr(self, "temp_dir") and self.temp_dir:
            self.temp_dir.cleanup()

    def deposit(
        self,
        storage=None,
        async_: bool = False,
    ):
        self.input_path = self.generate_input_path()

        super().deposit(
            storage,
            async_,
            delete_input=True,
        )

    def generate_input_path(self):
        if self.is_folder:
            return tempfile.mkdtemp()
        else:
            suffix = self.extension if self.extension else ""
            return tempfile.NamedTemporaryFile(delete=False, suffix=suffix).name

    @property
    def instructions(self):
        """
        The 'instructions' that define how to create the asset.
        """
        return dict(function=self.function, arguments=self.arguments)

    def get_md5_instructions(self):
        return md5_object(self.instructions)

    def get_md5_contents(self):
        # TODO - consider whether this should be deleted
        if self.input_path is None:
            return None
        else:
            return super().get_md5_contents()

    def get_size_mb(self):
        if self.input_path is None:
            return None
        else:
            return super().get_size_mb()

    def prepare_input(self):
        time_start = time.perf_counter()

        self.function(path=self.input_path, **self.arguments)

        time_end = time.perf_counter()
        self.computation_time_sec = time_end - time_start

    def receive_node_definition(self, definition):
        super().receive_node_definition(definition)
        requested_args = get_args(self.function)
        for key, value in definition.items():
            if key in requested_args:
                self.arguments[key] = value


# class FunctionAsset(FunctionAssetMixin, ExperimentAsset):
#     # FunctionAssetMixin comes first in the inheritance hierarchy
#     # because we need to use its ``__init__`` method.
#     """
#
#     """
#     pass


class OnDemandAsset(FunctionAssetMixin, ExperimentAsset):
    """
    An on-demand asset is an asset whose files are not stored directly in any storage back-end, but instead
    are created on demand when the asset is requested. This creation is typically triggered by making a call
    to the asset's URL, accessible via the ``OnDemandAsset.url`` attribute.

    Parameters
    ----------

    function : callable
        A function responsible for generating the asset. The function should receive an argument called ``path``
        and create a file or a folder at that path. It can also receive additional arguments specified via the
        ``arguments`` parameter.

    local_key : str
        A string identifier for the asset, for example ``"stimulus"``. If provided, this string identifier
        should together with ``parent`` and ``module_id`` should uniquely identify that asset (i.e. no other asset
        should share that combination of properties).

    arguments : dict
        An optional dictionary of arguments that should be passed to the function.

    is_folder : bool
        Whether the asset is a folder.

    description : str
        An optional longer string that provides further documentation about the asset.

    data_type : str
        Experimental: the nature of the asset's data. Could be used to determine visualization methods etc.

    extension : str
        The file extension, if applicable.

    key_within_module : str
        An optional key that uniquely identifies the asset within a given module. If left unspecified,
        this will be automatically generated with reference to the ``parent`` and the ``local_key`` arguments.

    key_within_experiment : str
        A string that uniquely identifies the asset within a given experiment. If left unspecified,
        this will be automatically generated with reference to the ``key_within_module`` and the ``module_id`` arguments.

    module_id : str
        Identifies the module with which the asset should be associated. If left blank, PsyNet will attempt to
        infer the ``module_id`` from the ``parent`` parameter, if provided.

    parent : object
        The object that 'owns' the asset, if applicable, for example a Participant or a Node.

    personal : bool
        Whether the asset is 'personal' and hence omitted from anonymous database exports.

    obfuscate : int
        Determines the extent to which the asset's generated URL should be obfuscated. By default, ``obfuscate=1``,
        which means that the URL contains a human-readable component containing useful metadata (e.g the participant
        ID), but also contains a randomly generated string so that malicious agents cannot retrieve arbitrary assets
        by guessing URLs. If ``obfuscate=0``, then the randomly generated string is not added. If ``obfuscate=2``,
        then the human-readable component is omitted, and only the random portion is kept. This might be useful in
        cases where you're worried about participants cheating on the experiment by looking at file URLs.

    Attributes
    ----------

    secret : str
        A randomly generated string that is used to prevent malicious agents from guessing the asset's URL.
        TODO - check whether the URL obfuscation functionality makes this redundant.

    Attributes
    ----------

    computation_time_sec : float
        The time taken to generate the asset.
        TODO - check whether this is populated in practice.

    psynet_version : str
        The version of PsyNet used to create the asset.

    deployment_id : str
        A string used to identify the particular experiment deployment.

    deposited: bool
        Whether the asset has been deposited yet.

    inherited : bool
        Whether the asset was inherited from a previous experiment, typically via the
        ``InheritedAssets`` functionality.

    inherited_from : str
        Identifies the source of an inherited asset.

    export_path : str
        A relative path that will be used by default when the asset is exported.

    participant_id : int
        ID of the participant who 'owns' the asset, if applicable.

    content_id : str
        A token used for checking whether the contents of two assets are equivalent.
        This takes various forms depending on the asset type.
        For a file, the ``content_id`` would typically be a hash;
        for an externally hosted asset, it would be the URL, etc.

    host_path : str
        The filepath used to host the asset within the storage repository, if applicable.

    url : str
        The URL that can be used to access the asset from the perspective of the experiment front-end.

    storage : AssetStorage
        The storage backend used for the asset.

    async_processes : list
        Lists all async processes that have been created for the asset, including completed ones.

    participant :
        If the parent is a ``Participant``, returns that participant.

    participants : list
        Lists all participants associated with the asset.

    trial :
        If the parent is a ``trial``, returns that trial.

    trials : list
        Lists all trials associated with the asset.

    node :
        If the parent is a ``Node``, returns that participant.

    nodes : list
        Lists all nodes associated with the asset.

    network :
        If the parent is a ``Network``, returns that participant.

    networks : list
        Lists all networks associated with the asset.

    errors : list
        Lists the errors associated with the asset.


    Linking assets to other database objects
    ----------------------------------------

    PsyNet assets may be linked to other database objects. There are two kinds of links that may be used.
    First, an asset may possess a *parent*. This parental relationship is strict in the sense that an asset
    may not possess more than one parent.

    However, in addition to the parental relationship, it is possible to link the asset to an arbitrary number
    of additional database objects. These latter links have a key-value construction, meaning that one can access
    a given asset by reference to a given key, for example: ``node.assets["response"]``.

    Importantly, the same asset can have different keys for different objects; for example, it might be the ``response``
    for one node, but the ``stimulus`` for another node. These latter relationships are instantiated with logic like
    the following:

    ::

        participant.assets["stimulus"] = my_asset
    """

    secret = Column(String)

    needs_storage_backend = False

    def __init__(
        self,
        *,
        function,
        local_key=None,
        key_within_module: Optional[str] = None,
        key_within_experiment=None,
        arguments: Optional[dict] = None,
        is_folder: bool = False,
        description=None,
        data_type=None,
        extension=None,
        module_id: Optional[str] = None,
        parent=None,
        personal=False,
        obfuscate=1,  # 0: no obfuscation; 1: can't guess URL; 2: can't guess content
    ):
        super().__init__(
            function=function,
            local_key=local_key,
            key_within_module=key_within_module,
            key_within_experiment=key_within_experiment,
            arguments=arguments,
            is_folder=is_folder,
            description=description,
            data_type=data_type,
            extension=extension,
            module_id=module_id,
            parent=parent,
            personal=personal,
            obfuscate=obfuscate,
        )
        self.secret = uuid.uuid4()  # Used to protect unauthorized access

    @classproperty
    def default_storage(cls):  # noqa
        return NoStorage()

    def _needs_depositing(self):
        return False

    def generate_input_path(self):
        return None

    def export(self, path, **kwargs):
        self.function(path=path, **self.arguments)

    def export_subfile(self, subfile, path):
        assert self.is_folder
        with tempfile.TemporaryDirectory() as tempdir:
            self.export(tempdir)
            shutil.copyfile(tempdir + "/" + subfile, path)

    def export_subfolder(self, subfolder, path):
        assert self.is_folder
        with tempfile.TemporaryDirectory() as tempdir:
            self.export(tempdir)
            shutil.copytree(tempdir + "/" + subfolder, path)

    def get_url(self):
        # We need to flush to make sure that self.id is populated
        db.session.flush()
        return f"/on-demand-asset?id={self.id}&secret={self.secret}"

    def generate_host_path(self):
        return None


class FastFunctionAsset(OnDemandAsset):
    """
    .. deprecated:: 11.7.0
        Use ``OnDemandAsset`` instead.
    """

    def __init__(
        self,
        *,
        function,
        local_key=None,
        key_within_module: Optional[str] = None,
        key_within_experiment=None,
        arguments: Optional[dict] = None,
        is_folder: bool = False,
        description=None,
        data_type=None,
        extension=None,
        module_id: Optional[str] = None,
        parent=None,
        personal=False,
        obfuscate=1,  # 0: no obfuscation; 1: can't guess URL; 2: can't guess content
    ):
        warnings.warn(
            f"{self.__class__.__name__} is deprecated and will be removed in future versions. "
            f"Please use OnDemandAsset instead.",
            DeprecationWarning,
        )

        super().__init__(
            function=function,
            local_key=local_key,
            key_within_module=key_within_module,
            key_within_experiment=key_within_experiment,
            arguments=arguments,
            is_folder=is_folder,
            description=description,
            data_type=data_type,
            extension=extension,
            module_id=module_id,
            parent=parent,
            personal=personal,
            obfuscate=obfuscate,
        )


class CachedFunctionAsset(FunctionAssetMixin, CachedAsset):
    """
    A Cached Function Asset is a type of asset whose files are created by running a function, and whose outputs
    are stored in a general repository that is shared between multiple experiment deployments, to avoid
    redundant computation or file uploads.


    Parameters
    ----------

    function : callable
        A function responsible for generating the asset. The function should receive an argument called ``path``
        and create a file or a folder at that path. It can also receive additional arguments specified via the
        ``arguments`` parameter.

    local_key : str
        A string identifier for the asset, for example ``"stimulus"``. If provided, this string identifier
        should together with ``parent`` and ``module_id`` should uniquely identify that asset (i.e. no other asset
        should share that combination of properties).

    arguments : dict
        An optional dictionary of arguments that should be passed to the function.

    is_folder : bool
        Whether the asset is a folder.

    description : str
        An optional longer string that provides further documentation about the asset.

    data_type : str
        Experimental: the nature of the asset's data. Could be used to determine visualization methods etc.

    extension : str
        The file extension, if applicable.

    key_within_module : str
        An optional key that uniquely identifies the asset within a given module. If left unspecified,
        this will be automatically generated with reference to the ``parent`` and the ``local_key`` arguments.

    key_within_experiment : str
        A string that uniquely identifies the asset within a given experiment. If left unspecified,
        this will be automatically generated with reference to the ``key_within_module`` and the ``module_id`` arguments.

    module_id : str
        Identifies the module with which the asset should be associated. If left blank, PsyNet will attempt to
        infer the ``module_id`` from the ``parent`` parameter, if provided.

    parent : object
        The object that 'owns' the asset, if applicable, for example a Participant or a Node.

    personal : bool
        Whether the asset is 'personal' and hence omitted from anonymous database exports.

    obfuscate : int
        Determines the extent to which the asset's generated URL should be obfuscated. By default, ``obfuscate=1``,
        which means that the URL contains a human-readable component containing useful metadata (e.g the participant
        ID), but also contains a randomly generated string so that malicious agents cannot retrieve arbitrary assets
        by guessing URLs. If ``obfuscate=0``, then the randomly generated string is not added. If ``obfuscate=2``,
        then the human-readable component is omitted, and only the random portion is kept. This might be useful in
        cases where you're worried about participants cheating on the experiment by looking at file URLs.

    Attributes
    ----------

    computation_time_sec : float
        The time taken to generate the asset.

    md5_contents : str
        Contains an automatically generated MD5 hash of the object's contents, where 'contents' is liberally defined;
        it could mean hashing the file itself, or hashing the arguments of the function used to generate that file.

    size_mb : float
        The size of the asset's file(s) (in MB).

    deposit_time_sec : float
        The time it took to deposit the asset.

    needs_storage_backend : bool
        Whether the asset type needs a storage backend, e.g. a file server, or whether it can do without
        (e.g. in the case of an externally hosted resource accessible by a URL).

    psynet_version : str
        The version of PsyNet used to create the asset.

    deployment_id : str
        A string used to identify the particular experiment deployment.

    deposited: bool
        Whether the asset has been deposited yet.

    inherited : bool
        Whether the asset was inherited from a previous experiment, typically via the
        ``InheritedAssets`` functionality.

    inherited_from : str
        Identifies the source of an inherited asset.

    export_path : str
        A relative path that will be used by default when the asset is exported.

    participant_id : int
        ID of the participant who 'owns' the asset, if applicable.

    content_id : str
        A token used for checking whether the contents of two assets are equivalent.
        This takes various forms depending on the asset type.
        For a file, the ``content_id`` would typically be a hash;
        for an externally hosted asset, it would be the URL, etc.

    host_path : str
        The filepath used to host the asset within the storage repository, if applicable.

    url : str
        The URL that can be used to access the asset from the perspective of the experiment front-end.

    storage : AssetStorage
        The storage backend used for the asset.

    async_processes : list
        Lists all async processes that have been created for the asset, including completed ones.

    participant :
        If the parent is a ``Participant``, returns that participant.

    participants : list
        Lists all participants associated with the asset.

    trial :
        If the parent is a ``trial``, returns that trial.

    trials : list
        Lists all trials associated with the asset.

    node :
        If the parent is a ``Node``, returns that participant.

    nodes : list
        Lists all nodes associated with the asset.

    network :
        If the parent is a ``Network``, returns that participant.

    networks : list
        Lists all networks associated with the asset.

    errors : list
        Lists the errors associated with the asset.


    Linking assets to other database objects
    ----------------------------------------

    PsyNet assets may be linked to other database objects. There are two kinds of links that may be used.
    First, an asset may possess a *parent*. This parental relationship is strict in the sense that an asset
    may not possess more than one parent.

    However, in addition to the parental relationship, it is possible to link the asset to an arbitrary number
    of additional database objects. These latter links have a key-value construction, meaning that one can access
    a given asset by reference to a given key, for example: ``node.assets["response"]``.

    Importantly, the same asset can have different keys for different objects; for example, it might be the ``response``
    for one node, but the ``stimulus`` for another node. These latter relationships are instantiated with logic like
    the following:

    ::

        participant.assets["stimulus"] = my_asset
        db.session.commit()
    """

    @property
    def cache_key(self):
        return self.get_md5_instructions()


class ExternalAsset(Asset):
    """
    An External Asset is an asset that is not managed by PsyNet. This would typically mean some kind of file
    that is hosted on a remote web server and is accessible by a URL.

    Parameters
    ----------

    url : str
        The URL at which the external asset may be accessed.

    local_key : str
        A string identifier for the asset, for example ``"stimulus"``. If provided, this string identifier
        should together with ``parent`` and ``module_id`` uniquely identify that asset (i.e. no other asset
        should share that combination of properties).

    description : str
        An optional longer string that provides further documentation about the asset.

    is_folder : bool
        Whether the asset is a folder.

    data_type : str
        Experimental: the nature of the asset's data. Could be used to determine visualization methods etc.

    extension : str
        The file extension, if applicable.

    parent : object
        The object that 'owns' the asset, if applicable, for example a Participant or a Node.

    key_within_module : str
        A string that uniquely identifies the asset within a given module. If left unspecified,
        this will be automatically generated with reference to the ``parent`` and the ``local_key`` arguments.

    key_within_experiment : str
        A string that uniquely identifies the asset within a given experiment. If left unspecified,
        this will be automatically generated with reference to the ``key_within_module`` and the ``module_id`` arguments.

    module_id : str
        The module within which the asset is located.

    personal : bool
        Whether the asset is 'personal' and hence omitted from anonymous database exports.

    Attributes
    ----------

    psynet_version : str
        The version of PsyNet used to create the asset.

    deployment_id : str
        A string used to identify the particular experiment deployment.

    deposited: bool
        Whether the asset has been deposited yet.

    inherited : bool
        Whether the asset was inherited from a previous experiment, typically via the
        ``InheritedAssets`` functionality.

    inherited_from : str
        Identifies the source of an inherited asset.

    export_path : str
        A relative path that will be used by default when the asset is exported.

    participant_id : int
        ID of the participant who 'owns' the asset, if applicable.

    content_id : str
        A token used for checking whether the contents of two assets are equivalent.
        This takes various forms depending on the asset type.
        For a file, the ``content_id`` would typically be a hash;
        for an externally hosted asset, it would be the URL, etc.

    host_path : str
        The filepath used to host the asset within the storage repository, if applicable.

    url : str
        The URL that can be used to access the asset from the perspective of the experiment front-end.

    storage : AssetStorage
        The storage backend used for the asset.

    async_processes : list
        Lists all async processes that have been created for the asset, including completed ones.

    participant :
        If the parent is a ``Participant``, returns that participant.

    participants : list
        Lists all participants associated with the asset.

    trial :
        If the parent is a ``trial``, returns that trial.

    trials : list
        Lists all trials associated with the asset.

    node :
        If the parent is a ``Node``, returns that participant.

    nodes : list
        Lists all nodes associated with the asset.

    network :
        If the parent is a ``Network``, returns that participant.

    networks : list
        Lists all networks associated with the asset.

    errors : list
        Lists the errors associated with the asset.


    Linking assets to other database objects
    ----------------------------------------

    PsyNet assets may be linked to other database objects. There are two kinds of links that may be used.
    First, an asset may possess a *parent*. This parental relationship is strict in the sense that an asset
    may not possess more than one parent.

    However, in addition to the parental relationship, it is possible to link the asset to an arbitrary number
    of additional database objects. These latter links have a key-value construction, meaning that one can access
    a given asset by reference to a given key, for example: ``node.assets["response"]``.

    Importantly, the same asset can have different keys for different objects; for example, it might be the ``response``
    for one node, but the ``stimulus`` for another node. These latter relationships are instantiated with logic like
    the following:

    ::

        participant.assets["stimulus"] = my_asset
        db.session.commit()
    """

    def __init__(
        self,
        url,
        *,
        local_key=None,
        key_within_module=None,
        key_within_experiment=None,
        description=None,
        is_folder=False,
        data_type=None,
        extension=None,
        parent=None,
        module_id=None,
        personal=False,
    ):
        self.host_path = url
        self.url = url
        self.deposited = True

        super().__init__(
            local_key=local_key,
            key_within_module=key_within_module,
            key_within_experiment=key_within_experiment,
            is_folder=is_folder,
            description=description,
            data_type=data_type,
            extension=extension,
            module_id=module_id,
            parent=parent,
            personal=personal,
        )

    def get_extension(self):
        return get_extension(self.url)

    def _deposit(self, storage: "AssetStorage", async_: bool, delete_input: bool):
        pass

    @property
    def identifiers(self):
        return {
            **super().identifiers,
            "url": self.url,
        }

    def get_content_id(self):
        return self.url

    @classproperty
    def default_storage(cls):  # noqa
        return WebStorage()

    def delete_input(self):
        raise NotImplementedError

    def generate_host_path(self):
        return None

    def get_url(self):
        return self.url


class ExternalS3Asset(ExternalAsset):
    """
    Represents an external asset that is stored in an Amazon Web Services S3 bucket.
    """

    s3_bucket = Column(String)
    s3_key = Column(String)

    def __init__(
        self,
        *,
        s3_bucket: str,
        s3_key: str,
        local_key=None,
        key_within_module=None,
        key_within_experiment=None,
        is_folder=False,
        description=None,
        data_type=None,
        module_id=None,
        parent=None,
        personal=False,
    ):
        self.s3_bucket = s3_bucket
        self.s3_key = s3_key
        url = self.generate_url()

        super().__init__(
            url=url,
            is_folder=is_folder,
            description=description,
            data_type=data_type,
            local_key=local_key,
            module_id=module_id,
            key_within_module=key_within_module,
            key_within_experiment=key_within_experiment,
            parent=parent,
            personal=personal,
        )

    def generate_url(self):
        return f"https://s3.amazonaws.com/{self.s3_bucket}/{self.s3_key}"

    @property
    def identifiers(self):
        return {
            **super().identifiers,
            "s3_bucket": self.s3_bucket,
            "s3_key": self.s3_key,
        }

    @cached_property
    def default_storage(self):  # noqa
        return S3Storage(self.s3_bucket, root="")

    def delete_input(self):
        raise NotImplementedError


class AssetStorage:
    """
    Defines a storage back-end for storing assets.
    """

    heroku_compatible = True

    @property
    def experiment(self):
        from .experiment import get_experiment

        return get_experiment()

    @property
    def deployment_id(self):
        return self.experiment.deployment_id

    def on_every_launch(self):
        pass

    def update_asset_metadata(self, asset: Asset):
        pass

    def receive_deposit(self, asset, host_path: str, async_: bool, delete_input: bool):
        if async_:
            f = self._async__call_receive_deposit
        else:
            f = self._call_receive_deposit

        f(asset, host_path, delete_input)

    def _receive_deposit(self, asset: Asset, host_path: str):
        self.raise_not_implemented_error()

    def _call_receive_deposit(
        self,
        asset: Asset,
        host_path: str,
        delete_input: bool,  # , db_commit: bool = False
    ):
        # logger.info("Calling _call_receive_deposit...")
        # We include this for compatibility with threaded dispatching.
        # Without it, SQLAlchemy complains that the object has become disconnected
        # from the SQLAlchemy session. This command 'merges' it back into the session.
        asset = db.session.merge(asset)
        self._receive_deposit(asset, host_path)
        asset.deposited = True
        asset.after_deposit()

        if delete_input:
            asset.delete_input()

    def _async__call_receive_deposit(
        self, asset: Asset, host_path: str, delete_input: bool
    ):
        LocalAsyncProcess(
            self._call_receive_deposit,
            arguments=dict(
                asset=asset,
                host_path=host_path,
                delete_input=delete_input,
                # db_commit=True,
            ),
            asset=asset,
        )

    def export(self, asset, path, **kwargs):
        self.raise_not_implemented_error()

    def prepare_for_deployment(self):
        pass

    def get_url(self, host_path: str):
        self.raise_not_implemented_error()

    @staticmethod
    def raise_not_implemented_error():
        raise NotImplementedError(
            "If your experiment uses assets you must specify a storage back-end in your experiment class, "
            "typically by writing something like\n\n"
            "    asset_storage = LocalStorage()\n\n"
            "in your experiment class. You will probably need to add the following to your imports too:\n\n"
            "    from psynet.asset import LocalStorage"
        )

    def check_cache(self, host_path: str, is_folder: bool):
        """
        Checks whether the registry can find an asset cached at ``host_path``.
        The implementation is permitted to make optimizations for speed
        that may result in missed caches, i.e. returning ``False`` when
        the cache did actually exists. However, the implementation should
        only return ``True`` if it is certain that the asset cache exists.

        Returns
        -------

        ``True`` or ``False``.

        """
        raise NotImplementedError

    @classmethod
    def http_export(cls, asset, path):
        url = cls._prepare_url_for_http_export(asset.url)

        if asset.is_folder:
            cls._http_folder_export(url, path)
        else:
            cls._http_file_export(url, path)

    @staticmethod
    def _prepare_url_for_http_export(url):
        if not url.startswith("http"):
            host = get_from_config("host")
            if host == "0.0.0.0":
                prefix = "http://localhost:5000"
            else:
                prefix = host
            url = prefix + url
        return url

    def export_subfile(self, asset, subfile, path):
        url = asset.url + "/" + subfile
        url = self._prepare_url_for_http_export(url)
        self._http_file_export(url, path)

    def export_subfolder(self, asset, subfolder, path):
        raise RuntimeError(
            "export_subfolder is not supported for assets being exported over HTTP."
            "This is because the internet provides "
            "no standard way to list the contents of a folder hosted "
            "on an arbitrary web server. You can avoid this issue in future"
            "by listing each asset as a separate file."
        )

    @staticmethod
    def _http_folder_export(url, path):
        with open(path, "w") as f:
            f.write(
                "It is not possible to automatically export assets over HTTP "
                "with type='folder'. This is because the internet provides "
                "no standard way to list the contents of a folder hosted "
                "on an arbitrary web server. You can avoid this issue in the "
                "future by listing each asset as a separate file."
            )

    @staticmethod
    def _http_file_export(url, path):
        try:
            r = requests.get(url)
            if r.status_code != 200:
                raise ConnectionError(
                    f"Failed to download from the following URL: {url} "
                    f"(status code = {r.status_code})"
                )
            with open(path, "wb") as file:
                file.write(r.content)
        except Exception:
            print(
                f"An error occurred when trying to download from the following URL: {url}"
            )
            raise


class WebStorage(AssetStorage):
    """
    The notional storage back-end for external web-hosted assets.
    """

    def export(self, asset, path, **kwargs):
        self.http_export(asset, path)


class NoStorage(AssetStorage):
    """
    A 'null' storage back-end for assets that don't require any storage.
    """

    def _receive_deposit(self, asset, host_path: str):
        raise RuntimeError("Asset depositing is not supported by 'NoStorage' objects.")

    def update_asset_metadata(self, asset: Asset):
        pass


class LocalStorage(AssetStorage):
    """
    Stores assets in a local folder on the same computer that is running your Python code.
    This approach is suitable when you are running experiments on a single local machine (e.g.
    when doing fieldwork or laboratory-based data collection), and when you are deploying your
    experiments to your own remote web server via Docker. It is *not* appropriate if you
    deploy your experiments via Heroku, because Heroku deployments split the processing
    over multiple web servers, and these different web servers do not share the
    same file system.
    """

    label = "assets"
    heroku_compatible = False

    def __init__(self, root=None):
        """

        Parameters
        ----------
        root :
            Optional path to the directory to be used for storage.
            Tilde expansion (e.g. '~/psynet') is performed automatically.

        label :
            Label for the storage object.
        """
        super().__init__()

        self._initialized = False
        self._root = root

    def setup_files(self):
        if self.on_deployed_server() or deployment_info.read("is_local_deployment"):
            self._ensure_root_dir_exists()
            self._create_symlink()

    def prepare_for_deployment(self):
        self.setup_files()

    def on_every_launch(self):
        self.setup_files()

    @cached_property
    def root(self):
        """
        We defer the registration of the root until as late as possible
        to avoid circular imports when loading the experiment.
        """
        if self._root:
            return self._root
        else:
            # return "$HOME/psynet-data/assets"

            if deployment_info.read("is_ssh_deployment"):
                return "/psynet-data/assets"
            else:
                return os.path.expanduser("~/psynet-data/assets")

    def _ensure_root_dir_exists(self):
        from pathlib import Path

        Path(self.root).mkdir(parents=True, exist_ok=True)

    @property
    def local_path(self):
        return os.path.join("static", self.label)

    @property
    def public_path(self):
        """
        This is the publicly exposed path by which the web browser can access the storage registry.
        This corresponds to a (symlinked) directory inside the experiment directory.
        """
        return "/" + self.local_path

    def _create_symlink(self):
        try:
            unlink(self.local_path)
        except (FileNotFoundError, IsADirectoryError, PermissionError):
            # Path(self.local_path).rmdir()
            try:
                shutil.rmtree(self.local_path)
            except (FileNotFoundError, NotADirectoryError, PermissionError, OSError):
                pass

        makedirs("static", exist_ok=True)

        try:
            symlink(self.root, self.local_path)
        except FileExistsError:
            pass

    def update_asset_metadata(self, asset: Asset):
        host_path = asset.host_path
        file_system_path = self.get_file_system_path(host_path)
        asset.var.file_system_path = file_system_path

    @staticmethod
    @cache
    def sftp_connection(ssh_host, ssh_user):
        from dallinger.command_line.docker_ssh import get_sftp

        return get_sftp(ssh_host, user=ssh_user)

    @staticmethod
    @cache
    def ssh_executor(ssh_host, ssh_user):
        from dallinger.command_line.docker_ssh import Executor

        return Executor(ssh_host, user=ssh_user)

    def _receive_deposit(self, asset: Asset, host_path: str):
        file_system_path = self.get_file_system_path(host_path)

        if self.on_deployed_server() or deployment_info.read("is_local_deployment"):
            # We are depositing an asset that sits on the present server already,
            # so we can just copy it.

            makedirs(os.path.dirname(file_system_path), exist_ok=True)

            if asset.is_folder:
                shutil.copytree(
                    asset.input_path,
                    os.path.expanduser(file_system_path),
                    dirs_exist_ok=True,
                )
            else:
                shutil.copyfile(asset.input_path, os.path.expanduser(file_system_path))
        else:
            if deployment_info.read("is_ssh_deployment"):
                ssh_host = deployment_info.read("ssh_host")
                ssh_user = deployment_info.read("ssh_user")

                docker_host_path = (
                    self.ssh_host_home_dir(ssh_host, ssh_user) + file_system_path
                )

                if asset.is_folder:
                    self._put_folder(
                        asset.input_path,
                        docker_host_path,
                        ssh_host,
                        ssh_user,
                    )
                else:
                    self._put_file(
                        asset.input_path,
                        docker_host_path,
                        ssh_host,
                        ssh_user,
                    )
            else:
                raise NotImplementedError

        asset.deposited = True

        # return dict(
        #     url=os.path.abspath(file_system_path),
        # )

    def _put_file(self, input_path, dest_path, ssh_host, ssh_user):
        from io import BytesIO

        sftp = self.sftp_connection(ssh_host, ssh_user)

        self._mk_dir_tree(os.path.dirname(dest_path), ssh_host, ssh_user)
        with open(input_path, "rb") as file:
            sftp.putfo(BytesIO(file.read()), dest_path)

    def _put_folder(self, input_path, dest_path, ssh_host, ssh_user):
        from io import BytesIO

        sftp = self.sftp_connection(ssh_host, ssh_user)

        self._mk_dir_tree(dest_path, ssh_host, ssh_user)

        # Traverse the local directory
        for dirpath, dirnames, filenames in walk(input_path):
            # For each directory in the local structure, create it remotely
            for dirname in dirnames:
                local_path = os.path.join(dirpath, dirname)
                relative_path = os.path.relpath(local_path, input_path)
                remote_path = os.path.join(dest_path, relative_path)
                self._mk_dir_tree(remote_path, ssh_host, ssh_user)

            # For each file, copy it to the remote directory
            for filename in filenames:
                local_path = os.path.join(dirpath, filename)
                relative_path = os.path.relpath(local_path, input_path)
                remote_path = os.path.join(dest_path, relative_path)

                with open(local_path, "rb") as file:
                    sftp.putfo(BytesIO(file.read()), remote_path)

    def _mk_dir_tree(self, dir, ssh_host, ssh_user):
        executor = self.ssh_executor(ssh_host, ssh_user)
        executor.run(f'mkdir -p "{dir}"')

    def on_deployed_server(self):
        from psynet.experiment import in_deployment_package

        return in_deployment_package()

    def export(self, asset, path, ssh_host=None, ssh_user=None, local=False):
        if self.on_deployed_server() or local:
            self._export_via_copying(asset, path)
        elif ssh_host is not None:
            self._export_via_ssh(asset, path, ssh_host, ssh_user)
        else:
            AssetStorage.http_export(asset, path)

    def _export_via_ssh(self, asset, local_path, ssh_host=None, ssh_user=None):
        if ssh_host is None or ssh_user is None:
            raise ValueError(
                "To export via SSH you need to provide an ssh_host and ssh_user. If you are seeing this error "
                "it means that probably these values haven't been propagated properly through their caller functions."
            )
        docker_host_path = (
            self.ssh_host_home_dir(ssh_host, ssh_user) + asset.var.file_system_path
        )
        sftp = self.sftp_connection(ssh_host, ssh_user)
        paramiko.sftp_file.SFTPFile.MAX_REQUEST_SIZE = pow(
            2, 22
        )  # 4 MB per chunk, prevents SFTPError('Garbage packet received')
        sftp.get(docker_host_path, local_path)

    def _export_via_copying(self, asset: Asset, path):
        from_ = self.get_file_system_path(asset.host_path)
        to_ = path
        if asset.is_folder:
            shutil.copytree(from_, to_, dirs_exist_ok=True)
        else:
            shutil.copyfile(from_, to_)

    def export_subfile(self, asset, subfile, path):
        if self.on_deployed_server() or deployment_info.read("is_local_deployment"):
            from_ = self.get_file_system_path(asset.host_path) + "/" + subfile
            to_ = path
            shutil.copyfile(from_, to_)
        else:
            super().export_subfile(asset, subfile, path)

    def export_subfolder(self, asset, subfolder, path):
        if self.on_deployed_server() or deployment_info.read("is_local_deployment"):
            from_ = self.get_file_system_path(asset.host_path) + "/" + subfolder
            to_ = path
            shutil.copytree(from_, to_, dirs_exist_ok=True)
        else:
            super().export_subfolder(asset, subfolder, path)

    def get_file_system_path(self, host_path):
        if host_path:
            return os.path.join(self.root, host_path)
        else:
            return None

    def get_url(self, host_path):
        assert (
            self.root
        )  # Makes sure that the root storage location has been instantiated
        return urllib.parse.quote(os.path.join(self.public_path, host_path))

    def check_cache(self, host_path: str, is_folder: bool):
        if self.on_deployed_server() or deployment_info.read("is_local_deployment"):
            return self.check_local_cache(host_path, is_folder)
        elif deployment_info.read("is_ssh_deployment"):
            return self.check_ssh_cache(
                host_path,
                is_folder,
                ssh_host=deployment_info.read("ssh_host"),
                ssh_user=deployment_info.read("ssh_user"),
            )
        else:
            raise RuntimeError(
                f"Not sure how to check cache given the current run configuration: {deployment_info.read_all()}"
            )

    def check_local_cache(self, host_path: str, is_folder: bool):
        file_system_path = self.get_file_system_path(host_path)
        return os.path.exists(file_system_path) and (
            (is_folder and os.path.isdir(file_system_path))
            or (not is_folder and os.path.isfile(file_system_path))
        )

    def check_ssh_cache(
        self, host_path: str, is_folder: bool, ssh_host: str, ssh_user: str
    ):
        sftp = self.sftp_connection(ssh_host, ssh_user)

        # At some point, we need to refactor the logic for get_file_system_path to clarify
        # whether we are running in Docker or not.
        # Docker: /psynet-data/assets
        # SSH: /home/pmch2/psynet-data/assets
        # local machine: ~/psynet-data/assets
        #
        # For now we hard-code...
        file_system_path = self.ssh_host_home_dir(
            ssh_host, ssh_user
        ) + self.get_file_system_path(host_path)

        try:
            if is_folder:
                sftp.listdir(file_system_path)
            else:
                sftp.stat(file_system_path)
            return True
        except FileNotFoundError:
            return False

    @cache
    def ssh_host_home_dir(self, ssh_host, ssh_user):
        executor = self.ssh_executor(ssh_host, ssh_user)
        return executor.run("echo $HOME").strip()


class DebugStorage(LocalStorage):
    """
    A local storage back-end used for debugging.

    .. deprecated:: 11.0.0
        Use ``LocalStorage`` instead.
    """

    def __init__(self, *args, **kwargs):
        warnings.warn(
            "DebugStorage is deprecated, please replace it with LocalStorage.",
            DeprecationWarning,
        )
        super().__init__(*args, **kwargs)


def list_files_in_s3_bucket(
    bucket_name: str,
    prefix: str = "",
    recursive: bool = True,
    sort_by_date: bool = False,
    params: Optional[dict] = None,
):
    """
    Lists files in an S3 bucket.

    Parameters
    ----------
    bucket_name :
        Bucket to list files within.

    prefix :
        Only lists files whose keys begin with this string.

    recursive :
        Whether to list files recursively.

    sort_by_date :
        Whether to sort files by modification date.

    params :
        Additional parameters to pass to the S3 client.

    Returns
    -------

    A generator that yields keys.

    """
    logger.info(
        "Listing files in S3 bucket %s with prefix '%s'...", bucket_name, prefix
    )
    if params is None:
        params = {}

    if not recursive:
        params["Delimiter"] = "/"

    paginator = get_s3_client().get_paginator("list_objects")

    contents = [
        content
        for page in paginator.paginate(
            Bucket=bucket_name,
            Prefix=prefix,
            **params,
        )
        for content in page.get("Contents", ())
    ]
    if sort_by_date:
        contents.sort(key=lambda x: x["LastModified"])

    return [content["Key"] for content in contents]


@cache
def list_files_in_s3_bucket__cached(*args, **kwargs):
    return list_files_in_s3_bucket(*args, **kwargs)


class AwsCliError(RuntimeError):
    pass


class S3TransferBackend:
    def __init__(self, s3_bucket: str):
        self.s3_bucket = s3_bucket

    def get_s3_url(self, s3_key: str):
        return f"s3://{self.s3_bucket}/{s3_key}"

    def check_recursive(self, recursive, local_path):
        assert recursive == os.path.isdir(local_path)

    def upload(self, path, s3_key, recursive):
        raise NotImplementedError

    def download(self, s3_key, target_path, recursive):
        raise NotImplementedError

    def delete(self, s3_key, recursive):
        raise NotImplementedError


class S3Boto3TransferBackend(S3TransferBackend):
    def upload(self, path, s3_key, recursive):
        client = get_s3_client()
        self.check_recursive(recursive, path)
        if os.path.isfile(path):
            client.upload_file(path, self.s3_bucket, s3_key)
        else:
            for _dir_path, _dir_names, _file_names in walk(path):
                _rel_dir_path = os.path.relpath(_dir_path, path)
                for _file_name in _file_names:
                    _local_path = os.path.join(_dir_path, _file_name)
                    if _rel_dir_path == ".":
                        _file_key = os.path.join(s3_key, _file_name)
                    else:
                        _file_key = os.path.join(s3_key, _rel_dir_path, _file_name)
                    client.upload_file(_local_path, self.s3_bucket, _file_key)

    def _download(self, client, s3_key, target_path):
        import botocore

        try:
            client.download_file(self.s3_bucket, s3_key, target_path)
        except botocore.exceptions.ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchKey", "404", "NotFound"):
                raise FileNotFoundError
            raise
        return True

    def download(self, s3_key, target_path, recursive):
        client = get_s3_client()
        if recursive:
            bucket = get_s3_bucket(self.s3_bucket)
            for obj in bucket.objects.filter(Prefix=s3_key + "/"):
                server_path = obj.key
                relative_path = server_path.replace(s3_key + "/", "")
                _target_path = os.path.join(target_path, relative_path)
                target_dir = os.path.dirname(_target_path)
                makedirs(target_dir, exist_ok=True)
                self._download(client, server_path, _target_path)
        else:
            return self._download(client, s3_key, target_path)

    def delete(self, s3_key, recursive):
        bucket = get_s3_bucket(self.s3_bucket)
        if recursive:
            bucket.objects.filter(Prefix=s3_key + "/").delete()
        else:
            bucket.Object(s3_key).delete()

    def move_file(self, source_s3_key, target_s3_key):
        import botocore

        client = get_s3_client()
        copy_source = {
            "Bucket": self.s3_bucket,
            "Key": source_s3_key,
        }
        try:
            client.copy(copy_source, self.s3_bucket, target_s3_key)
        except botocore.exceptions.ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchKey", "404", "NotFound"):
                raise FileNotFoundError
            raise

        client.delete_object(Bucket=self.s3_bucket, Key=source_s3_key)

    def move_folder(self, source_s3_key, target_s3_key):
        bucket = get_s3_bucket(self.s3_bucket)
        for obj in bucket.objects.filter(Prefix=source_s3_key + "/"):
            source_key = obj.key
            relative_key = source_key.replace(source_s3_key + "/", "")
            target_key = os.path.join(target_s3_key, relative_key)
            self.move_file(source_key, target_key)


class S3AwscliTransferBackend(S3TransferBackend):
    def __init__(self, s3_bucket):
        super().__init__(s3_bucket)

        try:
            self.run_command(["aws", "--version"], verbose=False)
        except AwsCliError:
            raise RuntimeError(
                "AWS CLI is not installed. Please install it and try again."
            )

    def copy(self, source, target, recursive):
        cmd = ["aws", "s3", "cp", source, target]
        if recursive:
            cmd.append("--recursive")
        self.run_command(cmd)

    def upload(self, path, s3_key, recursive):
        self.check_recursive(recursive, path)
        url = self.get_s3_url(s3_key)
        try:
            self.copy(path, url, recursive)
        except AwsCliError as err:
            if "NoSuchBucket" in str(err):
                S3Storage.create_bucket(self.s3_bucket)
                self.copy(path, url, recursive)
            else:
                raise

    def download(self, s3_key, target_path, recursive):
        logger.info(f"Downloading from AWS: {s3_key}")
        url = self.get_s3_url(s3_key)
        self.copy(url, target_path, recursive)

    def delete(self, s3_key, recursive):
        url = self.get_s3_url(s3_key)
        cmd = ["aws", "s3", "rm", url]
        if recursive:
            cmd.append("--recursive")
        self.run_command(cmd)

    def run_command(self, cmd, verbose=True):
        """
        Run an AWS CLI command for S3 operations.
        """
        if verbose:
            logger.info(f"Running AWS CLI command: {cmd}")
        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                env={
                    **environ,
                    **get_aws_credentials(capitalize=True),
                },
            )
        except subprocess.CalledProcessError as err:
            message = err.stderr.decode("utf8")
            raise AwsCliError(message)


class S3Storage(AssetStorage):
    """
    A storage back-end that stores assets using Amazon Web Services'
    S3 Storage system. This service is relatively inexpensive as long as your
    file collection does not number more than a few gigabytes. To use this
    service you will need to sign up for an Amazon Web Services account.

    You can use this storage back-end by setting the ``asset_storage`` property
    of your ``Experiment`` class in experiment.py, for example:

    ::

        import psynet.experiment
        from psynet.asset import S3Storage

        class Exp(psynet.experiment.Experiment):
            asset_storage = S3Storage("psynet-tests", "repp-tests")

    Parameters
    ----------
    s3_bucket : str
        The name of the S3 bucket to use.
    root : str
        The root directory within the bucket to use.
    backend : str
        The backend to use for transferring files to S3. Can be either "boto3" or "awscli". "awscli" relies on aws
        client being installed. It is faster than "boto3" (especially for uploading folders) but requires more
        dependencies which are not supported on Heroku. The default is "boto3".
    """

    def __init__(self, s3_bucket, root, backend="boto3"):
        super().__init__()
        assert not root.endswith("/")
        self.s3_bucket = s3_bucket
        self.root = root
        if backend == "boto3":
            self.backend = S3Boto3TransferBackend(s3_bucket)
        elif backend == "awscli":
            self.backend = S3AwscliTransferBackend(s3_bucket)
        else:
            NotImplementedError(f"Transfer backend {backend} is not supported.")

    def prepare_for_deployment(self):
        from .media import make_bucket_public

        if not self.bucket_exists(self.s3_bucket):
            self.create_bucket(self.s3_bucket)
        make_bucket_public(self.s3_bucket)

    def _receive_deposit(self, asset, host_path):
        s3_key = self.get_s3_key(host_path)
        if asset.is_folder:
            self.upload_folder(asset.input_path, s3_key)
        else:
            self.upload_file(asset.input_path, s3_key)

    def get_url(self, host_path: str):
        s3_key = self.get_s3_key(host_path)
        return os.path.join(
            "https://s3.amazonaws.com", self.s3_bucket, self.escape_s3_key(s3_key)
        )

    @staticmethod
    def bucket_exists(bucket_name):
        import botocore

        resource = get_s3_resource()
        try:
            resource.meta.client.head_bucket(Bucket=bucket_name)
        except botocore.exceptions.ClientError as e:
            error_code = int(e.response["Error"]["Code"])
            if error_code == 404:
                return False
        return True

    def get_s3_key(self, host_path: str):
        return os.path.join(self.root, host_path)

    def escape_s3_key(self, s3_key):
        # This might need revisiting as and when we find special characters that aren't quoted correctly
        return urllib.parse.quote_plus(s3_key, safe="/~()*!.'")

    def check_cache(self, host_path: str, is_folder: bool, use_cache=None):
        """
        Checks whether a file or folder is present in the remote bucket.
        Uses caching where appropriate for efficiency.
        """
        s3_key = os.path.join(self.root, host_path)

        if use_cache is None:
            from .experiment import is_experiment_launched

            use_cache = is_experiment_launched()

        if is_folder:
            return self.check_cache_for_folder(s3_key, use_cache)
        else:
            return self.check_cache_for_file(s3_key, use_cache)

    def check_cache_for_folder(self, s3_key, use_cache):
        files = self.list_files_with_prefix(s3_key + "/", use_cache)
        return len(files) > 0

    def check_cache_for_file(self, s3_key, use_cache):
        files = self.list_files_with_prefix(s3_key, use_cache)
        return s3_key in files

    def list_files_with_prefix(self, prefix, use_cache):
        try:
            if use_cache:
                # If we are in the 'preparation' phase of deployment, then we rely on a cached listing
                # of the files in the S3 bucket. This is necessary because the preparation phase
                # may involve checking caches for thousands of files at a time, and it would be slow
                # to talk to S3 separately for each one. This wouldn't catch situations where
                # the cache has been added during the preparation phase itself, but this shouldn't happen very often,
                # so doesn't need to be optimized for just yet.
                return [
                    x
                    for x in list_files_in_s3_bucket__cached(
                        self.s3_bucket, prefix=self.root
                    )
                    if x.startswith(prefix)
                ]
            else:
                return list_files_in_s3_bucket(self.s3_bucket, prefix)
        except Exception as err:
            if "NoSuchBucket" in str(err):
                return []
            raise

    # @create_bucket_if_necessary
    # def folder_exists__slow(self, s3_key):
    #     return len(self.list_folder(s3_key)) > 0
    #
    # # @create_bucket_if_necessary
    # def list_folder(self, folder):
    #     # cmd = f"aws s3 ls {s3_bucket}/{folder}/"
    #     # from subprocess import PIPE
    #     # credentials = psynet.media.get_aws_credentials()
    #     # cmd = ""
    #     # cmd += f"export AWS_ACCESS_KEY_ID={credentials['aws_access_key_id']}; "
    #     # cmd += f"export AWS_SECRET_ACCESS_KEY={credentials['aws_secret_access_key']}; "
    #     # cmd += f"aws s3 ls {s3_bucket} "
    #     # x = subprocess.run(cmd, stdout=PIPE, stderr=PIPE, universal_newlines=True, shell=True)
    #     # breakpoint()
    #     return [x.key for x in self.boto3_bucket.objects.filter(Prefix="folder" + "/")]

    # @cached_property
    # def regex_pattern(self):
    #     return re.compile("https://s3.amazonaws.com/(.*)/(.*)")

    def export(self, asset, path, **kwargs):
        s3_key = self.get_s3_key(asset.host_path)
        if asset.is_folder:
            self.download_folder(s3_key, path)
        else:
            self.download_file(s3_key, path)

    def export_subfile(self, asset, subfile, path):
        assert asset.is_folder
        s3_key = self.get_s3_key(asset.host_path) + "/" + subfile
        self.download_file(s3_key, path)

    def export_subfolder(self, asset, subfolder, path):
        assert asset.is_folder
        s3_key = self.get_s3_key(asset.host_path) + "/" + subfolder
        self.download_folder(s3_key, path)

    def download_file(self, s3_key, target_path):
        return self._download(s3_key, target_path, recursive=False)

    def download_folder(self, s3_key, target_path):
        return self._download(s3_key, target_path, recursive=True)

    def _download(self, s3_key, target_path, recursive):
        return self.backend.download(s3_key, target_path, recursive)

    def upload_file(self, path, s3_key):
        return self._upload(path, s3_key, recursive=False)

    def upload_folder(self, path, s3_key):
        return self._upload(path, s3_key, recursive=True)

    def _upload(self, path, s3_key, recursive):
        return self.backend.upload(path, s3_key, recursive)

    @staticmethod
    def create_bucket(s3_bucket):
        client = get_s3_client()
        client.create_bucket(Bucket=s3_bucket)

    def delete_file(self, s3_key):
        self.backend.delete(s3_key, recursive=False)

    def move_file(self, s3_key: str, new_s3_key: str):
        """
        Move a file from one location to another within the S3 bucket.

        :param s3_key: The current path of the file in the S3 bucket.
        :param new_s3_key: The new path where the file should be moved.
        """
        copy_source = {"Bucket": self.s3_bucket, "Key": s3_key}
        client = get_s3_client()
        client.copy(copy_source, self.s3_bucket, new_s3_key)
        self.delete_file(s3_key)

    def delete_folder(self, s3_key):
        self.backend.delete(s3_key, recursive=True)

    def delete_all(self):
        self.delete_folder(self.root)

    def list(
        self,
        folder_path: str,
        sort_by_date: bool = False,
        top: int = None,
        extension: str = None,
    ):
        keys = list_files_in_s3_bucket(
            self.s3_bucket,
            prefix=os.path.join(self.root, folder_path) + "/",
            sort_by_date=sort_by_date,
        )
        if extension:
            normalized_extension = (
                extension if extension.startswith(".") else f".{extension}"
            )
            keys = [key for key in keys if key.endswith(normalized_extension)]
        if top is not None:
            keys = keys[:top]
        return keys

    def read_file(self, file_path: str) -> str:
        client = get_s3_client()
        obj = client.get_object(Bucket=self.s3_bucket, Key=file_path)
        return obj["Body"].read().decode("utf-8")

    def write_file(self, file_path: str, content: str):
        client = get_s3_client()
        client.put_object(
            Bucket=self.s3_bucket, Key=file_path, Body=content.encode("utf-8")
        )


class AssetRegistry:
    initial_asset_manifesto_path = "pre_deployed_assets.csv"

    def __init__(self, storage: AssetStorage, n_parallel=None):
        self.storage = storage
        self.n_parallel = n_parallel
        self._staged_asset_specifications = []
        self._staged_asset_lookup_table = {}

        # inspector = sqlalchemy.inspect(db.engine)
        # if inspector.has_table("asset") and Asset.query.count() == 0:
        #     self.populate_db_with_initial_assets()

    # def __getitem__(self, item):
    #     from psynet.asset import Asset
    #
    #     return Asset.query.filter_by(key=item).one()

    @property
    def deployment_id(self):
        return self.storage.deployment_id

    @property
    def experiment(self):
        from .experiment import get_experiment

        return get_experiment()

    def stage(self, *args):
        for asset in [*args]:
            assert isinstance(asset, AssetSpecification)
            self._staged_asset_specifications.append(asset)
            # self._staged_asset_lookup_table[asset.key] = asset

    def update_asset_metadata(self, asset: Asset):
        pass

    def receive_deposit(
        self, asset: Asset, host_path: str, async_: bool, delete_input: bool
    ):
        return self.storage.receive_deposit(asset, host_path, async_, delete_input)

    # def get(self, key):
    #     return get_asset(key)

    def prepare_for_deployment(self):
        self.prepare_assets_for_deployment()
        self.storage.prepare_for_deployment()

    def prepare_assets_for_deployment(self):
        # if self.n_parallel:
        #     n_jobs = self.n_parallel
        # elif len(self._staged_asset_specifications) < 25:
        #     n_jobs = 1
        # else:
        #     n_jobs = psutil.cpu_count()

        # OLD NOTES, may not be relevant any more
        #
        # The parallel implementation is not reliable yet;
        # the language_tests demo fails due to a deadlock between
        # competing transactions. As a patch for now we disable
        # parallel processing.
        #
        # If you wish to revist this, you may find the following Postgres
        # code useful: it displays all blocking processes along with the
        # responsible queries.
        #
        # SELECT
        #     activity.pid,
        #     activity.usename,
        #     activity.query,
        #     blocking.pid AS blocking_id,
        #     blocking.query AS blocking_query
        # FROM pg_stat_activity AS activity
        # JOIN pg_stat_activity AS blocking ON blocking.pid = ANY(pg_blocking_pids(activity.pid));

        # SSH currently fails if we try to open more than one connection at the same time,
        # so for now we hard-code the number of jobs to zero. It would be good to revisit this.
        # Uploading all the files over one SSH connection shouldn't be slower than uploading them
        # over multiple connections. The main limitation with the current situation though
        # is that we can no longer programmatically generate stimuli in parallel.

        if len(self._staged_asset_specifications) > 0:
            for a in tqdm(
                self._staged_asset_specifications, desc="Generating/uploading assets..."
            ):
                a.prepare_for_deployment(registry=self)

        # logger.info("Preparing assets for deployment...")
        # n_jobs = 1
        # Parallel(
        #     n_jobs=n_jobs,
        #     verbose=10,
        #     backend="threading",
        # )(
        #     delayed(
        #         lambda a: threadsafe__prepare_asset_for_deployment(
        #             asset=a, registry=self
        #         )
        #     )(a)
        #     for a in self._staged_asset_specifications
        # )

        db.session.commit()

    # def save_initial_asset_manifesto(self):
    #     copy_db_table_to_csv("asset", self.initial_asset_manifesto_path)

    # def populate_db_with_initial_assets(self):
    #     with open(self.initial_asset_manifesto_path, "r") as file:
    #         ingest_to_model(file, Asset)


def threadsafe__prepare_asset_for_deployment(asset, registry):
    asset_2 = db.session.merge(asset)
    asset_2.prepare_for_deployment(registry=registry)


def asset(  # noqa: F841
    source: Union[str, Path, Callable],
    *,
    cache: bool = False,
    on_demand: bool = False,
    arguments: Optional[dict] = None,
    local_key=None,
    key_within_module=None,
    key_within_experiment=None,
    description=None,
    is_folder=False,
    data_type=None,
    extension=None,
    parent=None,
    module_id=None,
    personal=False,
):
    """
    Create an asset.

    Most users will find this the easiest way to create assets.
    Advanced users can also create assets via the constructor functions for each asset type:
    - :class:`ExternalAsset`
    - :class:`ExperimentAsset`
    - :class:`CachedFunctionAsset`
    - :class:`OnDemandAsset`


    Parameters
    ----------
    source : str, Path, or callable
        The source of the asset. If a string or Path, it will be treated as a local file or URL.
        If a callable, it will be treated as a function asset.

    cache : bool, default=False
        Cached assets are uploaded to a data-storage directory that is shared between experiment launches.
        This is primarily useful when working with a stimulus set that is time-consuming to
        generate and/or upload to the web server, because the generation and/or uploading only happens once.
        Cache invalidation is done based on file hashing (for file assets) or argument hashing (for function assets).
        See :meth:`FunctionAssetMixin.get_md5_instructions` for more information.

    on_demand : bool, default=False
        Whether to generate the asset on demand.

    arguments : dict, optional
        Arguments to pass to the function if source is a callable.

    local_key : str
        A string identifier for the asset, for example ``"stimulus"``. If provided, this string identifier
        should together with ``parent`` and ``module_id`` uniquely identify that asset (i.e. no other asset
        should share that combination of properties).

    key_within_module : str
        A string that uniquely identifies the asset within a given module. If left unspecified,
        this will be automatically generated with reference to the ``parent`` and the ``local_key`` arguments.

    key_within_experiment : str
        A string that uniquely identifies the asset within a given experiment. If left unspecified,
        this will be automatically generated with reference to the ``key_within_module`` and the ``module_id`` arguments.

    description : str
        An optional longer string that provides further documentation about the asset.

    is_folder : bool
        Whether the asset is a folder.

    data_type : str
        Experimental: the nature of the asset's data. Could be used to determine visualization methods etc.

    extension : str
        The file extension, if applicable.

    parent : object
        The object that 'owns' the asset, if applicable, for example a Participant or a Node.

    module_id : str
        The module within which the asset is located.

    personal : bool
        Whether the asset is 'personal' and hence omitted from anonymous database exports.

    Returns
    -------
    Asset
        The created asset. Depending on the input arguments, this could be:
        - ExternalAsset: For assets hosted externally at a URL
        - ExperimentAsset: For assets specific to the current experiment deployment
        - CachedFunctionAsset: For assets generated by a function and cached between experiment launches
        - OnDemandAsset: For assets generated by a function on demand
    """
    kwargs = locals()

    if callable(source):
        return _function_asset(**kwargs)
    else:
        # Remove arguments that are specific to function assets
        for arg in ["arguments", "on_demand", "cache"]:
            kwargs.pop(arg)

        source = str(source)

        if source.startswith("http"):
            # This is an external asset, i.e. one hosted externally at a URL
            url = kwargs.pop("source")
            return ExternalAsset(url, **kwargs)
        else:
            # This is a local file asset
            input_path = kwargs.pop("source")
            cls = CachedAsset if cache else ExperimentAsset
            return cls(input_path, **kwargs)


def _function_asset(source, cache, on_demand, **kwargs):
    function = source

    if cache:
        if on_demand:
            raise ValueError(
                "Sorry, currently function assets can't be both cached and on-demand."
            )
        return CachedFunctionAsset(function=function, **kwargs)
    else:
        if on_demand:
            return OnDemandAsset(function=function, **kwargs)
        else:
            raise ValueError(
                "Sorry, currently function assets must be marked as either cached or on-demand. "
                "Select the former if you want to pre-generate your assets, or the latter otherwise."
            )
