import collections
import datetime
import functools
import getpass
import hashlib
import importlib
import json
import os
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from contextlib import contextmanager, nullcontext
from pathlib import Path
from urllib.parse import urlsplit

import click
import click.shell_completion
import dallinger.command_line.utils
import pexpect
import psutil
import psycopg2
from dallinger import db
from dallinger.command_line.docker_ssh import (
    CONFIGURED_HOSTS,
    option_server,
    remote_postgres,
    resolve_server_option,
)
from dallinger.command_line.utils import verify_id as dallinger_verify_id
from dallinger.config import experiment_available, get_config
from dallinger.deployment_plan import DeploymentPolicyError
from dallinger.heroku.tools import HerokuApp
from dallinger.recruiters import ProlificRecruiter
from dallinger.version import __version__ as dallinger_version
from sqlalchemy.exc import ProgrammingError
from yaspin import yaspin

from psynet import __version__
from psynet.dev.command_line import dev as _dev_command_group
from psynet.runtime_init import ensure_runtime
from psynet.version import (
    check_core_dependency_versions_match_requirements,
    check_installed_dallinger_version_is_recommended,
    is_release_version_specifier,
    specified_version,
)

from . import deployment_info
from .bootstrap_commands import register_bootstrap_commands
from .data import (
    DatabaseInUseError,
    drop_all_db_tables,
    ingest_zip,
    init_db,
    populate_db_from_zip_file,
)
from .experiment_scaffold import (
    _DEPLOYMENT_POLICY_REVIEW_MARKER,
    _clear_deployment_policy_review_marker,
    _deployment_policy_needs_review,
    _remove_obsolete_generated_docker_scripts,
    _remove_obsolete_generated_dockerignore,
    _without_deployment_policy_review,
    dockertag_contents,
    ensure_deployment_policy,
    get_psynet_requirement,
    is_unambiguous_psynet_requirement,
    missing_scaffold_paths_required_for_local_run,
    requirement_includes_experiment_extra,
    scaffold_experiment_directory,
)
from .log import bold
from .lucid import get_lucid_service
from .recruiters import BaseLucidRecruiter, GenericRecruiter, HotAirRecruiter
from .redis import redis_vars
from .serialize import serialize, unserialize
from .server_logs import server_ingress, where_to_read_logs
from .utils import (
    format_bytes,
    get_args,
    get_experiment_url,
    get_logger,
    get_package_name,
    git_repository_available,
    in_python_package,
    is_in_repo_experiment,
    list_experiment_dirs,
    list_isolated_tests,
    load_runtime_server_config,
    make_parents,
    pretty_format_seconds,
    require_exp_directory,
    require_requirements_txt,
    run_subprocess_with_live_output,
)

ensure_runtime()

logger = get_logger()


def _reject_ingress_without_dallinger_support(ctx, param, value):
    """Reject ``--ingress cloudflare`` when Dallinger only supports classic ingress.

    The value is not passed on, because such a Dallinger has no ingress option.
    """
    if value == "cloudflare":
        raise click.UsageError(
            "--ingress cloudflare needs a Dallinger version with Cloudflare "
            "ingress support, which this Dallinger installation does not have. "
            "Install Dallinger from its master branch, or use classic ingress."
        )
    return None


try:
    from dallinger.command_line.docker_ssh import option_ingress
except ImportError:  # pragma: no cover - older Dallinger without Cloudflare ingress
    option_ingress = click.option(
        "--ingress",
        type=click.Choice(["classic", "cloudflare"]),
        default=None,
        callback=_reject_ingress_without_dallinger_support,
        help=(
            "How participants reach the experiment. Cloudflare ingress needs a "
            "newer Dallinger than the one installed."
        ),
    )


_LOCAL_PSYNET_WHEEL_PATTERN = "psynet-*.whl"
_LOCAL_IMAGE_PINS = "local-image-pins.txt"


def _use_local_psynet_option(func):
    return click.option(
        "--use-local-psynet",
        is_flag=True,
        default=False,
        help=(
            "Build the editable PsyNet checkout into the experiment image instead "
            "of installing the PsyNet version in requirements.txt."
        ),
    )(func)


def _use_local_dallinger_option(func):
    return click.option(
        "--use-local-dallinger",
        is_flag=True,
        default=False,
        help=(
            "Build the locally imported Dallinger source into the experiment "
            "image instead of installing the Dallinger version pinned in "
            "requirements.txt or constraints.txt."
        ),
    )(func)


def verify_id(ctx, param, app):
    # Dallinger's docker-ssh deploy allows --app to be omitted, in which case
    # it auto-generates a random app name (e.g., dlgr-a1b2c3d4) and uses the
    # single-app-per-server deployment route.
    # dallinger_verify_id will raise an error if app is None, however.
    # We therefore bypass the validation in this case.
    if app is None:
        return
    return dallinger_verify_id(ctx, param, app)


def _suppress_dallinger_header():
    """
    Stops the Dallinger logo from being printed in the command line.
    """
    dallinger.command_line.header = ""
    dallinger.command_line.utils.header = ""

    # We need to use importlib here to avoid confusion with the command group of the same name
    develop_module = importlib.import_module("dallinger.command_line.develop")
    develop_module.header = ""


_suppress_dallinger_header()


def log(msg, chevrons=True, verbose=True, **kw):
    """Log a message to stdout."""
    if verbose:
        if chevrons:
            click.echo("\n❯❯ " + msg, **kw)
        else:
            click.echo(msg, **kw)


def clean_sys_modules():
    to_clear = [k for k in sys.modules if k.startswith("dallinger_experiment")]
    for key in to_clear:
        del sys.modules[key]


def update_docker_tag():
    Path("Dockertag").write_text(dockertag_contents())


@click.group()
@click.version_option(
    __version__,
    "--version",
    "-v",
    message=f"{__version__} (using Dallinger {dallinger_version})",
)
def psynet():
    pass


psynet.add_command(_dev_command_group)


def reset_console():
    # Console resetting is required because of some nasty issue
    # with the Heroku command-line tool, where killing Heroku processes
    # ends up messing up the console.
    # I've tracked this down to the line
    # os.killpg(os.getpgid(self._process.pid), signal)
    # in heroku/tools.py in Dallinger, but I haven't found a way
    # to stop this line from messing up the terminal.
    # Instead, the present function is designed to sort out the terminal post hoc.
    #
    # Originally I tried the following:
    # os.system("reset")
    # This works but is too aggressive, it resets the whole terminal.
    #
    # However, the following cheeky hack seems to work quite nicely.
    # The 'read' command is a UNIX command that takes an arbitrary input from the user.
    import subprocess

    try:
        # It seems that the timeout must be at least 1.0 s for this to work reliably
        subprocess.call("read NULL", timeout=1.0, shell=True)
    except subprocess.TimeoutExpired:
        pass
    subprocess.call("stty sane", shell=True)


###########
# prepare #
###########
@psynet.command()
@click.option(
    "--archive",
    type=click.Path(exists=True),
    help=(
        "Path to an export archive for re-deployment. Accepts export.zip, "
        "a database/ directory, or an extracted export directory containing database/."
    ),
)
def prepare(archive):
    """
    Prepare the experiment for deployment.
    """
    _prepare(archive)


def _install_archive_template(archive: str, template_path: str) -> None:
    """Normalize an archive into the deploy template zip path.

    Only ``database/<table>.csv`` members are kept, whether the input is a zip
    (``export.zip`` or legacy ``database.zip``) or a directory. This matters
    because the template is deployed to the server, while an export archive
    also contains identifier sidecars and asset bytes that must stay local.
    """
    from .export.path_safety import AmbiguousArchiveLayoutError, UnsafePathError
    from .export.paths import (
        DATABASE_DIRNAME,
        is_zip_path,
        resolve_database_dir,
        table_csv_members,
    )

    archive = os.path.abspath(os.path.expanduser(archive))
    template_path = os.path.abspath(os.path.expanduser(template_path))
    make_parents(template_path)
    fd, temporary_path = tempfile.mkstemp(
        prefix=".database-template-", suffix=".zip", dir=os.path.dirname(template_path)
    )
    os.close(fd)
    try:
        if is_zip_path(archive):
            # Re-pack rather than copy: an export.zip also holds identifier
            # sidecars and asset bytes, and .deploy travels to the server.
            with zipfile.ZipFile(archive) as source:
                try:
                    members = table_csv_members(source)
                except (AmbiguousArchiveLayoutError, UnsafePathError) as exc:
                    raise click.UsageError(str(exc)) from exc
                if not members:
                    raise click.UsageError(
                        f"{archive} contains no table CSVs under database/, so it "
                        "cannot be used as a deployment archive."
                    )
                with zipfile.ZipFile(
                    temporary_path, "w", compression=zipfile.ZIP_DEFLATED
                ) as zf:
                    for member in members:
                        name = os.path.basename(member)
                        zf.writestr(f"{DATABASE_DIRNAME}/{name}", source.read(member))
        else:
            database_dir = resolve_database_dir(archive)
            with zipfile.ZipFile(
                temporary_path, "w", compression=zipfile.ZIP_DEFLATED
            ) as zf:
                for name in sorted(os.listdir(database_dir)):
                    if not name.endswith(".csv"):
                        continue
                    zf.write(
                        os.path.join(database_dir, name),
                        f"{DATABASE_DIRNAME}/{name}",
                    )
        os.replace(temporary_path, template_path)
    finally:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)


def _prepare(archive=None):
    from dallinger import db

    from .experiment import get_experiment

    redis_vars.clear()

    if archive:
        from psynet.experiment import database_template_path

        _install_archive_template(archive, database_template_path)

    db.init_db(drop_all=True)
    experiment = get_experiment()
    experiment.pre_deploy(redeploying_from_archive=archive is not None)
    db.session.flush()
    clean_sys_modules()
    update_docker_tag()

    db.session.commit()


#########
# debug #
#########


def _experiment_variables(connection, echo=False):
    cursor = None
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT vars FROM experiment")
        records = cursor.fetchall()

        if len(records) == 0:
            raise RuntimeError(
                "No rows found in the `experiment` table, maybe the experiment isn't launched yet?"
            )

        assert len(records) == 1

        _vars = unserialize(records[0][0])
        if echo:
            click.echo(serialize(_vars, indent=4))
        return _vars
    except psycopg2.errors.UndefinedTable:
        click.echo(
            "Could not find the table `experiment` on the remote database. This could mean that the experiment isn't "
            "launched yet, or it could mean that the experiment is using an incompatible version of PsyNet."
        )
    finally:
        if cursor is not None:
            cursor.close()


# Experiment variables ####


def _validate_location(ctx, param, value):
    """Click callback that accepts only the supported database locations."""
    allowed = ["local", "heroku", "ssh"]
    if value not in allowed:
        raise click.UsageError(
            f"Invalid location {value}; location must be one of: {', '.join(allowed)}"
        )
    return value


@psynet.command("experiment-variables")
@click.argument("location", default="local")  # , callback=_validate_location)
@click.option(
    "--app",
    default=None,
    help="Name of the experiment app (required for non-local deployments)",
)
@option_server
def experiment_variables(location, app, server):
    """
    Show the variables of the experiment.
    """
    with db_connection(location, app, server) as connection:
        return _experiment_variables(connection, echo=True)


def _read_experiment_variables(location, app=None, server=None):
    """Read an experiment's variables from its database without echoing them.

    For remote locations this opens an SSH tunnel to the experiment's database,
    so callers should avoid it unless they really need the variables.
    """
    with db_connection(location, app, server) as connection:
        return _experiment_variables(connection)


@contextmanager
def db_connection(location, app=None, server=None):
    """
    Get a database connection.
    """
    try:
        connection = None
        with get_db_uri(location, app, server) as db_uri:
            if "postgresql://" in db_uri or "postgres://" in db_uri:
                connection = psycopg2.connect(dsn=db_uri)
            else:
                connection = psycopg2.connect(database=db_uri, user="dallinger")
            yield connection
    except psycopg2.OperationalError as err:
        if "Connection refused" in str(err):
            raise ConnectionError(
                f"Couldn't connect to the experiment database. Are you sure the app name ({app}) is correct? "
                "You can list all valid apps using the following command:\n\tpsynet apps ssh"
            )
        else:
            raise
    finally:
        if connection:
            connection.close()


@contextmanager
def get_db_uri(location, app=None, server=None):
    match location:
        case "local":
            yield db.db_url
        case "heroku" | "docker_heroku":
            if app is None:
                raise click.UsageError("Missing parameter: --app")
            yield HerokuApp(app).db_uri
        case "ssh":
            if app is None:
                raise click.UsageError("Missing parameter: --app")
            server = resolve_server_option(
                click.get_current_context(silent=True), None, server
            )
            server_info = CONFIGURED_HOSTS[server]
            with remote_postgres(server_info, app) as db_uri:
                yield db_uri
        case _:
            raise click.BadParameter(f"Invalid location: {location}")


@psynet.command("db")
@click.argument("location", default="local", callback=_validate_location)
@click.option(
    "--app",
    default=None,
    help="Name of the experiment app (required for non-local deployments)",
)
@click.option(
    "--server",
    default=None,
    help="Name of the remote server (only relevant for ssh deployments)",
)
def _db(location, app, server):
    """
    Get the database connection URI.
    """
    with get_db_uri(location, app, server) as uri:
        click.echo(uri)
        return uri


@psynet.group("debug")
@click.pass_context
@require_exp_directory
def debug(ctx):
    """
    Debug the experiment.
    """
    pass


@psynet.command(
    context_settings=dict(
        allow_extra_args=True,
        ignore_unknown_options=True,
    )
)
@require_exp_directory
def sandbox(*args, **kwargs):
    """
    Sandbox the experiment (has been replaced with `psynet debug heroku`).
    """
    raise click.ClickException(
        "`psynet sandbox` has been replaced with `psynet debug heroku`, please use the latter."
    )


def _run_local(ctx, docker, archive, legacy, no_browsers, mode, context_group):
    """
    Debug the experiment locally (this should normally be your first choice).
    """
    if not ctx:
        from click import Context

        ctx = Context(context_group)

    if legacy and docker:
        raise click.UsageError(
            "It is not possible to select both --legacy and --docker modes simultaneously."
        )

    _pre_launch(ctx, mode=mode, archive=archive, local_=True, docker=docker, app=None)
    _cleanup_before_debug()

    try:
        # Note: PsyNet bypasses Dallinger's deploy-from-archive system and uses its own, so we set archive=None.
        if legacy:
            # Warning: _debug_legacy can fail if the experiment directory is imported before _debug_legacy is called.
            # We therefore need to avoid accessing config variables, calling import_local_experiment, etc.
            # This problem manifests specifically when the experiment contains custom tables.
            _debug_legacy(ctx, archive=None, no_browsers=no_browsers)
        elif docker:
            _debug_docker(ctx, archive=None, no_browsers=no_browsers)
        else:
            _debug_auto_reload(ctx, archive=None, no_browsers=no_browsers)
    finally:
        kill_psynet_worker_processes()
        _cleanup_exp_directory()


def _enable_sql_profile(sql_profile_options, sql_profile_dir):
    """
    Enable SQL profiling for CLI commands and configure output location.

    Parameters
    ----------
    sql_profile_options : str or None
        Options string for ``PSYNET_SQL_PROFILE`` (e.g. ``min_ms=5,top_n=50``).
    sql_profile_dir : str or None
        Parent directory for SQL profile outputs. When provided, a unique run
        subdirectory is created inside it. When ``None``, a temporary directory
        is created.

    Returns
    -------
    profile_dir : str
        Directory where SQL profile JSON files will be written.
    keep_profile_dir : bool
        ``True`` when the directory was explicitly provided, otherwise ``False``.
    """
    if sql_profile_options:
        os.environ["PSYNET_SQL_PROFILE"] = sql_profile_options
    elif not os.getenv("PSYNET_SQL_PROFILE"):
        os.environ["PSYNET_SQL_PROFILE"] = "1"

    os.environ["PSYNET_SQL_PROFILE_SILENT"] = "1"

    profile_dir, keep_profile_dir = _create_sql_profile_run_dir(sql_profile_dir)
    os.makedirs(profile_dir, exist_ok=True)
    os.environ["PSYNET_SQL_PROFILE_DIR"] = profile_dir
    return profile_dir, keep_profile_dir


def _create_sql_profile_run_dir(sql_profile_dir):
    """Create the SQL profiling output directory for a single command run."""
    if sql_profile_dir:
        os.makedirs(sql_profile_dir, exist_ok=True)
        return tempfile.mkdtemp(prefix="run-", dir=sql_profile_dir), True
    return tempfile.mkdtemp(prefix="psynet-sql-profile-"), False


def _is_ubuntu() -> bool:
    """Return True if the current OS is Ubuntu (or an Ubuntu derivative)."""
    try:
        with open("/etc/os-release") as f:
            return "ubuntu" in f.read().lower()
    except Exception:
        return False


def _open_in_browser(url: str) -> None:
    """Open *url* in a browser, preferring Google Chrome on Ubuntu for local files.

    Snap-confined browsers (e.g. Chromium on Ubuntu) cannot read ``file://``
    URLs outside their sandbox, so on Ubuntu we try non-snap Google Chrome
    first.  Falls back to ``click.launch()`` and finally prints the URL for
    the user to open manually.
    """
    if _is_ubuntu():
        # On Ubuntu the default browser is often snap-confined Chromium which
        # silently fails to read file:// URLs (ERR_FILE_NOT_FOUND).  Use
        # non-snap Google Chrome instead.
        for name in ("google-chrome", "google-chrome-stable"):
            path = shutil.which(name)
            if path:
                try:
                    subprocess.Popen(
                        [path, url],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    return
                except Exception:
                    continue
    else:
        try:
            click.launch(url)
            return
        except Exception:
            pass

    click.echo(
        "Could not open the SQL profile report automatically. "
        "Please open the file URL shown above in your browser."
    )


def _print_sql_profile_aggregation(profile_dir, *, formats, open_html, show_dir):
    """
    Print aggregated SQL profiling output for all processes.

    Parameters
    ----------
    profile_dir : str
        Directory containing per-process SQL profile JSON files.
    formats : set[str]
        Output formats to generate (e.g. ``{"html", "text"}``).
    open_html : bool
        Whether to attempt opening the HTML report in a browser.
    show_dir : bool
        Whether to print the location of the raw profile files.
    """
    from psynet.sqlalchemy_profiling import (
        aggregate_sqlalchemy_profiles,
        format_aggregated_html,
        format_aggregated_profile,
        parse_env_settings,
    )

    settings = parse_env_settings(os.getenv("PSYNET_SQL_PROFILE"))
    options = settings.get("options", {})
    top_n = int(options.get("top_n", 20))
    commit_top_n = int(options.get("commit_top_n", top_n))
    aggregated = aggregate_sqlalchemy_profiles(profile_dir)
    if "text" in formats:
        click.echo("")
        click.echo("Aggregated SQLAlchemy profile (all processes):")
        click.echo(
            format_aggregated_profile(
                aggregated, top_n=top_n, commit_top_n=commit_top_n
            )
        )
    if "json" in formats:
        json_path = os.path.join(profile_dir, "sql-profile-aggregated.json")
        with open(json_path, "w", encoding="utf-8") as handle:
            json.dump(aggregated, handle, indent=2, sort_keys=True)
        click.echo(f"SQL profile JSON: {json_path}")
    if "html" in formats:
        html_path = os.path.join(profile_dir, "sql-profile-report.html")
        with open(html_path, "w", encoding="utf-8") as handle:
            handle.write(
                format_aggregated_html(
                    aggregated, top_n=top_n, commit_top_n=commit_top_n
                )
            )
        click.echo(f"SQL profile report: {html_path}")
        if open_html:
            _open_in_browser(f"file://{html_path}")
    if show_dir:
        click.echo(f"Raw SQL profile files saved to: {profile_dir}")


_sql_profile_options = [
    click.option(
        "--sql-profile",
        is_flag=True,
        help="Enable SQL profiling and aggregate results across processes.",
    ),
    click.option(
        "--sql-profile-options",
        default=None,
        help="Options passed to PSYNET_SQL_PROFILE (e.g. 'min_ms=5,top_n=50').",
    ),
    click.option(
        "--sql-profile-dir",
        default=None,
        help="Parent directory for SQL profile outputs (creates a unique run subdirectory).",
    ),
    click.option(
        "--sql-profile-no-open",
        is_flag=True,
        help="Do not auto-open the SQL profile report in a browser.",
    ),
    click.option(
        "--sql-profile-format",
        default="html",
        help=("Comma-separated outputs: html,text,json,none (default: html)."),
    ),
]


def _add_sql_profile_options(func):
    for option in reversed(_sql_profile_options):
        func = option(func)
    return func


def _parse_sql_profile_formats(value: str):
    parts = {part.strip().lower() for part in (value or "").split(",") if part}
    if not parts:
        parts = {"html"}
    if "all" in parts:
        parts = {"html", "text", "json"}
    if "none" in parts:
        return set()
    unknown = parts - {"html", "text", "json"}
    if unknown:
        raise click.UsageError(
            "Unknown --sql-profile-format values: " + ", ".join(sorted(unknown))
        )
    return parts


def _should_open_sql_profile(no_open: bool) -> bool:
    if no_open:
        return False
    if os.getenv("CI"):
        return False
    return sys.stdout.isatty()


def sql_profiled_command(func):
    """
    Wrap a Click command to enable aggregated SQL profiling.

    Parameters
    ----------
    func : callable
        Command function with ``sql_profile`` keyword arguments.

    Returns
    -------
    callable
        Wrapped command that enables profiling and prints aggregation.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        profile_dir = None
        keep_profile_dir = False
        show_dir = False
        formats = set()
        open_html = False
        try:
            if kwargs.get("sql_profile"):
                formats = _parse_sql_profile_formats(kwargs.get("sql_profile_format"))
                profile_dir, keep_profile_dir = _enable_sql_profile(
                    kwargs.get("sql_profile_options"), kwargs.get("sql_profile_dir")
                )
                show_dir = kwargs.get("sql_profile_dir") is not None
                open_html = _should_open_sql_profile(
                    kwargs.get("sql_profile_no_open", False)
                )
                if "html" not in formats:
                    open_html = False
                if formats.intersection({"html", "json"}):
                    keep_profile_dir = True
            return func(*args, **kwargs)
        finally:
            if profile_dir:
                if formats:
                    _print_sql_profile_aggregation(
                        profile_dir,
                        formats=formats,
                        open_html=open_html,
                        show_dir=show_dir,
                    )
                if not keep_profile_dir:
                    shutil.rmtree(profile_dir, ignore_errors=True)

    return wrapper


@debug.command("local")
@click.option("--docker", is_flag=True, help="Docker mode.")
@click.option("--archive", default=None, help="Optional path to an experiment archive.")
@click.option(
    "--legacy",
    is_flag=True,
    help="Use gunicorn instead of Flask auto-reload (default four worker processes).",
)
@click.option("--no-browsers", is_flag=True, help="Skip opening browsers.")
@_add_sql_profile_options
@click.pass_context
@sql_profiled_command
def debug__local(
    ctx,
    docker,
    archive,
    legacy,
    no_browsers,
    sql_profile,
    sql_profile_options,
    sql_profile_dir,
    sql_profile_format,
    sql_profile_no_open,
):
    """
    Debug the experiment locally (this should normally be your first choice).
    """
    _run_local(
        ctx,
        docker,
        archive,
        legacy,
        no_browsers,
        mode="debug",
        context_group=debug,
    )


def run_prepare_in_subprocess():
    # `psynet prepare` runs `import_local_experiment`, which registers SQLAlchemy tables,
    # which can create a problem for subsequent `dallinger debug`.
    # To avoid problems, we therefore run `psynet prepare` in a subprocess.
    prepare_cmd = "psynet prepare"
    run_subprocess_with_live_output(prepare_cmd)


def _reset_local_data(*, remote, assume_yes=False):
    """Clear this computer's Redis and stop local servers before ``prepare``.

    Launches build the experiment's starting database with ``prepare`` on this
    computer, which drops every table, so leftover ``dallinger_heroku_*``
    backends must be stopped first. Chrome windows are left alone so a remote
    launch does not close the author's browser.

    Parameters
    ----------
    remote : bool
        Whether the experiment will run elsewhere. Remote launches first say
        what they reset, and ask before resetting data that is in use.
    assume_yes : bool
        Reset data that is in use without asking.
    """
    if remote:
        _confirm_local_data_reset(assume_yes)
    redis_vars.clear()
    kill_psynet_worker_processes()


def _confirm_local_data_reset(assume_yes):
    """Describe the local reset, and ask first if the local data looks in use."""
    from .data import _format_other_database_clients
    from .db import list_other_database_clients
    from .services import _is_interactive, _redis_url

    database = _url_without_password(_current_database_url())
    redis = _url_without_password(_redis_url())
    click.echo(
        "This launch builds the experiment's starting database on this computer. "
        "To do so, it will:\n"
        f"  - drop every table in the local database {database}\n"
        f"  - delete every key in local Redis {redis}\n"
        "  - stop the local PsyNet worker, clock and legacy web server processes "
        "using that database\n"
        "Other programs connected to the database or Redis, such as the web "
        "server of a running psynet debug local, Docker containers or another "
        "experiment, keep running and should be stopped or restarted."
    )
    in_use = []
    n_workers = len(list_psynet_worker_processes())
    if n_workers:
        in_use.append(
            f"{n_workers} local PsyNet server process(es) are using this database."
        )
    clients = list_other_database_clients()
    if clients:
        in_use.append(
            "Other clients are connected to the local database: "
            f"{_format_other_database_clients(clients)}."
        )
    n_redis_clients = _count_other_redis_clients()
    if n_redis_clients is None:
        in_use.append("Couldn't list the clients of local Redis, so it may be in use.")
    elif n_redis_clients:
        in_use.append(
            f"{n_redis_clients} other client(s) are connected to local Redis."
        )
    if not in_use:
        return
    click.echo("\n".join(in_use))
    if assume_yes:
        return
    if not _is_interactive():
        raise click.ClickException(
            "Refusing to reset local data in a non-interactive session. "
            "Re-run with --yes to reset it anyway, or stop the local experiment, "
            "or point DATABASE_URL and REDIS_URL at a scratch database."
        )
    click.confirm("Reset this local data and continue?", default=False, abort=True)


def _count_other_redis_clients():
    """Return the number of connections to local Redis from other programs.

    Keys left behind by a stopped experiment don't count, so a launch after
    ``psynet debug local`` has stopped doesn't ask. This process's pooled
    connections are closed first, so only the connection running the query
    belongs to it. Returns ``None`` if Redis refuses ``CLIENT LIST``, for
    example because of an ACL or a renamed command.
    """
    from dallinger.db import redis_conn
    from redis.exceptions import ResponseError

    redis_conn.connection_pool.disconnect()
    pipe = redis_conn.pipeline(transaction=False)
    pipe.client_id()
    pipe.client_list()
    try:
        own_id, clients = pipe.execute()
    except ResponseError as error:
        logger.warning("Couldn't list local Redis clients: %s", error)
        return None
    return sum(1 for client in clients if int(client["id"]) != own_id)


def _url_without_password(url):
    """Return ``url`` with any password removed, for display."""
    parts = urlsplit(url)
    if parts.password is None:
        return url
    host = parts.netloc.rpartition("@")[2]
    netloc = f"{parts.username}@{host}" if parts.username else host
    return parts._replace(netloc=netloc).geturl()


def _prepare_image_for_update():
    """Prepare the image for ``--update``; the running app keeps its database."""
    from .experiment import get_experiment

    get_experiment().pre_deploy(update=True)
    clean_sys_modules()
    update_docker_tag()


def _stop_leftover_debug_processes():
    """Stop leftover local debug workers and Chrome windows."""
    kill_psynet_worker_processes()
    if not os.getenv("KEEP_OLD_CHROME_WINDOWS_IN_DEBUG_MODE"):
        kill_psynet_chrome_processes()


def _cleanup_before_debug():
    _stop_leftover_debug_processes()

    # This is important for resetting the state before _debug_legacy;
    # otherwise `dallinger verify` throws an error.
    clean_sys_modules()  # Unimports the PsyNet experiment

    drop_all_db_tables()


def _cleanup_exp_directory():
    """
    Cleans up temporary files that are sometimes left behind by the experiment.
    """
    for file in ["server.log", "logs.jsonl"]:
        try:
            os.remove(file)
        except FileNotFoundError:
            pass

    for dir in [".deploy"]:
        try:
            shutil.rmtree(dir)
        except FileNotFoundError:
            pass


def run_pre_auto_reload_checks():
    config = get_config()
    if not config.ready:
        config.load()

    from dallinger.utils import develop_target_path

    from .experiment_scaffold import get_editable_psynet_source

    _develop_path = str(develop_target_path(config))
    if "." in _develop_path:
        raise ValueError(
            f"The target path for your app's temporary development directory ({_develop_path}) "
            "contains a period ('.'). Unfortunately Dallinger doesn't support this."
            "You should set a revised path in your .dallingerconfig file. "
            "We recommend: dallinger_develop_directory = /tmp/dallinger_develop"
        )

    if get_editable_psynet_source() is not None:
        root_dir = str(psynet_dir())
        root_basename = os.path.basename(root_dir)
        if root_basename == "psynet" and root_dir in os.getcwd():
            raise RuntimeError(
                "If running demo experiments inside your PsyNet installation, "
                "you will have to rename your PsyNet folder to something other than 'psynet', "
                "for example 'psynet-package'. Otherwise Python gets confused. Sorry about that! "
                f"The PsyNet folder you need to rename is located at {psynet_dir()}. "
                "After renaming it you will need to reinstall PsyNet by rerunning "
                "pip install -e . inside that directory."
            )


# Dallinger ``web_processes`` (formerly ``threads``) is gunicorn worker processes. Last-arrival GET
# /timeline occupies one process while each waiting partner POSTs hold-resume.
# A group of size *n* therefore wants *n* workers at the wake, or extra waiters
# sit in the listen queue. Concurrent last arrivals occupy two GET workers at
# once. Blocking SQL on a gevent worker also starves that worker's Redis listen
# greenlet, so Playwright hold tests use *n* + 2: one spare keeps a waiter
# subscribe off the last-arrival SQL worker, and the second spare covers the
# overlapping GET. That is closer to deploy (``web_processes = auto``) than a single
# worker. One worker saved ~1s of startup in 2022; local gunicorn does not pay
# a Heroku dyno cost, and performance-test / Playwright duration checks need
# overlap rather than serialized queueing. The default covers the largest
# stacked-hold group in that suite (four) for interactive debug; tests override
# with session count plus two.
LEGACY_DEBUG_GUNICORN_THREADS = "4"
LEGACY_DEBUG_GUNICORN_THREADS_ENV = "PSYNET_LEGACY_DEBUG_GUNICORN_THREADS"


def _legacy_debug_gunicorn_threads():
    """Return gunicorn worker processes for ``psynet debug --legacy``."""
    raw = os.environ.get(LEGACY_DEBUG_GUNICORN_THREADS_ENV)
    if raw is None or str(raw).strip() == "":
        return LEGACY_DEBUG_GUNICORN_THREADS
    try:
        workers = int(raw)
    except ValueError as err:
        raise click.UsageError(
            f"{LEGACY_DEBUG_GUNICORN_THREADS_ENV} must be a positive integer, "
            f"got {raw!r}."
        ) from err
    if workers < 1:
        raise click.UsageError(
            f"{LEGACY_DEBUG_GUNICORN_THREADS_ENV} must be a positive integer, "
            f"got {raw!r}."
        )
    return str(workers)


def _debug_legacy(ctx, archive, no_browsers):
    if archive:
        raise click.UsageError(
            "Legacy debug mode doesn't currently support loading from archive."
        )

    from dallinger.command_line import debug as dallinger_debug

    db.session.commit()

    try:
        ctx.invoke(
            dallinger_debug,
            verbose=True,
            bot=False,
            proxy=None,
            no_browsers=no_browsers,
            exp_config={"web_processes": _legacy_debug_gunicorn_threads()},
        )
    finally:
        db.session.commit()
        reset_console()


def _debug_docker(ctx, archive, no_browsers):
    from dallinger.command_line.docker import debug as dallinger_debug

    if archive:
        raise click.UsageError(
            "`psynet debug` with Docker doesn't currently support loading from archive."
        )

    db.session.commit()

    try:
        ctx.invoke(
            dallinger_debug,
            verbose=True,
            bot=False,
            proxy=None,
            no_browsers=no_browsers,
        )
    finally:
        db.session.commit()
        reset_console()


def launch_app_without_browsers(port, **kwargs):
    """Launch the development app without opening browsers.

    Stands in for Dallinger's ``launch_app_and_open_browser`` RQ job in
    auto-reload ``--no-browsers`` runs. Dallinger's job discards the launch
    response and logs into the dashboard through the browser it opens, so this
    job prints the recruitment message and the dashboard credentials instead.
    It must stay importable by module path because RQ workers resolve it that way.
    """
    from dallinger.command_line.develop import BASE_URL
    from dallinger.deployment import handle_launch_data

    launch_data = handle_launch_data(
        BASE_URL.format(port) + "launch", error=log, delay=1.0, context="local"
    )
    if launch_data.get("recruitment_msg"):
        log(launch_data["recruitment_msg"], chevrons=False)

    config = get_config()
    if not config.ready:
        config.load()
    log(f"Experiment dashboard: {BASE_URL.format(port)}dashboard")
    log(
        f"Dashboard user: {config.get('dashboard_user')} "
        f"password: {config.get('dashboard_password')}",
        chevrons=False,
    )


@contextmanager
def _stop_child_processes_on_signal():
    """Terminate descendant processes when this process is signalled.

    Ctrl-C in a terminal reaches the whole foreground process group, but a
    signal sent to the ``psynet`` PID alone would otherwise leave the
    ``flask run`` server started by ``dallinger develop debug`` running.
    Must be entered from the main thread.
    """

    def handler(signum, frame):
        children = psutil.Process().children(recursive=True)
        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        psutil.wait_procs(children, timeout=5)
        if signum == signal.SIGINT:
            raise KeyboardInterrupt
        raise SystemExit(128 + signum)

    signals = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    previous = {sig: signal.signal(sig, handler) for sig in signals}
    try:
        yield
    finally:
        for sig, previous_handler in previous.items():
            signal.signal(sig, previous_handler)


@contextmanager
def _exit_on_sigterm():
    """Raise ``SystemExit(128 + SIGTERM)`` on SIGTERM, so that ``finally`` blocks clean up.

    Must be entered from the main thread.
    """

    def handler(signum, frame):
        raise SystemExit(128 + signum)

    previous = signal.signal(signal.SIGTERM, handler)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def _debug_auto_reload(ctx, archive, no_browsers):
    from dallinger.command_line.develop import debug as dallinger_debug
    from dallinger.deployment import DevelopmentDeployment

    develop_module = importlib.import_module("dallinger.command_line.develop")
    launch_job = develop_module.launch_app_and_open_browser
    port = _local_base_port()
    # Dallinger's development server runs `flask run`, which reads this variable.
    os.environ["FLASK_RUN_PORT"] = str(port)
    debug_kwargs = {"skip_flask": False, "port": port}
    if no_browsers:
        develop_module.launch_app_and_open_browser = launch_app_without_browsers

    try:
        run_pre_auto_reload_checks()

        DevelopmentDeployment.archive = archive
        patch_dallinger_develop()

        develop_module.header = ""

        try:
            with _stop_child_processes_on_signal():
                ctx.invoke(dallinger_debug, **debug_kwargs)
        finally:
            db.session.commit()
            reset_console()
    finally:
        develop_module.launch_app_and_open_browser = launch_job


def patch_dallinger_develop():
    from dallinger.deployment import DevelopmentDeployment

    if not (
        hasattr(DevelopmentDeployment, "patched") and DevelopmentDeployment.patched
    ):
        old_run = DevelopmentDeployment.run

        def new_run(self):
            old_run(self)
            if hasattr(self, "archive") and self.archive:
                archive_path = os.path.abspath(self.archive)
                if not os.path.exists(archive_path):
                    raise click.BadParameter(
                        'Experiment archive "{}" does not exist.'.format(archive_path)
                    )
                init_db()
                ingest_zip(archive_path, engine=db.engine)

        DevelopmentDeployment.run = new_run
        DevelopmentDeployment.patched = True


patch_dallinger_develop()


def safely_kill_process(p):
    try:
        p.kill()
    except psutil.NoSuchProcess:
        pass


def kill_psynet_worker_processes():
    processes = list_psynet_worker_processes()
    if not processes:
        return
    pids = []
    for process in processes:
        try:
            pids.append(str(process.pid))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    pid_list = ", ".join(pids) if pids else "unknown"
    logger.warning(
        "Stopping %s leftover local PsyNet worker process(es) (pids %s). "
        "Launch paths including remote deploy do this so a stale "
        "dallinger_heroku_* backend cannot hold this Postgres database.",
        len(processes),
        pid_list,
    )
    log(
        f"Found {len(processes)} remaining PsyNet worker process(es) "
        f"(pids {pid_list}), terminating them now."
    )
    for p in processes:
        safely_kill_process(p)


def kill_psynet_chrome_processes():
    processes = list_psynet_chrome_processes()
    if len(processes) > 0:
        logger.debug(
            f"Found {len(processes)} remaining PsyNet Chrome process(es), terminating them now."
        )
    for p in processes:
        safely_kill_process(p)


def kill_chromedriver_processes():
    processes = list_chromedriver_processes()
    if len(processes) > 0:
        logger.debug(
            f"Found {len(processes)} chromedriver processes, terminating them now."
        )
    for p in processes:
        safely_kill_process(p)


def list_psynet_chrome_processes():
    return [p for p in psutil.process_iter() if is_psynet_chrome_process(p)]


def is_psynet_chrome_process(process):
    """
    Return whether ``process`` is a Chrome window this shell's local run opened.

    Matches debug windows pointed at this run's port and test-driver browsers
    whose profile carries this run's :func:`psynet_browser_prefix`, so cleanup
    leaves browsers belonging to other local experiments alone.
    """
    local_url = re.compile(rf"(localhost|127\.0\.0\.1):{_local_base_port()}(?!\d)")
    profile_prefix = psynet_browser_prefix("chrome")
    try:
        if "chrome" in process.name().lower():
            for cmd in process.cmdline():
                if local_url.search(cmd):
                    return True
                if "--user-data-dir=" in cmd and profile_prefix in cmd:
                    return True
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        pass

    return False


def _local_base_port():
    """Return the port of this shell's local server (Dallinger's ``base_port``)."""
    config = get_config()
    if config.ready:
        return config.get("base_port")
    return int(os.environ.get("base_port", 5000))


def psynet_browser_prefix(kind):
    """
    Return the temporary-file prefix for browsers started by this shell's tests.

    ``kind`` is ``"chrome"`` (profile directory) or ``"chromedriver"`` (log file).
    The prefix includes a hash of ``DATABASE_URL``, which identifies a local
    run in the same way as :func:`uses_current_database`.
    """
    tag = hashlib.sha1(_current_database_url().encode()).hexdigest()[:8]
    return f"psynet-{kind}-{tag}-"


def _current_database_url():
    from dallinger.db import corrected_db_url, db_url_default

    return corrected_db_url(os.environ.get("DATABASE_URL", db_url_default))


def uses_current_database(process):
    """
    Return whether ``process`` was started with this shell's ``DATABASE_URL``.

    Local servers inherit ``DATABASE_URL`` from the command that launched them,
    so this distinguishes this experiment's leftovers from other local
    experiments on the same machine. Processes whose environment can't be read
    are treated as someone else's.
    """
    from dallinger.db import corrected_db_url, db_url_default

    try:
        url = process.environ().get("DATABASE_URL", db_url_default)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False
    return corrected_db_url(url) == _current_database_url()


def list_psynet_worker_processes():
    """List local ``dallinger_heroku_*`` workers that use this shell's database."""
    return [
        p
        for p in psutil.process_iter()
        if is_psynet_worker_process(p) and uses_current_database(p)
    ]


def is_psynet_worker_process(process):
    """Return whether ``process`` is a local Dallinger web or worker process."""
    try:
        # This version catches processes in Linux
        if process.name().startswith("dallinger_herok"):
            return True
        # This version catches process in MacOS
        if "python" in process.name().lower():
            return any(
                Path(argument).name.startswith("dallinger_heroku_")
                for argument in process.cmdline()[:2]
            )
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    return False


def list_chromedriver_processes():
    return [p for p in psutil.process_iter() if is_chromedriver_process(p)]


def is_chromedriver_process(process):
    """Return whether ``process`` is a chromedriver started by this shell's tests."""
    prefix = psynet_browser_prefix("chromedriver")
    try:
        return "chromedriver" in process.name().lower() and any(
            prefix in part for part in process.cmdline()
        )
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False


###########
# run bot #
###########


def _run_bot(time_factor, dashboard_user, dashboard_password):
    from .experiment import get_experiment

    os.environ["PASSTHROUGH_ERRORS"] = "True"

    import logging

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    config = load_runtime_server_config()
    if dashboard_user is not None:
        config.set("dashboard_user", dashboard_user)
    if dashboard_password is not None:
        config.set("dashboard_password", dashboard_password)

    from .bot import BotDriver

    exp = get_experiment()
    exp.run_bot(BotDriver(), time_factor=time_factor)


@psynet.command()
@click.option(
    "--time-factor",
    type=float,
    default=0.0,
    help="Multiply the timings in time_estimate by this factor. When equal to zero (the default value), the bot will run through the experiment as fast as possible.",
)
@click.option(
    "--dashboard-user",
    help="The username for the experiment's dashboard (used for bot authentication).",
)
@click.option(
    "--dashboard-password",
    help="The password for the experiment's dashboard (used for bot authentication).",
)
@click.pass_context
@require_exp_directory
def run_bot(ctx, time_factor=0.0, dashboard_user=None, dashboard_password=None):
    """
    Run a bot through the local version of the experiment.
    Prior to running this command you must spin up a local experiment, for example
    by running ``psynet debug local``. You can then call ``psynet run-bot``
    multiple times to simulate multiple bots being run through the experiment.
    """
    _run_bot(time_factor, dashboard_user, dashboard_password)


##############
# pre deploy #
##############
def run_pre_checks_deploy(local_, recruiter):
    check_psynet_requirement_is_unambiguous()
    check_psynet_requirement_includes_experiment_extra()
    check_core_dependency_versions_match_requirements()
    if not local_:
        confirm_deploying_development_psynet()

    if local_ and not isinstance(recruiter, (GenericRecruiter, HotAirRecruiter)):
        raise click.UsageError(
            "``psynet deploy local`` currently only supports the 'generic' recruiter. "
            "Set recruiter = generic in your experiment config, or deploy to a remote server instead "
            "(e.g. ``psynet deploy ssh``)."
        )


def _abort_if_app_exists(server, app, *, update=False):
    """Refuse to create an app that is already on the server.

    Parameters
    ----------
    server : str
        SSH server name.
    app : str or None
        Experiment app name.
    update : bool
        When true, an existing app is the one being replaced.
    """
    if update or not app:
        return

    from dallinger.command_line.docker_ssh import get_apps

    apps = get_apps(server)
    existing_apps = {entry.name for entry in apps}
    if app in existing_apps:
        click.echo(
            "\n".join(
                [
                    f"App with name {app} already exists: found on server. Aborting.",
                    "Use a different name or destroy the current app.",
                ]
            )
        )
        raise click.Abort


_option_ssh_update = click.option(
    "--update",
    is_flag=True,
    help="Rebuild a running app in place, keeping its database and skipping launch.",
)

_option_yes_reset_local_data = click.option(
    "--yes",
    "-y",
    "assume_yes",
    is_flag=True,
    help=(
        "Reset the local database and Redis without asking, even if they look "
        "in use. Other prompts, such as starting local services, still ask."
    ),
)


_ssh_deployment_options = [
    option_server,
    click.option(
        "--dns-host",
        help="DNS name to use. Must resolve all its subdomains to the IP address specified as ssh host",
    ),
    option_ingress,
]


def _add_ssh_deployment_options(command):
    """Attach the options that say where and how an SSH app is deployed.

    ``debug ssh``, ``deploy ssh`` and ``performance-test ssh``, which deploys
    its own apps, share them.
    """
    for option in reversed(_ssh_deployment_options):
        command = option(command)
    return command


_SSH_COMMAND_FOR_MODE = {"sandbox": "psynet debug ssh", "live": "psynet deploy ssh"}


def _ssh_executor(server, app=None):
    """Return a Dallinger SSH ``Executor`` connected to a configured server."""
    from dallinger.command_line.docker_ssh import Executor

    server_info = CONFIGURED_HOSTS[server]
    return Executor(server_info["host"], user=server_info.get("user"), app=app)


def _read_running_deployment_info(server, app):
    """Return the ``deployment_info`` baked into a running SSH app's image.

    A stopped ``web``, as in a hibernated app, is read from a one-off container.
    """
    executor = _ssh_executor(server, app=app)
    compose = f"docker compose -f ~/dallinger/{shlex.quote(app)}/docker-compose.yml"
    path = f"/experiment/{deployment_info.path}"
    output = executor.run(
        f"{compose} exec -T web cat {path} 2>/dev/null "
        f"|| {compose} run --rm --no-deps -T web cat {path}",
        raise_=False,
    )
    text = output or ""
    return deployment_info.loads(text[text.find("{") : text.rfind("}") + 1])


def _check_ssh_update(server, app, mode, confirm=True):
    """Check and confirm an in-place SSH update, keeping the app's identity.

    Parameters
    ----------
    server : str
        SSH server name.
    app : str
        Experiment app name.
    mode : str
        ``"sandbox"`` for ``debug ssh`` or ``"live"`` for ``deploy ssh``.
    confirm : bool
        Ask the user to confirm the update first.
    """
    try:
        running = _read_running_deployment_info(server, app)
        identity = {key: running[key] for key in ("deployment_id", "secret", "mode")}
    except Exception as err:
        raise click.ClickException(
            f"Could not read the deployment ID and secret of {app} on {server} "
            f"({err!r}). --update needs them to keep the app's records together."
        )
    if identity["mode"] != mode:
        original = _SSH_COMMAND_FOR_MODE.get(identity["mode"], identity["mode"])
        raise click.UsageError(
            f"{app} was created with `{original}`. Update it with "
            f"`{original} --app {app} --update`."
        )
    if confirm and not user_confirms(
        f"This rebuilds and restarts {app} on {server}, keeping its database. "
        "Participants may see a short interruption. New assets are not deposited, "
        "and networks and pre-deploy routines are not run again. Don't change the "
        "timeline while participants are still taking part. Continue?",
        default=mode != "live",
    ):
        raise click.Abort
    deployment_info.write(
        deployment_id=identity["deployment_id"],
        secret=identity["secret"],
        keep_deployment_id=True,
    )


##########
# deploy #
##########


def _pre_launch(
    ctx,
    *,
    mode,
    archive,
    local_,
    ssh=False,
    docker=False,
    heroku=False,
    server=None,
    app=None,
    update=False,
    local_packages=(),
    assume_yes=False,
    performance_test_app=False,
    ingress=None,
):
    """Check and prepare the experiment directory before a launch.

    ``performance_test_app`` marks an app that ``psynet performance-test
    ssh`` deploys for bots: an update isn't confirmed first, and the
    experiment needn't have a consent page. ``ingress`` is the SSH deploy's
    ``--ingress`` option; the resolved ingress is recorded in ``deployment_info``.
    """
    from .experiment import get_experiment

    if docker:
        _reject_leftover_local_image_files()

    # Scaffold/git checks before Redis so missing-boilerplate guidance is visible
    # even when Redis is not running.
    _check_experiment_directory(mode, require_git_commit=not local_)
    _check_local_image_packages(local_packages)

    from .services import ensure_local_services

    # All launch paths (local, SSH, Heroku, Docker) run ``prepare`` / Redis
    # helpers on this machine before any remote packaging, so local Postgres
    # and Redis are required here even when the experiment ultimately runs
    # elsewhere.
    ensure_local_services(assume_yes=False, strict=True, remote_launch=not local_)

    deployment_info.init(
        redeploying_from_archive=archive is not None,
        mode=mode,
        is_local_deployment=local_,
        is_ssh_deployment=ssh,
        server=server,
        app=app,
    )

    if ssh:
        server_info = CONFIGURED_HOSTS[server]

        ssh_host = server_info["host"]
        ssh_user = server_info.get("user")

        deployment_info.write(
            ssh_host=ssh_host,
            ssh_user=ssh_user,
            ingress=server_ingress(server_info, ingress),
        )

        from dallinger.command_line.docker_ssh import ensure_remote_host_in_known_hosts

        ensure_remote_host_in_known_hosts(ssh_host, ssh_user)
        _abort_if_app_exists(server, app, update=update)
        if update:
            _check_ssh_update(server, app, mode, confirm=not performance_test_app)

    run_pre_checks(
        mode,
        local_,
        heroku,
        docker,
        app,
        local_packages,
        check_consents=not performance_test_app,
    )

    # An --update only rebuilds the image, so it leaves local data alone.
    if not update:
        _reset_local_data(remote=not local_, assume_yes=assume_yes)

    if os.environ.get("DALLINGER_SOURCE"):
        os.environ.pop("DALLINGER_NO_EGG_BUILD", None)
    else:
        os.environ["DALLINGER_NO_EGG_BUILD"] = "1"

    if is_in_repo_experiment():
        # In-repo demos/tests use PsyNet's shared development .venv; do not let
        # Dallinger invent a per-demo constraints.txt from PyPI.
        os.environ["SKIP_DEPENDENCY_CHECK"] = "1"
    elif docker and Path("Dockerfile").exists():
        # Tell Dallinger not to rebuild constraints.txt, because we'll manage
        # this within the Docker image.
        os.environ["SKIP_DEPENDENCY_CHECK"] = "1"

    experiment = get_experiment()
    experiment.update_deployment_id()

    config = get_config()
    for key in ("performance_test_app", "debug_ssh_app"):
        if mode == "live" and config.get(key, False):
            raise click.UsageError(
                f"{key} is set, which declares that the app's data is disposable. "
                "Remove it from the config to deploy in live mode."
            )
    deployment_info.write(locale=config.get("locale", "en"))

    if config.get("check_dallinger_version"):
        check_installed_dallinger_version_is_recommended()

    if update:
        _prepare_image_for_update()
    else:
        ctx.invoke(prepare, archive=archive)

    _forget_tables_defined_in_experiment_directory()

    if heroku:
        # Unimports the PsyNet experiment, because Dallinger will want to start from scratch when using Heroku.
        # We don't unimport it in other cases because reloading the experiment produces an unnecessary time overhead.
        clean_sys_modules()


def _forget_tables_defined_in_experiment_directory():
    # We need to instruct SQLAlchemy to forget tables defined in the experiment directory,
    # because otherwise SQLAlchemy will get confused and throw errors when we run subsequent commands
    # that import the same experiment from other locations (e.g. /tmp/dallinger_develop).

    from dallinger.db import Base

    tables_defined_in_experiment_directory = [
        mapper.class_.__tablename__
        for mapper in dallinger.db.Base.registry.mappers
        if mapper.class_.__module__.startswith("dallinger_experiment")
        and not mapper.class_.inherits_table
    ]

    for table in tables_defined_in_experiment_directory:
        Base.metadata.remove(Base.metadata.tables[table])


@psynet.group("deploy")
@require_exp_directory
def deploy():
    """
    Deploy the experiment.
    """
    pass


@deploy.command("local")
@click.option("--docker", is_flag=True, help="Docker mode.")
@click.option("--archive", default=None, help="Optional path to an experiment archive.")
@click.option(
    "--legacy",
    is_flag=True,
    help="Use gunicorn instead of Flask auto-reload (default four worker processes).",
)
@click.option("--no-browsers", is_flag=True, help="Skip opening browsers.")
@click.pass_context
def deploy__local(ctx, docker, archive, legacy, no_browsers):
    """
    Deploy the experiment locally (e.g., when collecting data on a computer in the lab or in the field).
    """
    _run_local(
        ctx, docker, archive, legacy, no_browsers, mode="live", context_group=deploy
    )


@deploy.command("heroku")
@click.option("--app", callback=verify_id, required=True, help="Experiment id")
@click.option("--archive", default=None, help="Optional path to an experiment archive")
@click.option("--docker", is_flag=True, default=False, help="Deploy using Docker")
@_option_yes_reset_local_data
@click.pass_context
def deploy__heroku(ctx, app, archive, docker, assume_yes):
    """
    Deploy the experiment to Heroku.
    """
    if docker:
        _deploy__docker_heroku(ctx, app, archive, assume_yes)
        return

    try:
        from dallinger.command_line import deploy as dallinger_deploy

        _pre_launch(
            ctx,
            mode="live",
            archive=archive,
            local_=False,
            heroku=True,
            app=app,
            assume_yes=assume_yes,
        )
        # Note: PsyNet bypasses Dallinger's deploy-from-archive system and uses its own, so we set archive=None.
        result = ctx.invoke(dallinger_deploy, verbose=True, app=app, archive=None)
        _post_deploy(result)
    finally:
        _cleanup_exp_directory()
        reset_console()


def _deploy__docker_heroku(ctx, app, archive, assume_yes=False):
    try:
        from dallinger.command_line.docker import deploy as dallinger_deploy

        if archive is not None:
            raise NotImplementedError(
                "Unfortunately docker-heroku sandbox doesn't yet support deploying from archive. "
                "This shouldn't be hard to fix..."
            )

        _pre_launch(
            ctx,
            mode="live",
            archive=archive,
            local_=False,
            docker=True,
            heroku=True,
            app=app,
            assume_yes=assume_yes,
        )
        result = ctx.invoke(dallinger_deploy, verbose=True, app=app)
        _post_deploy(result)
    finally:
        _cleanup_exp_directory()
        reset_console()


@deploy.command("ssh")
@click.option("--app", callback=verify_id, help="Experiment id")
@click.option("--archive", default=None, help="Optional path to an experiment archive")
@_add_ssh_deployment_options
@_option_ssh_update
@_option_yes_reset_local_data
@click.pass_context
def deploy__docker_ssh(
    ctx,
    app,
    archive,
    dns_host,
    server,
    ingress=None,
    update=False,
    assume_yes=False,
):
    """
    Deploy the experiment to a remote server via Docker and SSH.

    The image always installs the PsyNet and Dallinger versions pinned in
    requirements.txt. To try local checkouts, use ``psynet debug ssh`` with
    ``--use-local-psynet`` or ``--use-local-dallinger``.
    """
    try:
        _validate_ssh_deploy_update(app, archive, update)
        _configure_dallinger_image_source(use_local_dallinger=False)

        _pre_launch(
            ctx,
            mode="live",
            archive=archive,
            local_=False,
            ssh=True,
            docker=True,
            server=server,
            app=app,
            update=update,
            assume_yes=assume_yes,
            ingress=ingress,
        )

        from dallinger.command_line.docker_ssh import (
            deploy as dallinger_docker_ssh_deploy,
        )

        # Note: PsyNet bypasses Dallinger's deploy-from-archive system and uses its own, so we set archive_path=None.
        # Pass a real bool. Click stringifies an omitted default as 'False'.
        result = _invoke_docker_ssh_deploy(
            ctx,
            dallinger_docker_ssh_deploy,
            server=server,
            dns_host=dns_host,
            app=app,
            ingress=ingress,
            update=update,
        )

        _post_deploy(result)
    finally:
        _cleanup_exp_directory()
        reset_console()


def _validate_ssh_deploy_update(app, archive, update):
    """Reject an in-place SSH update that cannot keep an existing app."""
    if not update:
        return
    if not app:
        raise click.UsageError("Updating an SSH app requires --app.")
    if archive is not None:
        raise click.UsageError("--archive and --update cannot be used together.")


def _invoke_docker_ssh_deploy(
    ctx,
    command,
    *,
    server,
    dns_host,
    app,
    ingress=None,
    update=False,
    config_options=None,
):
    """Invoke Dallinger docker-ssh deploy/sandbox, forwarding ingress when supported.

    ``config_options`` are config variables that the app gets in its
    environment, on top of those of the local config.
    """
    kwargs = {
        "server": server,
        "dns_host": dns_host,
        "app_name": app,
        "config_options": config_options or {},
        "archive_path": None,
        "update": bool(update),
    }
    params = getattr(command, "params", ())
    if any(getattr(param, "name", None) == "ingress" for param in params):
        kwargs["ingress"] = ingress
    return ctx.invoke(command, **kwargs)


def _configure_dallinger_image_source(use_local_dallinger=False):
    """Choose the Dallinger tree that docker-ssh bakes into the experiment image."""
    if not use_local_dallinger:
        os.environ["DALLINGER_NO_EGG_BUILD"] = "1"
        # Dallinger bakes DALLINGER_SOURCE whenever it is set.
        if os.environ.pop("DALLINGER_SOURCE", None):
            click.echo(
                "Ignoring DALLINGER_SOURCE; only "
                "'psynet debug ssh --use-local-dallinger' bakes it."
            )
        return
    os.environ.pop("DALLINGER_NO_EGG_BUILD", None)
    source = os.environ.get("DALLINGER_SOURCE", "").strip()
    if not source:
        from dallinger.utils import get_editable_dallinger_path

        source = get_editable_dallinger_path() or ""
    if not source:
        import dallinger as dallinger_pkg

        root = Path(dallinger_pkg.__file__).resolve().parent.parent
        if (root / "pyproject.toml").is_file():
            source = str(root)
    if not source:
        raise click.UsageError(
            "--use-local-dallinger needs an editable Dallinger checkout or DALLINGER_SOURCE."
        )
    os.environ["DALLINGER_SOURCE"] = source
    click.echo(f"Baking local Dallinger from {source} into the experiment image.")


def _reject_leftover_local_image_files():
    """Stop if the experiment directory holds local-build files from an earlier run.

    The experiment Dockerfile installs a PsyNet wheel over the pinned version
    and prefers ``local-image-pins.txt`` over the pins, so files left by an
    interrupted ``psynet debug ssh --use-local-psynet`` or
    ``--use-local-dallinger`` run would replace the pins, even in
    ``psynet deploy``.
    """
    leftovers = sorted(p.name for p in Path.cwd().glob(_LOCAL_PSYNET_WHEEL_PATTERN))
    if Path(_LOCAL_IMAGE_PINS).exists():
        leftovers.append(_LOCAL_IMAGE_PINS)
    if leftovers:
        raise click.UsageError(
            f"Remove {', '.join(leftovers)} from the experiment directory. "
            "These files are left over from an interrupted 'psynet debug ssh' "
            "with --use-local-psynet or --use-local-dallinger, and the image "
            "would use them instead of the versions in requirements.txt."
        )


def _local_packages(use_local_psynet, use_local_dallinger):
    """Return the names of the packages built into the image from local checkouts."""
    return tuple(
        package
        for package, enabled in (
            ("psynet", use_local_psynet),
            ("dallinger", use_local_dallinger),
        )
        if enabled
    )


def _check_local_image_packages(local_packages):
    """Stop before launching if ``local_packages`` cannot be built into the image.

    Parameters
    ----------
    local_packages : tuple of str
        Packages built from local checkouts, from :func:`_local_packages`.
    """
    if not local_packages:
        return
    dockerfile = Path("Dockerfile")
    if not dockerfile.is_file() or _LOCAL_IMAGE_PINS not in dockerfile.read_text():
        raise click.UsageError(
            "This experiment's Dockerfile does not install local PsyNet or "
            "Dallinger builds. Run 'psynet scripts update' to refresh it."
        )
    if "psynet" in local_packages:
        from .experiment_scaffold import get_editable_psynet_source

        if get_editable_psynet_source() is None:
            raise click.UsageError(
                "--use-local-psynet needs an editable PsyNet checkout."
            )


@contextmanager
def _local_image_packages(local_packages):
    """Stage local PsyNet and Dallinger builds for the experiment image.

    For ``"psynet"``, the editable PsyNet checkout is built into a wheel in the
    experiment directory, so it is sent with the other experiment files, and
    the experiment Dockerfile installs it over the pinned version. Dallinger
    stages its own wheel when ``DALLINGER_SOURCE`` is set.

    The pins without these packages are written to ``local-image-pins.txt``,
    which the Dockerfile installs instead, because their pins may point at a
    checkout that only exists on this machine. Staged files are removed
    afterwards.

    Parameters
    ----------
    local_packages : tuple of str
        Packages built from local checkouts and checked by
        :func:`_check_local_image_packages`.
    """
    if not local_packages:
        yield
        return
    staged = []
    try:
        if "psynet" in local_packages:
            staged.append(_build_local_psynet_wheel())
        staged.append(_write_local_image_pins(local_packages))
        yield
    finally:
        for path in staged:
            path.unlink(missing_ok=True)


def _build_local_psynet_wheel():
    """Build the editable PsyNet checkout into a wheel in the experiment directory."""
    from dallinger.utils import build_and_place

    from .experiment_scaffold import get_editable_psynet_source

    source = get_editable_psynet_source()
    click.echo(f"Baking local PsyNet from {source} into the experiment image.")
    return Path.cwd() / Path(build_and_place(str(source), os.getcwd())).name


def _write_local_image_pins(local_packages):
    """Write the image's pins without ``local_packages`` to ``local-image-pins.txt``.

    Like the Dockerfile, this reads ``constraints.txt`` when present and
    ``requirements.txt`` otherwise. In-repo experiments always read
    ``requirements.txt``, because they ignore ``constraints.txt``.
    """
    from .experiment_scaffold import is_requirement_line_for

    source = Path("constraints.txt")
    if is_in_repo_experiment() or not source.is_file():
        source = Path("requirements.txt")
    kept = [
        line
        for line in source.read_text().splitlines(keepends=True)
        if not any(is_requirement_line_for(line, p) for p in local_packages)
    ]
    target = Path.cwd() / _LOCAL_IMAGE_PINS
    target.write_text("".join(kept))
    return target


def _awaken_ssh_app(server, app):
    """Wake a sleeping docker-ssh app before export or other database access."""
    try:
        from dallinger.command_line.docker_ssh import awaken_app
    except ImportError:
        return
    awaken_app(server, app, required=False)


def _post_deploy(result):
    assert isinstance(result, dict)
    assert "dashboard_user" in result
    assert "dashboard_password" in result
    export_launch_data(
        deployment_id=deployment_info.read("deployment_id"),
        **result,
    )


def export_launch_data(deployment_id, **kwargs):
    """
    Retrieves dashboard credentials from the current config and
    saves them to disk.
    """
    directory = Path("~/psynet-data/launch-data").expanduser() / deployment_id
    directory.mkdir(parents=True, exist_ok=True)
    _export_launch_info(directory, **kwargs)


def _export_launch_info(directory, dashboard_user, dashboard_password, **kwargs):
    file = directory.joinpath("launch-info.json")
    with open(file, "w") as f:
        json.dump(
            {
                "dashboard_user": dashboard_user,
                "dashboard_password": dashboard_password,
                **kwargs,
            },
            f,
            indent=4,
        )


##############
# pre sandbox #
##############


def check_prolific_payment(experiment, config):
    from .utils import get_config

    base_payment = config.get("base_payment")
    minutes = config.get("prolific_estimated_completion_minutes")
    wage_per_hour = get_config().get("wage_per_hour")
    assert wage_per_hour * minutes / 60 == base_payment, (
        "Wage per hour does not match Prolific reward"
    )


def _missing_boilerplate_fix(*, mode=None, missing_paths=None):
    """Return actionable guidance when experiment boilerplate is missing."""
    if is_in_repo_experiment():
        command = "psynet scripts scaffold"
        context = (
            "This looks like a PsyNet bundled demo or test experiment, so only "
            "template files are needed."
        )
    else:
        command = "psynet setup"
        context = (
            "For a standalone experiment this prepares files, pins PsyNet, "
            "writes constraints.txt, and installs packages into your active "
            "virtual environment. If you only need template files, run "
            "'psynet scripts scaffold' instead."
        )

    mode_clause = ""
    if mode is not None:
        mode_clause = f" before running 'psynet {mode} ...'"

    message = f"{context} Run '{command}' to generate the missing files{mode_clause}."
    if missing_paths and "config.txt" in missing_paths:
        message += (
            " If you are upgrading an experiment that already sets options in "
            "Experiment.config, create an empty config.txt with 'touch config.txt' "
            "instead of scaffolding a full template."
        )
    return message


def _prepare_in_repo_experiment():
    """Generate ignored boilerplate when running an in-repo experiment."""
    if not is_in_repo_experiment():
        return False
    with _without_deployment_policy_review():
        scaffold_experiment_directory()
    return True


def _check_experiment_directory(mode, *, require_git_commit=False):
    """
    Fail fast on missing scaffold or git before Redis or other heavy I/O.

    In-repo experiments are auto-scaffolded first so their missing-boilerplate
    check does not falsely fail. A missing ``deploy.toml`` is created from the
    PsyNet template and never overwritten. When that file replaces an existing
    experiment's ``.gitignore``-based selection, a local review marker makes
    the next debug, test, or deploy command check once, after the Git checks,
    whether ``.gitignore`` ignores files that deploy.toml does not exclude; it
    stops and lists them only if there are any. New experiments, temporary
    pytest scaffolds and in-repo auto-prepare skip the check. Remote deployments additionally
    require a Git commit for provenance; local debug and test runs may use a
    repository with no commits. Leftover generated ``.dockerignore`` files and
    ``docker/`` helper scripts are removed (custom copies are preserved with a
    warning). These checks must run before ``redis_vars.clear()`` so users
    without Redis still see actionable guidance.
    """
    prepared = _prepare_in_repo_experiment()
    ensure_deployment_policy()
    missing_after_policy_creation = missing_scaffold_paths_required_for_local_run()
    if not prepared:
        _remove_obsolete_generated_dockerignore()
        _remove_obsolete_generated_docker_scripts()
    if Path(".dockerignore").exists() or Path(".dockerignore").is_symlink():
        raise click.ClickException(
            "Custom .dockerignore files are no longer supported. Move any "
            "deployment exclusions to deploy.toml, then remove .dockerignore."
        )

    missing_boilerplate = missing_after_policy_creation
    if missing_boilerplate:
        missing_paths = ", ".join(missing_boilerplate)
        raise click.ClickException(
            "Experiment directory is missing required PsyNet boilerplate files "
            f"({missing_paths}). "
            f"{_missing_boilerplate_fix(mode=mode, missing_paths=missing_boilerplate)}"
        )
    # Git provenance (commit SHA and dirty state) is recorded for deployments.
    if not git_repository_available():
        from .light_utils import git_command_available

        if not git_command_available():
            raise click.ClickException(
                "Git does not appear to be installed. Install it from "
                "https://git-scm.com/downloads, then create a repository by "
                "running 'git init'. If you copied a demo into a new directory, "
                "run 'git init' before 'psynet debug local' or 'psynet test local'."
            )
        raise click.ClickException(
            "This directory is not a git repository. Create one by running "
            "'git init'. If you copied a demo into a new directory, run "
            "'git init' before 'psynet debug local' or 'psynet test local'."
        )
    from .experiment_setup import _containing_worktree_ignores_experiment

    if _containing_worktree_ignores_experiment():
        raise click.ClickException(
            "The containing Git repository ignores this experiment directory, "
            "so its commit cannot identify the experiment's source state. Run "
            "'psynet setup' to create a dedicated Git repository before continuing."
        )

    # Runs after the Git checks so 'git check-ignore' can report which
    # deployment-selected files the old .gitignore ignores.
    if _deployment_policy_needs_review():
        # Unexpected errors, such as a malformed deploy.toml, keep the marker
        # so that the check runs again once they are fixed.
        try:
            ignored_paths = deployment_info._git_ignored_deployment_paths(
                extra_excludes_file=_DEPLOYMENT_POLICY_REVIEW_MARKER
            )
        except DeploymentPolicyError as error:
            raise click.ClickException(f"deploy.toml is invalid: {error}") from error
        _clear_deployment_policy_review_marker()
        intro = (
            "PsyNet now uses deploy.toml instead of .gitignore to choose "
            "which files are deployed, and created one for this experiment."
        )
        advice = (
            "Add any that should not be deployed (credentials, private data, "
            "large or generated files) to [exclude] in deploy.toml, then "
            "rerun this command. This check runs only once; "
            "'dallinger deployment-files list' shows the full selection."
        )
        if ignored_paths is None:
            raise click.ClickException(
                f"{intro} PsyNet could not check whether your .gitignore "
                "ignores files that deploy.toml does not exclude, so review "
                "the selection with "
                f"'dallinger deployment-files list'.\n\n{advice}"
            )
        if ignored_paths:
            preview_limit = 10
            preview = "\n".join(f"  {path}" for path in ignored_paths[:preview_limit])
            remaining = len(ignored_paths) - preview_limit
            if remaining > 0:
                preview += f"\n  ... and {remaining} more"
            raise click.ClickException(
                f"{intro} Your .gitignore ignores these files, but deploy.toml "
                f"does not exclude them, so they would be deployed:\n{preview}\n\n{advice}"
            )
    if require_git_commit:
        from .light_utils import git_commit_available

        if not git_commit_available():
            raise click.ClickException(
                "This Git repository has no commits yet. Remote deployments need "
                "a commit so PsyNet can record exactly which source version was "
                "deployed. Review 'git status', commit the experiment files you "
                "want to keep, then rerun this command."
            )


def run_pre_checks(
    mode,
    local_,
    heroku=False,
    docker=False,
    app=None,
    local_packages=(),
    check_consents=True,
):
    """Check the experiment before a launch.

    ``check_consents=False`` skips the consent page check, for apps that only
    bots take part in.
    """
    from .experiment import get_experiment
    from .utils import check_todos_before_deployment

    # Directory readiness is checked earlier in ``_pre_launch`` (before Redis)
    # and directly from ``psynet test local``. Avoid duplicating that work here.

    if not local_:
        _check_constraints_before_remote_deploy()

    exp = get_experiment()
    exp.check_config()
    exp.check_size(heroku=heroku)
    if check_consents:
        exp.check_consents()
    exp.check_python_dependencies()

    try:
        with open("requirements.txt", "r") as f:
            for line in f.readlines():
                if (
                    "computational-audition-lab/psynet" in line.lower()
                    and not user_confirms(
                        "It looks like you're using an old version of PsyNet in requirements.txt "
                        "(computational-audition-lab/psynet); "
                        "the up-to-date version is located at PsyNetDev/PsyNet. Are you sure you want to continue?"
                    )
                ):
                    raise click.Abort
    except FileNotFoundError:
        raise click.ClickException(
            f"requirements.txt is missing from your experiment directory ({os.getcwd()})."
        )

    if (
        heroku
        and docker
        and not user_confirms(
            "Heroku deployment with Docker hasn't been working well recently; experiments have been failing to launch "
            "and returning a psutil version error. Are you sure you want to continue?"
        )
    ):
        raise click.Abort

    if docker:
        check_dockerfile()

    if not local_:
        config = get_config()
        if not config.ready:
            config.load()
        check_todos_before_deployment()

        if docker:
            if config.get("docker_image_base_name", None) is None:
                raise click.UsageError(
                    "docker_image_base_name must be specified in config.txt or ~/.dallingerconfig before you can "
                    "launch an experiment using Docker. Any image name works unless you push to a "
                    "registry, for example: \n"
                    "docker_image_base_name = my-psynet-experiments"
                )
            _expected_docker_volumes = "${HOME}/psynet-data/assets:/psynet-data/assets"
            if _expected_docker_volumes not in config.get(
                "docker_volumes", ""
            ) and not user_confirms(
                "For deploying PsyNet experiments with Docker, you should typically have the following line "
                "in your config.txt: \n"
                f"docker_volumes = {_expected_docker_volumes}\n"
                "You are advised to change this line then retry launching the experiment. "
                "However, if you're sure you want to continue, enter 'y' and press 'Enter'."
            ):
                raise click.Abort
            if config.get("host") != "0.0.0.0" and not user_confirms(
                "For deploying PsyNet experiments with Docker, you should typically have host = 0.0.0.0 in config.txt. "
                "You are advised to change this line then retry launching the experiment. "
                "However, if you're sure you want to continue, enter 'y' and press 'Enter'."
            ):
                raise click.Abort

        config.set("id", exp.make_uuid(app))

        recruiter = exp.recruiter
        is_prolific = isinstance(recruiter, ProlificRecruiter)

        if heroku:
            if not exp.asset_storage.heroku_compatible:
                raise AttributeError(
                    f"You can't deploy an experiment to Heroku with this asset storage back-end ({exp.asset_storage}). "
                    "The storage back-end is set in your experiment class with a line like `asset_storage = ...`. "
                    "If you don't need assets in your experiment, you can probably remove the line altogether. "
                    "If you do need assets, you should replace the current storage option with a "
                    "Heroku-compatible backend, for example S3Storage('your-bucket', 'your-root')."
                )
            if is_prolific:
                check_prolific_payment(exp, config)

        if mode == "sandbox":
            run_pre_checks_sandbox(local_packages)
        elif mode == "live":
            run_pre_checks_deploy(local_, recruiter)


def _check_constraints_before_remote_deploy():
    """Stop a remote deploy of a standalone experiment with a stale ``constraints.txt``.

    Docker deploys set ``SKIP_DEPENDENCY_CHECK`` for Dallinger later in
    ``_pre_launch``, so without this check the image would be built from the
    stale lockfile. In-repo demos use PsyNet's development environment instead.
    """
    if is_in_repo_experiment() or os.environ.get("SKIP_DEPENDENCY_CHECK"):
        return
    _check_constraints()


def run_pre_checks_sandbox(local_packages=()):
    """Check the PsyNet and Dallinger pins before a debug deploy.

    Parameters
    ----------
    local_packages : tuple of str
        Packages built into the image from local checkouts. Their pins do not
        decide what runs, so they are not checked.
    """
    if "psynet" not in local_packages:
        check_psynet_requirement_is_unambiguous()
        check_psynet_requirement_includes_experiment_extra()
    check_core_dependency_versions_match_requirements(skip=local_packages)


@debug.command("heroku")
@click.option(
    "--app", callback=verify_id, default=None, help="Name of the experiment app."
)
@click.option("--docker", is_flag=True, help="Docker mode.")
@click.option("--archive", default=None, help="Optional path to an experiment archive.")
@_option_yes_reset_local_data
@click.pass_context
def debug__heroku(ctx, app, docker, archive, assume_yes):
    """
    Debug the experiment on Heroku.
    """
    if docker:
        debug__docker_heroku(ctx, app, archive, assume_yes)
    else:
        from dallinger.command_line import sandbox as dallinger_sandbox

        try:
            _pre_launch(
                ctx,
                mode="sandbox",
                archive=archive,
                local_=False,
                heroku=True,
                app=app,
                assume_yes=assume_yes,
            )
            # Note: PsyNet bypasses Dallinger's deploy-from-archive system and uses its own, so we set archive=None.
            result = ctx.invoke(dallinger_sandbox, verbose=True, app=app, archive=None)
            _post_deploy(result)
        finally:
            _cleanup_exp_directory()
            reset_console()


def debug__docker_heroku(ctx, app, archive, assume_yes=False):
    from dallinger.command_line.docker import sandbox as dallinger_sandbox

    try:
        if archive is not None:
            raise NotImplementedError(
                "Unfortunately docker-heroku sandbox doesn't yet support deploying from archive. "
                "This shouldn't be hard to fix..."
            )
        _pre_launch(
            ctx,
            mode="sandbox",
            archive=archive,
            local_=False,
            docker=True,
            heroku=True,
            app=app,
            assume_yes=assume_yes,
        )
        result = ctx.invoke(dallinger_sandbox, verbose=True, app=app)
        _post_deploy(result)
    finally:
        _cleanup_exp_directory()
        reset_console()


@debug.command("ssh")
@click.option(
    "--app", callback=verify_id, default=None, help="Name of the experiment app."
)
@click.option("--archive", default=None, help="Optional path to an experiment archive.")
@_add_ssh_deployment_options
@_use_local_psynet_option
@_use_local_dallinger_option
@_option_ssh_update
@_option_yes_reset_local_data
@click.pass_context
def debug__docker_ssh(ctx, **options):
    """
    Debug the experiment on a remote server via SSH.
    """
    _debug_ssh(ctx, **options)


def _debug_ssh(
    ctx,
    *,
    app,
    server,
    dns_host,
    archive=None,
    ingress=None,
    use_local_psynet=False,
    use_local_dallinger=False,
    update=False,
    assume_yes=False,
    performance_test_app=False,
):
    """Deploy or update ``app`` on ``server`` in debug mode, as ``psynet debug ssh`` does.

    The app's environment sets ``debug_ssh_app``, which lets ``psynet
    destroy ssh`` destroy it when its pending async jobs can't be checked.
    With ``performance_test_app``, the app is one that ``psynet
    performance-test ssh`` deploys for its tests: its environment also sets
    ``performance_test_app``, and :func:`_pre_launch` relaxes its checks.
    """
    try:
        from dallinger.command_line.docker_ssh import sandbox

        _validate_ssh_deploy_update(app, archive, update)
        _configure_dallinger_image_source(use_local_dallinger=use_local_dallinger)
        local_packages = _local_packages(use_local_psynet, use_local_dallinger)

        _pre_launch(
            ctx,
            mode="sandbox",
            archive=archive,
            local_=False,
            ssh=True,
            docker=True,
            server=server,
            app=app,
            update=update,
            local_packages=local_packages,
            assume_yes=assume_yes,
            performance_test_app=performance_test_app,
            ingress=ingress,
        )
        config_options = {"debug_ssh_app": "true"}
        if performance_test_app:
            config_options["performance_test_app"] = "true"

        with _local_image_packages(local_packages):
            # Note: PsyNet bypasses Dallinger's deploy-from-archive system and uses its own, so we set archive_path=None.
            result = _invoke_docker_ssh_deploy(
                ctx,
                sandbox,
                server=server,
                dns_host=dns_host,
                app=app,
                ingress=ingress,
                update=update,
                config_options=config_options,
            )

        _post_deploy(result)
    finally:
        _cleanup_exp_directory()


##########
# install #
##########
@psynet.group("install")
def install():
    """
    Install additional PsyNet components.
    """
    pass


@install.command("autocomplete")
def install_autocomplete():
    """
    Install shell tab completion for the psynet command.

    This command automatically detects your shell (bash or zsh) and adds the appropriate
    completion setup to your shell configuration file.
    """
    import os
    import subprocess

    # Get the directory where this script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))
    psynet_root = os.path.dirname(script_dir)
    install_script = os.path.join(
        psynet_root, "psynet", "resources", "scripts", "install-completion.sh"
    )

    if not os.path.exists(install_script):
        raise click.ClickException(
            f"Installation script not found at {install_script}. "
            "Please ensure you're running this command from a proper PsyNet installation."
        )

    # Make the script executable
    os.chmod(install_script, 0o755)

    # Run the installation script
    try:
        subprocess.run([install_script], check=True)
    except subprocess.CalledProcessError as e:
        raise click.ClickException(f"Failed to install autocomplete: {e}")
    except FileNotFoundError:
        raise click.ClickException(
            "Could not find bash executable. Please install bash and try again."
        )


#######################
# installation update #
#######################
def _run_installation_update(dallinger_version, psynet_version, verbose):
    """Update the locally installed Dallinger and PsyNet packages."""
    from dallinger.utils import get_editable_dallinger_path

    from .experiment_scaffold import get_editable_source

    def _git_checkout(version, cwd, capture_output):
        with yaspin(text=f"Checking out {version}...", color="green") as spinner:
            subprocess.run(
                [f"git checkout {version}"],
                shell=True,
                cwd=cwd,
                capture_output=capture_output,
            )
            spinner.ok("✔")

    def _git_latest_tag(cwd, capture_output):
        return (
            subprocess.check_output(["git", "describe", "--abbrev=0", "--tag"], cwd=cwd)
            .decode("utf-8")
            .strip()
        )

    def _git_pull(cwd, capture_output):
        with yaspin(text="Pulling changes...", color="green") as spinner:
            subprocess.run(
                ["git pull"],
                shell=True,
                cwd=cwd,
                capture_output=capture_output,
            )
            spinner.ok("✔")

    def _git_needs_stashing(cwd):
        return (
            subprocess.check_output(["git", "diff", "--name-only"], cwd=cwd)
            .decode("utf-8")
            .strip()
            != ""
        )

    def _git_version_pattern():
        return re.compile("^v([0-9]+)\\.([0-9]+)\\.([0-9]+)$")

    def _prepare(version, project_name, cwd, capture_output):
        if _git_needs_stashing(cwd):
            with yaspin(
                text=f"Git commit your changes or stash them before updating {project_name}!",
                color="red",
            ) as spinner:
                spinner.ok("✘")
            raise SystemExit()

        _git_checkout("master", cwd, capture_output)
        _git_pull(cwd, capture_output)

        if version == "latest":
            version = _git_latest_tag(cwd, capture_output)

        _git_checkout(version, cwd, capture_output)

    capture_output = not verbose

    # Dallinger
    log("Updating Dallinger...")
    cwd = dallinger_dir()
    # Dallinger 12.4 and older only detect legacy .egg-link editable installs.
    dallinger_is_editable = (
        get_editable_source("dallinger") is not None
        or get_editable_dallinger_path() is not None
    )
    if dallinger_is_editable:
        _prepare(
            dallinger_version,
            "Dallinger",
            cwd,
            capture_output,
        )

    if dallinger_is_editable:
        text = "Installing base packages and development requirements..."
        install_command = "pip install --editable '.[data]'"
    else:
        text = "Installing base packages..."
        install_command = "pip install '.[data]'"

    with yaspin(
        text=text,
        color="green",
    ) as spinner:
        if dallinger_is_editable:
            subprocess.run(
                ["pip3 install -r dev-requirements.txt"],
                shell=True,
                cwd=cwd,
                capture_output=capture_output,
            )
        else:
            if _git_version_pattern().match(dallinger_version):
                install_command = f"pip install dallinger=={dallinger_version}"
            else:
                install_command = "pip install dallinger"
        subprocess.run(
            [install_command],
            shell=True,
            cwd=cwd,
            capture_output=capture_output,
        )
        spinner.ok("✔")

    # PsyNet
    log("Updating PsyNet...")
    cwd = psynet_dir()
    _prepare(
        psynet_version,
        "PsyNet",
        cwd,
        capture_output,
    )

    text = "Installing base packages and development requirements..."
    install_command = "pip install -e '.[dev]'"

    with yaspin(text=text, color="green") as spinner:
        install_command = install_command
        subprocess.run(
            [install_command],
            shell=True,
            cwd=cwd,
            capture_output=capture_output,
        )
        spinner.ok("✔")

    log(f"Updated PsyNet to version {get_version('psynet')}")


_installation_update_options = [
    click.option(
        "--dallinger-version",
        default="latest",
        help="The git branch, commit or tag of the Dallinger version to install.",
    ),
    click.option(
        "--psynet-version",
        default="latest",
        help="The git branch, commit or tag of the psynet version to install.",
    ),
    click.option("--verbose", is_flag=True, help="Verbose mode"),
]


def _add_installation_update_options(command):
    """Attach shared options to installation-update entry points."""
    for option in reversed(_installation_update_options):
        command = option(command)
    return command


@psynet.group("installation")
def installation():
    """
    Manage the local PsyNet and Dallinger installation.
    """
    pass


@installation.command("update")
@_add_installation_update_options
def installation_update(dallinger_version, psynet_version, verbose):
    """
    Update the locally installed Dallinger and PsyNet packages.

    This upgrades (or pin-selects) the PsyNet/Dallinger *installation* in your
    environment. It does not refresh experiment boilerplate files; for that,
    use ``psynet scripts update``.
    """
    _run_installation_update(dallinger_version, psynet_version, verbose)


@psynet.command("update")
@_add_installation_update_options
def update(dallinger_version, psynet_version, verbose):
    """
    Deprecated alias for ``psynet installation update``.
    """
    click.echo(
        "psynet update is deprecated; use 'psynet installation update' instead.",
        err=True,
    )
    _run_installation_update(dallinger_version, psynet_version, verbose)


def dallinger_dir():
    import dallinger as _

    return Path(_.__file__).parent.parent.resolve()


def psynet_dir():
    import psynet as _

    return Path(_.__file__).parent.parent.resolve()


def get_version(project_name):
    return (
        subprocess.check_output([f"{project_name} --version"], shell=True)
        .decode("utf-8")
        .strip()
    )


############
# estimate #
############
def _estimate(mode):
    from .experiment import import_local_experiment
    from .utils import get_config

    experiment_class = import_local_experiment()["class"]
    wage_per_hour = get_config().get("wage_per_hour")

    config = get_config()
    if not config.ready:
        config.load()

    if mode in ["reward", "both"]:
        max_reward = experiment_class.estimated_max_reward(wage_per_hour)
        log(
            f"Estimated maximum reward for participant: {config.currency}{round(max_reward, 2)}."
        )
    if mode in ["duration", "both"]:
        completion_time = experiment_class.estimated_completion_time(wage_per_hour)
        log(
            f"Estimated time to complete experiment: {pretty_format_seconds(completion_time)}."
        )
        if config.get("recruiter", None) == "prolific":
            for warning in prolific_listing_warnings(
                completion_time_s=completion_time,
                listed_minutes=config.get(
                    "prolific_estimated_completion_minutes", None
                ),
                base_payment=config.get("base_payment", None),
                currency=config.currency,
            ):
                log(f"Warning: {warning}")


# Prolific's published minimum hourly rates; update these if Prolific changes them.
_PROLIFIC_MINIMUM_PER_HOUR = {"£": 6.0, "$": 8.0}


def prolific_listing_warnings(
    completion_time_s, listed_minutes, base_payment, currency
):
    """
    Compare the Prolific listing in ``config.txt`` with PsyNet's estimates.

    Prolific requires ``base_payment`` alone, without bonuses, to meet its
    minimum hourly rate over participants' median completion time. The check
    therefore uses the longer of the listed and estimated durations.
    """
    warnings = []
    estimated_minutes = completion_time_s / 60
    if listed_minutes and listed_minutes < estimated_minutes:
        warnings.append(
            f"prolific_estimated_completion_minutes ({listed_minutes}) is shorter "
            f"than the estimated {estimated_minutes:.1f} minutes."
        )
    minimum = _PROLIFIC_MINIMUM_PER_HOUR.get(currency)
    minutes = max(listed_minutes or 0, estimated_minutes)
    if minimum and base_payment is not None and minutes:
        rate = base_payment / (minutes / 60)
        if rate < minimum:
            warnings.append(
                f"base_payment ({currency}{base_payment:.2f}) for {minutes:.1f} "
                f"minutes is {currency}{rate:.2f}/hour, below Prolific's minimum "
                f"of {currency}{minimum:.2f}/hour. Bonuses don't count towards "
                "Prolific's minimum, so raise base_payment."
            )
    return warnings


@psynet.command()
@click.option(
    "--mode",
    default="both",
    type=click.Choice(["reward", "duration", "both"]),
    help="Type of result. Can be either 'reward', 'duration', or 'both'.",
)
@require_exp_directory
def estimate(mode):
    """
    Estimate the maximum reward for a participant and the time for the experiment to complete, respectively.
    """
    try:
        _estimate(mode)
    except ProgrammingError:
        log("Initialize the database and try again.")
        db.session.rollback()
        init_db(drop_all=True)
        db.session.commit()
        _estimate(mode)


def setup_experiment_variables(experiment_class):
    experiment = experiment_class()
    experiment.setup_experiment_config()
    experiment.setup_experiment_variables()
    return experiment


@psynet.command()
@require_requirements_txt
def check_constraints():
    "Check whether the experiment contains an appropriate constraints.txt file."
    if os.environ.get("SKIP_DEPENDENCY_CHECK"):
        print("SKIP_DEPENDENCY_CHECK is set so we will skip checking constraints.txt.")
        return

    with yaspin(
        text="Verifying that constraints.txt is up-to-date with requirements.txt...",
        color="green",
    ) as spinner:
        _check_constraints(spinner)
        spinner.ok("✔")

    check_psynet_requirement_is_unambiguous()


def check_dockerfile():
    """
    Check that a Dockerfile exists and uses the correct format.

    This function performs two checks:

    1. Ensures a Dockerfile exists in the experiment directory
    2. Ensures the Dockerfile uses the new format (Python base image)
       rather than the outdated PsyNet base image format

    Raises
    ------
    click.UsageError
        If Dockerfile is missing or uses outdated format
    """
    from psynet.version import psynet_version

    update_scripts_recommendation = (
        "To fix this issue, run:\n"
        "  psynet scripts scaffold\n\n"
        "This creates any missing standard boilerplate files without overwriting existing ones.\n\n"
        "If you instead want to overwrite existing boilerplate with the latest templates, run:\n"
        "  psynet scripts update\n\n"
        "Note: This command will also update other experiment files including .gitignore, "
        "README.md, test.py, and configuration files in .vscode/ and .github/workflows/.\n\n"
        "IMPORTANT: Before running this command, commit any pending changes to git so you can "
        "review the automatic changes that psynet scripts update makes."
    )

    dockerfile_path = Path("Dockerfile")

    # Check 1: Dockerfile must exist
    if not dockerfile_path.exists():
        raise click.UsageError(
            "Docker deployments require a Dockerfile in the experiment directory.\n\n"
            + update_scripts_recommendation
        )

    # Check 2: Dockerfile must use new format (Python base image, not PsyNet base image)
    dockerfile_content = dockerfile_path.read_text()

    uses_psynet_base_image = bool(
        re.search(
            r"FROM\s+registry\.gitlab\.com/psynetdev/psynet:",
            dockerfile_content,
            re.IGNORECASE,
        )
    )

    if uses_psynet_base_image:
        raise click.UsageError(
            "Your Dockerfile appears to be using an outdated format that references a PsyNet base image:\n"
            f"  FROM registry.gitlab.com/psynetdev/psynet:...\n\n"
            f"This format is no longer supported in PsyNet v{psynet_version}. "
            "The Dockerfile should now build directly from a Python base image.\n\n"
            + update_scripts_recommendation
        )


def _check_constraints(spinner=None):
    directory = os.getcwd()

    # Freshness uses the same MD5-in-lockfile rule as ``psynet setup``.
    requirements_path = Path(directory) / "requirements.txt"
    constraints_path = Path(directory) / "constraints.txt"

    if not requirements_path.exists():
        if spinner:
            spinner.fail("✘")
        raise click.ClickException(
            "Experiment directory is missing a requirements.txt file. "
            "You need to create this file and put your Python package dependencies (e.g. psynet) in it."
        )
        # raise click.Abort()

    generate_constraints_cmd = (
        "    psynet setup\n"
        "or only refresh the lockfile with:\n"
        "    psynet generate-constraints"
    )

    if not constraints_path.exists():
        if spinner:
            spinner.fail("✘")
        raise click.ClickException(
            "Error: Experiment directory is missing a constraints.txt file. "
            "Standalone experiments need this lockfile so installs are "
            "reproducible. Please check that your requirements.txt file is "
            "up-to-date, then create constraints.txt by running:\n"
            + generate_constraints_cmd
        )

    from .constraints_compile import (
        constraints_are_hand_written,
        constraints_are_up_to_date,
    )

    if constraints_are_hand_written(constraints_path):
        click.echo(
            "constraints.txt was written by hand, so it is not checked against "
            "requirements.txt."
        )
        return
    if not constraints_are_up_to_date(
        requirements_path=requirements_path,
        constraints_path=constraints_path,
    ):
        if spinner:
            spinner.fail("✘")
        raise click.ClickException(
            "The constraints.txt file is not up-to-date with the requirements.txt file. "
            "Please regenerate constraints.txt by running:\n" + generate_constraints_cmd
        )


def check_psynet_requirement_is_unambiguous():
    """
    Validate that ``requirements.txt`` pins PsyNet unambiguously.

    The check requires a deterministic PsyNet specification so deployments are
    reproducible. Accepted formats are documented on
    :func:`psynet.experiment_scaffold.is_unambiguous_psynet_requirement`.

    Raises
    ------
    ValueError
        If the PsyNet requirement is missing or ambiguous.
    """
    environment_variable = "SKIP_CHECK_PSYNET_VERSION_REQUIREMENT"
    if os.environ.get(environment_variable, None):
        print(
            f"Skipping PsyNet version requirement check because {environment_variable} was non-empty."
        )
        return

    with yaspin(
        text="Verifying PsyNet version in requirements.txt...",
        color="green",
    ) as spinner:
        requirement = get_psynet_requirement()
        valid = requirement is not None and is_unambiguous_psynet_requirement(
            requirement
        )

        if valid:
            spinner.ok("✔")
        else:
            spinner.color = "red"
            spinner.fail("✗")

        if not valid:
            raise ValueError(_ambiguous_psynet_requirement_message(requirement))


def confirm_deploying_development_psynet():
    """Ask before a live remote deployment installs a development PsyNet.

    Release pins (``14.0.0``, ``14.0.0rc1`` or the tag ``v14.0.0``) pass
    silently. A commit, an alpha, or an entry accepted only because
    ``SKIP_CHECK_PSYNET_VERSION_REQUIREMENT`` is set is a development version.
    Setting that variable replaces the question with a warning.

    Raises
    ------
    click.Abort
        If the user declines to deploy a development version.
    """
    requirement = get_psynet_requirement()
    if requirement and is_release_version_specifier(specified_version(requirement)):
        return

    message = (
        "requirements.txt installs a development version of PsyNet, not a release:\n"
        f"  {requirement or '(no PsyNet entry)'}\n"
        "Live experiments should normally pin a PsyNet release, for example "
        "psynet[experiment]==<version>."
    )
    if os.environ.get("SKIP_CHECK_PSYNET_VERSION_REQUIREMENT"):
        click.echo(f"Warning: {message}", err=True)
        return
    if not user_confirms(
        f"{message}\nDeploy it anyway? (Set SKIP_CHECK_PSYNET_VERSION_REQUIREMENT=1 "
        "to skip this question.)"
    ):
        raise click.Abort


def check_psynet_requirement_includes_experiment_extra():
    """Require the PsyNet pin to install the experiment runtime.

    A pin of plain ``psynet`` installs only the command-line tools. The
    deployment image then has no Dallinger, and the clock process fails to
    start. A missing pin is left to
    :func:`check_psynet_requirement_is_unambiguous`, which runs first.

    Raises
    ------
    ValueError
        If the PsyNet requirement omits the ``[experiment]`` extra.
    """
    environment_variable = "SKIP_CHECK_PSYNET_EXPERIMENT_EXTRA"
    if os.environ.get(environment_variable):
        print(
            "Skipping the PsyNet [experiment] extra check because "
            f"{environment_variable} was non-empty."
        )
        return

    with yaspin(
        text="Verifying that requirements.txt installs psynet[experiment]...",
        color="green",
    ) as spinner:
        requirement = get_psynet_requirement()
        if requirement is None or requirement_includes_experiment_extra(requirement):
            spinner.ok("✔")
            return
        spinner.color = "red"
        spinner.fail("✗")

    suggested = _requirement_with_experiment_extra(requirement)
    raise ValueError(
        "The PsyNet requirement in requirements.txt must include the "
        "[experiment] extra.\n\n"
        "Without it, the deployment installs only the PsyNet command-line "
        "tools. The experiment image then has no Dallinger, and the clock "
        "process fails to start.\n\n"
        f"Your current requirements.txt entry is:\n  {requirement}\n\n"
        f"Change it to:\n  {suggested}\n\n"
        "You can skip this check by writing "
        f"`export {environment_variable}=1` (without quotes) in your terminal."
    )


def _requirement_with_experiment_extra(requirement: str) -> str:
    """Return ``requirement`` with ``experiment`` added to its PsyNet extras.

    Existing extras are kept. Extras are joined without spaces because
    ``#egg=`` fragments do not allow whitespace.
    """

    def add_extra(match):
        extras = [
            extra.strip()
            for extra in (match.group(2) or "").split(",")
            if extra.strip()
        ]
        return f"{match.group(1)}psynet[{','.join([*extras, 'experiment'])}]"

    return re.sub(
        r"(?i)(^\s*|#egg=)psynet(?:\[([^]]*)\])?",
        add_extra,
        requirement,
        count=1,
    )


def _is_local_psynet_requirement(requirement: str) -> bool:
    """Return whether a PsyNet requirement points at a local filesystem path."""
    compact = requirement.lower().replace(" ", "")
    return compact.startswith("-e") or "file://" in compact


def _ambiguous_psynet_requirement_message(requirement: str | None) -> str:
    """Build the deploy-time error for a missing or ambiguous PsyNet pin."""
    branch_note = (
        "This means you can't just give a branch name, e.g. master; you have to "
        "specify a particular version or a commit hash."
    )
    examples = [
        "* psynet[experiment]==10.1.1",
        "* psynet[experiment]@git+https://gitlab.com/PsyNetDev/PsyNet@v10.1.1#egg=psynet",
        "* psynet[experiment]@git+https://gitlab.com/PsyNetDev/PsyNet@45f317688af59350f9a6f3052fd73076318f2775#egg=psynet",
        "* psynet[experiment]@git+https://gitlab.com/alice/PsyNet@45f317688af59350f9a6f3052fd73076318f2775#egg=psynet",
        "* psynet[experiment]@git+https://gitlab.com/PsyNetDev/PsyNet@45f31768#egg=psynet",
    ]

    parts = [
        "When deploying an experiment, you need to specify PsyNet in an "
        "unambiguous way. " + branch_note,
    ]
    if requirement:
        parts.append(f"\n\nYour current requirements.txt entry is:\n  {requirement}")
        if _is_local_psynet_requirement(requirement):
            parts.append(
                "\n\nLocal path, wheel and editable installs cannot be resolved "
                "on a remote deploy server. Replace this entry with a published "
                "version or a pushed Git commit (see the examples below). If you "
                "developed against a local PsyNet checkout, re-run:\n"
                "  psynet setup --psynet-source commit\n"
                "to pin a pushed Git commit before deploying."
            )
    from .experiment_scaffold import get_editable_psynet_source

    if get_editable_psynet_source() is not None:
        parts.append(
            "\n\nTo try your editable PsyNet checkout on a server without "
            "pinning it, add --use-local-psynet to 'psynet debug ssh' or "
            "'psynet performance-test ssh'. 'psynet deploy' always needs a pin."
        )
    parts.append(
        "\n\nExamples:\n"
        + "\n".join(examples)
        + "\nYou can skip this check by writing "
        "`export SKIP_CHECK_PSYNET_VERSION_REQUIREMENT=1` (without quotes) "
        "in your terminal."
    )
    return "".join(parts)


##########
# export #
##########


def app_argument(func):
    return click.option(
        "--app",
        default=None,
        required=False,
        help="App id",
    )(func)


def _resolve_ssh_app(ctx, app, server):
    if app:
        return app

    from dallinger.command_line.docker_ssh import select_running_app

    try:
        resolved_app = select_running_app(server)
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc

    log(f"No --app provided; using running app on the server: {resolved_app}")
    return resolved_app


def _warn_deprecated_export_options(
    no_source, username, password, n_parallel=None, anonymize=False
):
    """Warn when deprecated export options are explicitly supplied.

    The options are still accepted so that older scripts keep running; they
    simply have no effect.
    """
    deprecated_options = [
        option
        for option, used in (
            ("--no-source", no_source),
            ("--username", username is not None),
            ("--password", password is not None),
            ("--n_parallel", n_parallel is not None),
            ("anonymize=", anonymize),
        )
        if used
    ]
    if deprecated_options:
        click.echo(
            "WARNING: Deprecated export option(s) "
            + ", ".join(deprecated_options)
            + " are accepted for compatibility but have no effect.",
            err=True,
        )


def export_arguments(func):
    args = [
        click.option("--path", default=None, help="Path to export directory"),
        click.option(
            "--assets",
            default="collected",
            help=(
                "Which assets to export; valid values are none and collected. "
                "'collected' (the default) exports assets created while the "
                "experiment was running (e.g. recordings), excluding assets prepared before "
                "launch, external URLs, and on-demand generation. "
                "'none' omits the assets folder."
            ),
        ),
        click.option(
            "--allow-project-mismatch",
            is_flag=True,
            default=False,
            help=(
                "Export even though the deployed experiment's code does not match "
                "this directory exactly."
            ),
        ),
        click.option(
            "--transfer",
            type=click.Choice(["auto", "archive", "incremental"]),
            default="auto",
            hidden=True,
            help=(
                "How to transfer the export: stream a complete server-built "
                "archive, or stream a core snapshot and fetch missing asset "
                "bytes over rsync. Defaults to automatic selection."
            ),
        ),
        click.option(
            "--n_parallel",
            default=None,
            hidden=True,
            help="Deprecated compatibility option with no effect",
        ),
        click.option(
            "--no-source",
            is_flag=True,
            default=False,
            hidden=True,
            help="Deprecated compatibility option with no effect",
        ),
        click.option(
            "--username",
            default=None,
            hidden=True,
            help="Deprecated compatibility option with no effect",
        ),
        click.option(
            "--password",
            default=None,
            hidden=True,
            help="Deprecated compatibility option with no effect",
        ),
    ]
    for arg in args:
        func = arg(func)
    return func


@psynet.group("export")
@require_exp_directory
def export():
    """
    Export the experiment.
    """
    pass


@export.command("local")
@export_arguments
@click.pass_context
def export__local(ctx=None, **kwargs):
    """
    Export the experiment locally.
    """
    export_(
        ctx,
        get_exp_variables=lambda: _read_experiment_variables("local"),
        local=True,
        **kwargs,
    )


@export.command("heroku")
@export_arguments
@click.option(
    "--app",
    required=True,
    help="Name of the app to export",
)
@click.pass_context
def export__heroku(ctx, app, **kwargs):
    """
    Export the experiment from Heroku.
    """
    export_(
        ctx,
        get_exp_variables=lambda: _read_experiment_variables("heroku", app=app),
        app=app,
        local=False,
        **kwargs,
    )


@export.command("ssh")
@click.option(
    "--app",
    default=None,
    required=False,
    callback=verify_id,
    help=("Name of the app to export (optional if only one running app is available)"),
)
@option_server
@export_arguments
@click.pass_context
def export__docker_ssh(ctx, app, server, **kwargs):
    """
    Export the experiment from a remote server via Docker and SSH.
    """
    app = _resolve_ssh_app(ctx, app, server)
    _awaken_ssh_app(server, app)
    export_(
        ctx,
        get_exp_variables=lambda: _read_experiment_variables(
            "ssh", app=app, server=server
        ),
        app=app,
        local=False,
        server=server,
        docker_ssh=True,
        pending_jobs=_fetch_ssh_pending_async_jobs_for_export(app, server),
        **kwargs,
    )


def export_(
    ctx,
    get_exp_variables,
    app=None,
    local=False,
    path=None,
    assets="collected",
    n_parallel=None,
    no_source=False,
    docker_ssh=False,
    server=None,
    dns_host=None,
    username=None,
    password=None,
    transfer="auto",
    allow_project_mismatch=False,
    pending_jobs=None,
    **kwargs,
):
    """
    Export data from an experiment.

    The data is exported into the specified export directory with the following structure:

    ::

        export_path/
        ├── database/
        │   ├── participant.csv
        │   ├── trial.csv
        │   └── …
        ├── participant_identifiers.csv
        ├── lucid_entrant_identifiers.csv   # Lucid experiments only
        ├── manifest.json
        ├── basic_data.json OR basic_data/  # optional
        ├── assets/                         # omitted when --assets none
        │   ├── manifest.csv
        │   └── <semantic export paths>
        └── logs.jsonl                      # SSH exports when available

    Table CSVs under ``database/`` use pseudonymous participant identifiers so
    the archive remains loadable. Original recruiter identifiers are written to
    the sidecar CSV files. This is identifier separation, not anonymization.
    Empty tables are omitted from ``database/``; ``manifest.json`` still records
    a row count of zero for them. Boolean columns are written as ``True`` /
    ``False`` rather than PostgreSQL ``t`` / ``f``.
    ``manifest.json`` records the deployment git commit instead of bundling
    source code.

    ``--archive`` (debug/deploy) accepts ``export.zip``, a ``database/``
    directory, or an extracted export directory containing ``database/``.

    ``get_exp_variables`` is a zero-argument callable returning the experiment's
    database variables. It is only called when the export actually needs them,
    because for remote experiments it opens an SSH tunnel to the experiment
    database. Server-built exports do not need them: they take the experiment's
    identity from an authenticated preflight instead.

    ``pending_jobs`` is a remote app's async job summary, taken before the
    export (see :func:`_fetch_ssh_pending_async_jobs`); local exports read their
    own. A warning about pending jobs ends the output.
    """
    anonymize = kwargs.pop("anonymize", None)
    _warn_deprecated_export_options(
        no_source, username, password, n_parallel, anonymize=bool(anonymize)
    )

    from .experiment import import_local_experiment

    if app is None and not local:
        raise ValueError(
            "Either the flag --local must be present or an app name must be provided via --app."
        )

    if app is not None and local:
        raise ValueError("You cannot provide both --local and --app arguments.")

    from .export.service import validate_asset_mode

    assets = validate_asset_mode(assets)

    experiment_class = import_local_experiment()["class"]

    config = get_config()
    if not config.ready:
        config.load()

    if local:
        exp_variables = get_exp_variables()
        _confirm_matching_experiment_label(
            exp_variables["label"], experiment_class.label
        )
        deployment_id = exp_variables["deployment_id"]
        assert len(deployment_id) > 0
        load_runtime_server_config(config, deployment_id=deployment_id)

    # Only the default location keeps a rotating history of previous exports.
    rotate_history = experiment_class.rotate_export_history if path is None else None
    path = experiment_class.export_path() if path is None else os.path.expanduser(path)

    from .export.client import TransferError, publish_export, staging_path_for

    staging = staging_path_for(path)
    shutil.rmtree(staging, ignore_errors=True)
    try:
        if local:
            pending_jobs = _build_local_export(str(staging), assets)
        else:
            _fetch_remote_export(
                experiment_class,
                str(staging),
                app=app,
                server=server,
                docker_ssh=docker_ssh,
                config=config,
                assets=assets,
                transfer=transfer,
                allow_project_mismatch=allow_project_mismatch,
            )
        published = publish_export(str(staging), path, rotate_history=rotate_history)
    except TransferError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        log(str(exc))
        raise click.Abort from exc
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    log(f"Export complete. You can find your results at: {published}")
    _warn_export_misses_pending_jobs(pending_jobs)


def _build_local_export(export_path, assets):
    """Build an export directly from the local deployment's database.

    Returns
    -------
    dict or None
        The pending async job summary taken before the export; see
        :func:`_get_local_pending_async_jobs`.
    """
    from .export.service import build_export_tree

    pending_jobs = _get_local_pending_async_jobs()
    log(f"Building export in {export_path}")
    build_export_tree(export_path, assets=assets, local=True)
    return pending_jobs


def _get_local_pending_async_jobs():
    """Summarize the local database's pending async jobs.

    Returns
    -------
    dict or None
        The summary from :func:`psynet.async_job._get_pending_job_summary`,
        or ``None`` after printing a warning if the database could not be
        queried.
    """
    from sqlalchemy.exc import DBAPIError

    from .async_job import _get_pending_job_summary

    try:
        return _get_pending_job_summary()
    except DBAPIError as exc:
        db.session.rollback()
        log(
            "WARNING: Skipped the check for pending async jobs: "
            f"could not query the database ({exc.orig})."
        )
        return None


def _normalize_public_origin(value):
    """Return an origin with no path, query, or fragment.

    Parameters
    ----------
    value : str or None
        Candidate public origin.

    Returns
    -------
    str or None
        The origin, or ``None`` when ``value`` is not an HTTP(S) origin.
    """
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _latest_launch_record(app, server):
    """Return the newest local launch note for this app on this server."""
    root = Path("~/psynet-data/launch-data").expanduser()
    if not root.is_dir():
        return None
    chosen = None
    chosen_mtime = -1
    for path in root.glob("*/launch-info.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            mtime = path.stat().st_mtime
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if payload.get("app") != app or payload.get("server") != server:
            continue
        if mtime >= chosen_mtime:
            chosen = payload
            chosen_mtime = mtime
    return chosen


def _remote_public_origin(app, server):
    """Read ``public_origin`` from the server's deployment manifest."""
    if not isinstance(app, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", app
    ):
        return None
    from dallinger.command_line.docker_ssh import ExecuteException

    from .export.client import SshSession

    command = f'cat "$HOME/dallinger/{shlex.quote(app)}/deployment.json"'
    try:
        with SshSession(server) as session:
            raw = session.executor.run(command, raise_=False)
    except (ExecuteException, OSError, KeyError) as exc:
        log(f"Could not read the remote deployment manifest: {exc}")
        return None
    try:
        payload = json.loads(raw or "")
    except json.JSONDecodeError:
        return None
    return _normalize_public_origin(payload.get("public_origin"))


def _ssh_dashboard_endpoint(app, server, config):
    """Dashboard address and credentials for an SSH deployment.

    Cloudflare apps are not served at ``https://<app>.<ssh-host>``. The
    deploy records the public origin locally; the server manifest is the
    fallback when that note is missing. The note's dashboard credentials take
    precedence over the local config, which may lack them.

    Raises
    ------
    KeyError
        If neither the note nor the config has dashboard credentials.
    """
    from .export.client import DashboardEndpoint

    record = _latest_launch_record(app, server)
    origin = None
    user = config.get("dashboard_user", None)
    password = config.get("dashboard_password", None)
    if record:
        origin = _normalize_public_origin(record.get("public_origin"))
        record_user = record.get("dashboard_user")
        record_password = record.get("dashboard_password")
        if record_user and record_password:
            user = record_user
            password = record_password
    if not (user and password):
        raise KeyError("dashboard_user and dashboard_password")
    if origin is None:
        origin = _remote_public_origin(app, server)
    if origin is None:
        origin = get_experiment_url(app, server)
    return DashboardEndpoint(base_url=origin, auth=(user, password))


_PENDING_JOB_CHECK_TIMEOUT_S = 30


class _PendingJobCheckError(Exception):
    """The check for an SSH app's pending async jobs could not run; the message says why."""


def _fetch_ssh_pending_async_jobs(app, server):
    """Ask a docker-ssh app which async jobs are still pending.

    ``psynet async-job-status`` runs in the app's web container over SSH, so
    the check doesn't depend on the app's public address, which a Cloudflare
    tunnel or DNS may make unreachable, or on dashboard credentials on this
    computer. Wake a hibernated app first (see :func:`_awaken_ssh_app`).

    Parameters
    ----------
    app : str
        The app name.
    server : str
        The configured SSH server.

    Returns
    -------
    dict
        The summary of :func:`psynet.async_job._get_pending_job_summary`.

    Raises
    ------
    _PendingJobCheckError
        If the app could not be checked, including when it doesn't answer
        within ``_PENDING_JOB_CHECK_TIMEOUT_S`` seconds.
    """
    import paramiko

    from .perf_ssh import RemoteApp

    try:
        remote = RemoteApp(_ssh_executor(server), app, server)
        return remote.run_psynet(
            "async-job-status", timeout_s=_PENDING_JOB_CHECK_TIMEOUT_S
        )
    except (click.ClickException, RuntimeError, OSError, paramiko.SSHException) as e:
        if "No such command" in str(e):
            reason = f"{app} runs a PsyNet version without this check"
        else:
            reason = f"could not query {app}'s web container on {server} ({e})"
        raise _PendingJobCheckError(reason) from e


def _fetch_ssh_pending_async_jobs_for_export(app, server):
    """Return :func:`_fetch_ssh_pending_async_jobs`, or ``None`` after a warning if the check can't run."""
    try:
        return _fetch_ssh_pending_async_jobs(app, server)
    except _PendingJobCheckError as e:
        log(
            f"WARNING: Skipped the check for pending async jobs: {e}. The export "
            "continues, but it will not include the results of jobs that haven't "
            "finished; check the app's logs to see whether any are still running."
        )
        return None


@psynet.command("async-job-status", hidden=True)
@click.option("--json-output", required=True, type=click.Path(dir_okay=False))
def async_job_status(json_output):
    """
    Write the running app's pending async jobs to --json-output; used by ``psynet destroy ssh`` and ``psynet export ssh``.
    """
    from .async_job import _get_pending_job_summary
    from .experiment import get_experiment

    load_runtime_server_config()
    # Registers the experiment's own async job classes, whose rows count too.
    get_experiment()
    with open(json_output, "w") as f:
        json.dump(_get_pending_job_summary(), f)


def _warn_export_misses_pending_jobs(summary):
    """Warn that an export lacks the results of pending async jobs."""
    if summary and summary["total"]:
        from .async_job import _describe_pending_jobs

        log(
            f"WARNING: {_describe_pending_jobs(summary)}. This export will not "
            "include their results; export again once they have finished."
        )


def _fetch_remote_export(
    experiment_class,
    export_path,
    *,
    app,
    server,
    docker_ssh,
    config,
    assets,
    transfer,
    allow_project_mismatch,
):
    """Download a server-built export, choosing the cheapest available transport."""
    from .export.client import (
        DashboardEndpoint,
        SshSession,
        TransferError,
        choose_transport,
        download_archive,
        extract_archive,
        fetch_logs,
        fetch_preflight,
        hydrate_assets,
        plan_asset_transfer,
        ssh_rsync_available,
        ssh_rsync_source,
    )
    from .export.identity import (
        ProjectIdentity,
        ProjectMismatch,
        check_export_format_version,
        confirm_project_identity,
        identity_changed,
        identity_from_manifest,
        local_project_identity,
    )

    if docker_ssh and server:
        endpoint = _ssh_dashboard_endpoint(app, server, config)
    else:
        endpoint = DashboardEndpoint(
            base_url=get_experiment_url(app, server),
            auth=(config.get("dashboard_user"), config.get("dashboard_password")),
        )
    local_identity = local_project_identity(experiment_class)

    def check_identity(remote):
        try:
            confirm_project_identity(
                local_identity,
                remote,
                allow_mismatch=allow_project_mismatch,
                emit=log,
            )
        except ProjectMismatch as exc:
            log(str(exc))
            raise click.Abort from exc

    remote_identity = ProjectIdentity.from_dict(fetch_preflight(endpoint))
    check_identity(remote_identity)

    session_cm = SshSession(server) if docker_ssh and server else nullcontext()
    with session_cm as ssh_session:
        over_ssh = ssh_session is not None and (
            assets == "none" or ssh_rsync_available(server, ssh_session)
        )
        chosen = choose_transport(
            remote_identity, assets=assets, over_ssh=over_ssh, requested=transfer
        )
        if (
            chosen == "archive"
            and transfer == "auto"
            and docker_ssh
            and assets != "none"
        ):
            log(
                "Transferring a complete server-built archive; incremental asset "
                "transfer is not available for this deployment or asset selection."
            )

        def download_into_staging(asset_bytes):
            download_dir = tempfile.mkdtemp(prefix="psynet-export-download-")
            try:
                archive_path = os.path.join(download_dir, "export.zip")
                with yaspin(text="Downloading export", color="green") as spinner:
                    download_archive(
                        endpoint, archive_path, assets=assets, asset_bytes=asset_bytes
                    )
                    spinner.ok("✔")
                return extract_archive(archive_path, export_path)
            finally:
                shutil.rmtree(download_dir, ignore_errors=True)

        if chosen == "incremental" and assets != "none":
            manifest = download_into_staging("manifest")
            try:
                plan = plan_asset_transfer(export_path)
                rsync_source, ssh_command = ssh_rsync_source(server, ssh_session)
                with yaspin(
                    text="Fetching missing asset bytes", color="green"
                ) as spinner:
                    materialized = hydrate_assets(
                        export_path,
                        plan,
                        rsync_source=rsync_source,
                        ssh_command=ssh_command,
                    )
                    spinner.ok("✔")
            except TransferError as exc:
                # The server can always read its own asset files, so an archive
                # is still worth trying before giving up on the export.
                log(
                    f"Incremental asset transfer failed: {exc}\n"
                    "Falling back to a complete server-built archive."
                )
                shutil.rmtree(export_path, ignore_errors=True)
                manifest = download_into_staging("include")
            except (OSError, ValueError, subprocess.CalledProcessError) as exc:
                log(
                    f"Incremental asset transfer failed: {exc}\n"
                    "Falling back to a complete server-built archive."
                )
                shutil.rmtree(export_path, ignore_errors=True)
                manifest = download_into_staging("include")
            else:
                log(f"Materialized {materialized} asset(s) from the local cache.")
                from .export.asset_cache import warn_if_cache_oversized

                oversized = warn_if_cache_oversized()
                if oversized:
                    log(oversized)
        else:
            manifest = download_into_staging("include")

        # Always re-check the downloaded manifest. Preflight can race with a
        # redeployment.
        if manifest:
            downloaded_identity = identity_from_manifest(manifest)
            if identity_changed(remote_identity, downloaded_identity):
                raise TransferError(
                    "The downloaded export does not match the deployment that "
                    "answered preflight. The experiment may have been replaced "
                    "during transfer; retry the export."
                )
            else:
                try:
                    check_export_format_version(downloaded_identity)
                except ProjectMismatch as exc:
                    log(str(exc))
                    raise click.Abort from exc

        if ssh_session is not None:
            fetch_logs(export_path, app=app, server=server, session=ssh_session)


def _confirm_matching_experiment_label(exported_label, local_label):
    """Ask the user to confirm an export whose experiment label looks wrong.

    ``exported_label`` may be ``None`` for exports produced by PsyNet versions
    that did not record the label, in which case the check is skipped.
    """
    if exported_label is None or exported_label == local_label:
        return
    if not user_confirms(
        f"The exported experiment's label ({exported_label}) does not seem consistent with the "
        f"local experiment's label ({local_label}). Are you sure you are running the export command from "
        "the right experiment folder? "
        "To continue anyway, press Y and Enter, otherwise just press Enter to cancel."
    ):
        raise click.Abort


###########
# assets  #
###########


@psynet.group("assets")
def assets():
    """Manage the local asset export cache and related utilities."""
    pass


@assets.group("cache")
def assets_cache():
    """Inspect and prune the local content-addressed asset cache."""
    pass


@assets_cache.command("info")
@click.option(
    "--cache-root",
    default=None,
    help="Override the default cache root directory.",
)
def assets_cache_info(cache_root):
    """Print statistics about the local asset cache."""
    from .export.asset_cache import (
        cache_size_bytes,
        default_cache_root,
        list_cached_objects,
        soft_limit_bytes,
        warn_if_cache_oversized,
    )

    root = Path(cache_root).expanduser() if cache_root else default_cache_root()
    objects = list_cached_objects(root)
    total = cache_size_bytes(root)
    limit = soft_limit_bytes()

    click.echo(f"Cache root:      {root}")
    click.echo(f"Cached objects:  {len(objects)}")
    click.echo(f"Total size:      {format_bytes(total)}")
    click.echo(f"Soft limit:      {format_bytes(limit)}")
    warning = warn_if_cache_oversized(root, limit_bytes=limit)
    if warning:
        click.echo(warning)


@assets_cache.command("list")
@click.option(
    "--cache-root",
    default=None,
    help="Override the default cache root directory.",
)
def assets_cache_list(cache_root):
    """List the SHA-256 digests of all objects currently in the cache."""
    from .export.asset_cache import default_cache_root, list_cached_objects

    root = Path(cache_root).expanduser() if cache_root else default_cache_root()
    objects = list_cached_objects(root)

    if not objects:
        click.echo("Cache is empty.")
        return

    for digest in objects:
        click.echo(digest)


@assets_cache.command("prune")
@click.option(
    "--all",
    "prune_all",
    is_flag=True,
    help="Remove every cached object.",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Skip the confirmation prompt.",
)
@click.option(
    "--cache-root",
    default=None,
    help="Override the default cache root directory.",
)
def assets_cache_prune(prune_all, yes, cache_root):
    """Remove every object from the local asset cache.

    Requires ``--all``.
    """
    from .export.asset_cache import (
        default_cache_root,
        list_cached_objects,
        prune_cached_objects,
    )

    if not prune_all:
        click.echo(
            "Specify what to prune.  Currently --all is the only supported mode."
        )
        raise click.UsageError("Missing required option: --all")

    root = Path(cache_root).expanduser() if cache_root else default_cache_root()
    objects = list_cached_objects(root)

    if not objects:
        click.echo("Cache is already empty.")
        return

    click.echo(f"This will remove {len(objects)} cached object(s) from {root}.")
    if not yes:
        click.confirm("Continue?", abort=True)

    removed = prune_cached_objects(cache_root=root)
    click.echo(f"Removed {len(removed)} cached object(s).")


@psynet.command()
@click.option(
    "--ip",
    default="127.0.0.1",
    help="IP address",
)
@click.option("--port", default="4444", help="Port")
def rpdb(ip, port):
    """
    Alias for `nc <ip> <port>`.
    """
    subprocess.run(
        ["nc %s %s" % (ip, port)],
        shell=True,
    )


###########
# load #
###########
@psynet.command()
@click.argument("path")
@require_exp_directory
def load(path):
    """Replace the local database with a provided zip file.

    Stop ``psynet debug`` and any other client using this database role first.
    The command refuses to drop tables while another client using the same
    database role is still connected.
    """
    from .experiment import import_local_experiment

    import_local_experiment()
    try:
        populate_db_from_zip_file(path)
    except DatabaseInUseError as err:
        raise click.ClickException(str(err)) from err


@psynet.command(
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.pass_context
def generate_config(ctx):
    """
    Generate a configuration file for the experiment.
    """
    path = os.path.expanduser("~/.dallingerconfig")
    if os.path.exists(path):
        if not user_confirms(
            f"Are you sure you want to overwrite your existing config file at '{path}'?",
            default=False,
        ):
            raise click.Abort

    with open(path, "w") as file:
        file.write("[Config variables]\n")
        assert len(ctx.args) % 2 == 0
        while len(ctx.args) > 0:
            value = ctx.args.pop()
            key = ctx.args.pop()
            assert not value.startswith("--")
            assert key.startswith("--")
            key = key[2:]
            file.write(f"{key} = {value}\n")


register_bootstrap_commands(psynet)


@psynet.command("update-scripts")
@require_exp_directory
def update_scripts():
    """
    Deprecated alias for ``psynet scripts update``.
    """
    click.echo(
        "psynet update-scripts is deprecated; use 'psynet scripts update' instead.",
        err=True,
    )
    scaffold_experiment_directory(overwrite=True)


@psynet.group("destroy")
def destroy():
    """
    Destroy the experiment.
    """
    pass


@destroy.command("heroku")
@click.option("--app", default=None, callback=verify_id, help="Experiment id")
@click.pass_context
def destroy__heroku(ctx, app):
    """
    Destroy the experiment on Heroku.
    """
    _destroy(
        ctx,
        dallinger.command_line.destroy,
        app=app,
    )


def user_confirms(question, default=False):
    """
    Like click.confirm but safe for using within our wrapped Docker commands.
    """
    print(question + " Enter 'y' for yes, 'n' for no.")
    return click.confirm("", default=default)


def _stdin_is_interactive():
    """Return whether stdin is a terminal, so the user can answer a prompt."""
    return sys.stdin.isatty()


def _confirm_destroy_with_pending_jobs(
    app, summary, ask_for_confirmation, discard_pending_jobs=False
):
    """Report an app's pending async jobs and decide whether to destroy it.

    Parameters
    ----------
    app : str
        The app name.
    summary : dict
        The output of :func:`_fetch_ssh_pending_async_jobs`.
    ask_for_confirmation : bool
        Whether the user may be asked. When ``False`` (batch mode, or a
        future ``--yes``), or when stdin is not a terminal, an app with
        pending jobs is not destroyed.
    discard_pending_jobs : bool
        Destroy the app even if jobs are pending, after reporting them.

    Returns
    -------
    bool
        Whether the app may be destroyed.
    """
    if not summary or not summary["total"]:
        return True
    from .async_job import _describe_pending_jobs

    if discard_pending_jobs:
        log(
            f"WARNING: {app}: {_describe_pending_jobs(summary)}. Discarding them "
            "because --discard-pending-jobs was passed."
        )
        return True
    log(
        f"WARNING: {app}: {_describe_pending_jobs(summary)}. Destroying the app "
        "now loses their results. Wait for them to finish, then run "
        "`psynet export ssh` again before destroying the app."
    )
    if ask_for_confirmation and _stdin_is_interactive():
        return user_confirms("Destroy the app anyway?", default=False)
    log(f"Not destroying {app}. Pass --discard-pending-jobs to destroy it anyway.")
    return False


# Config values in a docker-ssh app's compose file, which Dallinger writes as
# ``    key: "value"`` in the environment of the app's server processes.
_COMPOSE_SETTING = r'(?m)^\s+{}:\s*"?([^"\n]*)"?\s*$'


def _is_debug_ssh_app(server, app):
    """Say whether ``psynet debug ssh`` deployed an SSH app, from the ``debug_ssh_app`` config in its compose file.

    The compose file is read rather than the app's config in its web
    container, which may be what failed. Apps whose compose file can't be
    read count as not deployed by ``psynet debug ssh``.
    """
    import paramiko
    from dallinger.command_line.docker_ssh import ExecuteException

    cmd = f"cat ~/dallinger/{shlex.quote(app)}/docker-compose.yml"
    try:
        compose = _ssh_executor(server).run(
            _with_remote_timeout(cmd, _PENDING_JOB_CHECK_TIMEOUT_S), raise_=False
        )
    except (ExecuteException, OSError, KeyError, paramiko.SSHException) as e:
        log(f"Could not read {app}'s compose file on {server}: {e}")
        return False
    match = re.search(_COMPOSE_SETTING.format("debug_ssh_app"), compose or "")
    return bool(match) and match[1].strip().lower() == "true"


def _destroy_without_pending_job_check(app, server, error, discard_pending_jobs):
    """Decide whether to destroy an SSH app whose pending async jobs couldn't be checked.

    It is destroyed with ``discard_pending_jobs`` (with a warning), or silently
    if ``psynet debug ssh`` deployed it (see :func:`_is_debug_ssh_app`).

    Parameters
    ----------
    app : str
        The app name.
    server : str
        The configured SSH server.
    error : _PendingJobCheckError
        Why the check couldn't run.
    discard_pending_jobs : bool
        Whether ``--discard-pending-jobs`` was passed.

    Returns
    -------
    bool
        Whether the app may be destroyed.
    """
    problem = f"Could not check {app} for pending async jobs: {error}."
    if discard_pending_jobs:
        log(
            f"WARNING: {problem} Destroying it anyway because "
            "--discard-pending-jobs was passed."
        )
        return True
    if _is_debug_ssh_app(server, app):
        return True
    log(
        f"{problem} Not destroying {app}, because destroying it would lose the "
        "results of any jobs still running. If its web container isn't "
        f"running, start it (see 'psynet apps ssh --server {server}' or its "
        f"logs {where_to_read_logs(server, app)}) and run this command again. "
        "Otherwise check in its "
        "logs that its async jobs have finished, then pass "
        "--discard-pending-jobs to destroy it anyway."
    )
    return False


def _destroy(
    ctx,
    f_destroy,
    app,
    server=None,
    ask_for_confirmation=True,
    discard_pending_jobs=False,
):
    """Destroy a single app.

    For docker-ssh apps (``server`` given), first wake the app and check for
    pending async jobs with :func:`_confirm_destroy_with_pending_jobs`, or
    :func:`_destroy_without_pending_job_check` if the check can't run.
    """
    target = app or "the app"
    if server:
        target += f" from {server}"
        _awaken_ssh_app(server, app)
        try:
            pending_jobs = _fetch_ssh_pending_async_jobs(app, server)
        except _PendingJobCheckError as e:
            may_destroy = _destroy_without_pending_job_check(
                app, server, e, discard_pending_jobs
            )
        else:
            may_destroy = _confirm_destroy_with_pending_jobs(
                app, pending_jobs, ask_for_confirmation, discard_pending_jobs
            )
        if not may_destroy:
            return False
    confirmed = (
        user_confirms(f"Would you like to delete {target}?", default=True)
        if ask_for_confirmation
        else True
    )

    if confirmed:
        with yaspin(f"Destroying {app}...") as spinner:
            try:
                kwargs = {"app": app}
                kwargs = {**kwargs, "server": server} if server else kwargs
                # Dallinger still exposes this retired-platform option. Keep
                # it disabled until the upstream command removes it.
                if "expire_hit" in get_args(f_destroy):
                    ctx.invoke(
                        f_destroy,
                        expire_hit=False,
                        **kwargs,
                    )
                else:
                    ctx.invoke(
                        f_destroy,
                        **kwargs,
                    )
                spinner.ok("✔")
            except subprocess.CalledProcessError:
                spinner.fail("✗")
                click.echo(
                    f"Failed to destroy {app}. "
                    "Maybe it was already destroyed, or the app name was wrong?"
                )
                return False
            except click.Abort:
                spinner.fail("✗")
                raise
        return True
    return False


@psynet.group("hibernate")
def hibernate():
    """
    Hibernate a deployed experiment.
    """
    pass


@hibernate.command("ssh")
@click.option("--app", required=True, callback=verify_id, help="Experiment id")
@option_server
@click.pass_context
def hibernate__ssh(ctx, app, server):
    """
    Hibernate the experiment on a remote server via SSH.
    """
    ctx.invoke(_dallinger_hibernation_command("hibernate"), server=server, app=app)


@psynet.group("awaken")
def awaken():
    """
    Awaken a hibernated experiment.
    """
    pass


@awaken.command("ssh")
@click.option("--app", required=True, callback=verify_id, help="Experiment id")
@option_server
@click.pass_context
def awaken__ssh(ctx, app, server):
    """
    Awaken the experiment on a remote server via SSH.
    """
    ctx.invoke(_dallinger_hibernation_command("awaken"), server=server, app=app)


def _dallinger_hibernation_command(name):
    """Return Dallinger's docker-ssh ``hibernate`` or ``awaken`` command."""
    docker_ssh = importlib.import_module("dallinger.command_line.docker_ssh")
    command = getattr(docker_ssh, name, None)
    if command is None:
        raise click.UsageError(
            "The installed Dallinger does not support docker-ssh hibernation."
        )
    return command


@destroy.command("ssh")
@click.option("--app", default=None, help="Experiment id")
@click.argument("apps", required=False, nargs=-1)
@option_server
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Skip the confirmation prompt.",
)
@click.option(
    "--discard-pending-jobs",
    is_flag=True,
    default=False,
    help=(
        "Destroy apps even if they still have pending async jobs, or if "
        "they can't be checked for them, losing those jobs' results."
    ),
)
@click.pass_context
def destroy__docker_ssh(ctx, app, apps, server, yes, discard_pending_jobs):
    """
    Destroy the experiment on a remote server via SSH.

    Apps with pending async jobs are not destroyed unless you confirm
    interactively or pass --discard-pending-jobs; --yes does not skip that.
    Apps that can't be checked for pending jobs are not destroyed without
    --discard-pending-jobs, except apps deployed with `psynet debug ssh` or
    `psynet performance-test ssh`.
    """
    from dallinger.command_line.docker_ssh import destroy

    example_usage = "`psynet destroy ssh <app> <app> [--server <server>]`"
    if not app and not apps:
        raise click.UsageError(f"Provide an app name. Example: {example_usage}")
    if app:
        assert len(apps) == 0, "You cannot provide both --app and a list of apps."
        click.echo(f"Consider using the batch syntax: {example_usage}")
        if not _destroy(
            ctx,
            destroy,
            app=app,
            server=server,
            ask_for_confirmation=not yes,
            discard_pending_jobs=discard_pending_jobs,
        ):
            raise click.Abort()
    if len(apps) > 0:
        assert app is None, "You cannot provide both --app and a list of apps."
        confirmation = f"""
            Are you sure you want to remove {len(apps)} apps on {server} ({apps})?
            """
        if yes or click.confirm(confirmation, abort=True):
            failed = []
            for app in apps:
                try:
                    if not _destroy(
                        ctx,
                        destroy,
                        app=app,
                        server=server,
                        ask_for_confirmation=False,
                        discard_pending_jobs=discard_pending_jobs,
                    ):
                        failed.append(app)
                except click.Abort:
                    click.echo(
                        f"Failed to destroy {app}. "
                        "Maybe it was already destroyed, or the app name was wrong?"
                    )
                    failed.append(app)
                except Exception:
                    logger.exception(
                        "Failed to destroy app %s; continuing with remaining apps.",
                        app,
                    )
                    click.echo(
                        f"Failed to destroy {app}; continuing with remaining apps."
                    )
                    failed.append(app)
            if failed:
                raise click.Abort()


@psynet.group("apps")
def apps():
    """
    List the apps on the server.
    """
    pass


@apps.command("ssh")
@option_server
@click.pass_context
def apps__docker_ssh(ctx, server):
    from dallinger.command_line.docker_ssh import apps

    _apps = ctx.invoke(apps, server=server)
    if len(_apps) == 0:
        click.echo("No apps found.")


@psynet.group("stats")
def stats():
    """
    Show the stats of the experiment.
    """
    pass


@stats.command("ssh")
@option_server
@click.pass_context
def stats__docker_ssh(ctx, server):
    from dallinger.command_line.docker_ssh import stats

    ctx.invoke(stats, server=server)


@psynet.group("test")
@click.pass_context
@require_exp_directory
def test(ctx):
    """
    Test the experiment.
    """
    pass


_test_options = {}

_test_options["existing"] = click.option(
    "--existing",
    is_flag=True,
    help="Use this flag if the experiment server is already running",
)

_test_options["n_bots"] = click.option(
    "--n-bots",
    type=click.IntRange(min=1),
    help="Number of bots to use in the test. If not specified, will default to Experiment.test_n_bots.",
)

_test_options["parallel"] = click.option(
    "--parallel",
    is_flag=True,
    help=(
        "Forces the tests to be run in parallel, overriding the default specified in the Experiment class. "
        "Only relevant if the number of bots is greater than 1. Does the opposite of --serial."
    ),
)

_test_options["serial"] = click.option(
    "--serial",
    is_flag=True,
    help=(
        "Forces the tests to be run serially, overriding the default specified in the Experiment class. "
        "Does the opposite of --parallel."
    ),
)

_test_options["stagger"] = click.option(
    "--stagger",
    type=float,
    help="""
    Time interval to wait (in seconds) between instantiating each parallel bot.
    If not specified, will default to Experiment.test_parallel_stagger_interval_s (0.1 s)""",
)

_test_options["time_factor"] = click.option(
    "--time-factor",
    type=float,
    default=0.0,
    help="Multiply the timings in time_estimate by this factor. When equal to zero (the default value), the bot will run through the experiment as fast as possible.",
)


def _in_isolated_test_environment(func):
    """Run a local test or performance-test command in its own database, Redis and port.

    Applied outside :func:`sql_profiled_command` so that only the re-run child
    profiles and reports. With ``--existing`` the command tests a live server,
    so it runs in this process.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        from .isolated_environment import (
            READY_ENV_VAR,
            shared_environment_warning,
            should_isolate,
        )

        if not kwargs.get("existing"):
            try:
                isolate = should_isolate()
            except ValueError as e:
                raise click.ClickException(str(e)) from e
            if isolate:
                _rerun_in_isolated_test_environment()
            warning = shared_environment_warning()
            if warning:
                log(warning)
                os.environ[READY_ENV_VAR] = "1"
        return func(*args, **kwargs)

    return wrapper


@test.command("local")
@_test_options["existing"]
@_test_options["n_bots"]
@_test_options["parallel"]
@_test_options["serial"]
@_test_options["stagger"]
@_test_options["time_factor"]
@_add_sql_profile_options
@_in_isolated_test_environment
@sql_profiled_command
def test__local(
    existing=False,
    n_bots=None,
    parallel=None,
    serial=None,
    stagger=None,
    time_factor=None,
    sql_profile=False,
    sql_profile_options=None,
    sql_profile_dir=None,
    sql_profile_format=None,
    sql_profile_no_open=False,
):
    """
    Test the experiment locally.

    The tests get a free port, a database and a Redis server of their own, so
    they leave local debug servers alone. Set PSYNET_TEST_ENVIRONMENT=shared
    to run them against the local ones instead, which resets them.
    """
    assert not (parallel and serial)

    # --existing talks to a live server; skip local scaffold/git readiness.
    # Non-existing runs share debug's directory checks (incl. bundled-demo prepare).
    if not existing:
        _check_experiment_directory("test")

    # Same local Postgres/Redis requirement as ``psynet debug local`` /
    # ``psynet deploy local`` (virtualenv mode).
    from .services import ensure_local_services

    ensure_local_services(assume_yes=False, strict=True)

    from psynet.experiment import get_experiment

    if existing:
        load_runtime_server_config()
    exp = get_experiment()

    if n_bots:
        n_bots = int(n_bots)
        exp.test_n_bots = n_bots

    if parallel:
        exp.test_mode = "parallel"
    elif serial:
        exp.test_mode = "serial"

    if stagger:
        exp.test_parallel_stagger_interval_s = float(stagger)

    if time_factor:
        exp.test_time_factor = time_factor

    if existing:
        # Unlike the pytest path below, this reports nothing on its own, which
        # previously made a remote `psynet test ssh` look like it had done
        # nothing at all.
        click.echo(f"Running {exp.test_n_bots} bot(s) against the existing server...")
        exp.test_experiment()
        click.echo(f"Bot test passed ({exp.test_n_bots} bot(s)).")
        return

    import pytest

    exit_code = pytest.main(["test.py"])
    if exit_code != 0:
        # Use sys.exit() to ensure that the exit code is propagated to the shell.
        # This is helpful for CI pipelines, where we want to fail the build if the tests fail.
        sys.exit(exit_code)


def _rerun_in_isolated_test_environment():
    """Re-run this command in a child process with its own database, Redis and port.

    Dallinger connected to the shared database when this module was imported,
    so the switch needs a new process; see :mod:`psynet.isolated_environment`.
    The child re-runs the whole original command line (for example
    ``psynet test local --n-bots 4``) with this interpreter, and this process
    then exits with its code; if it was interrupted and the child exited with
    0, it exits with 130 after Ctrl+C and 143 after SIGTERM. SIGTERM is passed on to the
    child, which gets Ctrl+C from the terminal anyway. A second signal kills
    the child.
    """
    from .isolated_environment import IsolatedEnvironment
    from .services import SERVICES_CHECKED_ENV_VAR, ensure_local_services

    _check_no_debug_server_here()
    # Before creating the database and Redis, so that an experiment that isn't
    # set up fails without advice about services it won't use.
    _check_experiment_directory("test")
    ensure_local_services(assume_yes=False, strict=True)
    try:
        environment = IsolatedEnvironment.start()
    except RuntimeError as e:
        raise click.ClickException(str(e)) from e
    exit_code = 130
    interrupted = None
    with environment, _exit_on_sigterm():
        log(environment.describe())
        # On macOS framework builds, sys.orig_argv[0] is the framework's own
        # interpreter, which runs outside the virtual environment.
        process = subprocess.Popen(
            [sys.executable, *sys.orig_argv[1:]],
            env={**environment.env, SERVICES_CHECKED_ENV_VAR: "1"},
        )
        while True:
            try:
                exit_code = process.wait()
                break
            except (KeyboardInterrupt, SystemExit) as e:
                # Let the child stop its servers, unless signalled again.
                if interrupted is not None and process.poll() is None:
                    process.kill()
                elif isinstance(e, SystemExit):
                    process.terminate()
                interrupted = 130 if isinstance(e, KeyboardInterrupt) else e.code
    # A child killed by signal N reports -N; shells report 128 + N.
    if exit_code < 0:
        exit_code = 128 - exit_code
    sys.exit(exit_code or interrupted or 0)


def _check_no_debug_server_here():
    """Raise ``click.ClickException`` if ``psynet debug`` serves the current directory."""
    from .isolated_environment import check_no_debug_server

    try:
        check_no_debug_server(os.getcwd())
    except RuntimeError as e:
        raise click.ClickException(str(e)) from e


def build_remote_experiment_command(app, cmd):
    """Build a remote shell command that runs ``cmd`` inside the app's web container.

    ``docker compose exec -T`` disables TTY allocation, which is what makes the
    command safe to run when the local process has no interactive terminal.
    """
    return f"cd ~/dallinger/{shlex.quote(app)} && docker compose exec -T web {cmd}"


def _stop_when_disconnected(cmd):
    """Wrap ``cmd`` in a shell command that stops it once its stdin closes.

    Docker leaves an exec'd process running when its client goes away, so a
    dropped SSH connection would leave a load test running unwatched. The SSH
    session never writes to the container's stdin, which therefore reaches
    end-of-file only when the session ends.
    """
    script = (
        "exec 3<&0; "
        f"{cmd} </dev/null & pid=$!; "
        '(cat <&3 >/dev/null; kill "$pid") >/dev/null 2>&1 & '
        'wait "$pid"'
    )
    return f"sh -c {shlex.quote(script)}"


# GNU timeout's exit status for a command that it stopped.
_REMOTE_TIMEOUT_STATUS = 124
# How much longer than the server's timeout to wait for an answer over SSH.
_SSH_TIMEOUT_GRACE_S = 10


def _with_remote_timeout(cmd, timeout_s):
    """Wrap the server shell command ``cmd`` so that the server stops it after ``timeout_s`` seconds."""
    return f"timeout {int(timeout_s)} sh -c {shlex.quote(cmd)}"


def run_remote_experiment_command(executor, app, cmd, timeout_s=None):
    """Run ``cmd`` in the app's web container, echoing its output as it arrives.

    Dallinger's ``Executor.run_and_echo`` also watches local stdin so that the user
    can quit by pressing ``q``; that makes it exit immediately when stdin is closed
    or not a terminal, which silently truncates long-running remote tests. This
    helper only reads the remote channel, and raises ``click.ClickException`` if
    the remote command fails.

    Output is read to end-of-file rather than until the remote exit status is
    available. The exit status arrives before the last of the output, so polling
    on it drops whatever is still in flight -- typically the test summary, which
    is the part worth reading.

    With ``timeout_s``, the command is stopped after that many seconds and
    ``click.ClickException`` says so.
    """
    remote_cmd = build_remote_experiment_command(app, _stop_when_disconnected(cmd))
    if timeout_s is not None:
        remote_cmd = _with_remote_timeout(remote_cmd, timeout_s)
        deadline = time.monotonic() + timeout_s + _SSH_TIMEOUT_GRACE_S
    channel = executor.client.get_transport().open_session()
    # Closing the channel, also after Ctrl-C, ends the remote command's stdin,
    # which stops it (see _stop_when_disconnected).
    try:
        if timeout_s is not None:
            channel.settimeout(timeout_s + _SSH_TIMEOUT_GRACE_S)
        # Interleaving two streams without threads risks reordering the output,
        # and the caller only wants to read it, so merge stderr into stdout.
        channel.set_combine_stderr(True)
        channel.exec_command(remote_cmd)

        recent = collections.deque(maxlen=50)
        with channel.makefile("rb", 0) as stream:
            for line in iter(stream.readline, b""):
                text = line.decode("utf-8", "replace")
                recent.append(text.strip())
                sys.stdout.write(text)
                sys.stdout.flush()

        if timeout_s is not None:
            while not channel.exit_status_ready():
                if time.monotonic() > deadline:
                    raise TimeoutError
                time.sleep(0.1)
        status = channel.recv_exit_status()
    except TimeoutError as e:
        raise click.ClickException(f"no answer within {timeout_s} s") from e
    finally:
        channel.close()
    if timeout_s is not None and status == _REMOTE_TIMEOUT_STATUS:
        raise click.ClickException(f"no answer within {timeout_s} s")
    if status != 0:
        log(f"The following remote command failed with exit code {status}:\n{cmd}")
        raise click.ClickException(_remote_failure_summary(status, recent))
    return status


def _remote_failure_summary(status, recent_lines):
    """Return ``exit code N``, followed by the last error line of a failed remote command's output.

    Without an error line, the last non-empty line is used instead, if any.
    """
    lines = [line for line in recent_lines if line]
    errors = [line for line in lines if re.search(r"Error\b|Exception\b|FATAL\b", line)]
    last = (errors or lines)[-1:]
    return f"exit code {status}" + (f": {last[0]}" if last else "")


@test.command("ssh")
@click.option("--app", required=True, help="Name of the experiment app.")
@option_server
@_test_options["n_bots"]
@_test_options["parallel"]
@_test_options["serial"]
@_test_options["stagger"]
@_test_options["time_factor"]
@click.pass_context
def test__docker_ssh(
    ctx,
    app,
    server,
    n_bots=None,
    parallel=None,
    serial=None,
    stagger=None,
    time_factor=None,
):
    """
    Runs experiment tests on the remote server.
    Assumes that the app has already been launched on the remote server using ``psynet debug ssh``.

    Running this command will not reset the database to a vanilla state, but will instead just use the state
    that exists already. This may cause strange results if the tests are run multiple times.

    Note: this feature is currently experimental and the API is likely to change without warning.
    """
    cmd = "psynet test local --existing"

    if n_bots:
        cmd += f" --n-bots {n_bots}"

    if parallel:
        cmd += " --parallel"

    if serial:
        cmd += " --serial"

    if stagger:
        cmd += f" --stagger {stagger}"

    if time_factor:
        cmd += f" --time-factor {time_factor}"

    run_remote_experiment_command(_ssh_executor(server), app, cmd)


def _validate_performance_n_bots(ctx, param, value):
    """Click callback: return ``--n-bots`` as ``"auto"``, a list of bot counts, or ``None``."""
    if value is None:
        return None
    if value.strip().lower() == "auto":
        return "auto"
    try:
        counts = [int(x) for x in value.split(",")]
    except ValueError:
        counts = []
    if not counts or any(n < 1 for n in counts):
        raise click.BadParameter(
            "use 'auto' or comma-separated whole numbers of at least 1, such as 5,10,20."
        )
    return counts


_test_options["performance_n_bots"] = click.option(
    "--n-bots",
    callback=_validate_performance_n_bots,
    help="""
    Bots at once in each test: a comma-separated list, such as 5,10,20, runs
    one test per count, and 'auto' searches for the most bots that stay within
    the capacity limits, then runs a validation test at the recommended
    number (see 'Testing scalability' in the docs). Defaults to
    Experiment.test_n_bots.""",
)

_test_options["performance_no_confirm"] = click.option(
    "--no-confirm",
    is_flag=True,
    help="""
    With --n-bots auto, skip the validation test at the recommended number
    of participants, which can take up to an hour.""",
)


def _validate_bot_processes(ctx, param, value):
    """Click callback: return ``--bot-processes`` as ``"auto"`` or a whole number."""
    if value.strip().lower() == "auto":
        return "auto"
    try:
        n_processes = int(value)
    except ValueError:
        n_processes = 0
    if n_processes < 1:
        raise click.BadParameter("use 'auto' or a whole number of at least 1.")
    return n_processes


_test_options["performance_bot_processes"] = click.option(
    "--bot-processes",
    default="auto",
    show_default=True,
    callback=_validate_bot_processes,
    help="""
    Number of processes to run the bots in. 'auto' uses a process per 250
    bots, up to one per four CPU cores.""",
)

_test_options["performance_force"] = click.option(
    "--force",
    is_flag=True,
    help="""
    Run even if the database has participants that PsyNet bots didn't
    create, or the experiment runs in live mode or with a recruiter that
    may bring real participants (e.g. Prolific or Cint).""",
)

_test_options["performance_max_p95_ms"] = click.option(
    "--max-p95-ms",
    type=click.FloatRange(min=0, min_open=True),
    default=None,
    help="""
    The 95th-percentile response time of /timeline and /response that a
    passing test may reach. Defaults to 500.""",
)

_test_options["performance_max_queue_p95_s"] = click.option(
    "--max-queue-p95-s",
    type=click.FloatRange(min=0),
    default=None,
    help="""
    The 95th-percentile time, in seconds, that high-priority async jobs may
    wait for a worker in a passing test. Defaults to 5.""",
)

_test_options["performance_time_factor"] = click.option(
    "--time-factor",
    type=click.FloatRange(min=0),
    default=1.0,
    show_default=True,
    help="""
    Pace the bots at about this multiple of the timeline's time estimates;
    each bot's pace varies from 0.7 to 3 times it. 0 runs the bots as fast
    as possible.""",
)

_test_options["performance_stagger"] = click.option(
    "--stagger",
    type=click.FloatRange(min=0),
    help="""
    Average seconds between starting bots. Defaults to
    Experiment.test_parallel_stagger_interval_s (0.1 s).""",
)

_test_options["performance_arrival_minutes"] = click.option(
    "--arrival-minutes",
    type=click.FloatRange(min=0, min_open=True),
    default=None,
    help="""
    Spread each test's bots evenly over this many minutes, as participants
    arrive while a study is open, instead of --stagger. Not with --n-bots
    auto, whose validation test spreads them over one session.""",
)

_test_options["duration_minutes"] = click.option(
    "--duration-minutes",
    type=click.FloatRange(min=0, min_open=True),
    default=None,
    help="""
    Length of each test in minutes. Defaults to 1.5 participant sessions
    (at most 30 minutes), or one session (at most 5 minutes) for the tests
    of --n-bots auto.""",
)

_test_options["performance_json_output"] = click.option(
    "--json-output",
    type=click.Path(dir_okay=False, writable=True),
    default=None,
    help="""
    Write the results, with the run's options and environment, to this path
    as JSON after each test (see 'Testing scalability' in the docs).""",
)


def _performance_load_options(function):
    """Add the options that set a performance test's load and limits."""
    for name in reversed(
        [
            "performance_n_bots",
            "performance_stagger",
            "performance_time_factor",
            "duration_minutes",
            "performance_arrival_minutes",
            "performance_no_confirm",
            "performance_max_p95_ms",
            "performance_max_queue_p95_s",
            "performance_bot_processes",
        ]
    ):
        function = _test_options[name](function)
    return function


# ``performance-test ssh`` chooses where the remote run writes its bot log, so
# that it can copy the log back afterwards. It also prints where it saved the
# log and results, so the remote run doesn't print the container's paths.
_test_options["performance_bot_log"] = click.option(
    "--bot-log",
    type=click.Path(dir_okay=False, writable=True),
    default=None,
    hidden=True,
)

# ``performance-test ssh`` runs each test of its suite on its own in the
# web container: with a label, ``performance-test local`` runs one test of
# one bot count, without the suite's header and summary.
_test_options["performance_test_label"] = click.option(
    "--test-label",
    default=None,
    hidden=True,
)

# A later test of such a suite without database resets first pauses as a
# local suite would between tests, for a suite that started this long ago.
_test_options["performance_suite_started_s_ago"] = click.option(
    "--suite-started-s-ago",
    type=click.FloatRange(min=0),
    default=None,
    hidden=True,
)

AUDIT_PERFORMANCE_JSON = Path("artifacts") / "performance.json"
SIMULATED_EXPORT_PATH = Path("simulate") / "analysis" / "simulated_export"
AUDIT_ARTIFACT_IDS = {
    AUDIT_PERFORMANCE_JSON: "performance_result",
    SIMULATED_EXPORT_PATH: "simulate_export",
}


def resolve_audit_root() -> Path:
    """Resolve ``./audit`` for audit CLI commands."""
    from psynet.audit.cli import resolve_audit_dir

    try:
        return resolve_audit_dir(require_manifest=True)
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc


def resolve_audit_artifact_path(relative_path: Path) -> Path:
    """Resolve ``./audit/<relative_path>``, creating parents.

    Parameters
    ----------
    relative_path :
        Path relative to the resolved audit folder.
    """
    output_path = resolve_audit_root() / relative_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return output_path


def mark_audit_artifact_present(relative_path: Path) -> Path:
    """Mark the canonical artifact for ``relative_path`` present in the packet.

    Updates the artifact's declared path to ``relative_path`` so a custom
    manifest cannot be marked present against a different file.
    """
    from psynet.audit.cli import mark_artifact_present

    artifact_id = AUDIT_ARTIFACT_IDS.get(Path(relative_path))
    if artifact_id is None:
        raise RuntimeError(f"No audit artifact id is registered for {relative_path}.")
    audit_root = resolve_audit_root()
    try:
        mark_artifact_present(
            audit_root, artifact_id, path=Path(relative_path).as_posix()
        )
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Marked {artifact_id} present in {audit_root / 'audit.json'}")
    return audit_root


def performance_results_have_successful_bots(all_results) -> bool:
    """Return True when any :class:`~psynet.perf_test.PerformanceTestResult` completed a bot."""
    return any(result.bots_succeeded > 0 for result in all_results or [])


def mark_performance_result_present(all_results) -> None:
    """Mark ``performance_result`` present after a successful audit run."""

    if not performance_results_have_successful_bots(all_results):
        click.echo(
            "Skipping performance_result mark-present: no bots succeeded. "
            "The JSON was still written; re-run a successful test or mark present later.",
            err=True,
        )
        return
    mark_audit_artifact_present(AUDIT_PERFORMANCE_JSON)


def _replace_directory(source: Path, destination: Path) -> None:
    """Replace *destination* with *source*, restoring *destination* on failure."""

    backup = destination.with_name(f".{destination.name}.bak")
    if backup.exists():
        shutil.rmtree(backup)
    had_destination = destination.exists()
    if had_destination:
        destination.rename(backup)
    try:
        source.rename(destination)
    except OSError:
        if had_destination and backup.exists() and not destination.exists():
            backup.rename(destination)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def _run_simulate(ctx, n_bots=None):
    """Run experiment bots and export their data into the audit packet.

    Parameters
    ----------
    ctx :
        Click context used to invoke ``psynet test local`` and ``psynet export local``.
    n_bots :
        Number of bots; defaults to ``Experiment.test_n_bots``.
    """

    from psynet.audit.content import artifact_path_is_ready

    export_path = resolve_audit_artifact_path(SIMULATED_EXPORT_PATH)
    ctx.invoke(test__local, n_bots=n_bots)
    staging = Path(
        tempfile.mkdtemp(prefix=".simulated_export.", dir=export_path.parent)
    )
    try:
        ctx.invoke(
            export__local,
            # The experiment server has stopped; export reads the local database.
            no_source=True,
            path=staging.as_posix(),
        )
        if not artifact_path_is_ready(staging, allow_directory=True):
            raise click.ClickException(f"Simulate produced no files in {staging}.")
        _replace_directory(staging, export_path)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    click.echo(f"Simulated export: {export_path}")
    mark_audit_artifact_present(SIMULATED_EXPORT_PATH)


@psynet.group("performance-test")
@click.pass_context
@require_exp_directory
def performance_test(ctx):
    """
    Performance test the experiment.
    """
    pass


@performance_test.command("local")
@_test_options["existing"]
@_performance_load_options
@_test_options["performance_json_output"]
@_test_options["performance_bot_log"]
@_test_options["performance_test_label"]
@_test_options["performance_suite_started_s_ago"]
@_test_options["performance_force"]
@click.option("--debug", is_flag=True, help="Enable debug logging for verbose output")
@_in_isolated_test_environment
def performance_test__local(existing=False, json_output=None, debug=False, **options):
    """
    Run a performance test of the experiment locally.

    The --n-bots parameter can accept a comma-separated list of integers
    to run sequential tests with different concurrency levels.
    Example: --n-bots "5,10,20" will run three separate tests, and
    --n-bots auto searches for the most bots that pass the limits.

    By default, this command starts a new experiment server automatically,
    with a free port, a database and a Redis server of its own, so it leaves
    local debug servers alone (set PSYNET_TEST_ENVIRONMENT=shared to use the
    local ones instead, which resets them). Use --existing to connect to an
    already-running server instead.

    This command never updates an experiment audit. Use
    ``psynet audit performance-test`` to collect audit evidence.
    """
    with _exit_on_sigterm():
        return _run_performance_test_local(
            existing=existing, json_output=json_output, debug=debug, **options
        )


def _run_performance_test_local(*, existing, json_output, debug, **options):
    """Run a local performance test and return its result records.

    ``options`` are the performance-test options, such as ``n_bots``.
    """
    _check_arrival_options(**options)
    if existing:
        return _run_performance_test_with_existing_server(
            debug=debug, json_output=json_output, **options
        )
    return _run_performance_test_with_new_server(
        debug=debug, json_output=json_output, **options
    )


def _collect_run_metadata(experiment_label):
    """Capture environment metadata that makes a results file self-describing."""
    import platform as _platform

    import dallinger.version

    import psynet

    return {
        "psynet_version": psynet.__version__,
        "dallinger_version": dallinger.version.__version__,
        "python_version": _platform.python_version(),
        "platform": _platform.platform(),
        "experiment_label": experiment_label,
    }


def _write_json_results(json_output, *, metadata, options, all_results):
    """Write performance test results plus the metadata that produced them to JSON."""
    from dataclasses import asdict

    payload = {
        "schema_version": 1,
        **metadata,
        "options": options,
        "results": [asdict(r) for r in all_results],
    }
    # Written to a temporary file and renamed, so that an interrupt can't
    # leave a truncated file in place of the last complete one.
    # Unlike mkstemp's owner-only files, open() applies the umask.
    path = Path(json_output)
    temporary = path.with_name(f".{path.name}.{os.urandom(6).hex()}.tmp")
    try:
        with open(temporary, "x") as f:
            json.dump(payload, f, indent=2, allow_nan=False, default=str)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _check_existing_server_answers():
    """Raise ``click.ClickException`` unless a server runs for this shell's settings."""
    from psynet.perf_test import server_is_reachable

    if redis_vars.get("base_url", None) is None:
        raise click.ClickException(
            "No experiment server has registered in this shell's Redis. Start one "
            "with psynet debug local, or set REDIS_URL and DATABASE_URL to those "
            "of the running server."
        )
    base_url = get_experiment_url()
    if not server_is_reachable(base_url):
        raise click.ClickException(
            f"No server answers at {base_url}. Start one with psynet debug local, "
            "or remove --existing."
        )


_KEPT_PERFORMANCE_LOGS = 20


def _performance_log_directory():
    """Return this user's folder for performance-test logs, pruning old logs.

    Each run writes a server log and a bot log; only the newest
    ``_KEPT_PERFORMANCE_LOGS`` of each kind are kept. If the shared temporary
    folder already holds that folder but another user owns it or may write
    to it, a new private folder is used instead.
    """
    try:
        user = getpass.getuser()
    except (KeyError, OSError):
        # Containers run as the host uid, which may have no account or USER.
        user = str(os.getuid())
    directory = Path(tempfile.gettempdir()) / f"psynet-performance-logs-{user}"
    directory.mkdir(mode=0o700, exist_ok=True)
    info = directory.lstat()
    if (
        directory.is_symlink()
        or info.st_uid != os.getuid()
        or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    ):
        logger.warning(
            f"{directory} isn't private to this user, so the logs go to a new folder."
        )
        return Path(tempfile.mkdtemp(prefix="psynet-performance-logs-"))
    for prefix in ("psynet_server_", "psynet_bots_"):
        logs = []
        for path in directory.glob(f"{prefix}*.log"):
            try:
                logs.append((path.stat().st_mtime, path))
            except FileNotFoundError:
                continue
        for _mtime, path in sorted(logs, reverse=True)[_KEPT_PERFORMANCE_LOGS - 1 :]:
            path.unlink(missing_ok=True)
    return directory


def _run_performance_test_with_existing_server(
    *,
    debug=False,
    json_output=None,
    n_bots=None,
    stagger=None,
    time_factor=1.0,
    duration_minutes=None,
    arrival_minutes=None,
    bot_processes="auto",
    bot_log=None,
    test_label=None,
    suite_started_s_ago=None,
    force=False,
    **suite_options,
):
    """Run performance test connecting to an already-running server.

    With ``test_label``, it runs a single test of the one count in ``n_bots``
    under that label, without a suite; with ``suite_started_s_ago`` too, it
    first pauses as between the tests of a suite that started that long ago.
    ``suite_options`` are those of :func:`_run_performance_suite`.
    """
    import logging
    import sys

    from psynet.experiment import get_experiment
    from psynet.perf_test import log_to_console

    log_to_console(logging.DEBUG if debug else logging.INFO)

    load_runtime_server_config()
    _check_existing_server_answers()

    try:
        exp = get_experiment()
    except Exception as e:
        print(f"ERROR: Failed to get experiment: {e}", file=sys.stderr)
        print(
            "Make sure the experiment server is running first (psynet debug local)",
            file=sys.stderr,
        )
        sys.exit(1)

    from psynet.perf_test import PerformanceTester

    _check_no_real_participants(force)
    os.environ["PASSTHROUGH_ERRORS"] = "True"

    bot_counts = n_bots or [exp.test_n_bots]
    if test_label is not None and (bot_counts == "auto" or len(bot_counts) != 1):
        raise click.UsageError("--test-label runs one test of one --n-bots count.")

    estimated_duration_minutes = exp.estimated_duration_in_minutes
    tester = PerformanceTester(
        authenticated_session=exp.authenticated_session,
        base_url=exp.base_url,
        duration_minutes=_performance_test_duration(
            estimated_duration_minutes=estimated_duration_minutes,
            minimum_minutes=exp.test_duration_minutes,
            time_factor=time_factor,
            duration_minutes=duration_minutes,
            arrival_minutes=arrival_minutes,
            find_capacity=bot_counts == "auto",
        ),
        stagger_interval_s=(
            exp.test_parallel_stagger_interval_s if stagger is None else float(stagger)
        ),
        time_factor=time_factor,
        bot_processes=bot_processes,
        estimated_duration_minutes=estimated_duration_minutes,
        arrival_minutes=arrival_minutes,
    )
    # Bot processes append to this log too.
    if bot_log is None:
        bot_log_file = tempfile.NamedTemporaryFile(
            mode="a",
            delete=False,
            prefix="psynet_bots_",
            suffix=".log",
            dir=_performance_log_directory(),
        )
    else:
        # Bot processes append to the log, so clear an earlier run's output first.
        open(bot_log, "w").close()
        bot_log_file = open(bot_log, "a")
    remote = test_label is not None or bot_log is not None
    if not remote:
        print(f"Bot output log: {bot_log_file.name}")
    with bot_log_file:
        if test_label is None:
            return _run_performance_suite(
                tester,
                bot_counts,
                bot_log_file=bot_log_file,
                label=exp.label,
                metadata=_collect_run_metadata(exp.label),
                json_output=json_output,
                quiet=remote,
                **suite_options,
            )
        with tester.bot_runner(bot_counts[0], bot_log_file):
            if suite_started_s_ago is not None:
                tester.pause_between_tests(
                    datetime.datetime.now()
                    - datetime.timedelta(seconds=suite_started_s_ago)
                )
            result = tester.run_test(
                test_label,
                bot_counts[0],
                bot_log_file,
                tester.duration_minutes,
                arrival_minutes,
            )
        if json_output:
            _write_json_results(
                json_output,
                metadata=_collect_run_metadata(exp.label),
                options=_performance_json_options(
                    tester,
                    _performance_limits(
                        suite_options.get("max_p95_ms"),
                        suite_options.get("max_queue_p95_s"),
                    ),
                    capacity_search=False,
                ),
                all_results=[result],
            )
        return [result]


def _run_performance_suite(
    tester,
    n_bots,
    *,
    bot_log_file,
    label,
    metadata,
    json_output=None,
    no_confirm=False,
    max_p95_ms=None,
    max_queue_p95_s=None,
    database_reset=None,
    ssh_options=None,
    quiet=False,
    cleanup=None,
):
    """Run the tests of ``n_bots`` with ``tester`` and return their results.

    Parameters
    ----------
    tester : PerformanceTester or RemotePerformanceTester
        Runs each test.
    n_bots : list[int] or str
        The ``--n-bots`` counts, or ``"auto"`` for a capacity search.
    bot_log_file : file
        Where the bots log.
    label : str
        The experiment's label for the summary.
    metadata : dict
        The environment that :func:`_write_json_results` records.
    json_output : str, optional
        Where to write the results after each test.
    no_confirm, max_p95_ms, max_queue_p95_s
        The options of the same names.
    database_reset : psynet.perf_ssh.DatabaseReset, optional
        Resets the database before each test; closed at the end.
    ssh_options : dict, optional
        The options that only ``performance-test ssh`` has, for the JSON.
    quiet : bool
        Whether to leave out where the JSON was written.
    cleanup : callable, optional
        Called after ``database_reset`` closes, even after an error, for
        example to start the services it stopped.

    Raises
    ------
    click.ClickException
        If a reset stopped the run early, the final restore of the database
        failed or ``cleanup`` failed, once the results are saved.
    """
    from psynet.perf_test import PerformanceSuite

    find_capacity = n_bots == "auto"
    limits = _performance_limits(max_p95_ms, max_queue_p95_s)
    options = {
        **_performance_json_options(tester, limits, capacity_search=find_capacity),
        **(ssh_options or {}),
    }
    if find_capacity:
        options["confirm"] = not no_confirm
    started_at = datetime.datetime.now().isoformat(timespec="seconds")

    def save_json(all_results, finished=False):
        if json_output:
            _write_suite_json(
                json_output,
                suite,
                all_results,
                metadata={**metadata, "started_at": started_at},
                options=options,
                finished=finished,
                quiet=quiet,
            )

    suite = PerformanceSuite(
        tester,
        limits=limits,
        before_test=database_reset,
        label=label,
        after_test=save_json,
        local=ssh_options is None,
    )
    restore_error = cleanup_error = None
    try:
        if find_capacity:
            all_results = suite.find_capacity(
                bot_log_file=bot_log_file, confirm=not no_confirm
            )
        else:
            all_results = suite.run(n_bots, bot_log_file=bot_log_file)
        # Before the cleanup, which may fail.
        save_json(all_results, finished=True)
    finally:
        # Errors are reported with the reset's error, or after an error that
        # is already propagating.
        if database_reset is not None:
            try:
                try:
                    database_reset.close()
                except (click.Abort, click.exceptions.Exit):
                    raise
                except Exception as e:
                    # close() has already warned how to restore it by hand.
                    restore_error = e
            finally:
                try:
                    if cleanup is not None:
                        cleanup()
                except Exception as e:
                    logger.warning(
                        "Starting the app's server processes again failed: "
                        f"{str(e) or type(e).__name__}"
                    )
                    cleanup_error = e
    _raise_reset_error(suite, cleanup_error, restore_error)
    return all_results


def _performance_limits(max_p95_ms=None, max_queue_p95_s=None):
    """Return the :class:`~psynet.perf_test.CapacityLimits` of the ``--max-p95-ms`` and ``--max-queue-p95-s`` options."""
    from psynet.perf_test import CapacityLimits

    return CapacityLimits.from_options(
        max_p95_s=None if max_p95_ms is None else max_p95_ms / 1000,
        max_queue_p95_s=max_queue_p95_s,
    )


def _performance_json_options(tester, limits, *, capacity_search):
    """Return the options of a performance test run that ``--json-output`` records.

    Parameters
    ----------
    tester : PerformanceTester or RemotePerformanceTester
        Runs each test.
    limits : CapacityLimits
        The limits that the tests are judged by.
    capacity_search : bool
        Whether the run is a capacity search (``--n-bots auto``).

    Returns
    -------
    dict
    """
    return {
        "capacity_search": capacity_search,
        "max_p95_s": limits.max_p95_s,
        "max_queue_p95_s": limits.max_queue_p95_s,
        "duration_minutes": tester.duration_minutes,
        "estimated_duration_minutes": tester.estimated_duration_minutes,
        "session_minutes": tester.session_minutes,
        "stagger_interval_s": tester.stagger_interval_s,
        "arrival_minutes": tester.arrival_minutes,
        "time_factor": tester.time_factor,
        "bot_processes": tester.bot_processes,
    }


def _raise_reset_error(suite, cleanup_error=None, restore_error=None):
    """Fail the command if a database reset stopped ``suite`` early, the final restore failed or ``cleanup_error`` ended it, once its results are saved."""
    problems = []
    if suite.reset_error:
        problems.append(
            f"Resetting the database failed, so the run stopped early: "
            f"{suite.reset_error}"
        )
    if restore_error is not None:
        problems.append(
            "Restoring the database to how the run found it failed: "
            f"{str(restore_error) or type(restore_error).__name__}"
        )
    if cleanup_error is not None:
        problems.append(
            "Starting the app's server processes again failed: "
            f"{str(cleanup_error) or type(cleanup_error).__name__}"
        )
    if problems:
        raise click.ClickException("\n".join(problems))


def _performance_test_duration(
    *,
    estimated_duration_minutes,
    minimum_minutes,
    time_factor,
    duration_minutes,
    arrival_minutes,
    find_capacity,
):
    """Return the length of each (search) test in minutes, filling in its default.

    Parameters
    ----------
    estimated_duration_minutes : float
        The experiment's ``estimated_duration_in_minutes``.
    minimum_minutes : float
        The shortest default test, ``Experiment.test_duration_minutes``.
    time_factor : float
        The ``--time-factor`` option.
    duration_minutes, arrival_minutes : float or None
        The ``--duration-minutes`` and ``--arrival-minutes`` options.
    find_capacity : bool
        Whether this is a capacity search (``--n-bots auto``).
    """
    from psynet.perf_test import default_duration_minutes

    if duration_minutes is not None:
        return duration_minutes
    return default_duration_minutes(
        estimated_duration_minutes * time_factor,
        minimum_minutes,
        search=find_capacity,
    ) + (arrival_minutes or 0)


def _check_arrival_options(
    *,
    arrival_minutes=None,
    stagger=None,
    duration_minutes=None,
    n_bots=None,
    test_label=None,
    **_options,
):
    """Raise ``click.UsageError`` if ``--arrival-minutes`` conflicts with the other options.

    A single test of a remote suite (``test_label``) was checked on this
    computer; it may combine its stagger with a confirmation test's arrivals.
    """
    if arrival_minutes is None or test_label is not None:
        return
    if stagger is not None:
        raise click.UsageError(
            "--arrival-minutes and --stagger both set when bots start; use one."
        )
    if n_bots == "auto":
        raise click.UsageError(
            "--arrival-minutes can't be used with --n-bots auto, whose validation "
            "test spreads the bots' arrivals over one session. To try another "
            "window, run that test alone with --n-bots N --arrival-minutes M."
        )
    if duration_minutes is not None and arrival_minutes >= duration_minutes:
        raise click.UsageError(
            "--arrival-minutes must be shorter than --duration-minutes, so that "
            "every bot starts during the test."
        )


def _write_suite_json(
    json_output, suite, all_results, *, metadata, options, finished, quiet=False
):
    """Write ``suite``'s results so far, with its ``options`` and ``metadata``, to ``json_output``.

    Unless ``finished``, the suite is still running, ``finished_at`` is
    null, and a failed write is only logged. Once ``finished``, unless
    ``quiet``, it prints where it wrote them.
    """
    database_reset = suite.before_test
    # A remote run records the server's environment, such as its PsyNet version.
    metadata = {
        **(getattr(suite.tester, "remote_metadata", None) or {}),
        **metadata,
        "finished_at": (
            datetime.datetime.now().isoformat(timespec="seconds") if finished else None
        ),
        # The rows in each growing table of the snapshot every test started from.
        "snapshot_rows": database_reset.snapshot_rows if database_reset else None,
        "reset_error": suite.reset_error,
    }
    options = {
        "n_bots_sweep": [r.n_bots for r in all_results if not r.confirmation],
        **options,
    }
    if options["capacity_search"]:
        options["confirmation_skipped"] = suite.confirmation_skipped
    try:
        _write_json_results(
            json_output,
            metadata=metadata,
            options=options,
            all_results=all_results,
        )
    except (OSError, ValueError) as e:
        if finished:
            raise
        logger.warning(
            f"Could not save the results so far to {json_output}, so the run "
            f"continues without them for now: {e}"
        )
        return
    if finished and not quiet:
        print(f"Performance results (JSON): {json_output}")


def _check_no_real_participants(force, resetting=False):
    """Refuse to test an experiment that may have real participants, unless ``force``.

    That is one with participants that bots didn't create, or with live
    recruitment (see :func:`psynet.recruiters.recruits_real_participants`).
    When ``resetting`` the database, live mode is refused even with ``force``.
    """
    from psynet.perf_test import count_non_bot_participants
    from psynet.recruiters import recruits_real_participants

    if resetting and get_config().get("mode", None) == "live":
        raise click.ClickException(
            "Refusing to reset the database of an experiment in live mode, "
            "even with --force: resetting replaces its data."
        )
    reasons = []
    n = count_non_bot_participants()
    if n:
        reasons.append(
            f"the database has {n:,} participant(s) that PsyNet bots didn't create"
        )
    if live := recruits_real_participants():
        reasons.append(live)
    if not reasons:
        return
    message = (
        f"This may be an experiment with real participants: {'; '.join(reasons)}. "
        "Performance tests add bot participants to the database and load the "
        "server, so they must not run against an experiment that is collecting "
        "real data."
    )
    if not force:
        raise click.ClickException(
            f"{message} If it isn't collecting real data, rerun with --force."
        )
    print(f"Warning: {message} Continuing because of --force.")


class _OutputTee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            stream.write(data)
            stream.flush()

    def flush(self):
        for stream in self.streams:
            stream.flush()


def _drain_pexpect_output(process):
    """Continuously read from pexpect process so logfile receives output.

    If we don't do this, the server log will record very little of what actually
    transpires, which makes debugging very difficult.
    """
    while process.isalive():
        try:
            process.read_nonblocking(size=4096, timeout=1)
        except pexpect.TIMEOUT:
            pass
        except (pexpect.EOF, Exception):
            break


def _start_local_server_and_wait_for_ready(
    command_args,
    *,
    debug=False,
    max_wait=60,
    ready_phrase="Experiment launch complete!",
    extra_env=None,
):
    """Spawn ``psynet <command_args>`` and wait for launch completion.

    Parameters
    ----------
    command_args : list[str]
        Arguments passed to the ``psynet`` executable, for example
        ``["debug", "local", "--legacy", "--no-browsers"]`` or
        ``["debug", "local"]``.
    extra_env : dict[str, str], optional
        Environment variables to set for the server process.
    """
    print("▶ Starting experiment server...")

    tmp_log = tempfile.NamedTemporaryFile(
        delete=False,
        prefix="psynet_server_",
        suffix=".log",
        dir=_performance_log_directory(),
    )
    tmp_log_path = tmp_log.name
    tmp_log.close()
    print(f"Server log: {tmp_log_path}")

    log_file = open(tmp_log_path, "a", encoding="utf-8")
    logfile = _OutputTee(sys.stdout, log_file) if debug else log_file
    env = os.environ.copy()
    env.setdefault("SKIP_DEPENDENCY_CHECK", "1")
    env.setdefault("BROWSER", "true")
    env.update(extra_env or {})

    try:
        process = pexpect.spawn(
            "psynet",
            command_args,
            env=env,
            encoding="utf-8",
            timeout=max_wait,
        )
    except Exception:
        log_file.close()
        raise click.ClickException("Failed to start experiment server process.")

    process.logfile = logfile
    print("⏳ Waiting for server to be ready...", end="", flush=True)

    try:
        process.expect_exact(ready_phrase, timeout=max_wait)
        print(" Ready!")
        print()
        drain_thread = threading.Thread(
            target=_drain_pexpect_output,
            args=(process,),
            daemon=True,
        )
        drain_thread.start()
        return {
            "process": process,
            "tmp_log_path": tmp_log_path,
            "log_file": log_file,
        }
    except (pexpect.TIMEOUT, pexpect.EOF) as exc:
        recent_output = (process.before or "").splitlines()[-50:]
        stop_local_debug_process(process)

        if isinstance(exc, pexpect.EOF):
            failure_message = "Server process exited before becoming ready"
        else:
            failure_message = f"Server failed to start within {max_wait} seconds"
        print(
            f"\n❌ {failure_message}",
            file=sys.stderr,
        )
        if recent_output:
            print("Last server output:", file=sys.stderr)
            for line in recent_output:
                print(line, file=sys.stderr)
        log_file.close()
        from .isolated_environment import postgres_connection_limit_message

        advice = postgres_connection_limit_message("\n".join(recent_output))
        raise click.ClickException(
            "Failed to start experiment server." + (f" {advice}" if advice else "")
        )


def _terminate_server_process(process):
    def _signal_process_or_group(pid, sig):
        try:
            os.killpg(os.getpgid(pid), sig)
            return
        except Exception:
            pass
        os.kill(pid, sig)

    if not process.isalive():
        process.close(force=True)
        return

    finished = False

    try:
        process.sendcontrol("c")
        process.expect_exact(pexpect.EOF, timeout=15)
        finished = True
    except (OSError, pexpect.TIMEOUT, pexpect.EOF):
        # OSError is common when the PTY is already gone; still escalate below.
        pass

    if not finished:
        pid = getattr(process, "pid", None)
        if pid is not None:
            for sig, timeout in ((signal.SIGTERM, 5), (signal.SIGKILL, None)):
                try:
                    _signal_process_or_group(pid, sig)
                except ProcessLookupError:
                    break
                except Exception:
                    continue

                if timeout is None:
                    break

                try:
                    process.expect_exact(pexpect.EOF, timeout=timeout)
                    finished = True
                    break
                except (ProcessLookupError, pexpect.TIMEOUT, pexpect.EOF):
                    pass
                except Exception:
                    pass

    process.close(force=True)


def stop_local_debug_process(process):
    """
    Stop a local ``psynet debug`` pexpect process and reap leftover workers.

    Waits for the process to exit after Ctrl-C (escalating to SIGTERM/SIGKILL
    if needed), then terminates any orphaned ``dallinger_heroku_*`` worker
    processes so they cannot keep database connections open.
    """
    try:
        _terminate_server_process(process)
    finally:
        kill_psynet_worker_processes()


def _stop_server(server_info):
    """Stop ``psynet debug local`` and clean up resources."""

    process = server_info["process"]
    tmp_log_path = server_info["tmp_log_path"]
    log_file = server_info["log_file"]
    try:
        stop_local_debug_process(process)
    finally:
        try:
            process.logfile = None
        except Exception:
            pass

        try:
            log_file.close()
        except Exception:
            pass

    print(f"✓ Server stopped (log: {tmp_log_path})")


def _run_performance_test_with_new_server(*, debug=False, json_output=None, **options):
    """Run performance test after starting a new experiment server."""
    _check_no_debug_server_here()
    # Prefer legacy debug: gunicorn with several workers is closer to a deployed
    # server than the auto-reload develop path used by normal
    # ``psynet debug local``.
    server_info = _start_local_server_and_wait_for_ready(
        ["debug", "local", "--legacy", "--no-browsers"],
        debug=debug,
        extra_env={"PSYNET_PERFORMANCE_TEST": "1"},
    )
    try:
        all_results = _run_performance_test_with_existing_server(
            debug=debug, json_output=json_output, **options
        )
        print("✓ Performance test completed")
        return all_results
    finally:
        _stop_server(server_info)


def _performance_test_app_info():
    """Return whether the running experiment is a performance-test app."""
    config = load_runtime_server_config()
    return {"performance_test_app": bool(config.get("performance_test_app", False))}


@performance_test.command("app-info", hidden=True)
@click.option("--json-output", required=True, type=click.Path(dir_okay=False))
def performance_test__app_info(json_output):
    """
    Write whether this app is a performance-test app, whether it has launched, and its experiment's test defaults, to --json-output; used by ``performance-test ssh``.

    The defaults are left out if the experiment can't be loaded, so that an
    app whose experiment is broken can still be updated.
    """
    from psynet.experiment import get_experiment, is_experiment_launched

    info = _performance_test_app_info()
    try:
        info["launched"] = bool(is_experiment_launched())
    except Exception as e:
        logger.warning(f"Could not check whether the experiment has launched: {e}")
    try:
        exp = get_experiment()
        info["experiment"] = {
            "label": exp.label,
            "test_n_bots": exp.test_n_bots,
            "test_duration_minutes": exp.test_duration_minutes,
            "test_parallel_stagger_interval_s": exp.test_parallel_stagger_interval_s,
            "estimated_duration_minutes": exp.estimated_duration_in_minutes,
        }
    except Exception as e:
        logger.warning(f"Could not load the experiment's test defaults: {e}")
    with open(json_output, "w") as f:
        json.dump(info, f)


def _require_performance_test_app(server, app):
    """Return the :func:`_performance_test_app_info` of ``app`` on ``server``.

    The app's own config says whether it is a performance-test app, so this
    runs in its web container.

    Raises
    ------
    click.ClickException
        If ``performance-test ssh`` didn't deploy the app, its deploy never
        finished launching the experiment, or that can't be checked. Apps
        whose PsyNet predates the launch check count as launched.
    """
    from psynet.perf_ssh import RemoteApp

    _awaken_ssh_app(server, app)
    remote = RemoteApp(_ssh_executor(server), app, server)
    advice = (
        "Performance tests only run on apps that 'psynet performance-test ssh' "
        "deployed for them, whose data is disposable. Choose another --app name, "
        "and 'performance-test ssh' deploys a new app under that name."
    )
    try:
        info = remote.run_psynet("performance-test app-info")
    except (click.ClickException, RuntimeError) as e:
        raise click.ClickException(
            f"Could not check whether {app} on {server} is a performance-test app "
            f"({str(e) or 'see the output above'}). {advice}"
        ) from e
    if not info.get("performance_test_app"):
        raise click.ClickException(
            f"Refusing to use {app} on {server}: 'performance-test ssh' didn't "
            f"deploy it, so it may hold data that matters. {advice}"
        )
    if info.get("launched") is False:
        raise click.ClickException(
            f"Refusing to use {app} on {server}: its deploy didn't finish launching "
            "the experiment, so its containers run but it can't be tested. Destroy "
            f"it with 'psynet destroy ssh --server {server} --app {app}' and rerun "
            "this command to deploy it again, or choose another --app name."
        )
    return info


@performance_test.command("prepare-reset", hidden=True)
@click.option("--prefill-participants", type=click.IntRange(min=1))
@click.option("--wait-for-async-jobs", "async_timeout_s", type=int)
@click.option("--json-output", required=True, type=click.Path(dir_okay=False))
@_test_options["performance_bot_log"]
@_test_options["performance_force"]
def performance_test__prepare_reset(
    prefill_participants, async_timeout_s, json_output, bot_log, force
):
    """
    Check that the running server's database may be reset; used by ``performance-test ssh``.

    Refuses apps that ``performance-test ssh`` didn't deploy, live mode, and
    unless --force, non-bot participants and recruiters that may bring real
    ones. Then it pre-fills the database, waits for async jobs, and
    writes the number of async jobs still waiting to --json-output.
    """
    import logging

    from psynet.experiment import get_experiment
    from psynet.perf_test import (
        log_to_console,
        prefill_database,
        wait_for_async_jobs,
    )

    log_to_console(logging.INFO)
    if not _performance_test_app_info()["performance_test_app"]:
        raise click.ClickException(
            "Refusing to reset the database: 'performance-test ssh' didn't deploy "
            "this app, so its data may matter."
        )
    _check_existing_server_answers()
    get_experiment()
    _check_no_real_participants(force, resetting=True)
    if prefill_participants:
        from psynet.participant import Participant

        if n_existing := Participant.query.count():
            print(
                f"Warning: the database already has {n_existing:,} participants, "
                "for example from earlier tests; the pre-fill adds to them, and "
                "the snapshot keeps them all. To pre-fill an empty database, "
                "destroy the app, then run this command again: it deploys the "
                "app with an empty database and pre-fills it before any test."
            )
        with open(bot_log or os.devnull, "a") as bot_log_file:
            try:
                prefill_database(prefill_participants, bot_log_file)
            except RuntimeError as e:
                raise click.ClickException(str(e)) from e
    waiting = 0
    if async_timeout_s is not None:
        waiting = wait_for_async_jobs(timeout_s=async_timeout_s, finished=True)
    with open(json_output, "w") as f:
        json.dump({"waiting": waiting}, f)


@performance_test.command("ssh")
@click.option(
    "--app",
    required=True,
    callback=verify_id,
    help="""
    Name of the app to test. If the server has no app of that name, it is
    deployed in debug mode from this directory for performance tests.""",
)
@_add_ssh_deployment_options
@_use_local_psynet_option
@_use_local_dallinger_option
@_performance_load_options
@_test_options["performance_json_output"]
@click.option(
    "--reset-database",
    is_flag=True,
    help="""
    Start every test from the same database: take a snapshot before the
    first test, and before each later test stop the app's server
    processes, recreate its database from the snapshot, empty the async
    job queues and start the processes again. Adds about a minute per
    test, more for a large database. Never in live mode.""",
)
@click.option(
    "--prefill-participants",
    type=click.IntRange(min=1),
    help="""
    Before the first test, run this many bots through the experiment,
    50 at a time and without pauses, so that every test starts with that
    much data. Implies --reset-database.""",
)
@_test_options["performance_force"]
@_option_yes_reset_local_data
@click.pass_context
def performance_test__docker_ssh(
    ctx,
    app,
    server,
    dns_host=None,
    ingress=None,
    use_local_psynet=False,
    use_local_dallinger=False,
    assume_yes=False,
    json_output=None,
    reset_database=False,
    prefill_participants=None,
    **options,
):
    """
    Runs performance tests on the remote server, in an app deployed for them.

    If the server has no app named --app, this deploys one from this
    directory in debug mode, as ``psynet debug ssh`` would, and marks it as
    a performance-test app, whose data is disposable. Since only bots take
    part, the experiment needn't have a consent page. Later runs update it
    in place from this directory before testing, keeping its database. They
    refuse apps that this command didn't deploy, or whose deploy didn't
    finish launching the experiment. The app is kept after the run; destroy
    it with ``psynet destroy ssh``.

    The bots run inside the app's web container, while this computer runs
    the suite: it runs each test in the web container. With
    --reset-database or --prefill-participants, between tests it stops the
    app's server processes, restores the app's database from a snapshot in
    the app's PostgreSQL, and starts them again. At the end of the run it
    restores the database to how the run found it and drops the snapshot,
    and fails if it can't restore it. Without them, the tests use the
    database as it is.

    Be sure the app is configured to allow a large quantity of bots. If the
    app is in use during the performance test, results may not be reliable.
    """
    _check_arrival_options(**options)
    experiment = _prepare_performance_test_app(
        ctx,
        app,
        server=server,
        dns_host=dns_host,
        ingress=ingress,
        use_local_psynet=use_local_psynet,
        use_local_dallinger=use_local_dallinger,
        assume_yes=assume_yes,
    )
    try:
        _run_ssh_performance_test(
            app,
            server,
            experiment,
            reset=reset_database or bool(prefill_participants),
            prefill_participants=prefill_participants,
            json_output=json_output,
            **options,
        )
    finally:
        print(
            f"{app} is kept for later performance tests. Destroy it with:\n"
            f"    psynet destroy ssh --server {server} --app {app}"
        )


def _prepare_performance_test_app(ctx, app, *, server, **deploy_options):
    """Deploy ``app`` for performance tests, or update it in place if it exists.

    ``deploy_options`` are the options of ``psynet debug ssh`` (see
    :func:`_debug_ssh`).

    Returns
    -------
    dict
        The experiment's test defaults that ``performance-test app-info``
        reports.

    Raises
    ------
    click.ClickException
        If the app exists but ``performance-test ssh`` didn't deploy it, or
        its experiment can't be loaded.
    """
    from dallinger.command_line.docker_ssh import get_apps

    # Contacting the server loads the config, so a missing config.txt must be
    # scaffolded first.
    _check_experiment_directory("sandbox", require_git_commit=True)
    update = app in {entry.name for entry in get_apps(server)}
    if update:
        _require_performance_test_app(server, app)
        print(f"▶ Updating {app} on {server}, keeping its database...")
    else:
        print(f"▶ Deploying {app} on {server} for performance tests...")
    _debug_ssh(
        ctx,
        app=app,
        server=server,
        update=update,
        performance_test_app=True,
        **deploy_options,
    )
    info = _require_performance_test_app(server, app)
    if "experiment" not in info:
        raise click.ClickException(
            f"Could not load the experiment in {app}'s web container; see the "
            "output above."
        )
    return info["experiment"]


def _run_ssh_performance_test(
    app,
    server,
    experiment,
    *,
    reset=False,
    prefill_participants=None,
    n_bots=None,
    stagger=None,
    time_factor=1.0,
    duration_minutes=None,
    arrival_minutes=None,
    bot_processes="auto",
    force=False,
    **suite_options,
):
    """Run a suite from this computer, each test in ``app``'s web container.

    ``experiment`` holds the experiment's test defaults (see
    :func:`_prepare_performance_test_app`). With ``reset``, the database is
    reset before each test, after ``prefill_participants`` bots have run
    through the experiment. Default test lengths are those of
    ``performance-test local``, and ``suite_options`` those of
    :func:`_run_performance_suite`.
    """
    import logging

    from psynet.perf_ssh import RemoteApp, RemotePerformanceTester
    from psynet.perf_test import log_to_console

    log_to_console(logging.INFO)
    bot_log_file = tempfile.NamedTemporaryFile(
        mode="a",
        delete=False,
        prefix=f"psynet_bots_{app}_",
        suffix=".log",
        dir=_performance_log_directory(),
    )
    print(f"Bot output log: {bot_log_file.name}")
    remote = RemoteApp(
        _ssh_executor(server), app, server, force=force, bot_log_file=bot_log_file
    )
    bot_counts = n_bots or [experiment["test_n_bots"]]
    tester = RemotePerformanceTester(
        remote,
        duration_minutes=_performance_test_duration(
            estimated_duration_minutes=experiment["estimated_duration_minutes"],
            minimum_minutes=experiment["test_duration_minutes"],
            time_factor=time_factor,
            duration_minutes=duration_minutes,
            arrival_minutes=arrival_minutes,
            find_capacity=bot_counts == "auto",
        ),
        stagger_interval_s=(
            experiment["test_parallel_stagger_interval_s"]
            if stagger is None
            else stagger
        ),
        time_factor=time_factor,
        bot_processes=bot_processes,
        estimated_duration_minutes=experiment["estimated_duration_minutes"],
        arrival_minutes=arrival_minutes,
    )
    with bot_log_file, _exit_on_sigterm():
        return _run_performance_suite(
            tester,
            bot_counts,
            bot_log_file=bot_log_file,
            label=f"{app} on {server}",
            metadata={"experiment_label": experiment["label"]},
            database_reset=(
                _ssh_database_reset(remote, prefill_participants) if reset else None
            ),
            ssh_options={
                "reset_database": reset,
                "prefill_participants": prefill_participants,
            },
            cleanup=remote.start_stopped_services,
            **suite_options,
        )


def _ssh_database_reset(remote, prefill_participants):
    """Return the :class:`~psynet.perf_ssh.DatabaseReset` of the SSH app.

    Raises
    ------
    click.ClickException
        If the database may not be reset.
    """
    from psynet.perf_ssh import DatabaseReset

    try:
        database_reset = DatabaseReset(remote, prefill_participants)
    except ValueError as e:
        raise click.ClickException(str(e)) from e
    print(
        f"Database to reset: {database_reset.database} in "
        f"{database_reset.container} on {remote.server}"
    )
    return database_reset


_CONTAINER_WEB_PORT = 5000


@psynet.command(name="list-experiment-dirs")
@click.option("--for-ci-tests", is_flag=True)
def _list_experiment_dirs(for_ci_tests=False):
    """
    Lists the directories of all the experiments that are available under the 'demos' directory,
    plus those inside the 'tests/experiments' directory.
    """
    for directory in list_experiment_dirs(for_ci_tests=for_ci_tests):
        print(directory)


@psynet.command(name="list-isolated-tests")
def _list_isolated_tests():
    """
    Lists the directories of all the demo experiments that are available.
    """
    for test_ in list_isolated_tests():
        print(test_)


def _cli_resolve_audit_dir(*, require_manifest=False):
    """Resolve ``./audit`` for audit subcommands."""
    from psynet.audit.cli import resolve_audit_dir

    try:
        return resolve_audit_dir(require_manifest=require_manifest)
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc


# Recruiter specific
@psynet.group("audit")
@click.pass_context
def audit(ctx):
    """
    Collect and package experiment readiness evidence.

    Audits record artifacts, checks, and blockers for human inspection. Audit
    evidence commands run tests and write their canonical outputs into
    ./audit/. Run these commands from the experiment directory.
    """
    pass


@audit.command("simulate")
@_test_options["n_bots"]
@click.pass_context
@require_exp_directory
def audit_simulate(ctx, n_bots=None):
    """Run test bots and write the simulated export into the audit packet."""

    _run_simulate(ctx, n_bots=n_bots)


@audit.command("performance-test")
@_test_options["existing"]
@_performance_load_options
@click.option("--debug", is_flag=True, help="Enable debug logging for verbose output")
@require_exp_directory
@_in_isolated_test_environment
def audit_performance_test(existing=False, debug=False, **options):
    """Run a local performance test and write its audit evidence."""

    json_output = str(resolve_audit_artifact_path(AUDIT_PERFORMANCE_JSON))
    all_results = _run_performance_test_local(
        existing=existing, json_output=json_output, debug=debug, **options
    )
    mark_performance_result_present(all_results)


@audit.command("init")
@click.option(
    "--force",
    is_flag=True,
    help="Replace audit.json and starter section files.",
)
def audit_init(force):
    """Create a starter experiment audit at ``./audit``."""
    from psynet.audit.cli import init_audit, init_success_messages

    resolved = _cli_resolve_audit_dir()
    try:
        init_audit(resolved, force)
    except (FileExistsError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    for line in init_success_messages(resolved):
        click.echo(line)


@audit.command("validate")
def audit_validate():
    """Validate an experiment audit.

    Exit 0 means the packet is coherent, not that the experiment is ready
    (blockers may remain).
    """
    from psynet.audit.cli import (
        collect_audit_warnings,
        validate_audit,
        validate_success_message,
    )

    resolved = _cli_resolve_audit_dir(require_manifest=True)
    problems = validate_audit(resolved)
    if problems:
        for problem in problems:
            click.echo(problem, err=True)
        raise SystemExit(1)
    for warning in collect_audit_warnings(resolved):
        click.echo(f"Warning: {warning}", err=True)
    click.echo(validate_success_message(resolved))


@audit.command("render")
@click.option(
    "--output",
    type=click.Path(),
    default=None,
    help="Output directory for the rendered site.",
)
@click.option(
    "--allow-invalid",
    is_flag=True,
    help="Render even when validate would fail.",
)
def audit_render(output, allow_invalid):
    """Render a static experiment audit site."""
    from pathlib import Path

    from psynet.audit.cli import AuditValidationError, render_audit_site

    resolved = _cli_resolve_audit_dir(require_manifest=True)
    try:
        site_dir = render_audit_site(
            resolved,
            Path(output) if output is not None else None,
            allow_invalid=allow_invalid,
        )
    except AuditValidationError as exc:
        for problem in exc.problems:
            click.echo(problem, err=True)
        raise click.ClickException(
            "Render blocked by validation errors; fix them or pass --allow-invalid."
        ) from exc
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Rendered experiment audit site: {site_dir / 'index.html'}")


@audit.command("serve")
@click.option(
    "--host",
    default="127.0.0.1",
    show_default=True,
    help="Host interface to bind.",
)
@click.option(
    "--port",
    default=8765,
    show_default=True,
    type=int,
    help="TCP port to listen on.",
)
@click.option(
    "--render/--no-render",
    default=False,
    help="Render the static site before serving.",
)
@click.option(
    "--allow-invalid",
    is_flag=True,
    help="With --render, allow rendering even when validate would fail.",
)
def audit_serve(host, port, render, allow_invalid):
    """Serve the rendered experiment audit site over HTTP.

    Does not create a public tunnel; use a separate tunnel helper when remote
    review is needed.
    """
    from psynet.audit.cli import (
        AuditValidationError,
        render_audit_site,
        resolve_audit_site_dir,
        serve_audit_site,
    )

    if allow_invalid and not render:
        raise click.UsageError("--allow-invalid is only valid together with --render.")

    resolved = _cli_resolve_audit_dir(require_manifest=True)
    try:
        if render:
            site_dir = render_audit_site(
                resolved,
                allow_invalid=allow_invalid,
            )
            click.echo(f"Rendered experiment audit site: {site_dir / 'index.html'}")
        else:
            site_dir = resolve_audit_site_dir(resolved)
        serve_audit_site(site_dir, host=host, port=port)
    except AuditValidationError as exc:
        for problem in exc.problems:
            click.echo(problem, err=True)
        raise click.ClickException(
            "Render blocked by validation errors; fix them or pass --allow-invalid."
        ) from exc
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc


@audit.command("mark-present")
@click.argument("artifact_id")
@click.option(
    "--path",
    default=None,
    help="Optional new artifact path relative to the audit directory.",
)
def audit_mark_present(artifact_id, path):
    """Mark an artifact present and remove its blockers."""
    from psynet.audit.cli import mark_artifact_present

    resolved = _cli_resolve_audit_dir(require_manifest=True)
    try:
        mark_artifact_present(resolved, artifact_id, path)
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Marked {artifact_id!r} present in {resolved / 'audit.json'}")


@psynet.group("lucid")
@click.pass_context
def lucid(ctx):
    """
    Manage Lucid surveys.
    """
    pass


@lucid.command("cost")
@click.argument("survey_number", required=True)
@click.pass_context
def lucid__cost(ctx, survey_number):
    """
    Show the cost of a Lucid survey.
    """
    summary = get_lucid_service().get_cost(survey_number)
    c = summary["currency"]
    print(bold(f"Cost summary for survey: {survey_number}"))
    print(f"Sample:\t{summary['sample']} {c}")
    print(f"Fee:\t{summary['fee']} {c}")
    print(bold(f"Total:\t{summary['total']} {c}"))
    print(
        f"Total completes: {summary['total_completes']}, price per complete: {round(summary['cost_per_complete'], 2)} {c}"
    )


@lucid.command("compensate")
@click.argument("survey_number", required=True, nargs=1)
@click.argument("rids", required=True, nargs=-1)
@click.pass_context
def lucid__compensate(ctx, survey_number, rids):
    """
    Compensate participants for a Lucid survey.
    """
    rids = list(rids)
    confirmation = f"""
    Are you sure you want to compensate {len(rids)} participants?
    Note: This will ONLY mark these participants as completed, all other participants will be marked as TERMINATED.
    """
    if click.confirm(confirmation, abort=True):
        get_lucid_service().reconcile(survey_number, rids)
        log(
            f"{len(rids)} participants have been approved for survey number: {survey_number}"
        )


@lucid.command("locale")
@click.pass_context
def lucid__locale(ctx):
    """
    Show the locales of a Lucid survey.
    """
    print(
        get_lucid_service().get_lucid_country_language_lookup().to_markdown(index=False)
    )


@lucid.command("estimate")
@click.option(
    "--language-code",
    help="Lucid language code; see `psynet lucid locale`",
    required=True,
)
@click.option(
    "--country-code",
    help="Lucid country code; see `psynet lucid locale`",
    required=True,
)
@click.option("--completes", help="Number of completes", type=int, required=True)
@click.option("--wage", help="Wage per hour", type=float, required=True)
@click.option(
    "--survey-length",
    help="Length of survey in minutes (i.e., the expected time of a user to complete the survey)",
    type=int,
    required=True,
)
@click.option(
    "--duration",
    help="Duration how long the survey is put on the marketplace",
    type=int,
    required=True,
)
@click.option(
    "--delay", type=int, default=2 * 24 * 7, help="Delay in hours (default: 2 weeks)"
)
@click.option("--incidence-rate", type=float, default=0.6, help="Incidence rate")
@click.option("--collects-pii", is_flag=True, help="Survey collects PII")
@click.option("--qualifications", help="Path to qualifications JSON file", default=None)
@click.pass_context
def lucid__estimate(
    ctx,
    language_code,
    country_code,
    completes,
    wage,
    survey_length,
    duration,
    delay,
    incidence_rate,
    collects_pii,
    qualifications,
):
    """
    Estimate the cost of a Lucid survey.
    """
    if qualifications is not None:
        with open(qualifications, "r") as file:
            qualifications = json.load(file)
    params = locals()
    params.pop("ctx")  # pop context
    get_lucid_service().estimate(**params)


@lucid.command("status")
@click.argument("survey_number", required=True)
@click.argument("status", required=True)
@click.pass_context
def lucid__status(ctx, survey_number, status):
    """
    Change the status of a Lucid survey.
    """
    available_statuses = ["live", "paused", "completed", "archived", "pending"]
    assert status in available_statuses, (
        f"Invalid status: {status}, pick from: {available_statuses}"
    )
    if status == "completed":
        status = "complete"
    get_lucid_service().change_status(survey_number, status)


@lucid.command("qualifications")
@click.argument("survey_number", required=True)
@click.option("--path", default=None, help="Path to save the qualifications to")
@click.pass_context
def get_qualifications(ctx, survey_number, path):
    """
    Get the qualifications of a Lucid survey.
    """
    qualifications = get_lucid_service().get_qualifications(survey_number)
    json_string = json.dumps(qualifications, indent=4)
    if path:
        with open(path, "w") as file:
            file.write(json_string)
        log(f"Qualifications have been saved to {path}")
    else:
        print(json_string)


def _get_local_pandas():
    try:
        import pandas as pd

        return pd
    except ImportError:
        raise ImportError(
            "This command requires the pandas library. Install it with 'pip install pandas'"
        )


@lucid.command("studies")
@click.option("--live", is_flag=True, help="List live experiments")
@click.option("--paused", is_flag=True, help="List paused experiments")
@click.option("--completed", is_flag=True, help="List complete experiments")
@click.option("--archived", is_flag=True, help="List archived experiments")
@click.option("--pending", is_flag=True, help="List pending experiments")
@click.option("--n", default=10, help="Number of experiments to list")
@click.option("--order", default="id", help="Sort by column")
@click.pass_context
def lucid__list_studies(ctx, live, paused, completed, archived, pending, n, order):
    """
    List the studies of a Lucid survey.
    """
    pd = _get_local_pandas()
    assert n > 0 and n < 200
    allowed_statuses = []
    if live:
        allowed_statuses.append("live")
    if paused:
        allowed_statuses.append("paused")
    if completed:
        allowed_statuses.append("complete")
    if archived:
        allowed_statuses.append("archived")
    if pending:
        allowed_statuses.append("pending")
    all_studies = pd.DataFrame(
        get_lucid_service().list_studies(allowed_statuses, n, order_by=order)
    )
    if len(all_studies) == 0:
        print("No studies found with the given filters.")
        return
    all_studies["completes"] = all_studies.apply(
        lambda x: f"{x['total_completes']} / {x['expected_completes']}", axis=1
    )
    all_studies.create_date = all_studies.create_date.apply(
        lambda x: pd.to_datetime(x).strftime("%Y-%m-%d")
    )
    all_studies = all_studies[
        ["id", "create_date", "status", "locale", "completes", "total_screens", "name"]
    ]
    print(all_studies.to_markdown(index=False))


@lucid.command("submissions")
@click.argument("survey_number", required=True)
@click.option("--order", default="entry_date", help="Sort by column")
@click.pass_context
def lucid__list_submissions(ctx, survey_number, order):
    """
    List the submissions of a Lucid survey.
    """
    pd = _get_local_pandas()
    submissions = pd.DataFrame(get_lucid_service().get_submissions(survey_number))
    submissions.client_status = submissions.client_status.apply(
        lambda x: BaseLucidRecruiter.client_codes.get(x, "Unknown")
    )
    submissions.fulcrum_status = submissions.fulcrum_status.apply(
        lambda x: BaseLucidRecruiter.market_place_codes.get(x, "Unknown")
    )
    submissions.drop(columns=["panelist_id"], inplace=True)
    submissions.entry_date = pd.to_datetime(submissions.entry_date)
    submissions.last_date = pd.to_datetime(submissions.last_date)
    submissions["duration"] = (
        submissions.last_date - submissions.entry_date
    ).dt.total_seconds() / 60
    submissions.drop(columns=["last_date"], inplace=True)
    submissions = submissions.sort_values(by=order, ascending=False)
    print(submissions.to_markdown(index=False))


class ListOfStrings(click.ParamType):
    name = "list_of_strings"

    def convert(self, value, param, ctx):
        if value is None:
            return []
        return value.replace(",", " ").split()


@psynet.command("locales")
@click.option(
    "--codes-only",
    is_flag=True,
    help="Output locale codes only, on a single line.",
)
def locales(codes_only):
    """
    List supported translation locales.

    Example
    -------

    psynet locales
        List all supported locales with their names.

    psynet locales --codes-only
        Output locale codes on a single line (useful for scripting).
    """
    from psynet.translation.languages import psynet_supported_locales

    if codes_only:
        click.echo(" ".join(sorted(psynet_supported_locales)))
    else:
        from psynet.utils import get_language_dict

        language_dict = get_language_dict("en")
        click.echo(bold("Supported locales:"))
        click.echo()
        for locale in sorted(psynet_supported_locales):
            name = language_dict.get(locale, "Unknown")
            click.echo(f"  {locale:6} {name}")
        click.echo()
        click.echo(f"Total: {len(psynet_supported_locales)} locales")


@psynet.command("translate")
@click.argument("locales", nargs=-1)
@click.option(
    "--force", is_flag=True, help="Force retranslation of existing translations"
)
@click.option(
    "--skip-pot",
    is_flag=True,
    help="Skips the generation of the .pot file; useful for checking failed translations",
)
@click.option(
    "--continue-on-error",
    is_flag=True,
    default=False,
    help="Continue translating even if an error occurs",
)
@click.option(
    "--translator",
    default=None,
    help="The translator to use for translation. If not specified, the default translator will be used.",
)
def translate(locales, force, skip_pot, continue_on_error, translator):
    """
    Inspects the code in the current directory and generates automatic translations for a given set of languages.

    This command should be run from the root of either an experiment or a package.
    If run from an experiment, the translations will be saved in the experiment's "locales" directory.
    If run from a package, the translations will be saved in "{package_src_directory}/locales".

    Note: Currently only .py and .html files are translated.

    Parameters
    ----------
    languages :
        The target languages, specified as space-separated language codes
    force : bool
        If True, force retranslation of existing translations
    skip_pot : bool
        If True, skip the generation of the translation template (.pot file); useful for checking failed translations
        since recreating the template takes some time, but the translation did not change.

    Example
    -------

    psynet translate fr de
        Generate translations for French and German.
    """
    import warnings

    warnings.filterwarnings("ignore", category=DeprecationWarning)

    from psynet.translation.translate import translate_experiment, translate_package
    from psynet.translation.translators import get_translator_from_name

    translator = get_translator_from_name(translator)

    if in_python_package():
        click.echo(
            bold(f"Found a package called '{get_package_name()}' to translate")
            + f" at {os.getcwd()}."
        )
        translate_package(
            locales,
            force=force,
            skip_pot=skip_pot,
            continue_on_error=continue_on_error,
            translator=translator,
        )

    elif experiment_available():
        click.echo(bold("Found an experiment to translate") + f" at {os.getcwd()}.")
        translate_experiment(
            locales,
            force=force,
            skip_pot=skip_pot,
            continue_on_error=continue_on_error,
            translator=translator,
        )

    else:
        raise RuntimeError(
            f"The current directory {os.getcwd()} does not seem to be the root of an experiment or a package."
        )
