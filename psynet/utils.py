import contextlib
import gettext
import glob
import hashlib
import importlib
import inspect
import logging
import os
import re
import sys
import time
from _hashlib import HASH as Hash
from datetime import datetime
from functools import reduce, wraps
from os.path import exists
from os.path import join as join_path
from pathlib import Path
from typing import List, OrderedDict, Type, Union

import click
import html2text
import jsonpickle
import pexpect
import requests
import tomlkit
from babel.support import Translations
from bs4 import BeautifulSoup
from dallinger.config import experiment_available
from dallinger.heroku.tools import HerokuApp
from dallinger.recruiters import _descendent_classes
from flask import url_for
from flask.globals import current_app
from flask.templating import Environment, _render
from sqlalchemy import or_

from psynet.light_utils import (  # noqa: F401 – re-exported for backwards compat
    _IN_REPO_EXPERIMENT_ROOTS,
    ExperimentDirectoryNameError,
    _md5_update_from_dir,
    _md5_update_from_file,
    ensure_experiment_directory_name_does_not_conflict,
    get_psynet_root,
    git_command_available,
    git_repository_available,
    is_in_repo_experiment,
    md5_directory,
)
from psynet.translation.utils import load_po

package_root = os.path.dirname(os.path.abspath(__file__))


def psynet_source_prefixes():
    """Return path prefixes for PsyNet's own source files.

    Pass to ``warnings.warn(..., skip_file_prefixes=...)`` so a warning
    issued behind PsyNet wrappers refers to the first caller outside this
    package. Uses the ``psynet`` package directory, not the repository
    root, so demos and tests still count as caller code.

    Returns
    -------
    tuple of str
        A one-element tuple suitable for ``warnings.warn``.
    """
    return (package_root + os.sep,)


def get_logger(name="psynet"):
    return logging.getLogger(name)


logger = get_logger()


class NoArgumentProvided:
    """
    We use this class as a replacement for ``None`` as a default argument,
    to distinguish cases where the user doesn't provide an argument
    from cases where they intentionally provide ``None`` as an argument.
    """

    pass


def deep_copy(x):
    try:
        return jsonpickle.decode(jsonpickle.encode(x, keys=True), keys=True)
    except Exception:
        logger.error(f"Failed to copy the following object: {x}")
        raise


def get_arg_from_dict(x, desired: str, use_default=False, default=None):
    if desired not in x:
        if use_default:
            return default
        else:
            raise KeyError
    return x[desired]


def sql_sample_one(x):
    from sqlalchemy.sql import func

    return x.order_by(func.random()).first()


def call_function(function, *args, **kwargs):
    """
    Calls a function with ``*args`` and ``**kwargs``, but omits any ``**kwargs`` that are
    not requested explicitly.
    """
    kwargs = {key: value for key, value in kwargs.items() if key in get_args(function)}
    return function(*args, **kwargs)


def find_git_repo():
    """
    Finds the origin of the git repository of the current directory.
    """
    import subprocess

    try:
        origin = (
            subprocess.check_output(["git", "config", "--get", "remote.origin.url"])
            .strip()
            .decode("utf-8")
        )
        return origin
    except subprocess.CalledProcessError:
        return None


def call_function_with_context(function, *args, **kwargs):
    from psynet.participant import Participant
    from psynet.trial.main import Trial

    participant = kwargs.get("participant", NoArgumentProvided)
    experiment = kwargs.get("experiment", NoArgumentProvided)
    assets = kwargs.get("assets", NoArgumentProvided)
    nodes = kwargs.get("nodes", NoArgumentProvided)
    trial_maker = kwargs.get("trial_maker", NoArgumentProvided)
    trial = kwargs.get("trial", NoArgumentProvided)

    requested = get_args(function)

    if experiment == NoArgumentProvided and "experiment" in requested:
        from .experiment import get_experiment

        experiment = get_experiment()

    if "assets" in requested and assets == NoArgumentProvided:
        from psynet.asset import Asset

        # We initially query just assets that are not participant-specific.
        # We will add participant-specific assets later, looking specifically at
        # assets that are associated with the participant's module state.
        assets = Asset.query.filter_by(participant_id=None)

        if participant != NoArgumentProvided:
            assert isinstance(participant, Participant)
            participant_module_id = (
                participant.module_state.module_id if participant.module_state else None
            )
            assets = assets.filter_by(module_id=participant_module_id)

        assets = {asset.local_key: asset for asset in assets.all()}

        if participant != NoArgumentProvided and participant.module_state:
            assets.update(participant.module_state.assets)

    if participant != NoArgumentProvided and participant.module_state:
        if "nodes" in requested and nodes == NoArgumentProvided:
            from psynet.trial.main import TrialNode

            nodes = TrialNode.query.filter(
                or_(
                    TrialNode.module_id == participant.module_state.module_id,
                    TrialNode.module_id.is_(None),
                )
            ).all()

    if "trial" in requested and trial == NoArgumentProvided:
        if participant != NoArgumentProvided and isinstance(
            participant.current_trial, Trial
        ):
            trial = participant.current_trial

    if "trial_maker" in requested and trial_maker == NoArgumentProvided:
        if (
            participant != NoArgumentProvided
            and participant.in_module
            and isinstance(participant.current_trial, Trial)
        ):
            trial_maker = participant.current_trial.trial_maker

    new_kwargs = {
        "experiment": experiment,
        "participant": participant,
        "assets": assets,
        "nodes": nodes,
        "trial_maker": trial_maker,
        "trial": trial,
        **kwargs,
    }
    return call_function(function, *args, **new_kwargs)


config_defaults = {}


def get_config():
    from dallinger.config import get_config as dallinger_get_config

    config = dallinger_get_config()
    if not config.ready:
        config.load()
    return config


def get_from_config(key):
    global config_defaults

    config = get_config()
    if not config.ready:
        config.load()

    if key in config_defaults:
        return config.get(key, default=config_defaults[key])
    else:
        return config.get(key)


def get_args(f):
    return [str(x) for x in inspect.signature(f).parameters]


def get_object_from_module(module_name: str, object_name: str):
    """
    Finds and returns an object from a module.

    Parameters
    ----------

    module_name
        The name of the module.

    object_name
        The name of the object.
    """
    mod = importlib.import_module(module_name)
    obj = getattr(mod, object_name)
    return obj


def log_time_taken(fun):
    @wraps(fun)
    def wrapper(*args, **kwargs):
        with time_logger(fun.__name__):
            res = fun(*args, **kwargs)
        return res

    return wrapper


def negate(f):
    """
    Negates a function.

    Parameters
    ----------

    f
        Function to negate.
    """

    @wraps(f)
    def g(*args, **kwargs):
        return not f(*args, **kwargs)

    return g


def linspace(lower, upper, length: int):
    """
    Returns a list of equally spaced numbers between two closed bounds.

    Parameters
    ----------

    lower : number
        The lower bound.

    upper : number
        The upper bound.

    length : int
        The length of the resulting list.
    """
    if length == 1:
        return [lower]
    return [lower + x * (upper - lower) / (length - 1) for x in range(length)]


def merge_dicts(*args, overwrite: bool):
    """
    Merges a collection of dictionaries, with later dictionaries
    taking precedence when the same key appears twice.

    Parameters
    ----------

    *args
        Dictionaries to merge.

    overwrite
        If ``True``, when the same key appears twice in multiple dictionaries,
        the key from the latter dictionary takes precedence.
        If ``False``, an error is thrown if such duplicates occur.
    """

    if len(args) == 0:
        return {}
    return reduce(lambda x, y: merge_two_dicts(x, y, overwrite), args)


def merge_two_dicts(x: dict, y: dict, overwrite: bool):
    """
    Merges two dictionaries.

    Parameters
    ----------

    x :
        First dictionary.

    y :
        Second dictionary.

    overwrite :
        If ``True``, when the same key appears twice in the two dictionaries,
        the key from the latter dictionary takes precedence.
        If ``False``, an error is thrown if such duplicates occur.
    """

    if not overwrite:
        for key in y.keys():
            if key in x:
                raise DuplicateKeyError(
                    f"Duplicate key {key} found in the dictionaries to be merged."
                )

    return {**x, **y}


class DuplicateKeyError(ValueError):
    pass


def corr(x: list, y: list, method="pearson"):
    import pandas as pd

    df = pd.DataFrame({"x": x, "y": y}, columns=["x", "y"])
    return float(df.corr(method=method).at["x", "y"])


def md5_object(x):
    string = jsonpickle.encode(x, keys=True).encode("utf-8")
    hashed = hashlib.md5(string)
    return str(hashed.hexdigest())


# MD5 hashing code:
# https://stackoverflow.com/a/54477583/8454486
def md5_update_from_file(filename: Union[str, Path], hash: Hash) -> Hash:
    """Update *hash* with the contents of *filename* and return it."""
    _md5_update_from_file(filename, hash)
    return hash


def md5_file(filename: Union[str, Path]) -> str:
    """Return the MD5 hex digest of a single file."""
    h = hashlib.md5()
    _md5_update_from_file(filename, h)
    return h.hexdigest()


def md5_update_from_dir(directory: Union[str, Path], hash: Hash) -> Hash:
    """Recursively update *hash* with all non-hidden files under *directory*."""
    _md5_update_from_dir(directory, hash)
    return hash


def serialise_datetime(x):
    if x is None:
        return None
    return x.isoformat()


def unserialise_datetime(x):
    if x is None:
        return None
    return datetime.fromisoformat(x)


def clamp(x):
    return max(0, min(x, 255))


def rgb_to_hex(r, g, b):
    return "#{0:02x}{1:02x}{2:02x}".format(
        clamp(round(r)), clamp(round(g)), clamp(round(b))
    )


def serialise(obj):
    """Serialise objects not serialisable by default"""

    if isinstance(obj, (datetime)):
        return serialise_datetime(obj)
    raise TypeError("Type %s is not serialisable" % type(obj))


def format_datetime(datetime):
    return datetime.strftime("%Y-%m-%d %H:%M:%S")


def format_bytes(num: float) -> str:
    """
    Formats bytes into a human-readable string.

    Parameters
    ----------
    num : float
        The number of bytes to format.


    Returns
    -------
    str
        The formatted string.


    Examples
    --------
    >>> format_bytes(1024)
    '1.0KB'
    >>> format_bytes(1048576)
    '1.0MB'
    >>> format_bytes(1073741824)
    '1.0GB'
    """
    for x in ["bytes", "KB", "MB", "GB", "TB"]:
        if num < 1024.0:
            return "%3.1f%s" % (num, x)
        num /= 1024.0
    return "%3.1f%s" % (num, "PB")


def model_name_to_snake_case(model_name):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", model_name).lower()


def json_to_data_frame(json_data):
    import pandas as pd

    columns = []
    for row in json_data:
        [columns.append(key) for key in row.keys() if key not in columns]

    data_frame = pd.DataFrame.from_records(json_data, columns=columns)
    return data_frame


def wait_until(
    condition, max_wait, poll_interval=0.5, error_message=None, *args, **kwargs
):
    if condition(*args, **kwargs):
        return True
    else:
        waited = 0.0
        while waited <= max_wait:
            time.sleep(poll_interval)
            waited += poll_interval
            if condition(*args, **kwargs):
                return True
        if error_message is None:
            error_message = (
                "Condition was not satisfied within the required time interval."
            )
        raise RuntimeError(error_message)


def wait_while(condition, **kwargs):
    wait_until(lambda: not condition(), **kwargs)


def is_valid_html5_id(str):
    if not str or " " in str:
        return False
    return True


def pretty_format_seconds(seconds):
    total_seconds = int(round(seconds))
    minutes, seconds_remainder = divmod(total_seconds, 60)
    formatted_time = f"{minutes} min"
    if seconds_remainder > 0:
        formatted_time += f" {seconds_remainder} sec"
    return formatted_time


def require_exp_directory(f):
    """Decorator to verify that a command is run inside a valid PsyNet experiment directory."""
    error_one = "The current directory is not a valid PsyNet experiment."
    error_two = "There are problems with the current experiment. Please check with `dallinger verify`."

    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            ensure_experiment_directory_name_does_not_conflict()
            if not experiment_available():
                raise click.UsageError(error_one)
        except ExperimentDirectoryNameError as e:
            raise click.UsageError(str(e))
        except ValueError:
            raise click.UsageError(error_two)

        return f(*args, **kwargs)

    return wrapper


def require_requirements_txt(f):
    """Decorator to verify that a command is run inside a directory which contains a requirements.txt file."""

    @wraps(f)
    def wrapper(*args, **kwargs):
        if not Path("requirements.txt").exists():
            raise click.UsageError(
                "The current directory does not contain a requirements.txt file."
            )
        return f(*args, **kwargs)

    return wrapper


def _render_with_translations(
    locale, template_name=None, template_string=None, all_template_args=None
):
    """Render a template with translations applied."""
    from psynet.utils import get_config

    if all_template_args is None:
        all_template_args = {}

    all_template_args["config"] = dict(get_config().as_dict().items())

    assert [template_name, template_string].count(None) == 1, (
        "Only one of template_name or template_string should be provided."
    )

    if locale is None:
        locale = get_locale()

    app = current_app._get_current_object()  # type: ignore[attr-defined]
    gettext = get_translator()
    pgettext = get_translator(context=True)

    jinja_functions = {
        **app.jinja_env.globals,
        "gettext": gettext,
        "pgettext": pgettext,
        "url_for": url_for,
    }

    translation = Translations.load("translations", [locale])

    environment = Environment(
        loader=app.jinja_env.loader, extensions=["jinja2.ext.i18n"], app=app
    )
    environment.install_gettext_translations(translation)

    environment.globals.update(**jinja_functions)

    if template_name is not None:
        template = environment.get_template(template_name)
    else:
        template = environment.from_string(template_string)
    return _render(app, template, all_template_args)


def render_template_with_translations(template_name, locale=None, **kwargs):
    return _render_with_translations(
        template_name=template_name, locale=locale, all_template_args=kwargs
    )


def render_string_with_translations(template_string, locale=None, **kwargs):
    return _render_with_translations(
        template_string=template_string, locale=locale, all_template_args=kwargs
    )


def get_descendent_class_by_name(parent_class, name):
    """Attempt to return a subclass by name.

    Actual class names and known nicknames are both supported.
    """
    by_name = {}
    for cls in _descendent_classes(parent_class):
        ids = [cls.nickname, cls.__name__]
        for id_ in ids:
            previous_registered_cls = by_name.get(id_, None)
            if previous_registered_cls:
                should_overwrite = issubclass(cls, previous_registered_cls)
            else:
                should_overwrite = True
            if should_overwrite:
                by_name[id_] = cls
    klass = by_name.get(name)
    assert klass is not None, (
        f"Could not find class {name} in subclasses of {parent_class}"
    )
    return klass


def get_locale() -> str:
    from . import deployment_info
    from .experiment import in_deployment_package

    if in_deployment_package():
        return deployment_info.read("locale")
    else:
        return "en"


REGISTERED_TRANSLATIONS = {}


class TranslationNotFoundError(KeyError):
    pass


def check_translation_is_available(message, context, locale, namespace):
    from . import deployment_info
    from .experiment import get_experiment, in_deployment_package

    args = locals()

    is_available = (context, message) in REGISTERED_TRANSLATIONS[namespace][locale]

    if not is_available:
        message = (
            f"Could not find a translation for message {message!r} in locale = {locale}, context = {context}, namespace = {namespace}. "
            "Perhaps the translatable string was not properly captured by `psynet translate`? "
            "To mark a string as translatable, you should write e.g. _('Hello') or _p('welcome message', 'Hello'). "
            "You cannot rename the functions _ or _p, and you must pass them strings directly, not variables or strings wrapped in parentheses."
        )
        is_live_experiment = (
            in_deployment_package() and deployment_info.read("mode") == "live"
        )
        if is_live_experiment:
            message += " Since this is a live experiment, we instead presented the untranslated text."
        else:
            message += " If this happened in a live experiment, we would default to presenting the untranslated text."

        # We need to actually raise the TranslationNotFoundError here for it to be treated appropriately by report_error.
        try:
            raise TranslationNotFoundError(message)
        except TranslationNotFoundError as e:
            if is_live_experiment:
                get_experiment().report_error(e)
            else:
                raise e


def report_translation_error(message, context, locale):
    from psynet.experiment import get_experiment

    exp = get_experiment()
    error = TranslationNotFoundError(
        f"Translation not found for message '{message}' (context: {context}) in locale '{locale}'"
    )
    exp.report_error(error)


def get_translator(
    context=False,
    locale=None,
    namespace=None,
    locales_dir=None,
):
    """
    Return a translator.

    In most cases this function should be called with no arguments, in which case
    the locale will be taken from the config.txt file,
    the namespace will be inferred from the context in which the function was called,
    and the locales directory will be inferred from the namespace.

    The default translator is context-free, which means that it only takes a message argument.
    We recommend using this in most cases.
    You can obtain a context-aware translator by setting ``context = True``;
    such a translator takes both a context and a message argument.

    PsyNet uses automated code inspection tools to extract all translatable strings from your code.
    In order for these tools to work properly, you should save the returned translator
    with the name ``_`` if ``context = False`` or ``_p`` if ``context = True``.

    Once you have marked up your code with the ``_`` and ``_p`` functions,
    you can then run ``psynet translate`` to generate automatically translated versions of your strings.

    Example usage
    -------------

    >>> _ = get_translator()
    >>> _("Hello")  # Translate "Hello" into the current locale.

    >>> _p = get_translator(context=True)
    >>> _p("welcome message", "Hello")  # Translate "Hello" into the current locale, with context "welcome message".

    Parameters
    ----------
    context : bool, optional
        Whether to use the context argument. If True, the translator will be a function that takes a context argument and
        a message argument. If False, the translator will be a function that just takes a message argument.
    locale : str, optional
        The locale to use for translations. If not provided, the locale will be taken from the experiment config.
    namespace : str, optional
        The namespace to use for translations. If not provided, the namespace will be inferred from the context
        in which the function was called. The experiment directory has a namespace of "experiment", and the package
        directory has a namespace of the package name.
    locales_dir : str, optional
        The directory to use for translations. If not provided, the locales directory will be inferred from the namespace.
        In the case of an experiment, the locales directory will be the "locales" directory of the experiment's source directory.
        In the case of a package, the locales directory will be the "locales" directory of the package's source directory.
    """
    from .experiment import in_deployment_package

    if namespace is None:
        frame = inspect.currentframe().f_back
        package_name = frame.f_globals.get("__package__")

        if package_name is None:
            namespace = "experiment"
        else:
            package_name = package_name.split(".")[0]  # Remove any subpackage names.

        if package_name == "dallinger_experiment":
            namespace = "experiment"
        elif package_name == "":
            raise ValueError(
                "_get_translator could not work out what namespace to use. Try providing the namespace explicitly."
            )
        elif namespace is None:
            namespace = package_name

    def _get_translators(locales_dir, locale, namespace):
        if locales_dir is None:
            locales_dir = get_locales_dir(namespace)

        compile_mo_file_if_necessary(locales_dir, locale, namespace)

        translator = gettext.translation(namespace, locales_dir, [locale])

        if namespace not in REGISTERED_TRANSLATIONS:
            REGISTERED_TRANSLATIONS[namespace] = {}

        if locale not in REGISTERED_TRANSLATIONS[namespace]:
            po_path = join_path(locales_dir, locale, "LC_MESSAGES", f"{namespace}.po")
            po = load_po(po_path)
            keys = []
            for entry in po:
                msgctxt = None if entry.msgctxt == "" else entry.msgctxt
                keys.append((msgctxt, entry.msgid))
            REGISTERED_TRANSLATIONS[namespace][locale] = keys

        def _(message):
            context = None
            check_translation_is_available(message, context, locale, namespace)
            return translator.gettext(message)

        def _p(context, message):
            check_translation_is_available(message, context, locale, namespace)
            return translator.pgettext(context, message)

        return _, _p

    if not in_deployment_package():
        if locale is None:
            # We cannot load translations when we're not in the deployment package and the locale cannot be identified
            # automatically. Because we cannot import the experiment directory yet (to access config variables etc).
            # So in this case, we don't translate.
            _, _p = null_translator, null_translator_with_context
        else:
            # Provide translation when locale is specified
            _, _p = _get_translators(locales_dir, locale, namespace)
    else:
        if locale is None:
            locale = get_locale()

        if locale == "en":
            # Skill translation if English
            _, _p = null_translator, null_translator_with_context
        else:
            _, _p = _get_translators(locales_dir, locale, namespace)

    _.namespace = namespace
    _p.namespace = namespace

    _.locale = locale
    _p.locale = locale

    if context:
        return _p
    else:
        return _


def get_locales_dir(namespace: str):
    if namespace == "experiment":
        package_name = "dallinger_experiment"
    else:
        package_name = namespace
    source_dir = get_installed_package_source_directory(package_name)
    return source_dir / "locales"


def get_locales_dir_from_path(path="."):
    path = Path(path)

    if is_a_package(path):
        source_dir = get_package_source_directory(path)
        return path / source_dir / "locales"
    elif (path / "experiment.py").exists():
        return path / "locales"
    else:
        raise ValueError("Could not determine the locales directory.")


def null_translator(message):
    """
    A translator that returns the message unchanged.
    """
    return message


def null_translator_with_context(context, message):
    """
    A translator that returns the message unchanged.
    """
    return message


def compile_mo_file_if_necessary(locales_dir, locale, namespace):
    from .translation.utils import compile_mo

    mo_path = join_path(locales_dir, locale, "LC_MESSAGES", f"{namespace}.mo")
    po_path = join_path(locales_dir, locale, "LC_MESSAGES", f"{namespace}.po")

    assert exists(po_path)

    if not exists(mo_path) or os.path.getmtime(po_path) > os.path.getmtime(mo_path):
        logger.info(f"Compiling translation file {po_path}.")
        compile_mo(po_path)


def _get_translator_called_within_psynet():
    """
    Used for testing what happens when you call get_translator from within the PsyNet package.
    """
    return get_translator()


def _get_entity_dict_from_tuple_list(tuple_list, sort_by_value):
    dictionary = dict(
        zip([key for key, value in tuple_list], [value for key, value in tuple_list])
    )
    if sort_by_value:
        return dict(OrderedDict(sorted(dictionary.items(), key=lambda t: t[1])))
    else:
        return dictionary


def get_language_dict(locale, sort_by_name=True):
    from psynet.translation.languages import get_known_languages

    return _get_entity_dict_from_tuple_list(get_known_languages(locale), sort_by_name)


def get_country_dict(locale, sort_by_name=True):
    from psynet.translation.countries import get_known_countries

    return _get_entity_dict_from_tuple_list(get_known_countries(locale), sort_by_name)


def sample_from_surface_of_unit_sphere(n_dimensions):
    import numpy as np

    res = np.random.randn(n_dimensions, 1)
    res /= np.linalg.norm(res, axis=0)
    return res[:, 0].tolist()


def run_subprocess_with_live_output(command, timeout=None, cwd=None):
    _command = command.replace('"', '\\"').replace("'", "\\'")
    p = pexpect.spawn(f'bash -c "{_command}"', timeout=timeout, cwd=cwd)
    while not p.eof():
        line = p.readline().decode("utf-8")
        print(line, end="")
    p.close()
    if p.exitstatus > 0:
        sys.exit(p.exitstatus)


def get_extension(path):
    if path:
        _, extension = os.path.splitext(path)
        return extension
    else:
        return ""


def organize_by_key(lst, key, sort_key=None):
    """
    Sorts a list of items into groups.

    Parameters
    ----------
    lst :
        List to sort.

    key :
        Function applied to elements of ``lst`` which defines the grouping key.

    Returns
    -------

    A dictionary keyed by the outputs of ``key``.

    """
    out = {}
    for obj in lst:
        _key = key(obj)
        if _key not in out:
            out[_key] = []
        out[_key].append(obj)
    if sort_key:
        for value in out.values():
            value.sort(key=sort_key)
    return out


@contextlib.contextmanager
def working_directory(path):
    start_dir = os.getcwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(start_dir)


def get_custom_sql_classes():
    """

    Returns
    -------

    A dictionary of all custom SQLAlchemy classes defined in the local experiment
    (excluding any which are defined within packages).
    """

    def f():
        return {
            cls.__name__: cls
            for _, module in inspect.getmembers(sys.modules["dallinger_experiment"])
            for _, cls in inspect.getmembers(module)
            if inspect.isclass(cls)
            and cls.__module__.startswith("dallinger_experiment")
            and hasattr(cls, "_sa_registry")
        }

    try:
        return f()
    except KeyError:
        from psynet.experiment import import_local_experiment

        import_local_experiment()
        return f()


def make_parents(path):
    """
    Creates the parent directories for a specified file if they don't exist already.

    Returns
    -------

    The original path.
    """
    Path(os.path.dirname(path)).mkdir(parents=True, exist_ok=True)
    return path


def bytes_to_megabytes(bytes):
    return bytes / (1024 * 1024)


def get_file_size_mb(path):
    bytes = os.path.getsize(path)
    return bytes_to_megabytes(bytes)


def get_folder_size_mb(path):
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            total_size += os.path.getsize(fp)
    return bytes_to_megabytes(total_size)


# def run_async_command_locally(fun, *args, **kwargs):
#     """
#     This is for when want to run a command asynchronously (so that it doesn't block current execution)
#     but locally (so that we know we have access to local files).
#     """
#
#     def wrapper():
#         f = io.StringIO()
#         with contextlib.redirect_stdout(f):
#             try:
#                 fun(*args, **kwargs)
#             except Exception:
#                 print(traceback.format_exc())
#         log_to_redis(f.getvalue())
#
#     import threading
#
#     thr = threading.Thread(target=wrapper)
#     thr.start()


# def log_to_redis(msg):
#     """
#     This passes the message to the Redis queue to be printed by the worker that picks it up.
#     This is useful for logging from processes that don't have access to the main logger.
#     """
#     q = Queue("default", connection=redis_conn)
#     q.enqueue_call(
#         func=logger.info, args=(), kwargs=dict(msg=msg), timeout=1e10, at_front=True
#     )


@contextlib.contextmanager
def disable_logger():
    logging.disable(sys.maxsize)
    yield
    logging.disable(logging.NOTSET)


def clear_all_caches():
    import functools
    import gc

    for obj in gc.get_objects():
        try:
            if isinstance(obj, functools._lru_cache_wrapper):
                obj.cache_clear()
        except ReferenceError:
            pass
        except Exception as e:
            if "openai.OpenAIError" in str(e.__class__):
                pass
            else:
                raise e


@contextlib.contextmanager
def log_pexpect_errors(process):
    try:
        yield
    except (pexpect.EOF, pexpect.TIMEOUT) as err:
        print(f"A {err} error occurred. Printing process logs:")
        print(process.before)
        raise


# This seemed like a good idea for preventing cases where people use random functions
# in code blocks, page makers, etc. In practice however it didn't work, because
# some library functions tamper with the random state in a hidden way,
# making the check have too many false positives.
#
# @contextlib.contextmanager
# def disallow_random_functions(func_name, func=None):
#     random_state = random.getstate
#     numpy_random_state = numpy.random.get_state()
#
#     yield
#
#     if (
#         random.getstate() != random_state
#         or numpy.random.get_state() != numpy_random_state
#     ):
#         message = (
#             "It looks like you used Python's random number generator within "
#             f"your {func_name} code. This is disallowed because it allows your "
#             "experiment to get into inconsistent states. Instead you should generate "
#             "call any random number generators within code blocks, for_loop() constructs, "
#             "Trial.make_definition methods, or similar."
#         )
#         if func:
#             message += "\n"
#             message += "Offending code:\n"
#             message += inspect.getsource(func)
#
#         raise RuntimeError(message)


def is_method_overridden(obj, ancestor: Type, method: str):
    """
    Test whether a method has been overridden.

    Parameters
    ----------
    obj :
        Object to test.

    ancestor :
        Ancestor class to test against.

    method :
        Method name.

    Returns
    -------

    Returns ``True`` if the object shares a method with its ancestor,
    or ``False`` if that method has been overridden.

    """
    return getattr(obj.__class__, method) != getattr(ancestor, method)


@contextlib.contextmanager
def time_logger(label, threshold=0.01):
    log = {
        "time_started": time.monotonic(),
        "time_finished": None,
        "time_taken": None,
    }
    yield log
    log["time_finished"] = time.monotonic()
    log["time_taken"] = log["time_finished"] - log["time_started"]
    if log["time_taken"] > threshold:
        logger.info(
            "Task '%s' took %.3f s",
            label,
            log["time_taken"],
        )


@contextlib.contextmanager
def log_level(logger: logging.Logger, level):
    original_level = logger.level
    logger.setLevel(level)
    yield
    logger.setLevel(original_level)


# Path substrings / suffixes excluded from CI demo runs via ``for_ci_tests``.
# Playwright experiments have dedicated CI jobs; recruiter demos and gibbs_video
# are not meaningful (or lack deps) in the shared CI runner.
_CI_EXCLUDED_EXPERIMENT_PATH_MARKERS = (
    "recruiters",
    "/tests/deployment/",
    "playwright",
)
_CI_EXCLUDED_EXPERIMENT_PATH_SUFFIXES = ("/gibbs_video",)


def _excluded_from_ci_experiment_dirs(dir_path: str) -> bool:
    """Return whether an experiment directory should be skipped in CI demo runs."""
    return any(
        marker in dir_path for marker in _CI_EXCLUDED_EXPERIMENT_PATH_MARKERS
    ) or any(
        dir_path.endswith(suffix) for suffix in _CI_EXCLUDED_EXPERIMENT_PATH_SUFFIXES
    )


def list_experiment_dirs(for_ci_tests=False, ci_node_total=None, ci_node_index=None):
    """List in-repo experiment directories under :data:`_IN_REPO_EXPERIMENT_ROOTS`.

    Skips hidden directories while walking so leftover virtualenvs under a demo
    (e.g. ``.venv``) are not mistaken for experiments when they contain an
    ``experiment.py`` inside ``site-packages``.
    """
    psynet_root = get_psynet_root()
    dirs = []
    for relative in _IN_REPO_EXPERIMENT_ROOTS:
        for dir_, sub_dirs, files in os.walk(psynet_root / relative):
            # Prune in place so os.walk does not descend into .venv, .git, etc.
            sub_dirs[:] = [name for name in sub_dirs if not name.startswith(".")]
            if "experiment.py" not in files:
                continue
            if dir_.endswith("/develop"):
                continue
            if for_ci_tests and _excluded_from_ci_experiment_dirs(dir_):
                continue
            dirs.append(dir_)
    dirs = sorted(dirs)

    if ci_node_total is not None and ci_node_index is not None:
        dirs = with_parallel_ci(dirs, ci_node_total, ci_node_index)

    return dirs


def with_parallel_ci(paths, ci_node_total, ci_node_index):
    index = ci_node_index - 1  # 1-indexed to 0-indexed
    assert 0 <= index < ci_node_total
    return [paths[i] for i in range(len(paths)) if i % ci_node_total == index]


def list_isolated_tests(ci_node_total=None, ci_node_index=None):
    isolated_tests_root = get_psynet_root() / "tests" / "isolated"
    isolated_tests_demos = isolated_tests_root / "demos"
    isolated_tests_experiments = isolated_tests_root / "experiments"
    isolated_tests_features = isolated_tests_root / "features"
    isolated_tests_translation = isolated_tests_root / "translation"

    tests = []
    for directory in [
        isolated_tests_root,
        isolated_tests_demos,
        isolated_tests_experiments,
        isolated_tests_features,
        isolated_tests_translation,
    ]:
        tests.extend(glob.glob(str(directory / "*.py")))

    if ci_node_total is not None and ci_node_index is not None:
        tests = with_parallel_ci(tests, ci_node_total, ci_node_index)

    return tests


# Check TODOs
class PatternDir:
    def __init__(self, pattern, glob_dir):
        self.pattern = pattern
        self.glob_dir = glob_dir

    def __dict__(self):
        return {"pattern": self.pattern, "glob_dir": self.glob_dir}


def _should_skip_todo_path(path: Path) -> bool:
    skip_dirs = {"venv", ".venv", ".tox", "node_modules", "__pycache__"}
    return any(part in skip_dirs for part in path.parts)


def _check_todos(pattern, glob_dir):
    from glob import iglob

    todo_count = {}
    for path in list(iglob(glob_dir, recursive=True)):
        path_obj = Path(path)
        if _should_skip_todo_path(path_obj):
            continue
        if not path_obj.is_file():
            continue
        key = (path, pattern)
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            line_has_todo = [line.strip().startswith(pattern) for line in f.readlines()]
            if any(line_has_todo):
                todo_count[key] = sum(line_has_todo)
    return todo_count


def _aggregate_todos(pattern_dirs: List[PatternDir]):
    todo_count = {}
    for pattern_dir in pattern_dirs:
        todo_count.update(_check_todos(**pattern_dir.__dict__()))
    return todo_count


def check_todos_before_deployment():
    if os.environ.get("SKIP_TODO_CHECK"):
        print(
            "SKIP_TODO_CHECK is set so we will not check if there are any TODOs in the experiment folder."
        )
        return

    todo_count = _aggregate_todos(
        [
            # For now only limit to comments specific to the experiment logic (i.e. Python and JS)
            PatternDir("# TODO", "**/*.py"),  # Python comments
            PatternDir("// TODO", "**/*.py"),  # Javascript comment in py files
            PatternDir("// TODO", "**/*.html"),  # Javascript comment in html files
            PatternDir("// TODO", "**/*.js"),  # Javascript comment in js files
        ]
    )
    file_names = [key[0] for key in todo_count.keys()]
    total_todo_count = sum(todo_count.values())
    n_files = len(set(file_names))

    assert len(todo_count) == 0, (
        f"You have {total_todo_count} TODOs in {n_files} file(s) in your experiment folder. "
        "Please fix them or remove them before deploying. "
        "To view all TODOs in your project in PyCharm, go to 'View' > 'Tool Windows' > 'TODO'. "
        "You can skip this check by writing `export SKIP_TODO_CHECK=1` (without quotes) in your terminal."
    )


def as_plain_text(html):
    text = html2text.HTML2Text().handle(str(html))
    pattern = re.compile(r"\s+")
    text = re.sub(pattern, " ", text).strip()
    return text


def in_psynet_directory():
    try:
        with open(Path("pyproject.toml"), "r") as f:
            return 'name = "psynet"' in f.read()

    except FileNotFoundError:
        return False


def in_python_package():
    """
    Test whether the current directory is the root of a Python package.

    Returns
    -------
    bool
        True if the current directory contains either pyproject.toml or setup.py,
        indicating it is likely a Python package root directory.
    """
    return is_a_package(".")


def is_a_package(path):
    path = Path(path)
    files_to_check = ["pyproject.toml", "setup.py"]
    for file in files_to_check:
        if path.joinpath(file).exists():
            return True


def get_package_name(path="."):
    """
    Find the package name by inspecting a directory.

    Parameters
    ----------
    path : str or Path, optional
        Path to the directory containing ``pyproject.toml`` or ``setup.py``.

    Returns
    -------
    str
        The package name from the configuration file.

    Raises
    ------
    FileNotFoundError
        If neither ``pyproject.toml`` nor ``setup.py`` is present in ``path``.
    """
    path = Path(path)
    if (path / "pyproject.toml").exists():
        return get_package_name_from_pyproject(path)
    elif (path / "setup.py").exists():
        name = get_package_name_from_setup(path)
        if name is not None:
            return name
    raise FileNotFoundError(
        "Could not find pyproject.toml or setup.py in current directory"
    )


def get_package_name_from_pyproject(path="."):
    """
    Get package name from pyproject.toml file.

    Parameters
    ----------
    path : str or Path, optional
        Path to the directory containing pyproject.toml.

    Returns
    -------
    str
        The package name from pyproject.toml.
    """
    path = Path(path)
    with open(path / "pyproject.toml", "r") as f:
        pyproject = tomlkit.parse(f.read())
        return pyproject["project"]["name"]


def get_package_name_from_setup(path="."):
    """
    Get package name from setup.py file.

    Parameters
    ----------
    path : str or Path, optional
        Path to the directory containing setup.py.

    Returns
    -------
    str
        The package name from setup.py.
    """
    import ast

    path = Path(path)
    with open(path / "setup.py") as f:
        setup_contents = f.read()
    setup_ast = ast.parse(setup_contents)
    for node in ast.walk(setup_ast):
        keywords = getattr(node, "keywords", None)
        if isinstance(keywords, list) and len(keywords) > 0:
            for keyword in keywords:
                if keyword.arg == "name":
                    return ast.literal_eval(keyword.value)
    return None


def get_installed_package_source_directory(package_name: str) -> Path:
    """
    Get the source directory of an installed package.

    Parameters
    ----------
    package_name : str
        The name of the package.

    Returns
    -------
    Path
        The path to the package root directory.

    Raises
    ------
    FileNotFoundError
        If the package root directory cannot be found.
    """
    package = importlib.import_module(package_name)
    if getattr(package, "__file__", None) is not None:
        return Path(package.__file__).parent

    # Namespace packages (no ``__init__.py``) expose their location via
    # ``__path__``. Deployment copies of in-repo demos often omit scaffolded
    # ``__init__.py`` files because they are gitignored, so Dallinger loads
    # them as namespace packages.
    paths = getattr(package, "__path__", None)
    if paths:
        return Path(next(iter(paths))).resolve()

    raise FileNotFoundError(
        f"Could not determine the source directory for package {package_name!r}."
    )


def get_package_source_directory(path="."):
    """
    Get the source directory of the package by inspecting pyproject.toml or setup.py.
    Does not assume that the package is installed.

    Parameters
    ----------
    path : str
        The path to the package source directory.

    Returns
    -------
    str
        The path to the package source directory.

    Raises
    ------
    FileNotFoundError
        If the package source directory cannot be found.
    """
    path = Path(path)
    pyproject_path = path / "pyproject.toml"
    setup_path = path / "setup.py"

    # First try pyproject.toml
    if pyproject_path.exists():
        with open(pyproject_path, "r") as f:
            pyproject = tomlkit.parse(f.read())

        # Check for src_dir in [tool.setuptools]
        if "tool" in pyproject and "setuptools" in pyproject["tool"]:
            packages_dir = (
                pyproject["tool"]["setuptools"]
                .get("packages", {})
                .get("find", {})
                .get("where")
            )
            if isinstance(packages_dir, (list, tuple)):
                packages_dir = packages_dir[0] if packages_dir else None
            if packages_dir:
                packages_dir = Path(packages_dir)
                if not packages_dir.is_absolute():
                    packages_dir = path / packages_dir
                return str(packages_dir)

        # Check for packages-dir in [tool.poetry]
        if "tool" in pyproject and "poetry" in pyproject["tool"]:
            packages_dir = (
                pyproject["tool"]["poetry"].get("packages", [{}])[0].get("from")
            )
            if packages_dir:
                packages_dir = Path(packages_dir)
                if not packages_dir.is_absolute():
                    packages_dir = path / packages_dir
                return str(packages_dir)

    # Then try setup.py
    if setup_path.exists():
        import ast

        with open(setup_path, "r") as f:
            setup_contents = f.read()
        setup_ast = ast.parse(setup_contents)
        for node in ast.walk(setup_ast):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "setup":
                for keyword in node.keywords:
                    # Check package_dir argument
                    if keyword.arg == "package_dir":
                        if isinstance(keyword.value, ast.Dict):
                            for i, key in enumerate(keyword.value.keys):
                                if ast.literal_eval(key) == "":
                                    packages_dir = Path(
                                        ast.literal_eval(keyword.value.values[i])
                                    )
                                    if not packages_dir.is_absolute():
                                        packages_dir = path / packages_dir
                                    return str(packages_dir)

    # Fall back to default locations
    package_name = get_package_name(path)
    possible_locations = [
        package_name,
        os.path.join("src", package_name),
        os.path.join("source", package_name),
    ]

    for location in possible_locations:
        candidate = path / location
        if candidate.is_dir():
            return str(candidate)

    raise FileNotFoundError(
        f"Could not find package source directory for '{package_name}' "
        f"in configuration files or in default locations: {', '.join(possible_locations)}"
    )


def get_fitting_font_size(
    text, font_path, max_width, max_height, min_font_size, max_font_size
):
    """
    Find the largest font size that allows the text to fit within the given width and height.
    """
    from PIL import Image, ImageDraw, ImageFont

    font_size = min_font_size  # Start with the smallest font size
    draw = ImageDraw.Draw(Image.new("RGB", (max_width, max_height)))
    last_fitting_size = None

    # Increase font size until it exceeds the boundaries
    while True:
        font = ImageFont.truetype(font_path, font_size)
        text_width, text_height = draw.textbbox((0, 0), text, font=font)[
            2:
        ]  # Get width & height
        if text_width > max_width or text_height > max_height:
            if last_fitting_size is None:
                return min_font_size
            return last_fitting_size
        last_fitting_size = font_size
        if font_size >= max_font_size:
            return max_font_size
        font_size += 1


def text_to_image(text, path, width, height, font_size, font_path):
    from PIL import Image, ImageDraw, ImageFont

    im = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(im)
    font = ImageFont.truetype(font_path, font_size)

    # Compute text position to center it
    text_width, text_height = draw.textbbox((0, 0), text, font=font)[2:]
    if not (text_width <= width and text_height <= height):
        print(
            f"Text does not fit within the image dimensions. Text: {text} Path: {path} Width: {width} Height: {height} Font size: {font_size}"
        )
    text_x = (width - text_width) // 2
    text_y = (height - text_height) // 2

    # Draw text
    draw.text((text_x, text_y), text, fill="black", font=font)

    # Save image
    im.save(path)


def format_timedelta(timedelta_obj):
    """
    Formats a timedelta object as a human-readable string.
    Source: https://stackoverflow.com/questions/538666/format-timedelta-to-string
    """
    seconds = int(timedelta_obj.total_seconds())
    if seconds == 0:
        return "0 seconds"

    sign = ""
    if seconds < 0:
        sign = "-"
        seconds = abs(seconds)
    periods = [
        ("year", 60 * 60 * 24 * 365),
        ("month", 60 * 60 * 24 * 30),
        ("day", 60 * 60 * 24),
        ("hour", 60 * 60),
        ("minute", 60),
        ("second", 1),
    ]

    strings = []
    for period_name, period_seconds in periods:
        if seconds >= period_seconds:
            period_value, seconds = divmod(seconds, period_seconds)
            has_s = "s" if period_value > 1 else ""
            strings.append("%s %s%s" % (period_value, period_name, has_s))

    return f"{sign}{', '.join(strings)}"


def get_experiment_url(app=None, server=None):
    if server:
        if app:
            return f"https://{app}.{server}"
        else:
            raise ValueError("You must provide an app name if you provide a server.")
    else:
        if app:
            return HerokuApp(app).url
        else:
            from .redis import redis_vars

            return redis_vars.get("base_url")


def generate_text_file(path, text="Lorem ipsum"):
    with open(path, "w") as file:
        file.write(text)


def patch_yaspin_jupyter_detection():
    """
    Patch yaspin's is_jupyter detection to be more accurate.
    The default implementation just checks if stdout is not a TTY,
    which is not reliable as there are many cases where stdout might not be a TTY
    that are not Jupyter.
    """
    from yaspin.core import Yaspin

    def is_jupyter() -> bool:
        try:
            import IPython

            return IPython.get_ipython() is not None
        except ImportError:
            return False

    # Monkey patch the method
    Yaspin.is_jupyter = staticmethod(is_jupyter)


@contextlib.contextmanager
def suppress_stdout():
    """
    Context manager to suppress stdout within its context.
    Useful for silencing noisy third-party library output.
    """
    with open(os.devnull, "w") as devnull, contextlib.redirect_stdout(devnull):
        yield


def safe(func):
    """
    Decorator to catch exceptions, log them, and continue execution.

    Parameters
    ----------
    func : Callable
        The function to wrap.

    Returns
    -------
    callable
        The wrapped function.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in {func.__name__}: {e}", exc_info=True)

    return wrapper


def get_authenticated_session(base_url, username=None, password=None):
    """
    Returns a requests.Session authenticated with the dashboard login.

    Handles CSRF tokens automatically by fetching the login page first.

    Parameters
    ----------
    base_url : str
        The root URL of the server (e.g., 'http://localhost:5000').
    username : str, optional
        Dashboard username. If None, will use config.
    password : str, optional
        Dashboard password. If None, will use config.

    Returns
    -------
    session : requests.Session
        Authenticated session for making further requests.

    Raises
    ------
    RuntimeError
        If login fails due to invalid credentials.

    Examples
    --------
    >>> from psynet.utils import get_authenticated_session
    >>> session = get_authenticated_session('http://localhost:5000', 'admin', 'secret')
    >>> response = session.get('http://localhost:5000/bot/1')
    >>> response.raise_for_status()
    """
    config = get_config()
    if username is None:
        username = config.get("dashboard_user")
    if password is None:
        password = config.get("dashboard_password")

    session = requests.Session()

    # Tell the server to close the TCP connection after each request (disable HTTP keep-alive).
    # This should prevent "Connection reset by peer" errors caused by reusing stale keep-alive sockets,
    # which can happen if the server or a proxy drops idle connections
    # (see e.g. https://gitlab.com/PsyNetDev/PsyNet/-/jobs/11132444772)
    #
    # Trade-off: every request opens a new connection, which is less efficient.
    # The other approach would be to to keep connections alive but configure a Retry/Timeout policy
    # (e.g. with requests.adapters.HTTPAdapter + urllib3.util.Retry).
    # However, retry logic might complicate the logs when we get error messages due to server logic.
    # We therefore use `Connection: close` here for simplicity.
    session.headers["Connection"] = "close"

    login_url = f"{base_url}/dashboard/login"

    # Step 1: GET login page to fetch CSRF token
    resp = session.get(login_url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    csrf_input = soup.find("input", {"name": "csrf_token"})
    if not csrf_input or not csrf_input.get("value"):
        raise RuntimeError("Could not find CSRF token in login form.")
    csrf_token = csrf_input["value"]

    # Step 2: POST login form with CSRF token
    login_data = {
        "username": username,
        "password": password,
        "remember_me": "y",
        "csrf_token": csrf_token,
    }
    resp = session.post(login_url, data=login_data)
    resp.raise_for_status()

    # Step 3: Check for an error message in the response
    check_for_login_errors(resp)

    # Step 4: Try to access a protected route to confirm login
    protected_url = f"{base_url}/dashboard/index"
    check = session.get(protected_url)

    if check.status_code != 200 or (
        "csrf_token" in check.text and "username" in check.text
    ):
        raise RuntimeError(
            "Dashboard login failed: could not access protected route after login."
        )

    return session


def check_for_login_errors(response):
    soup = BeautifulSoup(response.text, "html.parser")

    top_level_alert = soup.find("div", class_="alert alert-danger")

    if not top_level_alert:
        return

    top_level_message = top_level_alert.get_text(strip=True)

    # Get any field-level error messages (e.g. under username)
    field_errors = soup.find_all(
        "span", style=lambda value: value and "color: red" in value
    )

    # Collect all messages
    messages = [top_level_message]

    for err in field_errors:
        messages.append(err.get_text(strip=True))

    message = " - ".join(messages)

    raise RuntimeError(f"Dashboard login failed with message: '{message}'. ")


def current_git_branch():
    import subprocess

    return (
        subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], stderr=subprocess.STDOUT
        )
        .strip()
        .decode("utf-8")
    )
