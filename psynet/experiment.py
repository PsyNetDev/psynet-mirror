import configparser
import inspect
import json
import os
import re
import shutil
import signal
import sys
import tempfile
import time
import traceback
import uuid
import zipfile
from collections import Counter, OrderedDict
from datetime import datetime, timedelta
from functools import cache, cached_property
from importlib import resources
from os.path import abspath, dirname, exists
from os.path import join as join_path
from pathlib import Path
from platform import python_version
from smtplib import SMTPAuthenticationError
from statistics import median
from typing import List, Optional, Type, Union

import dallinger.experiment
import dallinger.models
import flask
import psutil
import rpdb
import sqlalchemy.orm.exc
from click import Context
from dallinger import db
from dallinger.config import get_config as dallinger_get_config
from dallinger.config import is_valid_json
from dallinger.experiment import experiment_route, scheduled_task
from dallinger.experiment_server.dashboard import (
    DashboardTab,
    dashboard,
    dashboard_tab,
    find_log_line_number,
)
from dallinger.experiment_server.utils import nocache, success_response
from dallinger.notifications import admin_notifier
from dallinger.recruiters import (
    MockRecruiter,
    MTurkRecruiter,
    ProlificRecruiter,
    Recruiter,
    RecruitmentStatus,
)
from dallinger.utils import classproperty
from dallinger.utils import get_base_url as dallinger_get_base_url
from dallinger.version import __version__ as dallinger_version
from dominate import tags
from flask import g as flask_app_globals
from flask import jsonify, redirect, render_template, request, send_file, url_for
from flask_login import login_required
from sqlalchemy import Column, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import with_polymorphic

from psynet import __version__
from psynet.artifact import LocalArtifactStorage
from psynet.perf_test import run_parallel_test
from psynet.utils import (
    format_bytes,
    get_config,
    get_descendent_class_by_name,
    get_experiment_url,
)

from . import deployment_info
from .asset import Asset, AssetRegistry, LocalStorage, OnDemandAsset, S3Storage
from .bot import Bot, BotDriver, BotResponse
from .command_line import export_launch_data, log
from .data import SQLBase, SQLMixin, ingest_zip, register_table
from .db import transaction, with_transaction
from .end import RejectedConsentLogic, SuccessfulEndLogic, UnsuccessfulEndLogic
from .error import ErrorRecord
from .field import ImmutableVarStore, PythonDict
from .graphics import PsyNetLogo
from .notifier import Notifier
from .page import InfoPage
from .participant import Participant
from .recruiters import (  # noqa: F401
    BaseLucidRecruiter,
    CapRecruiter,  # noqa: F401; Backward compatibility alias
    DevLucidRecruiter,
    LabRecruiter,
    LucidRecruiter,
    StagingCapRecruiter,  # noqa: F401; Backward compatibility alias
    StagingLabRecruiter,
)
from .redis import redis_vars
from .serialize import serialize, unserialize
from .static_resources import get_static_package_extra_files
from .timeline import (
    WEBSOCKET_CHANNEL,
    DatabaseCheck,
    FailedValidation,
    ModuleState,
    ParticipantFailRoutine,
    PreDeployRoutine,
    RecruitmentCriterion,
    Response,
    Timeline,
    WebSocketElt,
)
from .translation.check import check_translations
from .translation.translate import create_pot
from .translation.utils import compile_mo, load_po
from .trial.main import Trial, TrialMaker, TrialNetwork
from .trial.record import (  # noqa -- this is to make sure the SQLAlchemy class is registered
    Recording,
)
from .utils import (
    NoArgumentProvided,
    call_function,
    call_function_with_context,
    disable_logger,
    ensure_experiment_directory_name_does_not_conflict,
    get_arg_from_dict,
    get_authenticated_session,
    get_logger,
    get_translator,
    is_in_repo_experiment,
    log_time_taken,
    render_template_with_translations,
    safe,
    serialise,
    suppress_stdout,
    working_directory,
)

logger = get_logger()


database_template_path = ".deploy/database_template.zip"


DEFAULT_LOCALE = "en"
INITIAL_RECRUITMENT_SIZE = 1


def error_response(*args, **kwargs):
    from dallinger.experiment_server.utils import (
        error_response as dallinger_error_response,
    )

    with disable_logger():
        return dallinger_error_response(*args, **kwargs)


def is_experiment_launched():
    return redis_vars.get("launch_finished", default=False)


def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, datetime):
        serial = obj.isoformat()
        return serial
    raise TypeError("Type not serializable")


def _reject_overridden_fail_participant(cls):
    """Reject PsyNet Experiment subclasses that replace fail_participant."""
    if cls.__name__ == "Experiment" and cls.__module__ == "psynet.experiment":
        return

    psy_experiment = None
    for base in cls.__mro__:
        if (
            base.__name__ == "Experiment"
            and getattr(base, "__module__", "") == "psynet.experiment"
        ):
            psy_experiment = base
            break
    if (
        psy_experiment is not None
        and cls.fail_participant is not psy_experiment.fail_participant
    ):
        raise RuntimeError(
            "Do not override Experiment.fail_participant. "
            "That Dallinger hook is not part of PsyNet's failure contract "
            "and used to fail owned nodes. Call Participant.fail() "
            "or register a ParticipantFailRoutine instead."
        )


class ExperimentMeta(type):
    def __init__(cls, name, bases, dct):
        cls.assets = AssetRegistry(storage=cls.asset_storage)

        # This allows users to perform in-place alterations to ``css`` and ``css_links`` without
        # inadvertently altering the base class.
        cls.css = cls.css.copy()
        cls.css_links = cls.css_links.copy()

        if hasattr(cls, "test_create_bots"):
            raise RuntimeError(
                "Experiment.test_create_bots has been removed, please do not override it. Instead you should put "
                "any custom bot initialization code inside test_run_bot (before calling super().test_run_bot())."
            )

        if hasattr(cls, "test_run_bots"):
            raise RuntimeError(
                "Experiment.test_run_bots has been renamed to Experiment.test_serial_run_bots. "
                "Please note that this test route is only used if the tests are run in serial mode."
            )

        # Check if __init__signature matches the problematic pattern: def __init__(self, session)
        sig = inspect.signature(cls.__init__)
        params = list(sig.parameters.keys())
        if "session" in params:
            raise RuntimeError(
                """
Your experiment class uses an outdated __init__ signature.
Please update the __init__ signature in your experiment class (see experiment.py)
to something like the following:

def __init__(self, **kwargs):
    # ...
    super().__init__(**kwargs)

Note: in many cases you don't need a custom __init__ method here at all.
For example, if your __init__ method just looks like the following, you can delete it entirely:

def __init__(self, session=None):
    super().__init__(session)
    self.initial_recruitment_size = 1
            """
            )

        _reject_overridden_fail_participant(cls)


@register_table
class Request(SQLBase, SQLMixin):
    __tablename__ = "request"

    # These fields are removed from the database table as they are not needed.
    failed = None
    failed_reason = None
    time_of_death = None
    vars = None

    id = Column(Integer, primary_key=True)
    unique_id = Column(String, ForeignKey("participant.unique_id"))
    duration = Column(Float)
    method = Column(String)
    endpoint = Column(String)
    params = Column(PythonDict, default={})
    status_code = Column(Integer)

    def to_dict(self):
        return {
            "id": self.id,
            "duration": self.duration,
            "time": self.creation_time,
            "unique_id": self.unique_id,
            "method": self.method,
            "endpoint": self.endpoint,
            "params": self.params,
        }


@register_table
class ExperimentStatus(SQLBase, SQLMixin):
    __tablename__ = "experiment_status"

    id = Column(Integer, primary_key=True)
    cpu_usage_pct = Column(Float)
    ram_usage_pct = Column(Float)
    disk_usage_pct = Column(Float)
    median_response_time = Column(Float)
    requests_per_minute = Column(Integer)
    n_working_participants = Column(Integer)
    extra_info = Column(PythonDict, default={})

    def __init__(self, **kwargs):
        named_arguments = {
            key: value for key, value in kwargs.items() if key in self.sql_columns
        }
        super().__init__(**named_arguments)
        self.extra_info = {
            key: value for key, value in kwargs.items() if key not in self.sql_columns
        }

    def to_dict(self):
        return {
            "id": self.id,
            "timestamp": self.creation_time,
            "cpu_usage_pct": self.cpu_usage_pct,
            "ram_usage_pct": self.ram_usage_pct,
            "disk_usage_pct": self.disk_usage_pct,
            "median_response_time": self.median_response_time,
            "requests_per_minute": self.requests_per_minute,
            "n_working_participants": self.n_working_participants,
            "extra_info": self.extra_info,
        }


class Experiment(dallinger.experiment.Experiment, metaclass=ExperimentMeta):
    # pylint: disable=abstract-method
    """
    The main experiment class from which to inherit when building experiments.

    Several experiment options can be set through the experiment class.
    For example, the storage back-end can be selected by setting the ``asset_storage`` attribute:

    ::

        class Exp(psynet.experiment.Experiment):

    Another experiment attribute is `export_classes_to_skip`, which is a list of classes to be excluded
    when exporting the database objects to JSON-style dictionaries. The default is `["ExperimentStatus"]`.

    Config variables can be set here, amongst other places (see online documentation for details):

    ::

        class Exp(psynet.experiment.Experiment):
            config = {
                "min_accumulated_reward_for_abort": 0.15,
                "show_abort_button": True,
            }

    Custom CSS stylesheets can be included here, to style the appearance of the experiment:

    ::

        class Exp(psynet.experiment.Experiment):
            css_links = ["static/theme.css"]

    CSS can also be included directly as part of the experiment class via the ``css`` attribute,
    see ``custom_theme`` demo for details.

    There are a number of variables tied to an experiment all of which are documented below.
    They have been assigned reasonable default values which can be overridden when defining an experiment
    (see method ``_default_variables``). Also, they can be enriched with new variables in the following way:

    ::

        import psynet.experiment

        class Exp(psynet.experiment.Experiment):
            variables = {
                "new_variable": "some-value",  # Adding a new variable
            }

    These variables can then be changed in the course of experiment, just like (e.g.) participant variables.

    ::

        from psynet.timeline import CodeBlock

        CodeBlock(lambda experiment: experiment.var.set("custom-variable", 42))

    Default experiment variables accessible through `psynet.experiment.Experiment.var` are:

    max_participant_payment : `float`
        The maximum payment in US dollars a participant is allowed to get. Default: `25.0`.

    soft_max_experiment_payment : `float`
        The recruiting process stops if the amount of accumulated payments
        (incl. time and performance rewards) in US dollars exceedes this value. Default: `1000.0`.

    hard_max_experiment_payment : `float`
        Guarantees that in an experiment no more is spent than the value assigned.
        Bonuses are not paid from the point this value is reached and a record of the amount
        of unpaid bonus is kept in the participant's `unpaid_bonus` variable. Default: `1100.0`.

    big_base_payment : `bool`
        Set this to `True` if you REALLY want to set `base_payment` to a value > 20.

    There are also a few experiment variables that are set automatically and that should,
    in general, not be changed manually:

    psynet_version : `str`
        The version of the `psynet` package.

    dallinger_version : `str`
        The version of the `Dallinger` package.

    python_version : `str`
        The version of the `Python`.

    hard_max_experiment_payment_email_sent : `bool`
        Whether an email to the experimenter has already been sent indicating the `hard_max_experiment_payment`
        had been reached. Default: `False`. Once this is `True`, no more emails will be sent about
        this payment limit being reached.

    soft_max_experiment_payment_email_sent : `bool`
        Whether an email to the experimenter has already been sent indicating the `soft_max_experiment_payment`
        had been reached. Default: `False`. Once this is `True`, no more emails will be sent about
        this payment limit being reached.


    In addition to the config variables in Dallinger, PsyNet adds the following:

    min_browser_version : `str`
        The minimum version of the Chrome browser a participant needs in order to take a HIT. Default: `80.0`.

    wage_per_hour : `float`
        The payment in currency the participant gets per hour. Default: `9.0`.

    currency : `str`
        The currency in which the participant gets paid. Default: `$`.

    min_accumulated_reward_for_abort : `float`
        The threshold of reward accumulated in US dollars for the participant to be able to receive
        compensation when aborting an experiment using the `Abort experiment` button. Default: `0.20`.

    show_abort_button : `bool`
        If ``True``, the `Ad` page displays an `Abort` button the participant can click to terminate the HIT,
        e.g. in case of an error where the participant is unable to finish the experiment. Clicking the button
        assures the participant is compensated on the basis of the amount of reward that has been accumulated.
        Default ``False``.

    show_reward : `bool`
        If ``True`` (default), then the participant's current estimated reward is displayed
        at the bottom of the page.

    show_footer : `bool`
        If ``True`` (default), then a footer is displayed at the bottom of the page containing a 'Help' button
        and reward information if `show_reward` is set to `True`.

    show_progress_bar : `bool`
        If ``True`` (default), then a progress bar is displayed at the top of the page.

    check_participant_opened_devtools : ``bool``
        If ``True``, whenever a participant opens the developer tools in the web browser,
        this is logged as participant.var.opened_devtools = ``True``,
        and the participant is shown a warning alert message.
        Default: ``False``.
        Note: Chrome does not currently expose an official way of checking whether
        the participant opens the developer tools. People therefore have to rely
        on hacks to detect it. These hacks can often be broken by updates to Chrome.
        We've therefore disabled this check by default, to reduce the risk of
        false positives. Experimenters wishing to enable the check for an individual
        experiment are recommended to verify that the check works appropriately
        before relying on it. We'd be grateful for any contributions of updated
        developer tools checks.

    window_width : ``int``
        Determines the width in pixels of the window that opens when the
        participant starts the experiment. Only active if
        recruiter.start_experiment_in_popup_window is True.
        Default: ``1024``.

    window_height : ``int``
        Determines the width in pixels of the window that opens when the
        participant starts the experiment. Only active if
        recruiter.start_experiment_in_popup_window is True.
        Default: ``768``.

    supported_locales : ``list``
        List of locales (i.e., ISO language codes) a user can pick from, e.g., ``'["en"]'``.
        Default: ``'[]'``.

    force_google_chrome : ``bool``
        Forces the user to use the Google Chrome browser. If another browser is used, it will give detailed instructions
        on how to install Google Chrome.
        Default: ``True``.

    leave_comments_on_every_page : ``bool``
        Allows the user to leave comments on every page.
        Default: ``False``.

    force_incognito_mode : ``bool``
        Forces the user to open the experiment in a private browsing (i.e. incognito mode). This is helpful as incognito
        mode prevents the user from accessing their browsing history, which could be used to influence the experiment.
        Furthermore it does not enable addons which can interfere with the experiment. If the user is not using
        incognito mode, it will give detailed instructions on how to open the experiment in incognito mode.
        Default: ``False``.

    allow_mobile_devices : ``bool``
        Allows the user to use mobile devices. If it is set to false it will tell the user to open the experiment on
        their computer.
        Default: ``False``.


    needs_internet_access: ``bool``
        Indicates whether the experiment needs internet access. Can be set to ``False`` for lab or field studies.
        Default: ``True``.



    Parameters
    ----------

    session:
        The experiment's connection to the database.
    """

    # Introduced this as a hotfix for a compatibility problem with macOS 10.13:
    # http://sealiesoftware.com/blog/archive/2017/6/5/Objective-C_and_fork_in_macOS_1013.html
    os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"

    export_classes_to_skip = ["ExperimentStatus"]
    initial_recruitment_size = INITIAL_RECRUITMENT_SIZE
    logos = []
    max_allowed_base_payment = 30

    timeline = Timeline(InfoPage("Placeholder timeline", time_estimate=5))

    asset_storage = LocalStorage()
    artifact_storage = LocalArtifactStorage()
    css = []
    css_links = []

    __extra_vars__ = {}

    variables = {}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        assert isinstance(self.css, list)
        assert isinstance(self.css_links, list)

        for css_link in self.css_links:
            if not css_link.startswith("static/"):
                raise ValueError(
                    "All css_links must point to files in the experiment's static directory "
                    f" (problematic link: '{css_link}')."
                )
            if not Path(css_link).is_file():
                raise ValueError(
                    f"Couldn't find the following CSS file: {css_link}. Check ``Experiment.css_links``."
                )

        config_initial_recruitment_size = self.get_initial_recruitment_size()
        initial_recruitment_size_config_changed = (
            config_initial_recruitment_size != INITIAL_RECRUITMENT_SIZE
        )
        initial_recruitment_size_experiment_changed = (
            self.__class__.initial_recruitment_size != INITIAL_RECRUITMENT_SIZE
        )

        config = get_config()
        if self.base_payment > 10 and not config.get("big_base_payment"):
            logger.warning(f"`base_payment` is set to `{self.base_payment}`!")
        assert self.base_payment <= 20 or config.get("big_base_payment"), (
            f"Are you sure about setting `base_payment = {self.base_payment}`? "
            "You probably forgot to divide `base_payment` by 100. "
            "In the special case you REALLY want to override this behaviour, set `big_base_payment = true`"
        )

        assert not (
            initial_recruitment_size_config_changed
            and initial_recruitment_size_experiment_changed
        ), (
            "You have set the initial recruitment size in both the config file and in your experiment class."
        )

        if initial_recruitment_size_config_changed:
            self.initial_recruitment_size = config_initial_recruitment_size
        elif initial_recruitment_size_experiment_changed:
            raise RuntimeError(
                "You can no longer directly set the initial recruitment size in your experiment class, you need to "
                "specify it in the config.txt file or in experiment.config"
            )
        else:
            assert self.initial_recruitment_size == INITIAL_RECRUITMENT_SIZE

        if not self.label:
            raise RuntimeError(
                "PsyNet now requires you to specify a descriptive label for your experiment "
                "in your Experiment class. For example, you might write: label = 'GSP experiment with faces'"
            )

        self.database_checks = []
        self.participant_fail_routines = []
        self.recruitment_criteria = []
        self._websocket_message_handlers = {}

        self.pre_deploy_routines = []
        if self.translation_checks_needed():
            self.pre_deploy_routines.append(
                PreDeployRoutine(
                    "check_experiment_translations",
                    check_translations,
                )
            )

        self.pre_deploy_routines.append(
            PreDeployRoutine(
                "compile_translations_if_necessary",
                self.compile_translations_if_necessary,
                {
                    "locales_dir": os.path.abspath("locales"),
                    "namespace": "experiment",
                },
            )
        )

        self.process_timeline()

    @cached_property
    def authenticated_session(self):
        return get_authenticated_session(self.base_url)

    def receive_websocket_frame(self, participant, frame, receive_time=None):
        """Dispatch a native PsyNet WebSocket frame."""
        from psynet.websocket import dispatch_websocket_frame

        return dispatch_websocket_frame(
            self,
            participant=participant,
            frame=frame,
            receive_time=receive_time,
        )

    @classmethod
    def get_index_html(cls):
        return f"""
<html>
<head>
    <title>PsyNet Experiment</title>
    <link rel="stylesheet" href="/static/css/bootstrap.min.css">
</head>
<body>
<div class="container mt-5">
    <div class="row justify-content-center">
        <div class="col-md-8">
            <h1 class="mb-4">PsyNet Experiment</h1>
            <p class="mb-3">
                If you are a participant, you are in the wrong place, please double-check your URL!
            </p>
            <p>
                If you are an experimenter, please
                <a href="{url_for("dashboard.dashboard_develop")}">click here</a>
                to access the dashboard.
            </p>
        </div>
    </div>
</div>
</body>
</html>
"""

    @classproperty
    def hidden_dashboards(cls):
        is_local_deployment = deployment_info.read("is_local_deployment")
        is_ssh_deployment = deployment_info.read("is_ssh_deployment")
        optional_tabs = [
            "dashboard.dashboard_heroku",
            "dashboard.dashboard_mturk",
            "dashboard.dashboard_lucid",
            "dashboard.dashboard_lifecycle",
        ]
        if not (is_local_deployment or is_ssh_deployment):
            optional_tabs.remove(
                "dashboard.dashboard_heroku"
            )  # if it's not local, nor ssh, then it's heroku
        config = get_config()

        try:
            recruiter_name = config.get("recruiter")

            if "mturk" in recruiter_name.lower():
                optional_tabs.remove("dashboard.dashboard_mturk")

            elif "lucid" in recruiter_name.lower():
                optional_tabs.remove("dashboard.dashboard_lucid")
        except KeyError:
            # This might happen if the config hasn't fully loaded yet
            pass

        return optional_tabs

    @classmethod
    def rename_dashboard_tabs(cls, tabs):
        route_names = [tab.route_name for tab in tabs]

        def _rename(key, title):
            if key in route_names:
                tabs[route_names.index(key)].title = title

        _rename("monitoring", "Networks")
        return tabs

    @classmethod
    def organize_dashboard_tabs(cls, tabs):
        tab_list = tabs.tabs
        tab_list = cls.rename_dashboard_tabs(tab_list)
        route2tab = {tab.route_name: tab for tab in tab_list}

        server_children = [
            "dashboard.dashboard_heroku",
            "dashboard.dashboard_ec2",
        ]

        recruiter_children = [
            "dashboard.dashboard_mturk",
            "dashboard.dashboard_lucid",
            "dashboard.dashboard_prolific",
        ]

        monitor_children = [
            "dashboard.dashboard_monitoring",
            "dashboard.dashboard_timeline",
            "dashboard.dashboard_resources",
            "dashboard.dashboard_sync_groups",
            "dashboard.dashboard_participants",
            "dashboard.dashboard_logger",
            "dashboard.dashboard_errors",
        ]

        def insert_group(tab_list, title, route_names):
            route_names = [
                route_name for route_name in route_names if route_name in route2tab
            ]
            if len(route_names) == 0:
                return tab_list
            group = DashboardTab(
                title=title,
                route_name=route_names[0],
                children_function=lambda: [
                    route2tab[route_name] for route_name in route_names
                ],
            )
            return tab_list + [group]

        new_tab_list = [route2tab["dashboard.dashboard_index"]]
        new_tab_list += [route2tab["dashboard.dashboard_deployments"]]
        new_tab_list = insert_group(new_tab_list, "Server", server_children)
        new_tab_list = insert_group(new_tab_list, "Recruiter", recruiter_children)
        new_tab_list = insert_group(new_tab_list, "Monitor", monitor_children)
        new_tab_list += [route2tab["dashboard.dashboard_data"]]
        new_tab_list += [route2tab["dashboard.dashboard_export"]]
        new_tab_list += [route2tab["dashboard.dashboard_database"]]
        new_tab_list += [route2tab["dashboard.dashboard_develop"]]
        inserted_routes = (
            [tab.route_name for tab in new_tab_list]
            + server_children
            + recruiter_children
            + monitor_children
        )
        missing_routes = [
            tab for tab in tab_list if tab.route_name not in inserted_routes
        ]
        return new_tab_list + missing_routes

    @classproperty
    def launched(cls):
        return is_experiment_launched()

    @property
    def supported_locales(self):
        """
        Returns the list of supported locales for the experiment.

        This can be specified in the config.txt file, or inferred from the locales present in the locales directory.
        """
        config = get_config()
        locale = config.get("locale", "en")
        supported_locales = json.loads(config.get("supported_locales", "[]"))
        supported_locales += [locale, "en"]
        supported_locales = list(set(supported_locales))

        return supported_locales

    def translation_checks_needed(self):
        non_en_locales = [locale for locale in self.supported_locales if locale != "en"]
        return len(non_en_locales) > 0

    @classmethod
    def create_translation_template_from_experiment_folder(
        cls, input_directory, pot_path
    ):
        create_pot(input_directory, pot_path)

    @classmethod
    def _create_translation_template_from_experiment_folder(cls, locales_dir="locales"):
        os.makedirs(locales_dir, exist_ok=True)

        pot_path = os.path.join(locales_dir, "experiment.pot")
        if exists(pot_path):
            os.remove(pot_path)
        cls.create_translation_template_from_experiment_folder(os.getcwd(), pot_path)
        if not exists(pot_path):
            raise FileNotFoundError(f"Could not find pot file at {pot_path}")
        return load_po(pot_path)

    def compile_translations_if_necessary(self, locales_dir, namespace):
        """Compiles translations if necessary."""
        if self.translation_checks_needed():
            for locale in self.supported_locales:
                if locale == "en":
                    continue
                po_path = os.path.join(
                    locales_dir, locale, "LC_MESSAGES", namespace + ".po"
                )
                assert os.path.exists(po_path), f"Could not find po file at {po_path}"
                compile_mo(po_path)
        else:
            assert self.supported_locales == ["en"], (
                "No translations are needed, so the supported locales should be ['en']"
            )

    def compile_psynet_translations_if_necessary(self):
        self.compile_translations_if_necessary(
            join_path(abspath(dirname(__file__)), "locales"), "psynet"
        )

    @classproperty
    def is_deployed_experiment(cls):
        return deployment_info.read("mode") == "live"

    @classproperty
    def needs_internet_access(cls):
        return get_config().get("needs_internet_access")

    @classproperty
    def artifact_storage_available(cls):
        if cls.artifact_storage is None:
            return False
        if not cls.needs_internet_access and isinstance(
            cls.artifact_storage, S3Storage
        ):
            # S3 not available when offline
            return False
        return True

    @classproperty
    def automatic_backups(cls):
        return False
        # TODO: reinstate this once we have fixed automatic backups
        # return cls.is_deployed_experiment and cls.artifact_storage_available

    @classproperty
    def notifier(cls) -> Notifier:
        notifier_name = get_config().get("notifier")
        notifier_class = get_descendent_class_by_name(Notifier, notifier_name)
        return notifier_class()

    @with_transaction
    def on_launch(self):
        self.compile_psynet_translations_if_necessary()
        redis_vars.set("creation_time", datetime.now())
        redis_vars.set("launch_started", True)

        # Dallinger's `get_base_url` only returns an accurate value when called within the context
        # of an HTTP request. We know that `on_launch` is called within the context of an HTTP request,
        # so we take this opportunity to save the base URL to Redis.
        redis_vars.set("base_url", dallinger_get_base_url())

        super().on_launch()
        if not deployment_info.read("redeploying_from_archive"):
            self.on_first_launch()
        self.on_every_launch()

        if self._websocket_message_handlers:
            from dallinger.experiment_server import sockets

            for channel_name in self._websocket_message_handlers:
                sockets.chat_backend.subscribe(self, channel_name)

        db.session.commit()
        redis_vars.set("launch_finished", True)
        self.notifier.on_launch()

        # This log message is used by the testing logic to identify when the experiment has been launched
        logger.info("Experiment launch complete!")

    @classproperty
    def creation_time(cls):  # noqa
        return redis_vars.get("creation_time")

    def on_first_launch(self):
        for trialmaker in self.timeline.trial_makers.values():
            trialmaker.on_first_launch(self)

    def on_every_launch(self):
        # This check is helpful to stop the database from being ingested multiple times
        # if the launch fails the first time
        deployment_db_ingested = redis_vars.get("deployment_db_ingested", False)
        if not deployment_db_ingested:
            ingest_zip(database_template_path, db.engine)
            redis_vars.set("deployment_db_ingested", True)
            assert ExperimentConfig.query.count() > 0

        self._nodes_on_deploy()

        config = dallinger_get_config()
        redis_vars.set("server_working_directory", os.getcwd())
        self.var.deployment_id = deployment_info.read("deployment_id")
        self.var.label = self.label
        if deployment_info.read("is_local_deployment"):
            # This is necessary because the local deployment command is blocking and therefore we can't
            # get the launch data from the command-line invocation.
            export_launch_data(
                self.var.deployment_id,
                dashboard_user=config.get("dashboard_user"),
                dashboard_password=config.get("dashboard_password"),
            )
        self.load_deployment_config()
        self.asset_storage.on_every_launch()
        self.record_experiment_status()

    @staticmethod
    def before_request():
        flask_app_globals.request_start_time = time.monotonic()

    @staticmethod
    def after_request(request, response):
        diff = time.monotonic() - flask_app_globals.request_start_time
        relevant_endpoints = [
            "/ad",
            "/consent",
            "/on-demand-asset",
            "/response",
            "/start",
            "/timeline",
        ]
        if any([endpoint == request.path for endpoint in relevant_endpoints]):
            params = dict(request.args)
            request_obj = Request(
                unique_id=params.get("unique_id", None),
                duration=diff,
                method=request.method,
                endpoint=request.path,
                params=params,
                status_code=response.status_code,
            )
            db.session.add(request_obj)
            db.session.commit()
        return response

    @staticmethod
    @with_transaction
    def gunicorn_on_exit(server):
        exp = get_experiment()
        exp.record_experiment_status(online=False)

    @staticmethod
    def gunicorn_worker_exit(server, worker):
        exp = get_experiment()
        # This function is not called on SIGKILL, however we can still log most such occurrences via
        # `gunicorn_post_worker_init`.
        if worker.exitcode == 0:
            # Occurs when max-requests is reached or when server is reloaded
            return None

        exp.notifier.notify(
            f"A worker (pid: {worker.pid}) was stopped with exit code {worker.exitcode} 🛑"
        )

    @staticmethod
    def gunicorn_post_worker_init(worker):
        exp = get_experiment()
        exp.notifier.notify(
            f"A worker restarted (new pid: {worker.pid}). "
            "Please check the logs to find out why ⚠️"
        )

    @classmethod
    def get_request_statistics(cls, lookback_s):
        now = datetime.now()
        lookback = now - timedelta(seconds=lookback_s)
        all_requests = Request.query.filter(Request.creation_time > lookback).all()
        durations = [req.duration for req in all_requests]
        return {
            "median_response_time": (
                float(median(durations)) if len(durations) > 0 else 0
            ),
            "requests_per_minute": len(durations),
        }

    @staticmethod
    def notify_recruiter_status_change(current_recruitment_status):
        if current_recruitment_status is not None:
            old_recruitment_status = redis_vars.get("recruitment_study_status", None)
            if old_recruitment_status != current_recruitment_status:
                redis_vars.set("recruitment_study_status", current_recruitment_status)
                exp = get_experiment()
                if old_recruitment_status is None:
                    exp.notifier.notify(
                        f"Recruitment status: `{current_recruitment_status}`"
                    )
                else:
                    exp.notifier.notify(
                        f"Recruitment status changed from `{old_recruitment_status}` to `{current_recruitment_status}`"
                    )

    @classmethod
    def format_recruiter_status(cls, status: Union[dict, RecruitmentStatus]) -> dict:
        recruiter_name = None
        if isinstance(status, dict):
            if "recruiter_name" in status:
                recruiter_name = status["recruiter_name"]
        elif isinstance(status, RecruitmentStatus):
            recruiter_name = status.recruiter_name
            status = status.__dict__
        else:
            raise ValueError(
                f"Unknown status type: {type(status)}. Must be one of: dict, RecruitmentStatus"
            )
        status = {
            f"recruitment_{k}": v for k, v in status.items() if k != "recruiter_name"
        }

        exp = get_experiment()

        return {
            **status,
            "recruiter": recruiter_name,
            "need_more_participants": exp.need_more_participants,
        }

    @scheduled_task("interval", seconds=60, max_instances=1)
    @log_time_taken
    @staticmethod
    @with_transaction
    def get_recruiter_status():
        exp = get_experiment()
        status = exp.recruiter.get_status()
        status = exp.format_recruiter_status(status)

        exp.notify_recruiter_status_change(status.get("recruitment_study_status", None))
        exp.artifact_storage.write_recruitment_status(status, exp.deployment_id)

    @classmethod
    def get_hardware_status(cls):
        cpu_freq = psutil.cpu_freq()
        ghz_cpus = "N/A" if cpu_freq is None else f"{cpu_freq.current / 1000:.1f}GHz"
        n_cpus = psutil.cpu_count(logical=False)
        cpu_specs = f"{n_cpus}x @ {ghz_cpus}"
        ram_specs = format_bytes(psutil.virtual_memory().total)
        disk_specs = format_bytes(psutil.disk_usage("/").total)

        config = get_config()
        mute_same_warning_for_n_hours = config.get("mute_same_warning_for_n_hours")
        resource_warning_pct = config.get("resource_warning_pct") * 100
        resource_danger_pct = config.get("resource_danger_pct") * 100

        ram_usage_pct = psutil.virtual_memory().percent
        cpu_usage_pct = psutil.cpu_percent()

        resources = {
            "ram": ram_usage_pct,
            "cpu": cpu_usage_pct,
        }
        for resource_type, pct in resources.items():
            if pct > resource_danger_pct:
                cls.notifier.resource_usage_notification(
                    resource_type, mute_same_warning_for_n_hours, level="danger"
                )
            elif pct > resource_warning_pct:
                cls.notifier.resource_usage_notification(
                    resource_type, mute_same_warning_for_n_hours, level="warning"
                )

        minimal_disk_space_warning_gb = config.get("minimal_disk_space_warning_gb")
        minimal_disk_space_danger_gb = config.get("minimal_disk_space_danger_gb")

        free_disk_usage_gb = psutil.disk_usage("/").free / (1024**3)
        if free_disk_usage_gb < minimal_disk_space_danger_gb:
            cls.notifier.resource_usage_notification(
                "disk", mute_same_warning_for_n_hours, level="danger"
            )
        elif free_disk_usage_gb < minimal_disk_space_warning_gb:
            cls.notifier.resource_usage_notification(
                "disk", mute_same_warning_for_n_hours, level="warning"
            )

        return {
            "cpu_specs": cpu_specs,
            "cpu_usage_pct": cpu_usage_pct,
            "ram_specs": ram_specs,
            "ram_usage_pct": ram_usage_pct,
            "disk_specs": disk_specs,
            "disk_usage_pct": 100 - psutil.disk_usage("/").percent,
        }

    @classproperty
    def base_url(cls):
        return get_experiment_url()

    @classmethod
    def get_artifact_url(cls, deployment_id, filename):
        return f"{cls.base_url}/dashboard/artifact/{deployment_id}/{filename}"

    @classproperty
    def deployment_id(cls):
        return deployment_info.read("deployment_id")

    @classproperty
    def basic_data_url(cls, config=None):
        """
        While it is not considered best practice in general to put authentication parameters in the  URL itself, we
        consider it to be worth it here, because it allows very easy access to the `/basic_data` route from e.g. the web
        browser, R, or Python.

        Note that the /basic_data route should not provide sensitive information anyway so it shouldn't really matter if
        someone accesses it.
        """
        if config is None:
            config = get_config()
        data_params = []
        for keys in ["dashboard_user", "dashboard_password"]:
            data_params.append(f"{keys}={config.get(keys)}")
        data_params = "&".join(data_params)
        return cls.base_url + "/basic_data?" + data_params

    @classproperty
    def dashboard_url(cls):
        return cls.base_url + "/dashboard"

    @staticmethod
    def get_last_n_from_class(
        klass: Type[Union[SQLMixin, SQLBase]], limit: int = 1000
    ) -> List[object]:
        """
        Returns the last n objects from the given class.
        """
        query = klass.query.order_by(klass.id.desc())
        if limit:
            query = query.limit(limit)
        return query.all()

    @classmethod
    def get_all_error_records(cls, limit=1000):
        return cls.get_last_n_from_class(ErrorRecord, limit=limit)

    @classmethod
    def get_experiment_information(cls):
        config = get_config()

        deployment_information = deployment_info.read_all()
        deployment_information["secret"] = str(deployment_information["secret"])
        is_ssh_deployment = deployment_information.get("is_ssh_deployment", False)

        logs_url = None
        if is_ssh_deployment:
            logs_url = "https://logs." + deployment_information.get("server")

        def unpack_export(export_type, deployment_id):
            assert export_type in ["psynet", "database"]
            exp = get_experiment()
            storage = exp.artifact_storage
            filename = f"{export_type}.zip"
            path = storage.prepare_path(deployment_id, filename)
            try:
                timestamp = (
                    storage.get_modification_date(path)
                    .astimezone()
                    .isoformat(timespec="minutes")
                )
                return {
                    "url": exp.get_artifact_url(deployment_id, filename),
                    "timestamp": timestamp,
                }
            except FileNotFoundError:
                return {
                    "url": None,
                    "timestamp": None,
                }

        deployment_id = deployment_information["deployment_id"]
        psynet_export = unpack_export("psynet", deployment_id)
        database_export = unpack_export("database", deployment_id)

        error_msgs = [
            f"{error.kind}:{error.message}" for error in cls.get_all_error_records()
        ]
        error_hist = dict(Counter(error_msgs))

        return {
            **deployment_information,
            "asset_storage": cls.asset_storage.__class__.__name__,
            "n_errors": len(error_msgs),
            "error_hist": error_hist,
            "title": config.get("title", None),
            "description": config.get("description", None),
            "label": cls.label,
            "initial_recruitment_size": cls.initial_recruitment_size,
            "auto_recruit": config.get("auto_recruit", None),
            "launch_time": cls.creation_time.astimezone().isoformat(timespec="minutes"),
            "now": datetime.now().astimezone().isoformat(timespec="minutes"),
            "experimenter_name": config.get("experimenter_name", None),
            "currency": config.get("currency", None),
            "dashboard_url": cls.dashboard_url,
            "logs_url": logs_url,
            "basic_data_url": cls.basic_data_url,
            "psynet_export_url": psynet_export["url"],
            "psynet_export_timestamp": psynet_export["timestamp"],
            "database_export_url": database_export["url"],
            "database_export_timestamp": database_export["timestamp"],
        }

    @classmethod
    def get_participant_status(cls):
        participants = Participant.query.all()
        complete_participants = [
            participant for participant in participants if participant.complete
        ]
        time_taken = []
        for participant in complete_participants:
            try:
                time_taken.append(
                    (participant.end_time - participant.creation_time).total_seconds()
                )
            except TypeError:
                # If the participant has no end time, just to be sure
                pass
        median_time_taken = median(time_taken) if len(time_taken) > 0 else 0
        estimated_duration = cls.estimated_completion_time(
            None
        )  # wage_per_hour is not used
        total_rewards = [
            participant.calculate_reward() for participant in complete_participants
        ]
        total_cost = sum(total_rewards)
        participant_status_summary = dict(
            Counter([participant.status for participant in participants])
        )
        return {
            "total_cost": total_cost,
            "participant_statuses": participant_status_summary,
            "median_time_taken": median_time_taken,
            "estimated_duration": estimated_duration,
        }

    @classmethod
    def get_status(cls, lookback_s=60):
        return {
            **super().get_status(),
            **cls.get_request_statistics(lookback_s=lookback_s),
            **cls.get_hardware_status(),
            **cls.get_participant_status(),
            **cls.get_experiment_information(),
        }

    @classmethod
    def record_experiment_status(cls, online: bool = True):
        status = cls.get_status(lookback_s=60)  # since we poll every minute
        status["isOffline"] = not online
        status_obj = ExperimentStatus(**status)
        db.session.add(status_obj)
        if cls.automatic_backups:
            cls.artifact_storage.write_experiment_status(status, cls.deployment_id)

    @scheduled_task("interval", seconds=60, max_instances=1)
    @log_time_taken
    @staticmethod
    @with_transaction
    def status_and_backups():
        # TODO: consider placing these in separate scheduled tasks
        if not is_experiment_launched():
            return
        exp = get_experiment()
        safe(exp.record_experiment_status)()
        if exp.automatic_backups:
            safe(exp.backup_basic_data)()
            safe(exp.backup_database)()

    @classmethod
    def backup_database(cls):
        with tempfile.TemporaryDirectory() as tempdir:
            # TODO: rewrite to avoid this psynet_export argument
            input_path = cls._export(tempdir, psynet_export=False)
            cls.artifact_storage.upload_export(
                input_path, deployment_id=cls.deployment_id
            )

    @classmethod
    def get_basic_data(
        cls,
        context=None,
        **kwargs,
    ):
        """
        Parameters
        ----------

        context: str
             Will receive a string that describes the context in which the function has been called.
             Possibles include:
             - "dashboard": The function is producing data to be displayed in the dashboard
             - "export": The function is being called within psynet export
             - "backup": The function is being called within PsyNet autobackups
             The default implementation of get_basic_data ignores this context parameter and just returns the same data in all
             contexts, but experimenters can optionally make their logical conditional on this variable.

        ** kwargs:
            Dictionary of arbitrary URL GET parameters that can optionally be used by the get_basic_data implementation to
            further customiser what data is provided.

        Returns
        -------
        dict | None
            A dictionary of data to be returned to the client. The keys of the dictionary should be strings, and the
            values can be any JSON-serializable object. Return ``None`` if no basic data is provided.

        Raises
        ------
        DataError
            A custom exception that can be raised if the data cannot be retrieved for some reason.

        See `artifact_storage` for an example.
        """
        return None

    @classmethod
    def backup_basic_data(cls):
        data = cls.get_basic_data(context="backup")
        if data is not None:
            cls.artifact_storage.write_basic_data(data)

    @staticmethod
    def request_contains_valid_dashboard_credentials(request):
        params = dict(request.args)
        username = params.get("dashboard_user", None)
        password = params.get("dashboard_password", None)
        config = get_config()
        return (
            config.get("dashboard_user") == username
            and config.get("dashboard_password") == password
        )

    @experiment_route("/basic_data", methods=["GET"])
    @nocache
    @staticmethod
    def basic_data():
        try:
            exp = get_experiment()
            if not exp.request_contains_valid_dashboard_credentials(request):
                return error_response(error_text="Invalid credentials", simple=True)

            data = exp.get_basic_data(context="route", **request.args)
            if data is None:
                return []

            return data
        except ValueError as e:
            return error_response(error_text=e.__str__(), simple=True)

    def load_deployment_config(self):
        config = dallinger_get_config()
        if not config.ready:
            config.load()
        # as_dict() resolves each key by source priority, matching what
        # config.get() would return; merging config.data layers manually
        # would resolve by load order instead. as_dict() only excludes
        # keys registered as sensitive, so also apply is_sensitive(),
        # which additionally matches sensitive-looking key names.
        self.var.deployment_config = {
            key: value
            for key, value in config.as_dict().items()
            if not config.is_sensitive(key)
        }

    def _nodes_on_deploy(self):
        from .trial.main import TrialNode

        db.session.commit()

        for node in (
            TrialNode.query.with_for_update(of=TrialNode).populate_existing().all()
        ):
            node.check_on_deploy()

        db.session.commit()

    def participant_constructor(self, *args, **kwargs):
        return Participant(experiment=self, *args, **kwargs)

    def initialize_bot(self, bot):
        """
        This function is called when a bot is created.
        It can be used to set stochastic random parameters corresponding
        to participant latent traits, for example.

        e.g.

        ```bot.var.musician = True``
        """
        pass

    test_n_bots = 1
    test_mode = "serial"
    test_time_factor = 0.0

    def test_experiment(self):
        os.environ["PASSTHROUGH_ERRORS"] = "True"
        self._check_static_spa_contracts()

        if self.test_mode == "serial" or self.test_n_bots == 1:
            self._test_experiment_serial()
        elif self.test_mode == "parallel":
            run_parallel_test(
                n_bots=self.test_n_bots,
                time_factor=self.test_time_factor,
                stagger_interval_s=self.test_parallel_stagger_interval_s,
                check_bots=self.test_check_bots,
            )
        else:
            raise ValueError(f"Invalid test mode: {self.test_mode}")

        self._report_request_statistics()

    def _check_static_spa_contracts(self):
        """Fail fast on static timeline pages that are not SPA-compatible.

        PageMakers are skipped here because their pages do not exist until
        runtime; bots still surface those via richer HTTP 500 details.
        """
        from .timeline import Page
        from .utils import get_config

        config = get_config()
        inplace = config.get("inplace_timeline_transitions")
        for elt in self.timeline.all_elts:
            if not isinstance(elt, Page):
                continue
            elt._check_spa_template_contract(inplace_timeline_transitions=inplace)

    # This is how many seconds to wait between invoking parallel bots
    test_parallel_stagger_interval_s = 0.1

    test_duration_minutes = 1

    def _report_request_statistics(self) -> Optional[float]:
        response = self.authenticated_session.get(self.base_url + "/request_statistics")
        response.raise_for_status()
        mean_duration = response.json()["mean_duration"]

        if mean_duration is None:
            logger.info("Found no requests to report statistics for.")
        else:
            logger.info(f"Mean HTTP request duration: {mean_duration:.3f} seconds")

    @experiment_route("/request_statistics", methods=["GET"])
    @classmethod
    @login_required
    @with_transaction
    def request_statistics(cls):
        # Note that we restrict consideration to the key participant-facing requests.
        key_endpoints = ["/timeline", "/response"]

        mean_duration = (
            db.session.query(func.avg(Request.duration))
            .filter(Request.endpoint.in_(key_endpoints))
            .scalar()
        )

        total_requests = (db.session.query(func.count(Request.id)).scalar()) or 0

        return {
            "mean_duration": mean_duration,
            "total_requests": total_requests,
        }

    def _test_experiment_serial(self):
        logger.info(f"Testing experiment with {self.test_n_bots} serial bot(s)...")

        bots = [BotDriver() for _ in range(self.test_n_bots)]
        self.test_serial_run_bots(bots)

        # At the checking stage, it's most convenient to test the actual Bot instances
        # rather than the BotDriver instances.
        with transaction():
            bots = Bot.query.all()
            self.test_check_bots(bots)

    def test_serial_run_bots(self, bots: List[BotDriver]):
        """
        Defines the logic for testing the experiment in a serial process
        (i.e. not running bots in parallel processes).
        This is useful for testing specific experiment logic,
        but less useful for load-testing.

        By default, this method is very simple: it just iterates over each
        bot in turn, and runs that bot from the beginning to the end
        of the experiment.

        Experiments can override this method to implement more complex logic.
        When doing so, it's worth familiarizing yourself a little with how
        the BotDriver class works. Unlike many other classes in PsyNet,
        it's not a SQLAlchemy model, but rather a utility class that
        wraps an underlying SQLAlchemy model (the Bot class).
        See the class's documentation for more details.
        """
        for bot in bots:
            self.run_bot(bot, time_factor=self.test_time_factor)

    @classmethod
    def run_bot(
        cls,
        bot: Optional[BotDriver] = None,
        render_pages: bool = True,
        time_factor: float = 0.0,
    ):
        if bot is None:
            bot = BotDriver()

        bot.take_experiment(render_pages, time_factor)

    def test_check_bots(self, bots: List[Bot]):
        for b in bots:
            self.test_check_bot(b)

    def test_check_bot(self, bot: Bot, **kwargs):
        assert not bot.failed

    @classmethod
    def error_page(
        cls,
        participant=None,
        error_text=None,
        recruiter=None,
        external_submit_url=None,
        compensate=True,
        error_type="default",
        request_data="",
        locale=DEFAULT_LOCALE,
    ):
        """Render HTML for error page."""
        from flask import make_response, request

        _p = get_translator(context=True)
        if error_text is None:
            error_text = _p(
                "error-msg",
                "There has been an error and so you are unable to continue, sorry!",
            )

        if participant is not None:
            hit_id = participant.hit_id
            assignment_id = participant.assignment_id
            worker_id = participant.worker_id
            participant_id = participant.id
        else:
            hit_id = request.form.get("hit_id", "")
            assignment_id = request.form.get("assignment_id", "")
            worker_id = request.form.get("worker_id", "")
            participant_id = request.form.get("participant_id", None)

        if participant_id:
            try:
                participant_id = int(participant_id)
            except (ValueError, TypeError):
                participant_id = None

        return make_response(
            render_template_with_translations(
                "psynet_error.html",
                locale=locale,
                error_text=error_text,
                compensate=compensate,
                contact_address=get_config().get("contact_email_on_error"),
                error_type=error_type,
                hit_id=hit_id,
                assignment_id=assignment_id,
                worker_id=worker_id,
                recruiter=recruiter,
                request_data=request_data,
                participant_id=participant_id,
                external_submit_url=external_submit_url,
            ),
            500,
        )

    def error_page_content(
        self,
        contact_address,
        error_type,
        hit_id,
        assignment_id,
        worker_id,
        external_submit_url,
    ):
        _ = get_translator()
        _p = get_translator(context=True)

        if hasattr(self.recruiter, "error_page_content"):
            return self.recruiter.error_page_content(
                assignment_id=assignment_id,
                external_submit_url=external_submit_url,
            )

        # TODO: Refactor this so that the error page content generation is deferred to the recruiter class.
        if isinstance(self.recruiter, ProlificRecruiter):
            return self.error_page_content__prolific()
        elif isinstance(self.recruiter, MTurkRecruiter):
            html = tags.div()
            with html:
                tags.p(
                    _p(
                        "mturk_error",
                        "To enquire about compensation, please contact the researcher at {EMAIL} and describe what led to this error.",
                    ).format(EMAIL=contact_address)
                )
                tags.p(
                    _p("mturk_error", "Please also quote the following information:")
                )
                tags.ul(
                    tags.li(f"{_('Error type')}: {error_type}"),
                    tags.li(f"{_('HIT ID')}: {hit_id}"),
                    tags.li(f"{_('Assignment ID')}: {assignment_id}"),
                    tags.li(f"{_('Worker ID')}: {worker_id}"),
                )

            return html
        else:
            return ""

    def error_page_content__prolific(self):
        _p = get_translator(context=True)

        html = tags.div()
        with html:
            tags.p(
                " ".join(
                    [
                        _p(
                            "prolific_error",
                            "Don't worry, your progress has been recorded.",
                        ),
                        _p(
                            "prolific_error",
                            "To enquire about compensation, please send the researcher a message via the Prolific website and describe what led to your error.",
                        ),
                    ]
                )
            )
        return html

    @scheduled_task("interval", minutes=1, max_instances=1)
    @staticmethod
    @with_transaction
    def check_database():
        if not is_experiment_launched():
            return
        exp = get_experiment()
        for c in exp.database_checks:
            c.run()

    @scheduled_task("interval", minutes=1, max_instances=1)
    @staticmethod
    @with_transaction
    def run_recruiter_checks():
        if not is_experiment_launched():
            return
        exp = get_experiment()
        recruiter = exp.recruiter
        logger.info("Running recruiter checks...")
        if hasattr(recruiter, "run_checks"):
            recruiter.run_checks()

    @scheduled_task("interval", seconds=2, max_instances=1)
    @log_time_taken
    @staticmethod
    @with_transaction
    def _grow_networks():
        if not is_experiment_launched():
            return
        exp = get_experiment()
        exp.grow_networks()

    @staticmethod
    def _fail_grown_network(network):
        """Mark a network's head (or degree-0 trials) failed after a grow error."""
        if network.head is not None and network.head.degree > 0:
            network.head.fail()
        elif network.head is not None and network.head.degree == 0:
            for trial in network.head.all_trials:
                trial.fail()

    @staticmethod
    def grow_networks():
        from psynet.trial.chain import ChainTrialMaker

        # The poller is the authoritative growth backstop for both across- and
        # within-chain networks. Within-chain trial finalization still attempts
        # immediate growth to reduce participant latency, but correctness does
        # not depend on that callback running. The readiness helpers use
        # ``skip_locked=True`` so maintenance can grow other networks rather
        # than waiting behind rows locked by participant requests or manual
        # grow calls.
        networks = []
        exp = get_experiment()
        for trial_maker in exp.timeline.trial_makers.values():
            if isinstance(trial_maker, ChainTrialMaker):
                networks.extend(trial_maker.get_networks_ready_to_grow())

        if len(networks) > 0:
            logger.info("Growing %i networks...", len(networks))
            # Iterate by ID so a mid-batch handle_error rollback cannot leave us
            # holding detached ORM instances for later networks.
            for network_id in [network.id for network in networks]:
                network = db.session.get(TrialNetwork, network_id)
                if network is None:
                    continue
                try:
                    network.trial_maker.call_grow_network(
                        network, check_readiness=False
                    )
                except Exception as err:
                    # Re-fetch after handle_error rollback; commit the fail so a
                    # later error in this batch cannot undo it.
                    exp.isolate_batch_item_failure(
                        err,
                        refetch=lambda: db.session.get(TrialNetwork, network_id),
                        fail=Experiment._fail_grown_network,
                        network=network,
                    )

            logger.info("Finished growing networks.")

    @scheduled_task("interval", seconds=5, max_instances=1)
    @log_time_taken
    @staticmethod
    @with_transaction
    def _finalize_pending_trials():
        if not is_experiment_launched():
            return
        # Event-driven finalize checks remain the fast path. This poller only
        # recovers trials that became ready without those callbacks running.
        Trial.finalize_pending_trials()

    @scheduled_task("interval", seconds=0.5, max_instances=1)
    @log_time_taken
    @staticmethod
    def _check_barriers():
        if not is_experiment_launched():
            return
        from .sync import check_barriers

        check_barriers()

    @scheduled_task("interval", seconds=2.5, max_instances=1)
    @log_time_taken
    @staticmethod
    @with_transaction
    def _check_sync_groups():
        if not is_experiment_launched():
            return
        exp = get_experiment()
        exp.check_sync_groups()

    @staticmethod
    def check_sync_groups():
        from .sync import SyncGroup

        groups = (
            # Eagerly load all polymorphic subclasses to avoid lazy loading in the loop
            db.session.query(with_polymorphic(SyncGroup, "*"))
            .filter(SyncGroup.active)
            # TODO - see if we can introduce this locking once the transaction managemnet in the tests is fixed
            # .with_for_update(of=[SyncGroup, Participant])
            .with_for_update(of=[SyncGroup])
            .populate_existing()
            .all()
        )

        for group in groups:
            group.check_numbers()

    @property
    def base_payment(self):
        return get_config().get("base_payment")

    @property
    def variable_placeholders(self):
        return {}

    def get_initial_recruitment_size(self):
        return get_config().get("initial_recruitment_size")

    @classproperty
    def label(cls):  # noqa
        return get_config().get("label")

    @staticmethod
    def export_path(deployment_id):
        export_root = "~/psynet-data/export"

        return os.path.join(
            export_root,
            deployment_id,
            re.sub(
                "__launch.*", "", deployment_id
            )  # Strip the launch date from the path to keep things short
            + "__export="
            + datetime.now().strftime("%Y-%m-%d--%H-%M-%S"),
        )

    @property
    def var(self):
        if self.experiment_config:
            return self.experiment_config.var
        else:
            return ImmutableVarStore(self.variables_initial_values)

    # We persist _experiment_config to avoid garbage collection and hence support database updates
    _experiment_config = None

    @property
    def experiment_config(self):
        self._experiment_config = ExperimentConfig.query.get(1)
        return self._experiment_config

    def register_participant_fail_routine(self, routine):
        self.participant_fail_routines.append(routine)

    def register_recruitment_criterion(self, criterion):
        self.recruitment_criteria.append(criterion)

    def register_database_check(self, task):
        self.database_checks.append(task)

    @classmethod
    def new(cls, session):
        return cls(session)

    @classmethod
    def amount_spent(cls):
        return sum(
            [
                (0.0 if p.base_payment is None else p.base_payment)
                + (0.0 if p.bonus is None else p.bonus)
                for p in Participant.query.all()
            ]
        )

    @classmethod
    def estimated_max_reward(cls, wage_per_hour):
        return cls.timeline.estimated_max_reward(wage_per_hour)

    @classmethod
    def estimated_completion_time(cls, wage_per_hour):
        return cls.timeline.estimated_completion_time(wage_per_hour)

    def setup_experiment_config(self):
        if self.experiment_config is None:
            logger.info("Setting up ExperimentConfig.")
            network = ExperimentConfig()
            db.session.add(network)
            db.session.commit()

    @classproperty
    def config(cls):
        return {}

    @classmethod
    def get_experiment_folder_name(cls):
        try:
            return deployment_info.read("folder_name")
        except (KeyError, FileNotFoundError):
            return os.path.basename(os.getcwd())

    @classmethod
    def get_username(cls):
        try:
            return os.getlogin()
        except OSError:
            return "unknown"

    @classmethod
    def config_defaults(cls):
        """
        Override this classmethod to register new default values for config variables.
        Remember to call super!
        """

        config = {
            **super().config_defaults(),
            "allow_mobile_devices": False,
            "base_payment": 0.10,
            "big_base_payment": False,
            "check_dallinger_version": False,
            "clock_on": True,
            "color_mode": "light",
            "currency": "$",
            "default_translator": "chat_gpt",
            "disable_browser_autotranslate": True,
            "disable_when_duration_exceeded": False,
            "docker_volumes": "${HOME}/psynet-data/assets:/psynet-data/assets",
            "duration": 100000000.0,
            "experimenter_name": cls.get_username(),
            "force_google_chrome": True,
            "notifier": "logger",
            "leave_comments_on_every_page": False,
            "force_incognito_mode": False,
            "openai_default_model": "gpt-4o",
            "openai_default_temperature": 0,
            "host": "0.0.0.0",
            "initial_recruitment_size": INITIAL_RECRUITMENT_SIZE,
            "label": cls.get_experiment_folder_name(),
            "lock_table_when_creating_participant": False,
            "loglevel": 1,
            "loglevel_worker": 1,
            "min_accumulated_reward_for_abort": 0.20,
            "min_browser_version": "80.0",
            "prolific_is_custom_screening": False,
            "prolific_enable_return_for_bonus": True,
            "protected_routes": json.dumps(_protected_routes),
            "show_abort_button": False,
            "show_footer": True,
            "show_progress_bar": True,
            "show_reward": True,
            "inplace_timeline_transitions": True,
            "legacy_js_var_globals": "warn",
            "needs_internet_access": True,
            "check_participant_opened_devtools": False,
            "supported_locales": "[]",
            "wage_per_hour": 9.0,
            "window_height": 768,
            "window_width": 1024,
            "mute_same_warning_for_n_hours": 1,
            "resource_warning_pct": 0.9,
            "resource_danger_pct": 0.95,
            "minimal_disk_space_warning_gb": 5,
            "minimal_disk_space_danger_gb": 2,
        }

        return cls._normalize_config_types(config)

    @classmethod
    def config_settings(cls):
        """
        Values set in the experiment's ``config`` dictionary.

        These are the experimenter's explicit decisions: they override the
        user's ``~/.dallingerconfig``. The experiment's ``config.txt``
        formally takes precedence over them (though PsyNet forbids setting
        the same key in both places), followed by environment variables and
        runtime writes.
        """
        return cls._normalize_config_types(
            {
                **super().config_settings(),
                **cls.config,
            }
        )

    @classmethod
    def _normalize_config_types(cls, config):
        """Cast config values to the types Dallinger expects."""
        config_types = dallinger_get_config().types

        for key, value in config.items():
            if not isinstance(value, (bool, int, float, str)):
                # Dallinger expects non-primitive types to be expressed as JSON-encoded strings.
                # We should probably update this behavior in the future.
                value = serialize(value)

            expected_type = config_types[key]
            value = expected_type(value)

            config[key] = value

        return config

    @property
    def _default_variables(self):
        return {
            "psynet_version": __version__,
            "dallinger_version": dallinger_version,
            "python_version": python_version(),
            "hard_max_experiment_payment_email_sent": False,
            "soft_max_experiment_payment_email_sent": False,
            "hard_max_experiment_payment": 1100.0,
            "soft_max_experiment_payment": 1000.0,
            "max_participant_payment": 25.0,
        }

    @experiment_route("/api/<endpoint>", methods=["GET", "POST"])
    @staticmethod
    @with_transaction
    def custom_route(endpoint):
        from psynet.api import EXPOSED_FUNCTIONS

        if endpoint not in EXPOSED_FUNCTIONS:
            return error_response(
                error_text=f"{endpoint} is not defined. Defined endpoints are: {list(EXPOSED_FUNCTIONS.keys())}",
                simple=True,
            )

        if request.method == "POST":
            data = request.get_json()
        elif request.method == "GET":
            data = request.args
        else:
            return error_response(
                error_text=f"Unsupported request method {request.method}", simple=True
            )
        function = EXPOSED_FUNCTIONS[endpoint]
        return function(**data)

    @property
    def psynet_logo(self):
        return PsyNetLogo()

    @property
    def start_experiment_in_popup_window(self):
        if self.var.has("start_experiment_in_popup_window"):
            # This is for simulating pop up behaviour in psynet demo tests
            return self.var.get("start_experiment_in_popup_window")
        elif hasattr(self.recruiter, "start_experiment_in_popup_window"):
            return self.recruiter.start_experiment_in_popup_window
        elif isinstance(self.recruiter, MTurkRecruiter):
            return True

        else:
            return False

    @property
    def description(self):
        return get_config().get("description")

    @property
    def ad_requirements(self):
        return [
            'The experiment can only be performed using a <span style="font-weight: bold;">laptop</span> (desktop computers are not allowed).',
            'You should use an <span style="font-weight: bold;">updated Google Chrome</span> browser.',
            'You should be sitting in a <span style="font-weight: bold;">quiet environment</span>.',
            'You should be at least <span style="font-weight: bold;">18 years old</span>.',
            'You should be a <span style="font-weight: bold;">fluent English speaker</span>.',
        ]

    @property
    def ad_payment_information(self):
        return f"""
                We estimate that the task should take approximately <span style="font-weight: bold;">{round(self.estimated_duration_in_minutes)} minutes</span>. Upon completion of the full task,
                <br>
                you should receive a reward of approximately
                <span style="font-weight: bold;">${"{:.2f}".format(self.estimated_reward_in_dollars)}</span> depending on the
                amount of work done.
                <br>
                In some cases, the experiment may finish early: this is not an error, and there is no need to write to us.
                <br>
                In this case you will be paid in proportion to the amount of the experiment that you completed.
                """

    @property
    def variables_initial_values(self):
        for key, value in self.variables.items():
            assert key not in list(get_config().as_dict().keys()), (
                f"Variable {key} is a config variable and should solely be specified in the config.txt or in "
                "experiment.config but NOT as experiment variable."
            )
        return {**self._default_variables, **self.variables}

    @property
    def estimated_duration_in_minutes(self):
        return self.timeline.estimated_time_credit.get_max("time") / 60

    @property
    def estimated_reward_in_dollars(self):
        wage_per_hour = get_config().get("wage_per_hour")
        return round(
            self.timeline.estimated_time_credit.get_max(
                "reward",
                wage_per_hour=wage_per_hour,
            ),
            2,
        )

    def setup_experiment_variables(self):
        # Note: the experiment network must be setup first before we can set these variables.
        for key, value in self.variables_initial_values.items():
            self.var.set(key, value)

        db.session.commit()

    # def prepare_generic_trial_network(self):
    #     network = GenericTrialNetwork(experiment=self)
    #     source = GenericTrialNode(network=network)
    #     db.session.add(network)
    #     db.session.add(source)
    #     db.session.commit()

    def process_timeline(self):
        for elt in self.timeline.all_elts:
            if isinstance(elt, DatabaseCheck):
                self.register_database_check(elt)
            if isinstance(elt, ParticipantFailRoutine):
                self.register_participant_fail_routine(elt)
            if isinstance(elt, RecruitmentCriterion):
                self.register_recruitment_criterion(elt)
            if isinstance(elt, Asset):
                elt.deposit_on_the_fly = False
                self.assets.stage(elt)
            if isinstance(elt, PreDeployRoutine):
                self.pre_deploy_routines.append(elt)
            if isinstance(elt, WebSocketElt) and elt.channel is not None:
                if not self._websocket_message_handlers:
                    # First WebSocketElt found: set the global channel so Dallinger
                    # automatically subscribes to dallinger_control on launch.
                    self.channel = WEBSOCKET_CHANNEL
                self._websocket_message_handlers.setdefault(elt.channel, []).append(
                    elt.handle_message
                )

    def receive_message(
        self, message, channel_name=None, participant=None, node=None, receive_time=None
    ):
        """Dispatch incoming WebSocket messages to the ``WebSocketElt`` handlers
        for the given channel.

        This override is activated automatically when any ``WebSocketElt``
        instances are present in the timeline. Handlers are keyed by channel
        name, so each Elt only receives messages from its own channel.
        """
        for handler in self._websocket_message_handlers.get(channel_name, []):
            handler(
                message,
                channel_name=channel_name,
                participant=participant,
                node=node,
                receive_time=receive_time,
                experiment=self,
            )

    def pre_deploy(self, redeploying_from_archive=False):
        self.update_deployment_id()
        self.setup_experiment_config()
        self.setup_experiment_variables()

        _write_pre_deploy_constant_registry()

        for module in self.timeline.modules.values():
            module.prepare_for_deployment(experiment=self)

        for routine in self.pre_deploy_routines:
            logger.info(f"Running pre-deployment routine '{routine.label}'...")
            call_function_with_context(
                routine.function, experiment=self, **routine.args
            )

        # Skip asset preparation and database snapshot when deploying from archive
        if not redeploying_from_archive:
            self.assets.prepare_for_deployment()
            self.create_database_snapshot()

        self.create_source_code_zip_file()

    @classmethod
    def create_source_code_zip_file(cls):
        from dallinger.command_line.utils import ExperimentFileSource

        # The config.txt file in the deployment package by default includes sensitive keys
        # (e.g. AWS API keys), so we don't allow this method to be run there
        assert not in_deployment_package()

        # We also need to check that the user hasn't left any sensitive keys in the
        # config.txt in their experiment directory.
        assert_config_txt_does_not_contain_sensitive_values()

        base_name = "source_code"
        with tempfile.TemporaryDirectory() as temp_dir:
            cwd = os.getcwd()
            ExperimentFileSource(cwd).apply_to(temp_dir, copy_func=shutil.copyfile)
            # `ExperimentFileSource` does not include `config.txt` (see `dallinger.utils.exclusion_policy`)
            # so we need to copy this manually.
            shutil.copyfile(f"{cwd}/config.txt", f"{temp_dir}/config.txt")
            # Delete static/assets directory to exclude them from the source code zip file
            shutil.rmtree(f"{temp_dir}/static/assets", ignore_errors=True)
            shutil.make_archive(base_name, "zip", temp_dir)

    @classmethod
    def update_deployment_id(cls):
        deployment_id = cls.generate_deployment_id()
        deployment_info.write(deployment_id=deployment_id)

    @classmethod
    def generate_deployment_id(cls):
        mode = deployment_info.read("mode")
        id_ = f"{cls.label}"
        id_ = id_.replace(" ", "-").lower()
        id_ += (
            "__mode="
            + mode
            + "__launch="
            + datetime.now().strftime("%Y-%m-%d--%H-%M-%S")
        )
        return id_

    @classmethod
    def create_database_snapshot(cls):
        logger.info("Creating a database snapshot...")
        try:
            os.remove(database_template_path)
        except FileNotFoundError:
            pass
        with tempfile.TemporaryDirectory() as temp_dir:
            with working_directory(temp_dir):
                with suppress_stdout():
                    dallinger.data.export("app", local=True, scrub_pii=False)
            shutil.copyfile(
                os.path.join(temp_dir, "data", "app-data.zip"),
                database_template_path,
            )

    @classmethod
    def check_size(cls):
        from dallinger.command_line.utils import ExperimentFileSource

        size_in_mb = ExperimentFileSource(os.getcwd()).size / (1024**2)
        log(f"Experiment directory size: {round(size_in_mb, 3)} MB.")

        exp_max_size_in_mb = int(os.environ.get("EXP_MAX_SIZE_MB", "256"))

        if size_in_mb > exp_max_size_in_mb:
            raise RuntimeError(
                f"Your experiment source package exceeds the {exp_max_size_in_mb} MB limit. "
                "Large packages are discouraged because they make deployment slow. You can override "
                "this limit by setting the EXP_MAX_SIZE_MB environment variable. "
                "However, the recommended approach (assuming your large files are "
                "assets, such as audio or video files) is to use PsyNet's asset management system; "
                "see https://psynetdev.gitlab.io/PsyNet/tutorials/assets.html for a tutorial. "
                "Importantly, you should either move your large files outside the experiment folder, "
                "or add them to `.gitignore`, once they are registered as `Asset` objects; that way "
                "they will not count towards your source package limit."
            )

    @classmethod
    def check_config(cls):
        config = get_config()

        if not config.get("clock_on"):
            # We force the clock to be on because it's necessary for the check_networks functionality.
            raise RuntimeError(
                "PsyNet requires the clock process to be enabled; please set clock_on = true in the "
                + "'[Server]' section of the config.txt."
            )

        if config.get("disable_when_duration_exceeded"):
            raise RuntimeError(
                "PsyNet requires disable_when_duration_exceeded = False; please set disable_when_duration_exceeded = False "
                + " in the '[Recruitment strategy]' section of the config.txt."
            )

        n_char_title = len(config.get("title"))
        if n_char_title > 128:
            raise RuntimeError(
                f"The maximum title length is 128 characters (current = {n_char_title}), please fix this in config.txt."
            )

        cls.check_base_payment(config)

        parser = configparser.ConfigParser()
        parser.read("config.txt")
        config_txt = {}

        for section in parser.sections():
            config_txt.update(dict(parser.items(section)))

        for key in cls.config:
            if key in config_txt:
                raise ValueError(
                    f"Config variable {key} was registered both in config.txt and experiment.py. "
                    f"Please choose just one location."
                )

        cls._warn_about_overridden_experiment_config(config)

    @classmethod
    def _warn_about_overridden_experiment_config(cls, config):
        """
        Warn when values set in ``Experiment.config`` lose out to
        higher-priority configuration sources.

        Values set in experiment.py override ``~/.dallingerconfig``, but
        environment variables and runtime writes still take precedence over
        them. This is easy to miss and can lead to confusing behavior (e.g. a
        ``dashboard_user`` set in experiment.py being silently replaced by a
        stale environment variable), so we warn about it loudly at deployment
        time.
        """
        if not cls.config:
            return

        experiment_values = {
            key: value
            for key, value in cls.config_settings().items()
            if key in cls.config
        }

        for key, experiment_value in experiment_values.items():
            resolved_value = config.get(key, None)
            if resolved_value == experiment_value:
                continue
            source = _identify_config_override_source(key)
            if config.is_sensitive(key):
                details = ""
            else:
                details = (
                    f" (experiment.py sets {experiment_value!r}, "
                    f"but the resolved value is {resolved_value!r})"
                )
            logger.warning(
                f"Config variable '{key}' is set in experiment.py but overridden by "
                f"{source}{details}. Values set in experiment.py have lower priority than "
                "environment variables and runtime configuration writes."
            )

    @classmethod
    def check_base_payment(cls, config):
        if config.get("base_payment") > cls.max_allowed_base_payment:
            raise ValueError(
                f"Your experiment's `base_payment` exceeds the maximum allowed value of {cls.max_allowed_base_payment}!\n\n"
                "Check that you have the units right; for example, if your currency is dollars, then base payment "
                "should be specified in dollars, not cents. If you're sure you want this large base payment, "
                "then set `Experiment.max_allowed_base_payment` to a larger value in experiment.py."
            )

    @property
    def num_working_participants(self):
        return Participant.query.filter_by(status="working", failed=False).count()

    def recruit(self):
        if self.need_more_participants:
            logger.info("Conclusion: recruiting another participant.")
            self.recruiter.recruit(n=1)
        else:
            logger.info("Conclusion: no recruitment required.")
            self.recruiter.close_recruitment()

    @property
    def need_more_participants(self):
        if self.amount_spent() >= self.var.soft_max_experiment_payment:
            self.ensure_soft_max_experiment_payment_email_sent()
            return False

        need_more = False
        for i, criterion in enumerate(self.recruitment_criteria):
            logger.info(
                "Evaluating recruitment criterion %i/%i...",
                i + 1,
                len(self.recruitment_criteria),
            )
            res = call_function(criterion.function, experiment=self)
            assert isinstance(res, bool)
            logger.info(
                "Recruitment criterion %i/%i ('%s') %s.",
                i + 1,
                len(self.recruitment_criteria),
                criterion.label,
                (
                    "returned True (more participants needed)."
                    if res
                    else "returned False (no more participants needed)."
                ),
            )
            if res:
                need_more = True
        return need_more

    def ensure_hard_max_experiment_payment_email_sent(self):
        if not self.var.hard_max_experiment_payment_email_sent:
            self.send_email_hard_max_payment_reached()
            self.var.hard_max_experiment_payment_email_sent = True

    def send_email_hard_max_payment_reached(self):
        config = get_config()
        template = """Dear experimenter,

            This is an automated email from PsyNet. You are receiving this email because
            the total amount spent in the experiment has reached the HARD maximum of ${hard_max_experiment_payment}.
            Working participants' bonuses will not be paid out. Instead, the amount of unpaid
            bonus is saved in the participant's `unpaid_bonus` variable.

            The application id is: {app_id}

            To see the logs, use the command "dallinger logs --app {app_id}"
            To pause the app, use the command "dallinger hibernate --app {app_id}"
            To destroy the app, use the command "dallinger destroy --app {app_id}"

            The PsyNet developers.
            """
        message = {
            "subject": "HARD maximum experiment payment reached.",
            "body": template.format(
                hard_max_experiment_payment=self.var.hard_max_experiment_payment,
                app_id=config.get("id"),
            ),
        }
        logger.info(
            f"HARD maximum experiment payment "
            f"of ${self.var.hard_max_experiment_payment} reached!"
        )
        try:
            admin_notifier(config).send(**message)
        except SMTPAuthenticationError as e:
            logger.error(
                f"SMTPAuthenticationError sending 'hard_max_experiment_payment' reached email: {e}"
            )
        except Exception as e:
            logger.error(
                f"Unknown error sending 'hard_max_experiment_payment' reached email: {e}"
            )

    def ensure_soft_max_experiment_payment_email_sent(self):
        if not self.var.soft_max_experiment_payment_email_sent:
            self.send_email_soft_max_payment_reached()
            self.var.soft_max_experiment_payment_email_sent = True

    def send_email_soft_max_payment_reached(self):
        config = get_config()
        template = """Dear experimenter,

            This is an automated email from PsyNet. You are receiving this email because
            the total amount spent in the experiment has reached the soft maximum of ${soft_max_experiment_payment}.
            Recruitment ended.

            The application id is: {app_id}

            To see the logs, use the command "dallinger logs --app {app_id}"
            To pause the app, use the command "dallinger hibernate --app {app_id}"
            To destroy the app, use the command "dallinger destroy --app {app_id}"

            The PsyNet developers.
            """
        message = {
            "subject": "Soft maximum experiment payment reached.",
            "body": template.format(
                soft_max_experiment_payment=self.var.soft_max_experiment_payment,
                app_id=config.get("id"),
            ),
        }
        logger.info(
            f"Recruitment ended. Maximum experiment payment "
            f"of ${self.var.soft_max_experiment_payment} reached!"
        )
        try:
            admin_notifier(config).send(**message)
        except SMTPAuthenticationError as e:
            logger.error(
                f"SMTPAuthenticationError sending 'soft_max_experiment_payment' reached email: {e}"
            )
        except Exception as e:
            logger.error(
                f"Unknown error sending 'soft_max_experiment_payment' reached email: {e}"
            )

    def is_complete(self):
        return (not self.need_more_participants) and self.num_working_participants == 0

    def assignment_abandoned(self, participant):
        self._handle_premature_exit(participant, "assignment_abandoned")

    def assignment_returned(self, participant):
        self._handle_premature_exit(participant, "assignment_returned")

    def assignment_reassigned(self, participant):
        self._handle_premature_exit(participant, "assignment_reassigned")

    def _handle_premature_exit(self, participant, cause_tag):
        """Fail a still-working participant after a recruiter exit event.

        Recruiter abandonment, return, and reassignment are premature exits.
        See :doc:`/tutorials/participant_and_trial_failure`.
        """
        if participant.complete:
            logger.info(
                "Ignoring recruiter event %s for participant %i; they already completed.",
                cause_tag,
                participant.id,
            )
            return

        if participant.failed:
            participant.append_failure_tags(cause_tag)
            return

        participant.append_failure_tags(cause_tag, "premature_exit")
        participant.fail()

    def fail_participant(self, participant):
        """Fail a participant using PsyNet's participant-failure contract.

        This Dallinger compatibility shim calls
        :meth:`~psynet.participant.Participant.fail` and does not fail owned
        nodes. Do not override it; PsyNet rejects subclasses that do.
        Recruiter premature-exit handling stays on
        :meth:`_handle_premature_exit`.
        """
        participant.fail()

    def data_check_failed(self, participant):
        """Ignore Dallinger's post-submission data check.

        PsyNet quality screening happens during the timeline via
        :meth:`~psynet.trial.main.TrialMaker.performance_check`. Dallinger's
        ``data_check`` runs after the participant has already submitted.
        To fail a participant after they have finished, call
        :meth:`~psynet.participant.Participant.fail`.
        """
        self._warn_unsupported_dallinger_submission_check("data_check", participant)

    def attention_check_failed(self, participant):
        """Ignore Dallinger's post-submission attention check.

        See :meth:`data_check_failed`.
        """
        self._warn_unsupported_dallinger_submission_check(
            "attention_check", participant
        )

    def _warn_unsupported_dallinger_submission_check(self, hook_name, participant):
        logger.warning(
            "PsyNet does not use Dallinger's %s hook for participant %i. "
            "That check runs after the participant has already submitted. "
            "Use TrialMaker.performance_check for in-experiment quality "
            "screening, or Participant.fail() to fail someone after they "
            "have finished. This method does not fail the participant or "
            "their nodes.",
            hook_name,
            participant.id,
        )

    def bonus(self, participant: Participant) -> float:
        """Calculate the reward the participant gets when completing the experiment.

        Parameters
        ----------
        participant : Participant
            The participant to calculate reward for.

        Returns
        -------
        float
            The calculated reward, rounded to 2 decimal places.
        """
        reward = participant.calculate_reward()
        print(f"Initially computed reward: {reward}")
        print(f"Participant status: {participant.status}")
        if participant.status not in ["screened_out", "returned"]:
            print(f"Subtracting base payment: {self.base_payment}")
            reward -= self.base_payment
        print(f"After base payment subtraction: {reward}")
        return round(self.check_bonus(reward, participant), 2)

    def check_bonus(self, reward, participant):
        """
        Ensures that a participant receives no more than a reward of max_participant_payment.
        Additionally, checks if both soft_max_experiment_payment or max_participant_payment have
        been reached or exceeded, respectively. Emails are sent out warning the user if either is true.

        :param reward: float
            The reward calculated in :func:`~psynet.experiment.Experiment.bonus()`.
        :type participant:
            :attr: `~psynet.participant.Participant`
        :returns:
            The possibly reduced reward as a ``float``.
        """

        # check hard_max_experiment_payment
        if (
            self.var.hard_max_experiment_payment_email_sent
            or self.amount_spent() + self.outstanding_base_payments() + reward
            > self.var.hard_max_experiment_payment
        ):
            participant.var.set("unpaid_bonus", reward)
            self.ensure_hard_max_experiment_payment_email_sent()

        # check soft_max_experiment_payment
        if self.amount_spent() + reward >= self.var.soft_max_experiment_payment:
            self.ensure_soft_max_experiment_payment_email_sent()

        # check max_participant_payment
        if participant.amount_paid() + reward > self.var.max_participant_payment:
            reduced_reward = round(
                self.var.max_participant_payment - participant.amount_paid(), 2
            )
            participant.send_email_max_payment_reached(self, reward, reduced_reward)
            return reduced_reward
        return reward

    def outstanding_base_payments(self):
        return self.num_working_participants * self.base_payment

    def with_lucid_recruitment(self):
        return issubclass(self.recruiter.__class__, BaseLucidRecruiter)

    def with_prolific_recruitment(self):
        return issubclass(self.recruiter.__class__, ProlificRecruiter)

    def process_response(
        self,
        participant_id,
        raw_answer,
        blobs,
        metadata,
        page_uuid,
        client_ip_address,
        answer=NoArgumentProvided,
        include_timeline_fragment=True,
    ):
        _p = get_translator(context=True)
        logger.info(
            f"Received a response from participant {participant_id} on page {page_uuid}."
        )
        participant = (
            Participant.query.with_for_update(of=Participant)
            .populate_existing()
            .get(participant_id)
        )

        if answer is not NoArgumentProvided and not isinstance(participant, Bot):
            raise ValueError(
                "Only bots are permitted to submit formatted answers directly "
                "instead of raw answers."
            )

        try:
            event = self.timeline.get_current_elt(self, participant)
            if page_uuid != participant.page_uuid:
                return self.response_rejected(
                    message=_p(
                        "timeline_problem",
                        "Synchronization problem detected. "
                        "Are you running the same experiment in multiple browser tabs? "
                        "Please close all other tabs and refresh the page.",
                    )
                )
            response = event.process_response(
                raw_answer=raw_answer,
                blobs=blobs,
                metadata=metadata,
                experiment=self,
                participant=participant,
                client_ip_address=client_ip_address,
                answer=answer,
            )
            validation = event.validate(
                response=response,
                answer=response.answer,
                raw_answer=raw_answer,
                participant=participant,
                experiment=self,
                page=event,
            )
            if isinstance(validation, str):
                validation = FailedValidation(message=validation)

            response.successful_validation = not isinstance(
                validation, FailedValidation
            )
            if not response.successful_validation:
                return self.response_rejected(message=validation.message)

            participant.inc_time_credit(event.time_estimate)
            participant.inc_progress(event.time_estimate)

            self.timeline.advance_page(self, participant)
            return self.response_approved(participant, include_timeline_fragment)
        except Exception as err:
            if os.getenv("PASSTHROUGH_ERRORS"):
                raise
            if not isinstance(err, self.HandledError):
                self.handle_error(
                    err,
                    participant=participant,
                    trial=participant.current_trial,
                    node=(
                        participant.current_trial.node
                        if participant.current_trial
                        else None
                    ),
                    network=(
                        participant.current_trial.network
                        if participant.current_trial
                        else None
                    ),
                )
            return error_response(participant=participant)

    def response_approved(self, participant, include_timeline_fragment=True):
        logger.debug("The response was approved.")
        page = self.timeline.get_current_elt(self, participant)
        payload = {
            "submission": "approved",
            "page": page.__json__(participant),
        }
        config = get_config()
        # In inplace mode, the same /response round-trip both advances the
        # participant state and returns the next timeline fragment. Skip the
        # fragment when the next page forces a full reload; the client will
        # navigate via /timeline instead.
        if (
            include_timeline_fragment
            and config.get("inplace_timeline_transitions")
            and not page.requires_full_page_reload
        ):
            payload["timeline_fragment"] = self.render_partial_timeline_payload(
                page, self, participant
            )
        return success_response(**payload)

    def response_rejected(self, message):
        logger.warning(
            "The response was rejected with the following message: '%s'.", message
        )
        return success_response(submission="rejected", message=message)

    def render_exit_message(self, participant):
        """
        This method is currently only called if the 'generic' recruiter is selected.
        We may propagate it to other recruiter methods eventually too.
        If left unchanged, the default recruiter exit message from Dallinger will be shown.
        Otherwise, one can return a custom message in various ways.
        If you return a string, this will be escaped appropriately and presented as text.
        Alternatively, more complex HTML structures can be constructed using the
        Python package ``dominate``, see Examples for details.

        Examples
        --------

        This would be appropriate for experiments with no payment:

        ::

            tags.div(
                tags.p("Thank you for participating in this experiment!"),
                tags.p("Your responses have been saved. You may close this window."),
            )

        This kind of structure could be used for passing participants to a particular
        URL in Prolific:

        ::

            tags.div(
                tags.p("Thank you for participating in this experiment!"),
                tags.p("Please click the following URL to continue back to Prolific:"),
                tags.a("Finish experiment", href="https://prolific.com"),
            )
        """
        return "default_exit_message"

    @classmethod
    def extra_files(cls):
        files = []
        for trialmaker in cls.timeline.trial_makers.values():
            files.extend(trialmaker.extra_files())
        files.extend(get_static_package_extra_files())

        # Warning: Due to the behavior of Dallinger's extra_files functionality, files are NOT
        # overwritten if they exist already in Dallinger. We should try and change this.
        files.extend(
            [
                (
                    # Warning: this won't affect templates that already exist in Dallinger
                    resources.files("psynet") / "templates",
                    "/templates",
                ),
                (
                    resources.files("psynet") / "resources/favicon.png",
                    "/static/favicon.png",
                ),
                (
                    resources.files("psynet") / "resources/favicon.svg",
                    "/static/favicon.svg",
                ),
                (
                    resources.files("psynet") / "resources/logo.png",
                    "/static/images/logo.png",
                ),
                (
                    resources.files("psynet") / "resources/images/psynet.svg",
                    "/static/images/logo.svg",
                ),
                (
                    resources.files("psynet")
                    / "resources/images/princeton-consent.png",
                    "/static/images/princeton-consent.png",
                ),
                (
                    resources.files("psynet") / "resources/images/unity_logo.png",
                    "/static/images/unity_logo.png",
                ),
                (
                    resources.files("psynet")
                    / "resources/scripts/dashboard_timeline.js",
                    "/static/scripts/dashboard_timeline.js",
                ),
                (
                    resources.files("psynet")
                    / "resources/scripts/d3-visualizations.js",
                    "/static/scripts/d3-visualizations.js",
                ),
                (
                    resources.files("psynet") / "resources/scripts/psynet.js",
                    "/static/scripts/psynet.js",
                ),
                (
                    resources.files("psynet") / "static/scripts/chatroom-widget.js",
                    "/static/scripts/chatroom-widget.js",
                ),
                (
                    resources.files("psynet")
                    / "resources/scripts/execute-front-end-js.js",
                    "/static/scripts/execute-front-end-js.js",
                ),
                (
                    resources.files("psynet") / "resources/scripts/jspsych-page.js",
                    "/static/scripts/jspsych-page.js",
                ),
                (
                    resources.files("psynet")
                    / "static/scripts/music-notation-prompt.js",
                    "/static/scripts/music-notation-prompt.js",
                ),
                (
                    resources.files("psynet")
                    / "resources/libraries/bootstrap/bootstrap.min.css",
                    "/static/css/bootstrap.min.css",
                ),
                (
                    resources.files("psynet")
                    / "resources/libraries/bootstrap/bootstrap.bundle.min.js",
                    "/static/scripts/bootstrap.bundle.min.js",
                ),
                (
                    resources.files("psynet")
                    / "resources/libraries/bootstrap-select/bootstrap-select.min.js",
                    "/static/scripts/bootstrap-select.min.js",
                ),
                (
                    resources.files("psynet")
                    / "resources/libraries/bootstrap-select/bootstrap-select.min.css",
                    "/static/css/bootstrap-select.min.css",
                ),
                (
                    resources.files("psynet") / "resources/css/consent.css",
                    "/static/css/consent.css",
                ),
                (
                    resources.files("psynet") / "resources/css/dashboard_timeline.css",
                    "/static/css/dashboard_timeline.css",
                ),
                (
                    resources.files("psynet")
                    / "resources/libraries/jQuery/jquery-3.7.1.min.js",
                    "/static/scripts/jquery-3.7.1.min.js",
                ),
                (
                    resources.files("psynet")
                    / "resources/libraries/platform-1.3.6/platform.min.js",
                    "/static/scripts/platform.min.js",
                ),
                (
                    resources.files("psynet") / "resources/libraries/PrismJS-1.30.0",
                    "/static/scripts/prism",
                ),
                (
                    resources.files("psynet")
                    / "resources/libraries/fitty-2.2.6/fitty.min.js",
                    "/static/scripts/fitty.min.js",
                ),
                (
                    resources.files("psynet")
                    / "resources/libraries/fitty-2.2.6/fitty.min.js",
                    "/static/scripts/fitty.min.js",
                ),
                (
                    resources.files("psynet")
                    / "resources/libraries/detectIncognito-1.3.0/detectIncognito.min.js",
                    "/static/scripts/detectIncognito.min.js",
                ),
                (
                    resources.files("psynet")
                    / "resources/libraries/raphael-2.3.0/raphael.min.js",
                    "/static/scripts/raphael-2.3.0.min.js",
                ),
                (
                    resources.files("psynet")
                    / "resources/libraries/jQuery-Knob/js/jquery.knob.js",
                    "/static/scripts/jquery.knob.js",
                ),
                (
                    resources.files("psynet") / "resources/libraries/js-synthesizer",
                    "/static/scripts/js-synthesizer",
                ),
                (
                    resources.files("psynet") / "resources/libraries/JSZip",
                    "/static/scripts/JSZip",
                ),
                (
                    resources.files("psynet") / "resources/libraries/Tonejs",
                    "/static/scripts/Tonejs",
                ),
                (
                    resources.files("psynet") / "resources/libraries/survey-jquery",
                    "/static/scripts/survey-jquery",
                ),
                (
                    resources.files("psynet") / "static/libraries/abc-js",
                    "/static/scripts/abc-js",
                ),
                (
                    resources.files("psynet") / "resources/libraries/d3/d3.v4.js",
                    "/static/scripts/d3.v4.js",
                ),
                (
                    resources.files("psynet") / "resources/libraries/d3/d3-tip.min.js",
                    "/static/scripts/d3-tip.min.js",
                ),
                (
                    resources.files("psynet") / "resources/libraries/d3/d3-tip.css",
                    "/static/css/d3-tip.css",
                ),
                (
                    resources.files("psynet")
                    / "resources/libraries/jqueryui/jquery-ui.css",
                    "/static/css/jquery-ui.css",
                ),
                (
                    resources.files("psynet")
                    / "resources/libraries/jqueryui/jquery-ui.min.js",
                    "/static/scripts/jquery-ui.min.js",
                ),
                (
                    resources.files("psynet")
                    / "resources/libraries/international-keyboards",
                    "/static/international-keyboards",
                ),
                (
                    resources.files("psynet") / "resources/css/fonts",
                    "/static/css/fonts",
                ),
                (
                    resources.files("psynet")
                    / "resources/scripts/prepare_docker_image.sh",
                    "prepare_docker_image.sh",
                ),
                (
                    resources.files("psynet") / "resources/DEPLOYMENT_PACKAGE",
                    "DEPLOYMENT_PACKAGE",
                ),
                (
                    "config.txt",
                    ".config.backup",
                ),
                (
                    ".deploy",
                    ".deploy",
                ),
                (
                    "source_code.zip",
                    "source_code.zip",
                ),
            ]
        )
        # We don't think this is needed any more but just keeping a note in case we're proved wrong (25 Sep 2023)
        # if isinstance(cls.assets.storage, DebugStorage):
        #     _path = f"static/{cls.assets.storage.label}"
        #     files.append(
        #         (
        #             _path,
        #             _path,
        #         )
        #     )
        return files

    @classmethod
    def extra_parameters(cls):
        """
        Register PsyNet-specific configuration parameters.
        """
        config = dallinger_get_config()

        def legacy_js_var_globals_validator(value):
            """Validate the legacy JavaScript variable global access mode."""
            if value not in {"warn", "error", "off"}:
                raise ValueError(
                    '`legacy_js_var_globals` must be one of: "warn", "error", or "off".'
                )

        config.register("big_base_payment", bool)
        config.register("lab_recruiter_auth_token", str, sensitive=True)
        config.register("lab_recruiter_external_submission_url", str)
        config.register("check_dallinger_version", bool)
        config.register("check_participant_opened_devtools", bool)
        config.register("currency", str)
        config.register("default_translator", str)
        config.register("enable_google_search_console", bool)
        config.register("google_translate_json_path", str, sensitive=True)
        config.register("google_translate_project_id", str, sensitive=True)
        config.register("initial_recruitment_size", int)
        config.register("openai_api_key", str, sensitive=True)
        config.register("openai_default_model", str)
        config.register("openai_default_temperature", str)
        config.register("label", str)
        config.register("locale", str)
        config.register("lucid_api_key", str, sensitive=True)
        config.register("lucid_recruitment_config", str)
        config.register("lucid_sha1_hashing_key", str, sensitive=True)
        config.register("min_accumulated_reward_for_abort", float)
        config.register("min_browser_version", str)
        config.register("show_abort_button", bool)
        config.register("show_footer", bool)
        config.register("show_progress_bar", bool)
        config.register("show_reward", bool)
        config.register("inplace_timeline_transitions", bool)
        config.register(
            "legacy_js_var_globals",
            str,
            validators=[legacy_js_var_globals_validator],
        )
        config.register("wage_per_hour", float)
        config.register("window_height", int)
        config.register("window_width", int)

        def is_valid_locale(value):
            from .translation import psynet_supported_locales

            locales = json.loads(value)
            if len(locales) == 0 or locales == ["en"]:
                return

            for locale in json.loads(value):
                if locale == "en":
                    continue
                assert locale in psynet_supported_locales, (
                    f"Locale {locale} not available in PsyNet."
                )

        config.register(
            "supported_locales", str, validators=[is_valid_json, is_valid_locale]
        )
        config.register("force_google_chrome", bool)
        config.register("leave_comments_on_every_page", bool)
        config.register("force_incognito_mode", bool)
        config.register("allow_mobile_devices", bool)
        config.register("notifier", str)
        config.register("experimenter_name", str)
        config.register("slack_channel_name", str)
        config.register("slack_bot_token", str, sensitive=True)
        config.register("needs_internet_access", bool)

        def is_positive_float(value):
            assert float(value) > 0

        def is_between_0_and_1(value):
            assert 0 <= float(value) <= 1

        config.register(
            "mute_same_warning_for_n_hours", float, validators=[is_positive_float]
        )
        config.register(
            "resource_warning_pct",
            float,
            validators=[is_positive_float, is_between_0_and_1],
        )
        config.register(
            "resource_danger_pct",
            float,
            validators=[is_positive_float, is_between_0_and_1],
        )
        config.register(
            "minimal_disk_space_warning_gb", float, validators=[is_positive_float]
        )
        config.register(
            "minimal_disk_space_danger_gb", float, validators=[is_positive_float]
        )

        def color_mode_validator(value):
            assert value in ["light", "dark", "auto"]

        config.register("color_mode", str, validators=[color_mode_validator])

        def unsupported_prolific_screen_out_validator(value):
            if value:
                raise ValueError(
                    "`prolific_enable_screen_out` is no longer supported. "
                    "Prolific no longer supports the corresponding screen-out "
                    "API route. Please remove this parameter from your "
                    "configuration and use `prolific_enable_return_for_bonus` "
                    "instead."
                )

        config.register("prolific_enable_return_for_bonus", bool)
        config.register(
            "prolific_enable_screen_out",
            bool,
            validators=[unsupported_prolific_screen_out_validator],
        )

    @dashboard_tab("Export")
    @classmethod
    def dashboard_export(cls):
        return render_template(
            "dashboard_export.html",
            title="Database export",
            automatic_backups=cls.automatic_backups,
        )

    @dashboard_tab("Basic data")
    @classmethod
    def dashboard_data(cls):
        data = cls.get_basic_data(context="monitor", **request.args)
        data = json.dumps(data, indent=4)

        return render_template(
            "dashboard_data.html",
            title="Basic data",
            data=data,
            url=cls.basic_data_url,
        )

    @staticmethod
    def _parse_status(params):
        exp = get_experiment()
        deployment_id = params.get("deployment_id", None)
        if deployment_id is None:
            return error_response("No deployment_id specified.")
        status_type = params.get("type", None)

        try:
            archived = params.get("archived", "false") == "true"
            if status_type == "recruitment":
                return exp.artifact_storage.read_recruitment_status(
                    archived, deployment_id
                )
            elif status_type == "experiment":
                return exp.artifact_storage.read_experiment_status(
                    archived, deployment_id
                )
            else:
                return error_response(
                    "Invalid status type specified. Use 'recruitment' or 'experiment'."
                )
        except json.JSONDecodeError:
            logger.exception(f"Failed to decode JSON file: {deployment_id}")
            return error_response("Failed to decode JSON file.")

    @dashboard.route("/status/get")
    # Avoid overriding Experiment.get_status
    def get_experiment_status():  # noqa F811
        exp = get_experiment()
        return exp._parse_status(request.args)

    @dashboard.route("/archive/deployment")
    def archive_deployment():  # noqa F811
        try:
            exp = get_experiment()
            if "id" not in request.args:
                return error_response("No id specified.")
            exp.artifact_storage.archive(deployment_id=request.args["id"])

            return success_response()
        except Exception as e:
            return error_response(f"Failed to archive deployment: {str(e)}")

    @dashboard.route("/restore/deployment")
    def restore_deployment():  # noqa F811
        try:
            exp = get_experiment()
            if "id" not in request.args:
                return error_response("No id specified.")
            exp.artifact_storage.restore(deployment_id=request.args["id"])

            return success_response()
        except Exception as e:
            return error_response(f"Failed to restore deployment: {str(e)}")

    @dashboard.route("/update/recruitment")
    def update_recruitment():  # noqa F811
        try:
            exp = get_experiment()
            params = dict(request.args)
            deployment_id = params["deployment_id"]
            params["type"] = "recruitment"
            status = exp._parse_status(params)
            recruiter_name = status.get("recruiter_name", None)
            if recruiter_name is None:
                recruiter_name = status.get("recruiter", None)
            if recruiter_name is None:
                return error_response("No recruiter name specified.")
            status = {k.replace("recruitment_", ""): v for k, v in status.items()}

            recruiter_class = get_descendent_class_by_name(Recruiter, recruiter_name)

            if issubclass(recruiter_class, MockRecruiter):
                mock_recruiter_class = recruiter_class
            else:
                # Look for subclasses which also inherit from MockRecruiter
                mock_recruiter_subclasses = [
                    cls
                    for cls in MockRecruiter.__subclasses__()
                    if recruiter_class.nickname in cls.nickname.lower()
                ]

                if len(mock_recruiter_subclasses) != 1:
                    return error_response("Recruiter could not be instantiated.")
                mock_recruiter_class = mock_recruiter_subclasses[0]

            mock_recruiter = mock_recruiter_class(**status)

            mock_recruiter.register_study(**status)

            recruiter_status = mock_recruiter.get_status()
            recruiter_status = exp.format_recruiter_status(recruiter_status)

            exp.artifact_storage.write_recruitment_status(
                recruiter_status, deployment_id
            )

            return success_response()
        except Exception as e:
            return error_response(
                f"Failed to fetch information from recruiter: {str(e)}"
            )

    @dashboard.route("/comment/set/<deployment_id>", methods=["POST"])
    @with_transaction
    def set_comment(deployment_id):  # noqa F811
        params = request.form
        if "txt" not in params:
            return error_response("No comment specified.")

        txt = params["txt"]
        get_experiment().artifact_storage.write_comment(
            text=txt, deployment_id=deployment_id
        )

        return success_response()

    @dashboard.route("/comment/get/<deployment_id>", methods=["GET"])
    def get_comment(deployment_id):  # noqa F811
        return get_experiment().artifact_storage.read_comment(deployment_id)

    @dashboard_tab("Deployments")
    @classmethod
    def dashboard_deployments(cls):
        title = "Deployment monitor"
        if cls.artifact_storage is None:
            return render_template(
                "dashboard_custom.html",
                title=title,
                html="You have not specified a artifact storage in your experiment class, so you cannot view the deployment monitor.",
            )
        return render_template(
            "dashboard_deployments.html",
            title=title,
            deployments=cls.artifact_storage.list_subfolders("deployments"),
            archived=cls.artifact_storage.list_subfolders("archive"),
            current_deployment_id=cls.deployment_id,
            secret=str(deployment_info.read("secret")).replace("-", ""),
            exp_config=get_config().as_dict(include_sensitive=False),
        )

    @dashboard_tab("Errors")
    @classmethod
    def dashboard_errors(cls):
        error_summary = {}
        for err in cls.get_all_error_records():
            _error = {
                "token": err.token,
                "creation_time": err.creation_time.strftime("%Y-%m-%d %H:%M:%S"),
                "traceback": err.traceback,
                "log_line_number": err.log_line_number,
                "ids": err.ids,
            }

            kind, msg = err.kind, err.message
            if kind not in error_summary:
                error_summary[kind] = {}
            if msg not in error_summary[kind]:
                error_summary[kind][msg] = []
            error_summary[kind][msg].append(_error)
        return render_template(
            "dashboard_errors.html",
            title="Errors",
            error_summary=error_summary,
        )

    @dashboard_tab("Timeline")
    @classmethod
    def dashboard_timeline(cls):
        exp = get_experiment()
        panes = exp.monitoring_panels()

        module_info = {
            "modules": [{"id": module.id} for module in exp.timeline.module_list]
        }

        return render_template(
            "dashboard_timeline.html",
            title="Timeline modules",
            panes=panes,
            timeline_modules=json.dumps(module_info, default=serialise),
            currency=get_config().currency,
        )

    @dashboard_tab("Resources")
    @classmethod
    def dashboard_resources(cls):
        from .dashboard.resources import report_resource_use

        return report_resource_use()

    @dashboard_tab("Lucid")
    @classmethod
    def dashboard_lucid(cls):
        from .dashboard.lucid import report_lucid

        return report_lucid()

    @dashboard_tab("Sync groups")
    @classmethod
    def dashboard_sync_groups(cls):
        from .dashboard.sync_groups import report_sync_groups

        return report_sync_groups()

    @dashboard.route(
        "/sync-groups/<int:sync_group_id>/participant/<int:participant_id>/fail",
        methods=["POST"],
    )
    @login_required
    @with_transaction
    def manual_fail_sync_group_participant(sync_group_id, participant_id):  # noqa F811
        from .dashboard.sync_groups import manual_fail_sync_group_participant

        return manual_fail_sync_group_participant(
            participant_id,
            sync_group_id,
            fail_reason=request.form.get("fail_reason"),
        )

    @dashboard.route(
        "/sync-groups/<int:sync_group_id>/participant/<int:participant_id>/kick",
        methods=["POST"],
    )
    @login_required
    @with_transaction
    def manual_kick_sync_group_participant(sync_group_id, participant_id):  # noqa F811
        from .dashboard.sync_groups import manual_kick_sync_group_participant

        return manual_kick_sync_group_participant(
            participant_id,
            sync_group_id,
            kick_reason=request.form.get("kick_reason"),
        )

    @dashboard_tab("Participants")
    @classmethod
    def dashboard_participants(cls):
        message = ""
        participant = None

        assignment_id = request.args.get("assignment_id", default=None)
        participant_id = request.args.get("participant_id", default=None)
        worker_id = request.args.get("worker_id", default=None)

        try:
            if assignment_id is not None:
                participant = cls.get_participant_from_assignment_id(
                    assignment_id, for_update=False
                )
            elif participant_id is not None:
                participant = cls.get_participant_from_participant_id(
                    int(participant_id), for_update=False
                )
            elif worker_id is not None:
                participant = cls.get_participant_from_worker_id(
                    worker_id, for_update=False
                )
            else:
                message = "Please select a participant."
        except ValueError:
            message = "Invalid ID."
        except sqlalchemy.orm.exc.NoResultFound:
            message = "Failed to find any matching participants."
        except sqlalchemy.orm.exc.MultipleResultsFound:
            message = "Found multiple participants matching those specifications."

        return render_template(
            "dashboard_participant.html",
            title="Participant",
            participant=participant,
            message=message,
            app_base_url=get_experiment_url(),
        )

    @classmethod
    def get_participant_from_assignment_id(
        cls, assignment_id: str, for_update: bool = False
    ):
        """
        Get a participant with a specified ``assignment_id``.
        Throws a ``sqlalchemy.orm.exc.NoResultFound`` error if there is no such participant,
        or a ``sqlalchemy.orm.exc.MultipleResultsFound`` error if there are multiple such participants.

        Parameters
        ----------
        assignment_id :
            ID of the participant to retrieve.

        for_update :
            Set to ``True`` if you plan to update this Participant object.
            The Participant object will be locked for update in the database
            and only released at the end of the transaction.

        Returns
        -------

        The corresponding participant object.
        """
        query = Participant.query.filter_by(assignment_id=assignment_id)
        if for_update:
            query = query.with_for_update(of=Participant).populate_existing()
        return query.one()

    @classmethod
    def get_participant_from_participant_id(
        cls, participant_id: int, for_update: bool = False
    ):
        """
        Get a participant with a specified ``participant_id``.
        Throws a ``ValueError`` if the ``participant_id`` is not a valid integer,
        a ``sqlalchemy.orm.exc.NoResultFound`` error if there is no such participant,
        or a ``sqlalchemy.orm.exc.MultipleResultsFound`` error if there are multiple such participants.

        Parameters
        ----------
        participant_id :
            ID of the participant to retrieve.

        for_update :
            Set to ``True`` if you plan to update this Participant object.
            The Participant object will be locked for update in the database
            and only released at the end of the transaction.

        Returns
        -------

        The corresponding participant object.
        """
        participant_id = int(participant_id)
        query = Participant.query.filter_by(id=participant_id)
        if for_update:
            query = query.with_for_update(of=Participant).populate_existing()
        return query.one()

    @classmethod
    def get_participant_from_worker_id(cls, worker_id: str, for_update: bool = False):
        """
        Get a participant with a specified ``worker_id``.
        Throws a ``sqlalchemy.orm.exc.NoResultFound`` error if there is no such participant,
        or a ``sqlalchemy.orm.exc.MultipleResultsFound`` error if there are multiple such participants.

        Parameters
        ----------
        worker_id :
            ID of the participant to retrieve.

        for_update :
            Set to ``True`` if you plan to update this Participant object.
            The Participant object will be locked for update in the database
            and only released at the end of the transaction.

        Returns
        -------

        The corresponding participant object.
        """
        query = Participant.query.filter_by(worker_id=worker_id)
        if for_update:
            query = query.with_for_update(of=Participant).populate_existing()
        return query.one()

    @classmethod
    def get_participant_from_unique_id(cls, unique_id: str, for_update: bool = False):
        """
        Get a participant with a specified ``unique_id``.
        Throws a ``sqlalchemy.orm.exc.NoResultFound`` error if there is no such participant,
        or a ``sqlalchemy.orm.exc.MultipleResultsFound`` error if there are multiple such participants.

        Parameters
        ----------
        unique_id :
            Unique ID of the participant to retrieve.

        for_update :
            Set to ``True`` if you plan to update this Participant object.
            The Participant object will be locked for update in the database
            and only released at the end of the transaction.

        Returns
        -------

        The corresponding participant object.
        """
        query = Participant.query.filter_by(unique_id=unique_id)
        if for_update:
            query = query.with_for_update(of=Participant).populate_existing()
        return query.one()

    @experiment_route("/google3580fca13e19b596.html")
    @staticmethod
    def google_search_console():
        """
        This route is disabled by default, but can be enabled by setting
        `enable_google_search_console = true` in config.txt.
        Enabling this route allows the site to be claimed in the Google Search Console
        dashboard of the computational.audition@gmail.com Google account.
        This allows the account to investigate and debug Chrome warnings
        (e.g. 'Deceptive website ahead'). See https://search.google.com/u/4/search-console.
        """
        if get_config().get("enable_google_search_console", default=False):
            return render_template("google3580fca13e19b596.html")
        else:
            return flask.Response(
                (
                    "Google search console verification is disabled, "
                    "you can activate it by setting enable_google_search_console = true in config.txt.",
                ),
                status=404,
            )

    @experiment_route("/ad", methods=["GET"])
    @nocache
    @staticmethod
    @with_transaction
    def advertisement():
        from dallinger.experiment_server.experiment_server import prepare_advertisement

        def get_unique_id_from_url_parameters(entry_information):
            exp = get_experiment()
            entry_data = exp.normalize_entry_information(entry_information)
            worker_id = entry_data.get("worker_id")
            assignment_id = entry_data.get("assignment_id")
            return f"{worker_id}:{assignment_id}"

        try:
            is_redirect, kw = prepare_advertisement()
            if is_redirect:
                return kw["redirect"]
            else:
                return render_template_with_translations("ad.html", **kw)
        except Exception as e:
            if "already_did_exp_hit" in str(e):
                unique_id = get_unique_id_from_url_parameters(request.args.to_dict())

                logger.info(
                    f"Redirecting existing participant {unique_id} to timeline."
                )
                return redirect(f"/timeline?unique_id={unique_id}")
            return Experiment.pre_timeline_error_page(e, request)

    @experiment_route("/consent")
    @staticmethod
    @with_transaction
    def consent():
        entry_information = request.args.to_dict()
        exp = get_experiment()
        entry_data = exp.normalize_entry_information(entry_information)

        hit_id = entry_data.get("hit_id")
        assignment_id = entry_data.get("assignment_id")
        worker_id = entry_data.get("worker_id")
        unique_id = worker_id + ":" + assignment_id
        try:
            return render_template_with_translations(
                "consent.html",
                hit_id=hit_id,
                assignment_id=assignment_id,
                worker_id=worker_id,
                unique_id=unique_id,
                mode=get_config().get("mode"),
                query_string=request.query_string.decode(),
            )
        except Exception as e:
            return Experiment.pre_timeline_error_page(e, request)

    @experiment_route("/start", methods=["GET"])
    @staticmethod
    @with_transaction
    def route_start():
        try:
            return render_template_with_translations("start.html")
        except Exception as e:
            return Experiment.pre_timeline_error_page(e, request)

    @staticmethod
    def pre_timeline_error_page(e, request):
        error_text = f"Error when calling {request.path} route: {e}"
        logger.error(error_text)
        exp = get_experiment()
        recruiter = exp.recruiter
        external_submit_url = None
        if isinstance(recruiter, (DevLucidRecruiter, LucidRecruiter)):
            rid = request.args.to_dict()["RID"]
            recruiter.set_termination_details(rid, error_text)
            external_submit_url = recruiter.external_submit_url(assignment_id=rid)
        return Experiment.error_page(
            recruiter=recruiter, external_submit_url=external_submit_url
        )

    @experiment_route("/download_source", methods=["GET"])
    @classmethod
    def download_source(cls):
        config = get_config()

        if not authenticate(request.authorization, config):
            return jsonify({"message": "Invalid credentials"}), 401

        filename = "source_code.zip"
        logger.info(f"Downloading experiment source code from {os.getcwd()}/{filename}")
        return send_file(filename, mimetype="zip")

    @classmethod
    def _export(
        cls,
        export_dir,
        config=None,
        n_parallel=None,
        psynet_export: bool = True,
        anonymize: str = "no",
        **kwargs,
    ):
        if config is None:
            config = get_config()
        if psynet_export:
            from .command_line import export__local

            ctx = Context(export__local)
            ctx.invoke(
                export__local,
                path=export_dir,
                n_parallel=n_parallel,
                username=config.get("dashboard_user"),
                password=config.get("dashboard_password"),
                assets=kwargs.get("assets"),
                anonymize=anonymize,
                legacy=True,
            )
        else:
            if anonymize == "both":
                scrub_pii = [True, False]
            elif anonymize == "yes":
                scrub_pii = [True]
            elif anonymize == "no":
                scrub_pii = [False]
            else:
                raise ValueError("anonymize must be 'yes' or 'no' or 'both'")
            for scrub in scrub_pii:
                folder_name = "anonymized" if scrub else "regular"
                sub_dir = os.path.join(export_dir, folder_name)
                os.makedirs(sub_dir, exist_ok=True)
                with working_directory(sub_dir):
                    dallinger.data.export("app", local=True, scrub_pii=scrub)
        zip_filename = "psynet" if psynet_export else "database"
        zip_name = shutil.make_archive(zip_filename, "zip", export_dir)
        exp = get_experiment()
        storage = exp.artifact_storage
        try:
            storage.upload_export(zip_name, exp.deployment_id)
            if psynet_export:
                url = exp.get_artifact_url(exp.deployment_id, "psynet.zip")
                cls.notifier.notify(
                    f"A fresh data export has been created, it can be accessed {cls.notifier.url('here', url)}."
                )
        except Exception as e:
            logger.error(f"Failed to save backup: {e}")
        return zip_name

    @staticmethod
    def _download_export(
        anonymize: str,
        export_type: str,  # can be "database" or "psynet"
        **kwargs,
    ):
        assert export_type in ("psynet", "database")
        exp = get_experiment()

        with tempfile.TemporaryDirectory() as tempdir:
            config = get_config()
            psynet_export = export_type == "psynet"
            zip_filepath = exp._export(
                tempdir,
                config=config,
                anonymize=anonymize,
                psynet_export=psynet_export,
                **kwargs,
            )
            return send_file(zip_filepath, mimetype="zip")

    @dashboard.route("/artifact/<deployment_id>/<filename>", methods=["GET"])
    @staticmethod
    @with_transaction
    def download_artifact(deployment_id, filename):
        from flask_login import current_user

        if not current_user.is_authenticated and request.remote_addr != "127.0.0.1":
            return error_response(error_text="Invalid credentials", simple=True)
        exp = get_experiment()
        with tempfile.TemporaryDirectory() as tempdir:
            storage = exp.artifact_storage
            path = storage.prepare_path(deployment_id, filename)
            destination = os.path.join(tempdir, os.path.basename(path))
            storage.download(path, destination)
            if not os.path.exists(destination):
                return error_response(
                    error_text=f"Artifact {deployment_id}/{filename} not found."
                )
            return send_file(destination, mimetype="application/octet-stream")

    @dashboard.route("/export/download", methods=["GET"])
    @staticmethod
    @with_transaction
    def download_export():
        from flask_login import current_user

        if not current_user.is_authenticated and request.remote_addr != "127.0.0.1":
            return error_response(error_text="Invalid credentials", simple=True)

        kwargs = dict(request.args)
        anonymize = kwargs.pop("anonymize", "no")
        export_type = kwargs.pop("type", "database")

        exp = get_experiment()
        return exp._download_export(anonymize, export_type, **kwargs)

    @dashboard.route("/export/trigger", methods=["GET"])
    @staticmethod
    @with_transaction
    def trigger_export():
        kwargs = dict(request.args)
        anonymize = kwargs.pop("anonymize", "no")
        export_type = kwargs.pop("type", "database")
        assets = kwargs.get("assets", "none")

        # We just call _download_export for the side effect of uploading the export to the storage service.
        exp = get_experiment()
        exp._download_export(
            anonymize=anonymize,
            export_type=export_type,
            assets=assets,
        )

        return success_response(
            anonymize=anonymize,
            export_type=export_type,
            assets=assets,
        )

    @experiment_route("/get_participant_info_for_debug_mode", methods=["GET"])
    @staticmethod
    @with_transaction
    def get_participant_info_for_debug_mode():
        if not get_config().get("mode") == "debug":
            return error_response()

        participant = Participant.query.first()
        json_data = {
            "id": participant.id,
            "unique_id": participant.unique_id,
            "assignment_id": participant.assignment_id,
            "page_uuid": participant.page_uuid,
        }
        logger.debug(
            f"Returning from /get_participant_info_for_debug_mode: {json_data}"
        )
        return json.dumps(json_data, default=serialise)

    @experiment_route("/on-demand-asset", methods=["GET"])
    @staticmethod
    def get_on_demand_asset():
        id = request.args.get("id")
        secret = request.args.get("secret")

        assert id
        assert secret

        id = int(id)

        asset = OnDemandAsset.query.filter_by(id=id).one()
        suffix = asset.extension if asset.extension else ""

        with tempfile.NamedTemporaryFile(suffix=suffix) as temp_file:
            asset.export(temp_file.name)

            return send_file(temp_file.name, max_age=0)

    @experiment_route("/error-page", methods=["POST", "GET"])
    @classmethod
    @with_transaction
    def render_error(cls):
        request_data = request.form.get("request_data")
        participant_id = request.form.get("participant_id")

        compensate = True
        participant = None
        recruiter = None
        external_submit_url = None

        if participant_id:
            participant = Participant.query.filter_by(id=participant_id).one()
            recruiter = get_experiment().recruiter
            external_submit_url = None
            if hasattr(recruiter, "external_submit_url"):
                external_submit_url = recruiter.external_submit_url(
                    participant=participant
                )

            if isinstance(recruiter, (DevLucidRecruiter, LucidRecruiter)):
                compensate = False
                recruiter.set_termination_details(
                    participant.assignment_id, "error-page_route"
                )

        return cls.error_page(
            participant=participant,
            request_data=request_data,
            recruiter=recruiter,
            external_submit_url=external_submit_url,
            compensate=compensate,
        )

    @experiment_route("/module", methods=["POST"])
    @classmethod
    @with_transaction
    def get_module_details_as_rendered_html(cls):
        exp = get_experiment()
        module = exp.timeline.get_module(request.values["moduleId"])
        return module.visualize()

    @experiment_route("/module/tooltip", methods=["POST"])
    @classmethod
    @with_transaction
    def get_module_tooltip_as_rendered_html(cls):
        exp = get_experiment()
        module = exp.timeline.get_module(request.values["moduleId"])
        return module.visualize_tooltip()

    @experiment_route("/module/progress_info", methods=["GET"])
    @classmethod
    @with_transaction
    def get_progress_info(cls):
        exp = get_experiment()
        module_ids = request.args.getlist("module_ids[]")
        return exp._get_progress_info(module_ids)

    def _get_progress_info(self, module_ids: list):
        progress_info = {
            "spending": {
                "amount_spent": self.amount_spent(),
                "currency": get_config().currency,
                "soft_max_experiment_payment": self.var.soft_max_experiment_payment,
                "hard_max_experiment_payment": self.var.hard_max_experiment_payment,
            }
        }

        participant_counts_by_module = self.get_participant_counts_by_module()

        for module_id in module_ids:
            module = self.timeline.modules[module_id]
            participant_counts = participant_counts_by_module[module_id]
            progress_info.update(
                module.get_progress_info(
                    participant_counts,
                )
            )

        return progress_info

    def get_participant_counts_by_module(self):
        counts = {module_id: {} for module_id in self.timeline.modules.keys()}

        for attr in ["started", "finished", "aborted"]:
            col = getattr(ModuleState, attr)
            rows = (
                db.session.query(
                    ModuleState.module_id, func.count(ModuleState.id).label("count")
                )
                .filter(col)
                .group_by(ModuleState.module_id)
            ).all()
            rows = dict(rows)

            for module_id in counts.keys():
                counts[module_id][attr] = rows.get(module_id, 0)

        return counts

    @experiment_route("/module/update_spending_limits", methods=["POST"])
    @classmethod
    @with_transaction
    def update_spending_limits(cls):
        hard_max_experiment_payment = request.values["hard_max_experiment_payment"]
        soft_max_experiment_payment = request.values["soft_max_experiment_payment"]
        exp = get_experiment()
        exp.var.set("hard_max_experiment_payment", float(hard_max_experiment_payment))
        exp.var.set("soft_max_experiment_payment", float(soft_max_experiment_payment))
        logger.info(
            f"Experiment variable 'hard_max_experiment_payment set' set to {hard_max_experiment_payment}."
        )
        logger.info(
            f"Experiment variable 'soft_max_experiment_payment set' set to {soft_max_experiment_payment}."
        )
        return success_response()

    @experiment_route("/debugger/<password>", methods=["GET"])
    @classmethod
    @with_transaction
    def route_debugger(cls, password):
        exp = get_experiment()
        if password == "my-secure-password-195762":
            exp.new(db.session)
            rpdb.set_trace()
            return success_response()
        return error_response()

    @experiment_route("/node/<int:node_id>/fail", methods=["GET", "POST"])
    @staticmethod
    @with_transaction
    def fail_node(node_id):
        from dallinger.models import Node

        node = Node.query.with_for_update(of=Node).populate_existing().get(node_id)
        node.fail(reason="http_fail_route_called")
        return success_response()

    @experiment_route("/info/<int:info_id>/fail", methods=["GET", "POST"])
    @staticmethod
    @with_transaction
    def fail_info(info_id):
        from dallinger.models import Info

        info = Info.query.with_for_update(of=Info).populate_existing().get(info_id)
        info.fail(reason="http_fail_route_called")
        return success_response()

    @experiment_route("/network/<int:network_id>/grow", methods=["GET", "POST"])
    @classmethod
    @with_transaction
    def grow_network(cls, network_id):
        exp = get_experiment()
        from .trial.main import TrialNetwork

        network = (
            TrialNetwork.query.with_for_update(of=[TrialNetwork])
            .populate_existing()
            .get(network_id)
        )
        trial_maker = exp.timeline.get_trial_maker(network.trial_maker_id)
        trial_maker.call_grow_network(network)
        return success_response()

    @experiment_route(
        "/network/<int:network_id>/call_async_post_grow_network",
        methods=["GET", "POST"],
    )
    @staticmethod
    @with_transaction
    def call_async_post_grow_network(network_id):
        from .trial.main import NetworkTrialMaker, TrialNetwork

        network = (
            TrialNetwork.query.with_for_update(of=TrialNetwork)
            .populate_existing()
            .get(network_id)
        )
        trial_maker = get_trial_maker(network.trial_maker_id)
        assert isinstance(trial_maker, NetworkTrialMaker)
        trial_maker.queue_async_post_grow_network(network)
        return success_response()

    # Lucid recruitment specific route
    @experiment_route("/terminate_participant", methods=["GET"])
    @classmethod
    @with_transaction
    def terminate_participant(cls):
        recruiter = get_experiment().recruiter
        participant = recruiter.get_participant(request)

        # Don't terminate participants who have already completed the experiment.
        # This can happen due to race conditions when the page redirects to Lucid
        # after completion, triggering the beforeunload event.
        if participant is not None and participant.progress == 1:
            logger.info(
                f"Skipping termination for participant {participant.id} who has already completed (progress=1)."
            )
            external_submit_url = recruiter.external_submit_url(participant=participant)
            return render_template_with_translations(
                "exit_recruiter_lucid.html",
                external_submit_url=external_submit_url,
            )

        # If participant lookup failed, we still need to terminate on Lucid's side
        # using the assignment_id from the request
        if participant is None:
            assignment_id = request.values.get("assignmentId") or request.values.get(
                "RID"
            )
            unique_id = request.values.get("unique_id")
            if assignment_id is None and unique_id is not None:
                assignment_id = unique_id.split(":")[1]

            external_submit_url = recruiter.terminate_participant(
                assignment_id=assignment_id, reason=request.values.get("reason")
            )
        else:
            external_submit_url = recruiter.terminate_participant(
                participant=participant, reason=request.values.get("reason")
            )

        return render_template_with_translations(
            "exit_recruiter_lucid.html",
            external_submit_url=external_submit_url,
        )

    @experiment_route("/change_lucid_status", methods=["GET"])
    @classmethod
    def change_lucid_status(cls):
        get_experiment().recruiter.change_lucid_status(request.values.get("status", ""))
        return success_response()

    @staticmethod
    def get_client_ip_address():
        if request.environ.get("HTTP_X_FORWARDED_FOR") is None:
            return request.environ["REMOTE_ADDR"]
        else:
            return request.environ["HTTP_X_FORWARDED_FOR"]

    @experiment_route("/set_participant_as_aborted/<assignment_id>", methods=["GET"])
    @classmethod
    @with_transaction
    def route_set_participant_as_aborted(cls, assignment_id):  # TODO - update
        participant = cls.get_participant_from_assignment_id(
            assignment_id, for_update=True
        )
        participant.aborted = True
        if participant.module_state:
            participant.module_state.abort()
        logger.info(f"Aborted participant with ID '{participant.id}'.")
        return success_response()

    @experiment_route("/abort/<assignment_id>", methods=["GET"])
    @classmethod
    @with_transaction
    def route_abort(cls, assignment_id):
        try:
            template_name = "abort_not_possible.html"
            participant = None
            participant_abort_info = None
            if assignment_id is not None:
                participant = cls.get_participant_from_assignment_id(
                    assignment_id, for_update=False
                )
                if participant.calculate_reward() >= get_config().get(
                    "min_accumulated_reward_for_abort"
                ):
                    template_name = "abort_possible.html"
                    participant_abort_info = participant.abort_info()
        except ValueError:
            logger.error("Invalid assignment ID.")
        except sqlalchemy.orm.exc.NoResultFound:
            logger.error("Failed to find any matching participants.")
        except sqlalchemy.orm.exc.MultipleResultsFound:
            logger.error("Found multiple participants matching those specifications.")

        return render_template_with_translations(
            template_name,
            participant=participant,
            participant_abort_info=participant_abort_info,
        )

    @experiment_route("/timeline", methods=["GET"])
    @classmethod
    @with_transaction
    def route_timeline(cls):
        unique_id = request.args.get("unique_id")
        mode = request.args.get("mode")
        participant = cls.get_participant_from_unique_id(unique_id, for_update=False)
        experiment = get_experiment()

        return cls._route_timeline(experiment, participant, mode)

    @experiment_route("/participant_status/<participant_id>", methods=["GET"])
    @classmethod
    @login_required
    @with_transaction
    def route_participant_status(cls, participant_id):
        """
        This route provides a .zip file containing useful information about the
        participant's current status. This information is used by automated tests
        to verify what is being displayed on the current page and what response
        should be submitted by the bot.

        The zip file contains:
        - status.json: a JSON file summarising the participant's status
        - bot_response_files/: a directory containing the files that the participant would upload as a response to the page
        """
        participant = Bot.query.get(participant_id)
        experiment = get_experiment()

        status = {
            "status": participant.status,
            "page_uuid": participant.page_uuid,
        }

        if participant.status == "working":
            current_page = participant.get_current_page()
            bot_response = current_page.call__get_bot_response(experiment, participant)

            if not isinstance(bot_response, BotResponse):
                bot_response = BotResponse(answer=bot_response)

            status["page"] = {
                "id": current_page.id,
                "label": current_page.label,
                "text": current_page.plain_text,
                "time_estimate": current_page.time_estimate,
                "bot_response": bot_response.__json__(),
            }
        else:
            bot_response = None

        with tempfile.TemporaryDirectory() as tempdir:
            # status.json (a JSON file summarising the participant's status)
            status_path = os.path.join(tempdir, "status.json")
            with open(status_path, "w") as f:
                json.dump(status, f)

            # bot_response_files/... (the files that the participant would upload as a response to the page)
            files_dir = os.path.join(tempdir, "bot_response_files")
            os.makedirs(files_dir, exist_ok=True)
            if bot_response:
                for key, blob in bot_response.blobs.items():
                    src_path = blob.file
                    dst_path = os.path.join(files_dir, key)
                    shutil.copyfile(src_path, dst_path)

            # status.zip (a zip file containing the status.json and the bot_response_files)
            zip_path = os.path.join(tempdir, "status.zip")
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.write(status_path, "status.json")

                if bot_response:
                    for filename in bot_response.blobs:
                        zf.write(
                            os.path.join(files_dir, filename),
                            os.path.join("bot_response_files", filename),
                        )

            return send_file(zip_path, mimetype="application/zip")

    @classmethod
    def fail_participant_on_error(cls, participant, error):
        error_type = str(type(error))
        # convert error type like <class 'Exception'> to 'Exception'
        error_type = error_type.split("'")[1]
        participant.failure_tags.append(error_type)
        participant.fail(error_type)

    @classmethod
    def _route_timeline(cls, experiment, participant, mode):
        try:
            if not isinstance(participant, Bot):
                participant.client_ip_address = cls.get_client_ip_address()
            page = cls.get_current_page(experiment, participant)
            if mode == "json":
                return jsonify(page.__json__(participant))
            if mode is not None:
                raise ValueError(
                    f"Unsupported /timeline mode '{mode}'. "
                    "Only mode=json remains supported on this route."
                )
            # Full timeline renders still happen here for initial page loads and
            # for the legacy reload-based mode. Inplace fragment rendering is an
            # internal helper reached from /response instead.
            return page.render(experiment, participant)
        except cls.HandledError as err:
            return err.error_page()
        except Exception as err:
            if os.getenv("PASSTHROUGH_ERRORS"):
                raise
            handled_error = cls.handle_error(
                err,
                participant=participant,
                trial=participant.current_trial,
                node=(
                    participant.current_trial.node
                    if participant.current_trial
                    else None
                ),
                network=(
                    participant.current_trial.network
                    if participant.current_trial
                    else None
                ),
            )
            cls.fail_participant_on_error(participant, err)
            return handled_error.error_page()

    @classmethod
    def isolate_batch_item_failure(cls, error, *, refetch, fail, **error_parents):
        """
        Report a per-item batch failure, mark the item failed, and commit.

        Used by pollers that process many candidates in one transaction
        (network growth, finalize backstop). ``handle_error`` rolls back the
        session, so ``refetch`` must return a fresh ORM instance (or ``None``).
        ``fail`` receives that instance and marks it failed. The fail is
        committed immediately so a later ``handle_error`` in the same batch
        cannot undo it (same mid-batch commit pattern as ErrorRecord logging).
        """
        if not isinstance(error, cls.HandledError):
            cls.handle_error(error, **error_parents)
        entity = refetch()
        if entity is None:
            return None
        fail(entity)
        db.session.commit()
        return entity

    @classmethod
    def handle_error(cls, error, **kwargs):
        parents = cls._compile_error_parents(**kwargs)
        db.session.rollback()
        cls.report_error(error, **parents)
        return cls.HandledError(**parents)

    @staticmethod
    def _compile_error_parents(**kwargs):
        # We merge to prevent sqlalchemy.orm.exc.DetachedInstanceError
        parents = {
            key: db.session.merge(value)
            for key, value in kwargs.items()
            if value is not None
        }
        types = [
            "process",
            "asset",
            "response",
            "trial",
            "node",
            "network",
            "participant",
        ]
        for i, parent_type in enumerate(types):
            if parent_type in parents:
                parent = parents[parent_type]
                for grandparent_type in types[(i + 1) :]:
                    if (
                        grandparent_type not in parents
                        and hasattr(parent, grandparent_type)
                        and getattr(parent, grandparent_type) is not None
                    ):
                        parents[grandparent_type] = getattr(parent, grandparent_type)
        return {f"{key}_id": value.id for key, value in parents.items()}

    class HandledError(Exception):
        def __init__(self, message=None, participant=None, **kwargs):
            super().__init__(message)
            self.participant = participant

        def error_page(self):
            return Experiment.error_page(self.participant)

    @classmethod
    def report_error(
        cls,
        error,
        **kwargs,
    ):
        token = cls.generate_error_token()

        try:
            log_line_number = find_log_line_number(token)
        except FileNotFoundError:
            log_line_number = None

        cls.log_to_stdout(error, token, **kwargs)
        cls.log_to_db(error, token, log_line_number, **kwargs)
        cls.log_to_notifier(token, log_line_number, **kwargs)

    @classmethod
    def generate_error_token(cls):
        return str(uuid.uuid4())[:8]

    @classmethod
    def log_to_stdout(cls, error, token, **kwargs):
        _ = error
        context = {**kwargs}
        print("\n")
        logger.error(
            "EXPERIMENT ERROR - err-%s:%s",
            token,
            context,
            exc_info=True,
        )
        print("\n")

    @classmethod
    def log_to_db(cls, error, token, log_line_number, **kwargs):
        # We considered running this function within its own database session,
        # but this proved incompatible with passing pre-existing SQLAlchemy objects
        # to the ErrorRecord constructor.
        trace = traceback.format_exc()
        record = ErrorRecord(
            error=error,
            traceback=trace,
            token=token,
            log_line_number=log_line_number,
            **kwargs,
        )
        db.session.add(record)
        # We don't normally write session.commit() within inner code,
        # but we do here, because we really want to make sure error reporting works.
        db.session.commit()

    @classmethod
    def log_to_notifier(cls, token, line_number, **kwargs):
        url = cls.dashboard_url + "/logger"

        if line_number is not None:
            start = max(0, line_number - 10)
            end = line_number + 10

            url += f"?highlight={line_number}&start={start}&end={end}"

        error_txt = f"error (`{token}`)"
        text = f"An {cls.notifier.url(error_txt, url)} occurred:"
        text += "\n```" + traceback.format_exc() + "```"
        cls.notifier.notify(text)

    # @classmethod
    # def serialize_error_context(
    #     cls,
    #     participant=None,
    #     response=None,
    #     trial=None,
    #     node=None,
    #     network=None,
    #     process=None,
    #     asset=None,
    # ):
    #     context = {}
    #     if participant:
    #         context["participant_id"] = participant.id
    #         context["worker_id"] = participant.worker_id
    #     if response:
    #         context["response_id"] = response.id
    #     if trial:
    #         context["trial_id"] = trial.id
    #     if node:
    #         context["node_id"] = node.id
    #     if network:
    #         context["network_id"] = network.id
    #     if process:
    #         context["process_id"] = process.id
    #     if asset:
    #         context["asset_id"] = asset.id
    #     return context

    class UniqueIdError(PermissionError):
        def __init__(self, expected, provided, participant):
            self.participant = participant

            message = "".join(
                [
                    f"Mismatch between expected unique_id ({expected}) "
                    f"and provided unique_id ({provided}) "
                    f"for participant {participant.id}."
                ]
            )
            super().__init__(message)

        def http_response(self):
            last_exception = sys.exc_info()
            if last_exception[0]:
                logger.error(
                    "Failure for request: {!r}".format(dict(request.args)),
                    exc_info=last_exception,
                )

            msg = (
                "There was a problem authenticating your session, "
                + "did you switch browsers? Unfortunately this is not currently "
                + "supported by our system."
            )
            return Experiment.error_page(
                participant=self.participant,
                error_text=msg,
                error_type="authentication",
            )

    @classmethod
    @log_time_taken
    def get_current_page(cls, experiment, participant):
        if participant.elt_id[1:] == [-1]:
            experiment.timeline.advance_page(experiment, participant)

        page = experiment.timeline.get_current_elt(experiment, participant)
        page.pre_render()

        return page

    @staticmethod
    def render_partial_timeline_payload(page, experiment, participant):
        """
        Render the current timeline page as the internal inplace fragment payload.

        This helper is the shared render authority for inplace fragment output
        returned directly from /response.
        """
        # Mirror the full-page /timeline path (see get_current_page), which
        # calls pre_render() before rendering. Without this, pages advanced via
        # an inplace transition would skip pre_render() hooks (e.g. prompt/control
        # setup such as S3 presigned URL preparation).
        page.pre_render()
        return {
            "html": page.render(experiment, participant, partial_mode=True),
            "page_uuid": participant.page_uuid,
        }

    @classmethod
    def check_unique_id(cls, participant, unique_id):
        valid = participant.unique_id == unique_id
        if not valid:
            raise cls.UniqueIdError(
                expected=unique_id,
                provided=participant.unique_id,
                participant=participant,
            )
        else:
            return True

    @experiment_route("/timeline/progress_and_reward", methods=["GET"])
    @classmethod
    @with_transaction
    def get_progress_and_reward(cls):
        participant_id = request.args.get("participantId")
        participant = Participant.query.get(participant_id)
        progress_percentage = round(participant.progress * 100)
        data = {
            "progressPercentage": progress_percentage,
            "progressPercentageStr": f"{progress_percentage}%",
        }
        if get_config().get("show_reward"):
            time_reward = participant.time_reward
            performance_reward = participant.performance_reward
            total_reward = participant.calculate_reward()
            data["reward"] = {
                "time": time_reward,
                "performance": performance_reward,
                "total": total_reward,
            }
        return data

    @experiment_route("/response", methods=["POST"])
    @classmethod
    @with_transaction
    def route_response(cls):
        exp = get_experiment()
        json_data = json.loads(request.values["json"])
        blobs = request.files.to_dict()

        participant_id = get_arg_from_dict(json_data, "participant_id")
        page_uuid = get_arg_from_dict(json_data, "page_uuid")
        raw_answer = get_arg_from_dict(
            json_data, "raw_answer", use_default=True, default=NoArgumentProvided
        )
        answer = get_arg_from_dict(
            json_data, "answer", use_default=True, default=NoArgumentProvided
        )
        metadata = get_arg_from_dict(json_data, "metadata")
        include_timeline_fragment = get_arg_from_dict(
            json_data, "include_timeline_fragment", use_default=True, default=True
        )
        client_ip_address = cls.get_client_ip_address()

        res = exp.process_response(
            participant_id,
            raw_answer,
            blobs,
            metadata,
            page_uuid,
            client_ip_address,
            answer,
            include_timeline_fragment,
        )

        return res

    @experiment_route("/log/<level>/<unique_id>", methods=["POST"])
    @classmethod
    @with_transaction
    def http_log(cls, level, unique_id):
        participant = cls.get_participant_from_unique_id(unique_id, for_update=False)
        try:
            cls.check_unique_id(participant, unique_id)
        except cls.UniqueIdError as e:
            return e.http_response()

        message = request.values["message"]

        assert level in ["warning", "info", "error"]

        string = f"[CLIENT {participant.id}]: {message}"

        if level == "info":
            logger.info(string)
        elif level == "warning":
            logger.warning(string)
        elif level == "error":
            logger.error(string)
        else:
            raise RuntimeError("This shouldn't happen.")

        return success_response()

    @staticmethod
    def extra_routes():
        raise RuntimeError(
            "\n\n"
            + "Due to a recent update, the following line is no longer required in PsyNet experiments:\n\n"
            + "extra_routes = Exp().extra_routes()\n\n"
            + "Please delete it from your experiment.py file and try again.\n"
        )

    @experiment_route(
        "/participant_opened_devtools/<unique_id>",
        methods=["POST"],
    )
    @classmethod
    @with_transaction
    def participant_opened_devtools(cls, unique_id):
        participant = cls.get_participant_from_unique_id(unique_id, for_update=False)

        cls.check_unique_id(participant, unique_id)

        participant.var.opened_devtools = True

        return success_response()

    def monitoring_statistics(self, **kwarg):
        stats = super().monitoring_statistics(**kwarg)

        del stats["Infos"]

        stats["Trials"] = OrderedDict(
            (
                ("count", Trial.query.count()),
                ("failed", Trial.query.filter_by(failed=True).count()),
            )
        )

        return stats

    def check_consents(self):
        if (
            deployment_info.read("is_local_deployment")
            and deployment_info.read("mode") == "debug"
        ):
            return
        self.timeline.check_consents(self)

    def check_python_dependencies(self):
        if os.environ.get("SKIP_DEPENDENCY_CHECK"):
            return
        if is_in_repo_experiment():
            if Path("constraints.txt").exists():
                logger.warning(
                    "Ignoring constraints.txt in in-repo experiment %s; in-repo "
                    "experiments use PsyNet's shared development environment "
                    "instead of per-demo constraint pins.",
                    Path.cwd(),
                )
            return
        extra_deps = self.notifier.python_dependencies
        with open("constraints.txt", "r") as f:
            constraints = f.readlines()
        for dep in extra_deps:
            self.check_python_dependency(dep, constraints)

    def check_python_dependency(self, dep, constraints):
        for constraint in constraints:
            if constraint.startswith(f"{dep}=="):
                return
        raise ValueError(
            f"Missing Python dependency: {dep}. "
            f"Please make sure it's installed locally (``pip install {dep}``), "
            f"then add ``{dep}`` to requirements.txt, "
            "then regenerate constraints.txt (``psynet generate-constraints``)."
        )


Experiment.SuccessfulEndLogic = SuccessfulEndLogic
Experiment.UnsuccessfulEndLogic = UnsuccessfulEndLogic
Experiment.RejectedConsentLogic = RejectedConsentLogic


def handle_shutdown_signal(*args, **kwargs):
    process_name = os.path.basename(sys.argv[0])
    if process_name.endswith("clock"):
        Experiment.record_experiment_status(online=False)
        Experiment.notifier.notify("Experiment was taken down ⛔️")
    sys.exit(0)


signal.signal(signal.SIGTERM, handle_shutdown_signal)
signal.signal(signal.SIGINT, handle_shutdown_signal)


@register_table
class ExperimentConfig(SQLBase, SQLMixin):
    """
    This SQL-backed class provides a way to store experiment configuration variables
    that can change over the course of the experiment.
    See :class:`psynet.experiment.Experiment` documentation for example usage.
    """

    __tablename__ = "experiment"

    # Removing these fields because they don't make much sense for the experiment configuration object
    creation_time = None
    failed = None
    failed_reason = None
    time_of_death = None


def _patch_dallinger_models():
    # There are some Dallinger functions that rely on the ability to look up
    # models by name in dallinger.models. One example is the code for
    # generating dashboard tabs for SQL object types. We therefore need
    # to patch in certain PsyNet classes so that Dallinger can access them.
    dallinger.models.Trial = Trial
    dallinger.models.Response = Response


_patch_dallinger_models()


def import_local_experiment():
    # Imports experiment.py and returns a dict consisting of
    # 'package' which corresponds to the experiment *package*,
    # 'module' which corresponds to the experiment *module*, and
    # 'class' which corresponds to the experiment *class*.
    # It also adds the experiment directory to sys.path, meaning that any other
    # modules defined there can be imported using ``import``.
    # import pdb; pdb.set_trace()
    #
    # TODO - Is it a problem if we try to import_local_experiment before config.load() has been called?
    ensure_experiment_directory_name_does_not_conflict()
    dallinger_get_config()

    import dallinger.experiment

    dallinger.experiment.load()

    dallinger_experiment = sys.modules.get("dallinger_experiment")
    sys.path.append(os.getcwd())

    try:
        module = dallinger_experiment.experiment
    except AttributeError as e:
        raise Exception(
            f"Possible ModuleNotFoundError in your experiment's experiment.py file. "
            f'Please check your imports!\nOriginal error was "AttributeError: {e}"'
        )

    return {
        "package": dallinger_experiment,
        "module": module,
        "class": dallinger.experiment.load(),  # TODO - use the class as loaded above instead?
    }


@cache
def get_experiment() -> Experiment:
    """
    Returns an initialized instance of the experiment class.
    """
    return import_local_experiment()["class"]()


@cache
def get_trial_maker(trial_maker_id) -> TrialMaker:
    exp = get_experiment()
    return exp.timeline.get_trial_maker(trial_maker_id)


def assert_config_txt_does_not_contain_sensitive_values():
    config = get_config()
    with open("config.txt", "r") as f:
        for line in f.readlines():
            for var in config.sensitive:
                if var in line:
                    raise ValueError(
                        f"Sensitive key '{var}' found in config.txt. Please move all sensitive "
                        "keys to `.dallingerconfig` and try again."
                    )


def in_deployment_package():
    return os.path.exists("DEPLOYMENT_PACKAGE")


def _identify_config_override_source(key):
    """Identify which configuration source overrides an experiment.py value."""
    if key in os.environ:
        return "an environment variable"

    return "another configuration source"


def authenticate(auth, config):
    return (
        auth
        and auth.username == config.get("dashboard_user")
        and auth.password == config.get("dashboard_password")
    )


# Dallinger defines various HTTP routes that provide access to database content.
# We disable the following HTTP routes in PsyNet experiments because they could
# in theory leak personal data or be used to manipulate the state of the
# experiment. Most data should instead be transferred via authenticated PsyNet routes.
_protected_routes = [
    "/network/<network_id>",
    "/question/<participant_id>",
    "/node/<int:node_id>/neighbors",
    "/node/<participant_id>",
    "/node/<int:node_id>/vectors",
    "/node/<int:node_id>/connect/<int:other_node_id>",
    "/info/<int:node_id>/<int:info_id>",
    "/node/<int:node_id>/infos",
    "/node/<int:node_id>/received_infos",
    "/tracking_event/<int:node_id>",
    "/info/<int:node_id>",
    "/node/<int:node_id>/transmissions",
    "/node/<int:node_id>/transmit",
    "/node/<int:node_id>/transformations",
    "/transformation/<int:node_id>/<int:info_in_id>/<int:info_out_id>",
]


def pre_deploy_constant(key, func: callable):
    """
    Registers a pre-deploy constant.
    A pre-deploy constant is a value that is computed before the experiment is deployed,
    and then stored in a file in the .deploy directory.
    When the value is accessed during the deployed experiment,
    the value is retrieved from the file rather than being computed again.
    A common application is experiments whose design is determined by the contents of a directory,
    such as experiments that use audio stimuli,
    which are not uploaded directly to the experiment server and hence cannot be accessed
    by file listing commands.

    Parameters
    ----------
    key : str
        The key of the pre-deploy constant. If it's not a string, it will be converted to one
        using ``psynet.serialize.serialize``.
    func : callable
        A callable that computes and returns the value of the pre-deploy constant.

    Returns
    -------
    The value of the pre-deploy constant.

    Examples
    --------

    # You could place this in your experiment.py file to list the files in the ``data`` directory.
    >>> data_files = pre_deploy_constant("data_files", sorted(os.listdir("data")))
    """
    assert callable(func), (
        "The func argument must be a callable (e.g. lambda: os.listdir('data'))."
    )
    key = serialize(key)

    try:
        return _pre_deploy_constant_registry[key]
    except KeyError:
        if not in_deployment_package():
            value = func()
            _pre_deploy_constant_registry[key] = value
            return value
        else:
            raise ValueError(
                f"Failed to find a value for pre-deploy constant {key}. "
                "If you defined this constant yourself, "
                f"please ensure that pre_deploy_constant('{key}', func) is placed "
                "somewhere in ``experiment.py`` such that it will be run when the file is loaded "
                "(e.g., don't put it within a CodeBlock.)"
            )


def _read_pre_deploy_constant_registry():
    with open(".deploy/pre_deploy_constant_registry.json", "r") as f:
        return unserialize(f.read())


def _write_pre_deploy_constant_registry():
    global _pre_deploy_constant_registry
    os.makedirs(".deploy", exist_ok=True)
    with open(".deploy/pre_deploy_constant_registry.json", "w") as f:
        f.write(serialize(_pre_deploy_constant_registry))


if in_deployment_package():
    _pre_deploy_constant_registry = _read_pre_deploy_constant_registry()
else:
    _pre_deploy_constant_registry = {}
