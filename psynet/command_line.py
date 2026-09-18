import datetime
import functools
import importlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import zipfile
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlencode

import click
import click.shell_completion
import dallinger.command_line.utils
import pexpect
import psutil
import psycopg2
import requests
from dallinger import db
from dallinger.command_line.docker_ssh import (
    CONFIGURED_HOSTS,
    option_server,
    remote_postgres,
)
from dallinger.command_line.utils import verify_id as dallinger_verify_id
from dallinger.config import experiment_available, get_config
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
)

from . import deployment_info
from .bootstrap_commands import register_bootstrap_commands
from .data import drop_all_db_tables, dump_db_to_disk, ingest_zip, init_db
from .experiment_scaffold import (
    dockertag_contents,
    get_psynet_requirement,
    is_unambiguous_psynet_requirement,
    missing_scaffold_paths_required_for_local_run,
    scaffold_experiment_directory,
)
from .log import bold
from .lucid import get_lucid_service
from .recruiters import BaseLucidRecruiter, HotAirRecruiter
from .redis import redis_vars
from .serialize import serialize, unserialize
from .utils import (
    get_args,
    get_experiment_url,
    get_logger,
    get_package_name,
    git_repository_available,
    in_python_package,
    is_in_repo_experiment,
    list_experiment_dirs,
    list_isolated_tests,
    make_parents,
    pretty_format_seconds,
    require_exp_directory,
    require_requirements_txt,
    run_subprocess_with_live_output,
    working_directory,
)

ensure_runtime()

logger = get_logger()


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
    help="Path to database archive for re-deployment",
)
def prepare(archive):
    """
    Prepare the experiment for deployment.
    """
    _prepare(archive)


def _prepare(archive=None):
    from dallinger import db

    from .experiment import get_experiment

    redis_vars.clear()

    if archive:
        from psynet.experiment import database_template_path

        shutil.copyfile(archive, database_template_path)

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
    allowed = ["local", "heroku", "ssh"]
    if value not in allowed:
        raise click.UsageError(
            f"Invalid location {value}; location must be one of: {', '.join(allowed)}"
        )


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


def prompt_for_ssh_server():
    click.echo(
        "Choose one of the configured servers (add one with `dallinger docker-ssh servers add`):"
    )
    return click.Choice(CONFIGURED_HOSTS.keys())


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
            if server is None:
                server = prompt_for_ssh_server()
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
@click.option("--legacy", is_flag=True, help="Legacy mode.")
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


def _cleanup_before_debug():
    kill_psynet_worker_processes()

    if not os.getenv("KEEP_OLD_CHROME_WINDOWS_IN_DEBUG_MODE"):
        kill_psynet_chrome_processes()

    # This is important for resetting the state before _debug_legacy;
    # otherwise `dallinger verify` throws an error.
    clean_sys_modules()  # Unimports the PsyNet experiment

    drop_all_db_tables()


def _cleanup_exp_directory():
    """
    Cleans up temporary files that are sometimes left behind by the experiment.
    """
    for file in ["source_code.zip", "server.log", "logs.jsonl"]:
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

    _develop_path = str(develop_target_path(config))
    if "." in _develop_path:
        raise ValueError(
            f"The target path for your app's temporary development directory ({_develop_path}) "
            "contains a period ('.'). Unfortunately Dallinger doesn't support this."
            "You should set a revised path in your .dallingerconfig file. "
            "We recommend: dallinger_develop_directory = /tmp/dallinger_develop"
        )

    if is_editable("psynet"):
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
            exp_config={"threads": "1"},
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


def _debug_auto_reload(ctx, archive, no_browsers):
    if no_browsers:
        raise click.UsageError(
            "--no-browsers option is not supported in this debug mode."
        )

    run_pre_auto_reload_checks()

    from dallinger.command_line.develop import debug as dallinger_debug
    from dallinger.deployment import DevelopmentDeployment

    DevelopmentDeployment.archive = archive
    patch_dallinger_develop()

    develop_module = importlib.import_module("dallinger.command_line.develop")
    develop_module.header = ""

    try:
        ctx.invoke(dallinger_debug, skip_flask=False)
    finally:
        db.session.commit()
        reset_console()


def _load_runtime_server_config(config=None, deployment_id=None):
    config = config or get_config()
    if not config.ready:
        config.load()

    # The debug server runs from Dallinger's generated development directory,
    # whose config.txt includes runtime values such as dashboard credentials.
    server_working_directory = redis_vars.get("server_working_directory", None)
    if server_working_directory:
        config.load_from_file(os.path.join(server_working_directory, "config.txt"))
        return config

    if deployment_id:
        launch_info_path = (
            Path("~/psynet-data/launch-data").expanduser()
            / deployment_id
            / "launch-info.json"
        )
        if launch_info_path.exists():
            with open(launch_info_path, encoding="utf-8") as f:
                config.extend(json.load(f))

    return config


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
    if len(processes) > 0:
        log(
            f"Found {len(processes)} remaining PsyNet worker process(es), terminating them now."
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
    try:
        if "chrome" in process.name().lower():
            for cmd in process.cmdline():
                if "localhost:5000" in cmd:
                    return True
                if "user-data-dir" in cmd:
                    return True
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    return False


def list_psynet_worker_processes():
    return [p for p in psutil.process_iter() if is_psynet_worker_process(p)]


def is_psynet_worker_process(process):
    try:
        # This version catches processes in Linux
        if "dallinger_herok" in process.name():
            return True
        # This version catches process in MacOS
        if "python" in process.name().lower():
            for cmd in process.cmdline():
                if "dallinger_heroku_" in cmd:
                    return True
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    return False


def list_chromedriver_processes():
    return [p for p in psutil.process_iter() if is_chromedriver_process(p)]


def is_chromedriver_process(process):
    try:
        return "chromedriver" in process.name().lower()
    except psutil.NoSuchProcess:
        pass


###########
# run bot #
###########


def _run_bot(time_factor, dashboard_user, dashboard_password):
    from .experiment import get_experiment

    os.environ["PASSTHROUGH_ERRORS"] = "True"

    import logging

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    config = get_config()
    if not config.ready:
        config.load()

    config.set("dashboard_user", dashboard_user)
    config.set("dashboard_password", dashboard_password)

    exp = get_experiment()
    exp.run_bot(time_factor=time_factor)


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
def run_pre_checks_deploy(exp, config, is_mturk, local_, recruiter):
    check_psynet_requirement_is_unambiguous()
    check_core_dependency_versions_match_requirements()
    initial_recruitment_size = exp.initial_recruitment_size

    if (
        is_mturk
        and initial_recruitment_size <= 10
        and not user_confirms(
            f"Are you sure you want to deploy to MTurk with initial_recruitment_size set to {initial_recruitment_size}? "
            f"You will not be able to recruit more than {initial_recruitment_size} participant(s), "
            "due to a restriction in the MTurk pricing scheme.",
            default=True,
        )
    ):
        raise click.Abort

    if local_ and not isinstance(recruiter, HotAirRecruiter):
        raise click.UsageError(
            "``psynet deploy local`` currently only supports the 'generic' recruiter. "
            "Set recruiter = generic in your experiment config, or deploy to a remote server instead "
            "(e.g. ``psynet deploy ssh``)."
        )


def _abort_if_app_exists(server, app):
    if not app:
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
):
    from .experiment import get_experiment

    # Scaffold/git checks before Redis so missing-boilerplate guidance is visible
    # even when Redis is not running.
    _check_experiment_directory(mode)

    from .services import ensure_local_services

    # All launch paths (local, SSH, Heroku, Docker) run ``prepare`` / Redis
    # helpers on this machine before any remote packaging, so local Postgres
    # and Redis are required here even when the experiment ultimately runs
    # elsewhere.
    ensure_local_services(assume_yes=False, strict=True)

    redis_vars.clear()
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

        deployment_info.write(ssh_host=ssh_host, ssh_user=ssh_user)

        from dallinger.command_line.docker_ssh import ensure_remote_host_in_known_hosts

        ensure_remote_host_in_known_hosts(ssh_host, ssh_user)
        _abort_if_app_exists(server, app)

    run_pre_checks(mode, local_, heroku, docker, app)

    # Always use the Dallinger version in requirements.txt, not the local editable one
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
    deployment_info.write(locale=config.get("locale", "en"))

    if config.get("check_dallinger_version"):
        check_installed_dallinger_version_is_recommended()

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
@click.option("--legacy", is_flag=True, help="Legacy mode.")
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
@click.pass_context
def deploy__heroku(ctx, app, archive, docker):
    """
    Deploy the experiment to Heroku.
    """
    if docker:
        _deploy__docker_heroku(ctx, app, archive)

    try:
        from dallinger.command_line import deploy as dallinger_deploy

        _pre_launch(
            ctx,
            mode="live",
            archive=archive,
            local_=False,
            heroku=True,
            app=app,
        )
        # Note: PsyNet bypasses Dallinger's deploy-from-archive system and uses its own, so we set archive=None.
        result = ctx.invoke(dallinger_deploy, verbose=True, app=app, archive=None)
        _post_deploy(result)
    finally:
        _cleanup_exp_directory()
        reset_console()


def _deploy__docker_heroku(ctx, app, archive):
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
        )
        result = ctx.invoke(dallinger_deploy, verbose=True, app=app)
        _post_deploy(result)
    finally:
        _cleanup_exp_directory()
        reset_console()


@deploy.command("ssh")
@click.option("--app", callback=verify_id, help="Experiment id")
@click.option("--archive", default=None, help="Optional path to an experiment archive")
@option_server
@click.option(
    "--dns-host",
    help="DNS name to use. Must resolve all its subdomains to the IP address specified as ssh host",
)
@click.pass_context
def deploy__docker_ssh(ctx, app, archive, dns_host, server):
    """
    Deploy the experiment to a remote server via Docker and SSH.
    """
    try:
        # Ensures that the experiment is deployed with the Dallinger version specified in requirements.txt,
        # irrespective of whether a different version is installed locally.
        os.environ["DALLINGER_NO_EGG_BUILD"] = "1"

        _pre_launch(
            ctx,
            mode="live",
            archive=archive,
            local_=False,
            ssh=True,
            docker=True,
            server=server,
            app=app,
        )

        from dallinger.command_line.docker_ssh import (
            deploy as dallinger_docker_ssh_deploy,
        )

        # Note: PsyNet bypasses Dallinger's deploy-from-archive system and uses its own, so we set archive_path=None.
        # Explicitly pass update=False to avoid Click converting the default to the string 'False'
        result = ctx.invoke(
            dallinger_docker_ssh_deploy,
            server=server,
            dns_host=dns_host,
            app_name=app,
            config_options={},
            archive_path=None,
            update=False,
        )

        _post_deploy(result)
    finally:
        _cleanup_exp_directory()
        reset_console()


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
    scaffold_experiment_directory()
    return True


def _check_experiment_directory(mode):
    """
    Fail fast on missing scaffold or git before Redis or other heavy I/O.

    In-repo experiments are auto-scaffolded first so their missing-boilerplate
    check does not falsely fail. These checks must run before ``redis_vars.clear()``
    so users without Redis still see actionable guidance.
    """
    _prepare_in_repo_experiment()

    missing_boilerplate = missing_scaffold_paths_required_for_local_run()
    if missing_boilerplate:
        missing_paths = ", ".join(missing_boilerplate)
        raise click.ClickException(
            "Experiment directory is missing required PsyNet boilerplate files "
            f"({missing_paths}). "
            f"{_missing_boilerplate_fix(mode=mode, missing_paths=missing_boilerplate)}"
        )

    # We need an active git repository for Dallinger to recognize .gitignore properly
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


def run_pre_checks(mode, local_, heroku=False, docker=False, app=None):
    from dallinger.recruiters import MTurkRecruiter

    from .experiment import get_experiment
    from .utils import check_todos_before_deployment

    # Directory readiness is checked earlier in ``_pre_launch`` (before Redis)
    # and directly from ``psynet test local``. Avoid duplicating that work here.

    exp = get_experiment()
    exp.check_config()
    exp.check_size()
    exp.check_consents()
    exp.check_python_dependencies()

    # Make sure source_code.zip is in .gitignore
    try:
        with open(".gitignore", "r") as f:
            source_code_zip_found = False
            for line in f.readlines():
                if "source_code.zip" in line:
                    source_code_zip_found = True
                    break
            if not source_code_zip_found:
                raise click.ClickException(
                    "Please add source_code.zip to .gitignore and try again."
                )
    except FileNotFoundError:
        raise click.ClickException(
            f".gitignore is missing from your experiment directory ({os.getcwd()}). "
            + _missing_boilerplate_fix()
        )

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

    if heroku:
        if docker and not user_confirms(
            "Heroku deployment with Docker hasn't been working well recently; experiments have been failing to launch "
            "and returning a psutil version error. Are you sure you want to continue?"
        ):
            raise click.Abort

        try:
            with open(".gitignore", "r") as f:
                for line in f.readlines():
                    if line.startswith(".deploy"):
                        if not user_confirms(
                            "The .gitignore file contains '.deploy'; "
                            "in order to deploy on Heroku without Docker this line must ordinarily be removed. "
                            "Are you sure you want to continue?"
                        ):
                            raise click.Abort
        except FileNotFoundError:
            pass

    if docker:
        check_dockerfile()

    if not local_:
        init_db(drop_all=True)

        config = get_config()
        if not config.ready:
            config.load()
        check_todos_before_deployment()

        if docker:
            if config.get("docker_image_base_name", None) is None:
                raise click.UsageError(
                    "docker_image_base_name must be specified in config.txt or ~/.dallingerconfig before you can "
                    "launch an experiment using Docker. For example, you might write the following: \n"
                    "docker_image_base_name = registry.gitlab.developers.cam.ac.uk/mus/cms/psynet-experiment-images"
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
        is_mturk = isinstance(recruiter, MTurkRecruiter)
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
            run_pre_checks_sandbox(exp, config, is_mturk)
        elif mode == "live":
            run_pre_checks_deploy(exp, config, is_mturk, local_, recruiter)


def run_pre_checks_sandbox(exp, config, is_mturk):
    check_psynet_requirement_is_unambiguous()
    check_core_dependency_versions_match_requirements()

    us_only = config.get("us_only")

    if (
        is_mturk
        and us_only
        and not user_confirms(
            "Are you sure you want to sandbox with us_only = True? "
            "Only people with US accounts will be able to test the experiment.",
            default=True,
        )
    ):
        raise click.Abort


@debug.command("heroku")
@click.option(
    "--app", callback=verify_id, default=None, help="Name of the experiment app."
)
@click.option("--docker", is_flag=True, help="Docker mode.")
@click.option("--archive", default=None, help="Optional path to an experiment archive.")
@click.pass_context
def debug__heroku(ctx, app, docker, archive):
    """
    Debug the experiment on Heroku.
    """
    if docker:
        debug__docker_heroku(ctx, app, archive)
    else:
        from dallinger.command_line import sandbox as dallinger_sandbox

        try:
            _pre_launch(
                ctx, mode="sandbox", archive=archive, local_=False, heroku=True, app=app
            )
            # Note: PsyNet bypasses Dallinger's deploy-from-archive system and uses its own, so we set archive=None.
            result = ctx.invoke(dallinger_sandbox, verbose=True, app=app, archive=None)
            _post_deploy(result)
        finally:
            _cleanup_exp_directory()
            reset_console()


def debug__docker_heroku(ctx, app, archive):
    from dallinger.command_line.docker import sandbox as dallinger_sandbox

    try:
        if archive is not None:
            raise NotImplementedError(
                "Unfortunately docker-heroku sandbox doesn't yet support deploying from archive. "
                "This shouldn't be hard to fix..."
            )
        _pre_launch(
            ctx, mode="sandbox", archive=archive, local_=False, docker=True, app=app
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
@option_server
@click.option(
    "--dns-host",
    help="DNS name to use. Must resolve all its subdomains to the IP address specified as ssh host",
)
@click.pass_context
def debug__docker_ssh(ctx, app, archive, server, dns_host):
    """
    Debug the experiment on a remote server via SSH.
    """
    try:
        from dallinger.command_line.docker_ssh import sandbox

        os.environ["DALLINGER_NO_EGG_BUILD"] = "1"

        _pre_launch(
            ctx,
            mode="sandbox",
            archive=archive,
            local_=False,
            ssh=True,
            docker=True,
            server=server,
            app=app,
        )

        # Note: PsyNet bypasses Dallinger's deploy-from-archive system and uses its own, so we set archive_path=None.
        # Explicitly pass update=False to avoid Click converting the default to the string 'False'
        result = ctx.invoke(
            sandbox,
            server=server,
            dns_host=dns_host,
            app_name=app,
            config_options={},
            archive_path=None,
            update=False,
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
    if is_editable("dallinger"):
        _prepare(
            dallinger_version,
            "Dallinger",
            cwd,
            capture_output,
        )

    if is_editable("dallinger"):
        text = "Installing base packages and development requirements..."
        install_command = "pip install --editable '.[data]'"
    else:
        text = "Installing base packages..."
        install_command = "pip install '.[data]'"

    with yaspin(
        text=text,
        color="green",
    ) as spinner:
        if is_editable("dallinger"):
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


def is_editable(project):
    for path_item in sys.path:
        egg_link = os.path.join(path_item, project + ".egg-link")
        if os.path.isfile(egg_link):
            return True
    return False


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

    from .constraints_compile import constraints_are_up_to_date

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
        "* psynet==10.1.1",
        "* psynet@git+https://gitlab.com/PsyNetDev/PsyNet@v10.1.1#egg=psynet",
        "* psynet@git+https://gitlab.com/PsyNetDev/PsyNet@45f317688af59350f9a6f3052fd73076318f2775#egg=psynet",
        "* psynet@git+https://gitlab.com/alice/PsyNet@45f317688af59350f9a6f3052fd73076318f2775#egg=psynet",
        "* psynet@git+https://gitlab.com/PsyNetDev/PsyNet@45f31768#egg=psynet",
    ]

    parts = [
        "When deploying an experiment, you need to specify PsyNet in an "
        "unambiguous way. " + branch_note,
    ]
    if requirement:
        parts.append(f"\n\nYour current requirements.txt entry is:\n  {requirement}")
        if _is_local_psynet_requirement(requirement):
            parts.append(
                "\n\nLocal path and editable installs cannot be resolved on a "
                "remote deploy server. If you developed against a local PsyNet "
                "checkout, re-run:\n"
                "  psynet setup --psynet-source commit\n"
                "to pin a pushed Git commit before deploying."
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


def _get_local_export_url(config):
    try:
        port = config.get("base_port")
    except KeyError:
        port = 5000
    return f"http://127.0.0.1:{port}"


def export_arguments(func):
    args = [
        click.option("--path", default=None, help="Path to export directory"),
        click.option("--legacy", is_flag=True, help="Process the export locally"),
        click.option(
            "--assets",
            default="experiment",
            help="Which assets to export; valid values are none, experiment, and all",
        ),
        click.option(
            "--anonymize",
            default="both",
            help="Whether to anonymize the data; valid values are yes, no, or both (the latter exports both ways)",
        ),
        click.option(
            "--n_parallel",
            default=None,
            help="Number of parallel jobs for exporting assets",
        ),
        click.option(
            "--no-source",
            is_flag=True,
            default=False,
            help="Skip exporting the experiment's source code",
        ),
        click.option(
            "--username",
            default=None,
            help="This is used to authenticate to the remote server. If missing, this will be guessed from local config files.",
        ),
        click.option(
            "--password",
            default=None,
            help="This is used to authenticate to the remote server. If missing, this will be guessed from local config files.",
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
    exp_variables = ctx.invoke(experiment_variables, location="local")
    export_(ctx, local=True, exp_variables=exp_variables, **kwargs)


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
    exp_variables = ctx.invoke(experiment_variables, location="heroku", app=app)
    export_(ctx, app=app, local=False, exp_variables=exp_variables, **kwargs)


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
    exp_variables = ctx.invoke(
        experiment_variables, location="ssh", app=app, server=server
    )
    export_(
        ctx,
        app=app,
        local=False,
        server=server,
        exp_variables=exp_variables,
        docker_ssh=True,
        **kwargs,
    )


def export_(
    ctx,
    exp_variables,
    app=None,
    local=False,
    path=None,
    legacy=False,
    assets="experiment",
    anonymize="both",
    n_parallel=None,
    no_source=False,
    docker_ssh=False,
    server=None,
    dns_host=None,
    username=None,
    password=None,
):
    """
    Export data from an experiment.

    The data is exported into the specified export directory with the following structure:

    ::

        export_path/
        ├── logs.jsonl
        ├── source_code.zip
        ├── regular/
        │   ├── database.zip
        │   ├── basic_data.json OR basic_data/
        │   ├── data/
        │   └── assets/
        └── anonymous/
            ├── database.zip
            ├── basic_data.json OR basic_data/
            ├── data/
            └── assets/

    logs.jsonl:
        Contains the experiment logs exported from the remote server.
    source_code.zip:
        Contains a snapshot of the experiment source code at the time of deployment.
    regular/:
        Contains non-anonymized data:
            - the database.zip file generated by the default Dallinger export command
            - basic_data.json for the experiment (if provided)
            - basic_data/ if basic data was returned as DataFrames
            - experiment data in CSV format
            - assets
    anonymous/:
        Contains anonymized data:
            - the database.zip file generated by the default Dallinger export command
            - basic_data.json for the experiment (if provided)
            - basic_data/ if basic data was returned as DataFrames
            - experiment data in CSV format
            - assets
    """
    from .experiment import import_local_experiment

    deployment_id = exp_variables["deployment_id"]
    assert len(deployment_id) > 0

    remote_exp_label = exp_variables["label"]
    experiment_class = import_local_experiment()["class"]
    local_exp_label = experiment_class.label

    if not remote_exp_label == local_exp_label:
        if not user_confirms(
            f"The remote experiment's label ({remote_exp_label}) does not seem consistent with the "
            f"local experiment's label ({local_exp_label}). Are you sure you are running the export command from "
            "the right experiment folder? If not, the export process is likely to fail. "
            "To continue anyway, press Y and Enter, otherwise just press Enter to cancel."
        ):
            raise click.Abort

    config = get_config()
    if not config.ready:
        config.load()
    if local:
        _load_runtime_server_config(config, deployment_id=deployment_id)

    if path is None:
        path = experiment_class.export_path(deployment_id)

    path = os.path.expanduser(path)

    if app is None and not local:
        raise ValueError(
            "Either the flag --local must be present or an app name must be provided via --app."
        )

    if app is not None and local:
        raise ValueError("You cannot provide both --local and --app arguments.")

    if assets not in ["none", "experiment", "all"]:
        raise ValueError("--assets must be either none, experiment, or all.")

    if anonymize not in ["yes", "no", "both"]:
        raise ValueError("--anonymize must be either yes, no, or both.")

    if anonymize in ["yes", "no"]:
        anonymize_modes = [anonymize]
    else:
        anonymize_modes = ["yes", "no"]

    source_code_exported = False
    if not legacy:
        try:
            experiment_url = get_experiment_url(app, server)
        except KeyError:
            if not local:
                raise
            experiment_url = _get_local_export_url(config)
        params = {
            "type": "psynet",
            "anonymize": anonymize,
            "assets": assets,
        }
        export_endpoint = f"{experiment_url}/dashboard/export/download?" + urlencode(
            params
        )
        with yaspin(text="Requesting export from dashboard", color="green") as spinner:
            response = requests.get(
                export_endpoint,
                auth=(config.get("dashboard_user"), config.get("dashboard_password")),
            )
            spinner.ok("✔")
        os.makedirs(path, exist_ok=True)
        zip_path = os.path.join(path, "data.zip")
        if response.status_code == 200:
            with open(zip_path, "wb") as f:
                f.write(response.content)
            # unzip the file
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(path)
            # Download source code unless --no-source was passed
            if not no_source:
                _export_source_code(
                    app,
                    local,
                    server,
                    path,
                    username,
                    password,
                    experiment_url=experiment_url,
                )
            log(f"Export complete. You can find your results at: {path}")
        else:
            log(
                f"Failed to export data. Response: {response.reason} ({response.status_code})"
            )
            try:
                message = response.json().get("message")
                log(f"Reason: {message}.")
            except json.JSONDecodeError as e:
                log(
                    f"Additionally, decoding JSON data from the response failed with '{str(e)}'"
                    f"\nResponse content: {response.content}"
                )
            log("You can add the --legacy flag to retry the export locally.")
    else:
        for anonymize_mode in anonymize_modes:
            _anonymize = anonymize_mode == "yes"
            should_export_source_code = not (source_code_exported or no_source)
            _export_(
                ctx,
                app,
                local,
                path,
                assets,
                _anonymize,
                should_export_source_code,
                n_parallel,
                docker_ssh,
                server,
                dns_host,
                username,
                password,
            )
            if should_export_source_code:
                source_code_exported = True


def _export_(
    ctx,
    app,
    local,
    export_path,
    assets,
    anonymize: bool,
    export_source_code: bool,
    n_parallel=None,
    docker_ssh=False,
    server=None,
    dns_host=None,
    username=None,
    password=None,
):
    """
    An internal version of the export version where argument preprocessing has been done already.
    """
    database_zip_path = export_database(
        ctx, app, local, export_path, anonymize, docker_ssh, server, dns_host
    )
    export_data(local, anonymize, database_zip_path, export_path)

    if assets != "none":
        experiment_assets_only = assets == "experiment"
        include_on_demand_assets = assets == "all"
        export_assets(
            export_path,
            anonymize,
            experiment_assets_only,
            include_on_demand_assets,
            n_parallel,
            server,
            local,
        )

    if export_source_code:
        _export_source_code(app, local, server, export_path, username, password)

    # Export logs.jsonl file for SSH exports
    if docker_ssh and server:
        export_logs(app, server, export_path)

    log(f"Export complete. You can find your results at: {export_path}")


def export_logs(app, server, export_path):
    """Export the logs.jsonl file from the remote server."""
    from dallinger.command_line.docker_ssh import CONFIGURED_HOSTS, Executor, get_sftp

    server_info = CONFIGURED_HOSTS[server]
    ssh_host = server_info["host"]
    ssh_user = server_info.get("user")

    local_logs_path = os.path.join(export_path, "logs.jsonl")

    log(f"Exporting logs to {local_logs_path}")

    try:
        sftp = get_sftp(ssh_host, ssh_user)
        executor = Executor(ssh_host, ssh_user, app)

        remote_home_path = executor.run("echo $HOME", raise_=False).strip()
        remote_logs_path = f"{remote_home_path}/dallinger/{app}/logs.jsonl"

        sftp.get(remote_logs_path, local_logs_path)

        with yaspin(text="Logs exported.", color="green") as spinner:
            spinner.ok("✔")

    except Exception as e:
        log(f"Warning: Failed to export logs from {remote_logs_path}: {str(e)}")


def _export_source_code(
    app, local, server, export_path, username, password, experiment_url=None
):
    import requests

    config = get_config()
    if not config.ready:
        config.load()

    username = username or config.get("dashboard_user", None)
    password = password or config.get("dashboard_password", None)

    if not all([username, password]):
        if not click.confirm(
            "\nPsyNet failed to find dashboard credentials in your local config files. "
            "These dashboard credentials are needed to authenticate to the remote server "
            "in order to download the experiment's source code. "
            "You can provide these credentials now in a follow-up dialog; you can find these "
            "credentials printed to your console as part of the experiment deployment command. "
            "Alternatively, you can choose to skip downloading the source code. "
            "\nDo you want to proceed with entering username and password now? "
            "Enter 'y', or 'n' to skip downloading the source code.",
            default=True,
            abort=False,
        ):
            log("WARNING: Experiment source code could not be downloaded.")
            return

    log(
        "Downloading source code... (if this fails, you can skip this step by appending `--no-source` to your `psynet export` command)"
    )
    if experiment_url:
        url = experiment_url.rstrip("/")
    elif local:
        url = "http://localhost:5000"
    else:
        if server:
            url = f"https://{app}.{server}"
        else:
            url = HerokuApp(app).url

    url += "/download_source"
    source_code_zip_path = os.path.join(export_path, "source_code.zip")

    while True:
        if not all([username, password]):
            username = click.prompt("Enter dashboard username")
            password = click.prompt("Enter dashboard password", hide_input=True)

        with yaspin(
            text=f"Requesting source code from {url}", color="green"
        ) as spinner:
            response = requests.get(url, auth=(username, password))

        if response.status_code == 200:
            with open(source_code_zip_path, "wb") as f:
                f.write(response.content)
            spinner.ok("✔")
            log(f"Experiment source code saved to {source_code_zip_path}")
            break
        elif response.status_code == 401:
            try_again = click.confirm(
                "Authentication failed.\nPress ENTER to try again or 'n' to skip downloading the source code.",
                default=True,
                abort=False,
            )
            if not try_again:
                log("Skipped downloading the source code.")
                break
            # Reset the credentials so the user gets another chance to enter them correctly
            username, password = None, None
        else:
            spinner.color = "red"
            spinner.fail("✘")
            click.confirm(
                "Experiment source code could not be downloaded."
                "\nPress ENTER to continue with the remainder of data export, ignoring the source code."
                "\nNote: To skip exporting the source code in the future, add `--no-source` option to your `psynet export` command.",
                default=True,
                prompt_suffix="",
                show_default=False,
            )
            log(
                f"WARNING: Failed to download experiment source code. Response: {response.reason} ({response.status_code})"
            )
            try:
                message = response.json().get("message")
                log(f"\nReason: {message}.")
            except json.JSONDecodeError as e:
                log(
                    f"\nAdditionally, decoding JSON data from the response failed with '{str(e)}'"
                    f"\nResponse content: {response.content}"
                )
            break


def export_database(
    ctx, app, local, export_path, anonymize, docker_ssh, server, dns_host
):
    if local:
        app = "local"

    subdir = "anonymous" if anonymize else "regular"

    database_zip_path = os.path.join(export_path, subdir, "database.zip")

    log(f"Exporting raw database content to {database_zip_path}")

    from dallinger import data as dallinger_data
    from dallinger import db as dallinger_db

    # if docker_ssh:
    #     from dallinger.command_line.docker_ssh import export as dallinger_export
    # else:
    #     from dallinger.data import export as dallinger_export
    # Dallinger hard-codes the list of table names, but this list becomes out of date
    # if we add custom tables, so we have to patch it.
    dallinger_data.table_names = sorted(dallinger_db.Base.metadata.tables.keys())

    with tempfile.TemporaryDirectory() as tempdir:
        with working_directory(tempdir):
            if docker_ssh:
                from dallinger.command_line.docker_ssh import export

                ctx.invoke(
                    export,
                    server=server,
                    app=app,
                    no_scrub=not anonymize,
                )
            else:
                from dallinger.command_line import export

                ctx.invoke(
                    export,
                    app=app,
                    local=local,
                    no_scrub=not anonymize,
                )

            shutil.move(
                os.path.join(tempdir, "data", f"{app}-data.zip"),
                make_parents(database_zip_path),
            )

    with yaspin(text="Completed.", color="green") as spinner:
        spinner.ok("✔")

    return database_zip_path


def export_data(local, anonymize, database_zip_path, export_path):
    subdir = "anonymous" if anonymize else "regular"
    data_path = os.path.join(export_path, subdir, "data")

    if not local:
        log("Populating the local database with the downloaded data.")
        populate_db_from_zip_file(database_zip_path)

    dump_db_to_disk(data_path, scrub_pii=anonymize)
    export_basic_data(export_path, anonymize)

    with yaspin(text="Completed.", color="green") as spinner:
        spinner.ok("✔")


def export_basic_data(export_path, anonymize):
    from .experiment import get_experiment

    exp = get_experiment()
    data = exp.get_basic_data(context="export", anonymize=anonymize)
    if data is None:
        return

    subdir = "anonymous" if anonymize else "regular"
    basic_data_path = os.path.join(export_path, subdir)
    serializer = _select_basic_data_serializer(data)
    serializer(basic_data_path, data)


def _select_basic_data_serializer(data):
    if _is_dataframe_dict(data):
        return _write_basic_dataframes
    return _write_basic_data_json


def _write_basic_dataframes(export_subdir_path, data):
    basic_data_dir = os.path.join(export_subdir_path, "basic_data")
    os.makedirs(basic_data_dir, exist_ok=True)
    filename_counts = {}
    used_filenames = set()
    for key, dataframe in data.items():
        filename = _make_basic_data_filename(key, filename_counts, used_filenames)
        csv_path = os.path.join(basic_data_dir, f"{filename}.csv")
        dataframe.to_csv(csv_path, index=False)


def _write_basic_data_json(export_subdir_path, data):
    basic_data_path = os.path.join(export_subdir_path, "basic_data.json")
    with open(make_parents(basic_data_path), "w") as file:
        json.dump(data, file, indent=2)


def _make_basic_data_filename(key, counts, used_filenames):
    """
    Allocate a unique CSV-safe filename stem for one basic-data key.

    Parameters
    ----------
    key : Any
        Original basic-data key from the export payload.
    counts : dict[str, int]
        Per-sanitized-key counters used to generate numeric suffixes.
    used_filenames : set[str]
        Case-folded filename stems already reserved in this export run.

    Returns
    -------
    str
        A unique filename stem (without extension).
    """
    sanitized = _sanitize_basic_data_key(key)
    counts[sanitized] = counts.get(sanitized, 0)

    while True:
        counts[sanitized] += 1
        count = counts[sanitized]
        filename = sanitized if count == 1 else f"{sanitized}_{count}"
        # Reserve names case-insensitively to avoid collisions on
        # case-insensitive filesystems (e.g., default macOS/Windows).
        reserved_name = filename.casefold()
        if reserved_name not in used_filenames:
            used_filenames.add(reserved_name)
            return filename


def _sanitize_basic_data_key(key):
    filename = str(key).strip()
    filename = re.sub(r"[\\/]+", "_", filename)
    filename = re.sub(r"[^A-Za-z0-9._-]+", "_", filename)
    filename = filename.strip("._")
    return filename or "data"


def _is_dataframe_dict(data):
    if not isinstance(data, dict) or not data:
        return False
    try:
        import pandas as pd
    except ImportError:
        return False
    return all(isinstance(value, pd.DataFrame) for value in data.values())


def populate_db_from_zip_file(zip_path):
    from dallinger import data as dallinger_data

    db.session.commit()  # The process can freeze without this
    init_db(drop_all=True)
    dallinger_data.ingest_zip(zip_path)


def export_assets(
    export_path,
    anonymize,
    experiment_assets_only,
    include_on_demand_assets,
    n_parallel,
    server,
    local,
):
    # Assumes we already have loaded the experiment into the local database,
    # as would be the case if the function is called from psynet export.
    from .data import export_assets as _export_assets

    log(f"Exporting assets to {export_path}")

    include_private = not anonymize
    subdir = "anonymous" if anonymize else "regular"
    asset_path = os.path.join(export_path, subdir, "assets")

    _export_assets(
        asset_path,
        include_private,
        experiment_assets_only,
        include_on_demand_assets,
        n_parallel,
        server,
        local,
    )


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
    "Populates the local database with a provided zip file."
    from .experiment import import_local_experiment

    import_local_experiment()
    populate_db_from_zip_file(path)


# Example usage: psynet generate-config --recruiter mturk
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
@click.option(
    "--expire-hit/--no-expire-hit",
    flag_value=True,
    default=None,
    help="Expire any MTurk HITs associated with this experiment.",
)
@click.pass_context
def destroy__heroku(ctx, app, expire_hit):
    """
    Destroy the experiment on Heroku.
    """
    _destroy(
        ctx,
        dallinger.command_line.destroy,
        dallinger.command_line.expire,
        app=app,
        expire_hit=expire_hit,
    )


def user_confirms(question, default=False):
    """
    Like click.confirm but safe for using within our wrapped Docker commands.
    """
    print(question + " Enter 'y' for yes, 'n' for no.")
    return click.confirm("", default=default)


def _destroy(
    ctx,
    f_destroy,
    f_expire,
    app,
    expire_hit,
    server=None,
    ask_for_confirmation=True,
):
    confirmed = (
        user_confirms(
            "Would you like to delete the app from the web server?", default=True
        )
        if ask_for_confirmation
        else True
    )

    if confirmed:
        with yaspin("Destroying app...") as spinner:
            try:
                kwargs = {"app": app}
                kwargs = {**kwargs, "server": server} if server else kwargs
                if expire_hit in get_args(f_destroy):
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
                    "Failed to destroy the app. Maybe it was already destroyed, or the app name was wrong?"
                )

    if expire_hit is None:
        if user_confirms(
            "Would you like to look for a related MTurk HIT to expire?", default=True
        ):
            expire_hit = True

    if expire_hit:
        sandbox = user_confirms("Is this a sandbox HIT?", default=True)

        with yaspin("Expiring hit...") as spinner:
            ctx.invoke(
                f_expire,
                app=app,
                sandbox=sandbox,
            )
            spinner.ok("✔")


@destroy.command("ssh")
@click.option("--app", default=None, help="Experiment id")
@click.argument("apps", required=False, nargs=-1)
@option_server
@click.option(
    "--expire-hit",
    flag_value=True,
    default=False,
    help="Expire any MTurk HITs associated with this experiment.",
)
@click.pass_context
def destroy__docker_ssh(ctx, app, apps, server, expire_hit):
    """
    Destroy the experiment on a remote server via SSH.
    """
    from dallinger.command_line import expire
    from dallinger.command_line.docker_ssh import destroy

    example_usage = "`psynet destroy ssh <app> <app> [--server <server>]`"
    if app:
        assert len(apps) == 0, "You cannot provide both --app and a list of apps."
        click.echo(f"Consider using the batch syntax: {example_usage}")
        _destroy(
            ctx,
            destroy,
            expire,
            app=app,
            expire_hit=expire_hit,
            server=server,
        )
    if len(apps) > 0:
        assert app is None, "You cannot provide both --app and a list of apps."
        confirmation = f"""
            Are you sure you want to remove {len(apps)} apps on {server} ({apps})?
            """
        if click.confirm(confirmation, abort=True):
            for app in apps:
                _destroy(
                    ctx,
                    destroy,
                    expire,
                    app=app,
                    expire_hit=expire_hit,
                    server=server,
                    ask_for_confirmation=False,
                )


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


@test.command("local")
@_test_options["existing"]
@_test_options["n_bots"]
@_test_options["parallel"]
@_test_options["serial"]
@_test_options["stagger"]
@_test_options["time_factor"]
@_add_sql_profile_options
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
        exp.test_experiment()
        return

    import pytest

    exit_code = pytest.main(["test.py"])
    if exit_code != 0:
        # Use sys.exit() to ensure that the exit code is propagated to the shell.
        # This is helpful for CI pipelines, where we want to fail the build if the tests fail.
        sys.exit(exit_code)


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
    from dallinger.command_line.docker_ssh import Executor

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

    server_info = CONFIGURED_HOSTS[server]
    ssh_host = server_info["host"]
    ssh_user = server_info.get("user")
    executor = Executor(ssh_host, user=ssh_user)
    executor.run_and_echo(f"cd ~/dallinger/{app} && docker compose exec web {cmd}")


_test_options["performance_n_bots"] = click.option(
    "--n-bots",
    help="""
    The --n-bots parameter can accept a comma-separated list of integers
    to run sequential tests with different maximum concurrency levels.
    Example: --n-bots "5,10,20" will run three separate tests.
    If not specified, will default to Experiment.test_n_bots""",
)

_test_options["performance_time_factor"] = click.option(
    "--time-factor",
    type=float,
    default=None,
    help="""
    Multiply the timings in time_estimate by a random amount around this factor.
    Actual multiplier will vary randomly using a lognormal distribution with an upper
    bound of 3x this factor. When equal to zero, the bot will run through the
    experiment as fast as possible. If not specified, defaults to 1.0""",
)

_test_options["performance_stagger"] = click.option(
    "--stagger",
    help="""
    Average time interval to wait (in seconds) between starting each bot.
    Start times will vary randomly using a gamma distribution with an upper bound of 5x this value.
    If not specified, will default to Experiment.test_parallel_stagger_interval_s (0.1 s)""",
)

_test_options["duration_minutes"] = click.option(
    "--duration-minutes",
    type=float,
    default=None,
    help="""
    Total performance-test measurement window in minutes. This includes
    first-bot initialization and ramp-up towards 'n-bots', so the test may spend
    less than 'duration-minutes' at the target concurrency.
    If not specified, defaults to Experiment.test_duration_minutes (1 minute)""",
)

_test_options["performance_json_output"] = click.option(
    "--json-output",
    type=click.Path(dir_okay=False, writable=True),
    default=None,
    help="""
    If provided, write performance test results to this path as JSON.
    The file will contain a top-level object with: schema_version, psynet_version,
    dallinger_version, python_version, platform, experiment_label,
    started_at / finished_at (ISO timestamps), options (n_bots_sweep,
    duration_minutes, stagger_interval_s, time_factor), and results
    (one entry per bot count tested, with all metrics).
    Useful for downstream consumption (e.g. benchmarking tools like asv).
    Do not combine with --audit.""",
)


def _audit_flag_option(help_text: str):
    """Return a boolean ``--audit`` flag."""
    return click.option(
        "--audit",
        is_flag=True,
        default=False,
        help=help_text,
    )


_test_options["performance_audit"] = _audit_flag_option(
    """
    Write performance results to ./audit/artifacts/performance.json
    and mark performance_result present. Run from the experiment directory.
    Do not combine with --json-output. Use --no-mark-present to write the
    file without updating audit.json."""
)

_test_options["simulate_audit"] = _audit_flag_option(
    """
    After exporting data/simulated_data/, zip it to
    ./audit/artifacts/simulated_data.zip and mark simulation_export present.
    Run from the experiment directory. Use --no-mark-present to write the zip
    without updating audit.json."""
)

_test_options["audit_no_mark_present"] = click.option(
    "--no-mark-present",
    is_flag=True,
    default=False,
    help="With --audit, write the artifact file but do not update audit.json.",
)

AUDIT_PERFORMANCE_JSON = Path("artifacts") / "performance.json"
AUDIT_SIMULATED_DATA_ZIP = Path("artifacts") / "simulated_data.zip"
SIMULATED_DATA_EXPORT_PATH = Path("data") / "simulated_data"
AUDIT_ARTIFACT_IDS = {
    AUDIT_PERFORMANCE_JSON: "performance_result",
    AUDIT_SIMULATED_DATA_ZIP: "simulation_export",
}


def resolve_audit_root() -> Path:
    """Resolve ``./audit`` for ``--audit`` / audit CLI commands."""
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


def require_audit_when_skipping_mark_present(
    audit: bool, no_mark_present: bool
) -> None:
    """Reject ``--no-mark-present`` unless ``--audit`` is set."""
    if no_mark_present and not audit:
        raise click.UsageError("--no-mark-present requires --audit.")


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


def maybe_mark_audit_artifact_present(
    audit: bool,
    relative_path: Path,
    *,
    mark_present: bool,
) -> None:
    """Mark the written ``--audit`` artifact present unless the caller opted out."""
    if not audit or not mark_present:
        return
    mark_audit_artifact_present(relative_path)


def performance_results_have_successful_bots(all_results) -> bool:
    """Return True when any performance result completed at least one bot."""
    for result in all_results or []:
        if not isinstance(result, dict):
            continue
        try:
            succeeded = int(result.get("bots_succeeded") or 0)
        except (TypeError, ValueError):
            continue
        if succeeded > 0:
            return True
    return False


def maybe_mark_performance_result_present(
    audit: bool,
    all_results,
    *,
    mark_present: bool,
) -> None:
    """Mark ``performance_result`` present after a successful ``--audit`` run."""
    if not audit or not mark_present:
        return
    if not performance_results_have_successful_bots(all_results):
        click.echo(
            "Skipping performance_result mark-present: no bots succeeded. "
            "The JSON was still written; re-run a successful test or mark present later.",
            err=True,
        )
        return
    mark_audit_artifact_present(AUDIT_PERFORMANCE_JSON)


def resolve_performance_json_output(json_output=None, audit=False):
    """Resolve the JSON output path for a performance test.

    Parameters
    ----------
    json_output :
        Explicit JSON output path from ``--json-output``.
    audit :
        Whether ``--audit`` was set.

    Returns
    -------
    str or None
        Absolute or relative path to write, or ``None`` when no JSON output is
        requested.
    """
    if json_output and audit:
        raise click.UsageError("Use either --json-output or --audit, not both.")
    if json_output:
        return str(json_output)
    if not audit:
        return None
    return str(resolve_audit_artifact_path(AUDIT_PERFORMANCE_JSON))


def write_directory_zip(source_dir: Path, zip_path: Path) -> None:
    """Zip files under ``source_dir``.

    When ``source_dir`` is under the current working directory, archive members
    keep that relative prefix (for example ``data/simulated_data/...``).
    Directory entries are omitted; empty trees are rejected.
    """
    source_dir = Path(source_dir)
    if not source_dir.is_dir():
        raise click.UsageError(
            f"Cannot write audit zip: {source_dir} is not a directory."
        )

    zip_path = Path(zip_path)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    cwd = Path.cwd().resolve()
    resolved_source = source_dir.resolve()
    try:
        resolved_source.relative_to(cwd)
        archive_root = cwd
    except ValueError:
        archive_root = resolved_source.parent

    partial = zip_path.with_name(zip_path.name + ".partial")
    if partial.exists():
        partial.unlink()
    partial_resolved = partial.resolve()
    try:
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(resolved_source.rglob("*")):
                if not path.is_file():
                    continue
                if path.resolve() == partial_resolved:
                    continue
                archive.write(path, path.relative_to(archive_root).as_posix())
            if not archive.namelist():
                raise click.UsageError(
                    f"Cannot write audit zip: {source_dir} contains no files."
                )
        partial.replace(zip_path)
    except Exception:
        if partial.exists():
            partial.unlink()
        raise


def package_simulated_data_for_audit(
    export_path: Path = SIMULATED_DATA_EXPORT_PATH,
) -> Path:
    """Zip a simulate export into the audit packet's simulated-data artifact."""
    zip_path = resolve_audit_artifact_path(AUDIT_SIMULATED_DATA_ZIP)
    write_directory_zip(export_path, zip_path)
    return zip_path


def _run_simulate(ctx, audit=False, mark_present=True):
    """Run the experiment test, export simulated data, and optionally zip it."""
    if audit:
        resolve_audit_root()
    ctx.invoke(test__local)
    ctx.invoke(
        export__local,
        # TODO - maybe legacy is not the best name for this parameter...
        legacy=True,  # required because the server is not running any more, so we need to go direct to the DB
        no_source=True,
        path=SIMULATED_DATA_EXPORT_PATH.as_posix(),
    )
    if not audit:
        return
    zip_path = package_simulated_data_for_audit()
    click.echo(f"Simulated data (audit zip): {zip_path}")
    maybe_mark_audit_artifact_present(
        audit, AUDIT_SIMULATED_DATA_ZIP, mark_present=mark_present
    )


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
@_test_options["performance_n_bots"]
@_test_options["performance_stagger"]
@_test_options["performance_time_factor"]
@_test_options["duration_minutes"]
@_test_options["performance_json_output"]
@_test_options["performance_audit"]
@_test_options["audit_no_mark_present"]
@click.option("--debug", is_flag=True, help="Enable debug logging for verbose output")
def performance_test__local(
    existing=False,
    n_bots=None,
    stagger=None,
    time_factor=None,
    duration_minutes=None,
    json_output=None,
    audit=False,
    no_mark_present=False,
    debug=False,
):
    """
    Run a performance test of the experiment locally.

    The --n-bots parameter can accept a comma-separated list of integers
    to run sequential tests with different concurrency levels.
    Example: --n-bots "5,10,20" will run three separate tests.

    By default, this command starts a new experiment server automatically.
    Use --existing to connect to an already-running server instead.
    """
    require_audit_when_skipping_mark_present(audit, no_mark_present)
    json_output = resolve_performance_json_output(json_output, audit=audit)
    if existing:
        all_results = _run_performance_test_with_existing_server(
            n_bots, stagger, time_factor, duration_minutes, debug, json_output
        )
    else:
        all_results = _run_performance_test_with_new_server(
            n_bots, stagger, time_factor, duration_minutes, debug, json_output
        )
    maybe_mark_performance_result_present(
        audit, all_results, mark_present=not no_mark_present
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
    from psynet.perf_test import _to_json_safe

    payload = {
        "schema_version": 1,
        **metadata,
        "options": _to_json_safe(options),
        "results": [_to_json_safe(r) for r in all_results],
    }
    with open(json_output, "w") as f:
        json.dump(payload, f, indent=2, allow_nan=False)


def _run_performance_test_with_existing_server(
    n_bots, stagger, time_factor, duration_minutes, debug, json_output=None
):
    """Run performance test connecting to an already-running server."""
    import logging
    import sys

    from psynet.experiment import get_experiment

    # Configure logging to output to console
    root_logger = logging.getLogger()
    log_level = logging.DEBUG if debug else logging.INFO
    root_logger.setLevel(log_level)

    # Remove any existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Add console handler with clean format (no prefixes)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    formatter = logging.Formatter("%(message)s")
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    bot_log_file = tempfile.NamedTemporaryFile(
        delete=False, prefix="psynet_bots_", suffix=".log"
    )
    print(f"Bot output log: {bot_log_file.name}")

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

    os.environ["PASSTHROUGH_ERRORS"] = "True"

    # Parse n_bots - can be comma-separated list
    if n_bots:
        bot_counts = [int(x.strip()) for x in n_bots.split(",")]
    else:
        bot_counts = [exp.test_n_bots]

    tester = PerformanceTester(
        authenticated_session=exp.authenticated_session,
        base_url=exp.base_url,
        n_bots=exp.test_n_bots,
        duration_minutes=(
            exp.test_duration_minutes if duration_minutes is None else duration_minutes
        ),
        stagger_interval_s=(
            exp.test_parallel_stagger_interval_s if stagger is None else float(stagger)
        ),
        # Documented CLI default is 1.0 (realistic pacing). Do not fall back to
        # Experiment.test_time_factor, which defaults to 0.0 for correctness tests.
        time_factor=(1.0 if time_factor is None else time_factor),
    )
    started_at = datetime.datetime.now().isoformat(timespec="seconds")
    all_results = tester.run(bot_counts=bot_counts, bot_log_file=bot_log_file)
    finished_at = datetime.datetime.now().isoformat(timespec="seconds")
    bot_log_file.close()
    print(f"Bot output log: {bot_log_file.name}")

    if json_output:
        metadata = {
            **_collect_run_metadata(exp.label),
            "started_at": started_at,
            "finished_at": finished_at,
        }
        options = {
            "n_bots_sweep": bot_counts,
            "duration_minutes": tester.duration_minutes,
            "stagger_interval_s": tester.stagger_interval_s,
            "time_factor": tester.time_factor,
        }
        _write_json_results(
            json_output,
            metadata=metadata,
            options=options,
            all_results=all_results,
        )
        print(f"Performance results (JSON): {json_output}")
    return all_results


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
):
    """Spawn ``psynet <command_args>`` and wait for launch completion.

    Parameters
    ----------
    command_args : list[str]
        Arguments passed to the ``psynet`` executable, for example
        ``["debug", "local", "--legacy", "--no-browsers"]`` or
        ``["debug", "local"]``.
    """
    print("▶ Starting experiment server...")

    tmp_log = tempfile.NamedTemporaryFile(
        delete=False, prefix="psynet_server_", suffix=".log"
    )
    tmp_log_path = tmp_log.name
    tmp_log.close()
    print(f"Server log: {tmp_log_path}")

    log_file = open(tmp_log_path, "a", encoding="utf-8")
    logfile = _OutputTee(sys.stdout, log_file) if debug else log_file
    env = os.environ.copy()
    env.setdefault("SKIP_DEPENDENCY_CHECK", "1")
    env.setdefault("BROWSER", "true")

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
        raise click.ClickException("Failed to start experiment server.")


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


def _run_performance_test_with_new_server(
    n_bots, stagger, time_factor, duration_minutes, debug, json_output=None
):
    """Run performance test after starting a new experiment server"""
    # Prefer legacy debug: it more closely matches a real deployed server than
    # the auto-reload develop path used by normal ``psynet debug local``.
    server_info = _start_local_server_and_wait_for_ready(
        ["debug", "local", "--legacy", "--no-browsers"],
        debug=debug,
    )

    try:
        _load_runtime_server_config()
        all_results = _run_performance_test_with_existing_server(
            n_bots, stagger, time_factor, duration_minutes, debug, json_output
        )
        print("✓ Performance test completed")
        return all_results

    finally:
        _stop_server(server_info)


@performance_test.command("ssh")
@click.option("--app", required=True, help="Name of the experiment app.")
@option_server
@_test_options["performance_n_bots"]
@_test_options["performance_stagger"]
@_test_options["performance_time_factor"]
@_test_options["duration_minutes"]
@_test_options["performance_json_output"]
@_test_options["performance_audit"]
@_test_options["audit_no_mark_present"]
@click.pass_context
def performance_test__docker_ssh(
    ctx,
    app,
    server,
    n_bots=None,
    stagger=None,
    time_factor=None,
    duration_minutes=None,
    json_output=None,
    audit=False,
    no_mark_present=False,
):
    """
    Runs performance tests on the remote server. Assumes that the app has
    already been launched on the remote server using ``psynet debug ssh``.

    Running this command will not reset the database to a vanilla state, but
    will instead just use the state that exists already. Be sure the app has is
    configured to allow a large quantity of bots.

    If the app is in use during the performance test, results may not be
    reliable.

    Note: The --json-output, --audit, and --no-mark-present options are not yet
    supported for remote SSH execution. For JSON output, run
    ``psynet performance-test local --json-output`` or ``--audit`` instead.
    """
    require_audit_when_skipping_mark_present(audit, no_mark_present)
    if json_output or audit:
        raise click.UsageError(
            "--json-output, --audit, and --no-mark-present are not yet "
            "implemented for SSH mode. "
            "Use 'psynet performance-test local' with those options instead.",
        )

    from dallinger.command_line.docker_ssh import Executor

    cmd = _build_ssh_performance_test_cmd(
        n_bots=n_bots,
        stagger=stagger,
        time_factor=time_factor,
        duration_minutes=duration_minutes,
    )

    server_info = CONFIGURED_HOSTS[server]
    ssh_host = server_info["host"]
    ssh_user = server_info.get("user")
    executor = Executor(ssh_host, user=ssh_user)
    executor.run_and_echo(f"cd ~/dallinger/{app} && docker compose exec web {cmd}")


def _build_ssh_performance_test_cmd(n_bots, stagger, time_factor, duration_minutes):
    """Build the remote performance-test command, preserving explicit zeros."""
    cmd = "psynet performance-test local --existing"

    if n_bots is not None:
        cmd += f" --n-bots {n_bots}"

    if stagger is not None:
        cmd += f" --stagger {stagger}"

    if time_factor is not None:
        cmd += f" --time-factor {time_factor}"

    if duration_minutes is not None:
        cmd += f" --duration-minutes {duration_minutes}"

    return cmd


@psynet.command()
@_test_options["simulate_audit"]
@_test_options["audit_no_mark_present"]
@click.pass_context
@require_exp_directory
def simulate(ctx, audit=False, no_mark_present=False):
    """
    Generates simulated data for an experiment by running the experiment's regression test
    and exporting the resulting data.

    Writes ``data/simulated_data/``. Pass ``--audit`` to also zip that directory
    to ``./audit/artifacts/simulated_data.zip`` and mark
    ``simulation_export`` present.
    """
    # No need to catch the exit code here, because test__local now uses sys.exit()
    # if an error occurs.
    require_audit_when_skipping_mark_present(audit, no_mark_present)
    _run_simulate(ctx, audit=audit, mark_present=not no_mark_present)


@psynet.command(name="list-experiment-dirs")
@click.option("--for-ci-tests", is_flag=True)
@click.option("--ci-node-total", default=None, type=int)
@click.option("--ci-node-index", default=None, type=int)
def _list_experiment_dirs(for_ci_tests=False, ci_node_total=None, ci_node_index=None):
    """
    Lists the directories of all the experiments that are available under the 'demos' directory,
    plus those inside the 'tests/experiments' directory.
    """
    for directory in list_experiment_dirs(
        for_ci_tests=for_ci_tests,
        ci_node_total=ci_node_total,
        ci_node_index=ci_node_index,
    ):
        print(directory)


@psynet.command(name="list-isolated-tests")
@click.option("--ci-node-total", default=None, type=int)
@click.option("--ci-node-index", default=None, type=int)
def _list_isolated_tests(ci_node_total=None, ci_node_index=None):
    """
    Lists the directories of all the demo experiments that are available.
    """
    for test_ in list_isolated_tests(
        ci_node_total=ci_node_total,
        ci_node_index=ci_node_index,
    ):
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
    Package experiment readiness evidence (does not run tests).

    An audit records artifacts, checks, and blockers for human inspection.
    It does not run tests or collect evidence for you. Audits always live in
    ./audit/ inside the experiment directory. Run these commands from the
    experiment directory.
    """
    pass


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
