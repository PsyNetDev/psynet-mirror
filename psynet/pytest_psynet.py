import logging
import os
import re
import subprocess
import sys
import time
import warnings
from functools import cached_property
from pathlib import Path
from urllib import parse

import dallinger.pytest_dallinger
import pexpect
import pexpect.exceptions
import pytest
import sqlalchemy.exc
from dallinger import db, pytest_dallinger
from dallinger.bots import BotBase
from dallinger.config import get_config
from dallinger.models import Node
from dallinger.pytest_dallinger import flush_output
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    NoSuchElementException,
    TimeoutException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from psynet.artifact import LocalArtifactStorage, S3ArtifactStorage
from psynet.participant import Participant

from . import artifact as psynet_artifact
from . import asset as psynet_asset
from . import data as _psynet_data  # noqa: F401  # patches dallinger.db.init_db
from .command_line import (
    clean_sys_modules,
    kill_chromedriver_processes,
    kill_psynet_chrome_processes,
    stop_local_debug_process,
    working_directory,
)
from .experiment import get_experiment, import_local_experiment
from .experiment_scaffold import (
    scaffold_missing_files,
)
from .modular_page import ModularPage, PushButtonControl
from .redis import redis_vars
from .test_helpers.mock_s3 import (
    get_mock_s3_client,
    get_mock_s3_resource,
)
from .testing.chrome_driver import create_psynet_chrome_driver
from .trial.main import TrialNetwork
from .trial.static import StaticNode, StaticTrial, StaticTrialMaker
from .utils import clear_all_caches, is_in_repo_experiment, wait_until

logger = logging.getLogger(__file__)
warnings.filterwarnings("ignore", category=sqlalchemy.exc.SAWarning)

ci_only = pytest.mark.skipif(
    os.environ.get("CI") is None, reason="This test only runs in CI environment"
)

local_only = pytest.mark.skipif(
    os.environ.get("CI") is not None, reason="This test only runs in local environment"
)


def assert_text(driver, element_id, value):
    def get_element():
        try:
            return driver.find_element(By.ID, element_id)
        except NoSuchElementException:
            pass

    wait_until(
        get_element,
        max_wait=5,
        error_message=f"Could not find element with ID {element_id}",
    )
    element = get_element()

    def sanitize(x):
        pattern = re.compile(r"\s+")
        return re.sub(pattern, " ", x).strip()

    if sanitize(element.text) != sanitize(value):
        raise AssertionError(
            f"""
            Found some unexpected HTML text.

            Expected: {sanitize(value)}

            Found: {sanitize(element.text)}
            """
        )


@pytest.fixture
def mock_s3_root(tmp_path, monkeypatch):
    """
    Configure the filesystem-backed S3 mock for PsyNet tests.

    This fixture monkeypatches current-process S3 helpers and sets
    ``PSYNET_MOCK_S3_ROOT``, so child processes such as ``psynet prepare`` use
    the same mock too. It verifies storage/export behavior, not public HTTP
    access to generated S3 URLs.
    """
    root = tmp_path / "psynet-mock-s3"
    client = get_mock_s3_client(str(root))
    resource = get_mock_s3_resource(str(root))

    monkeypatch.setenv("PSYNET_MOCK_S3_ROOT", str(root))
    monkeypatch.setattr(psynet_asset, "get_s3_client", lambda: client)
    monkeypatch.setattr(psynet_asset, "get_s3_resource", lambda: resource)
    monkeypatch.setattr(psynet_asset, "get_s3_bucket", resource.Bucket)
    monkeypatch.setattr(psynet_artifact, "get_s3_client", lambda: client)
    psynet_asset.list_files_in_s3_bucket__cached.cache_clear()

    try:
        client.create_bucket(Bucket="psynet-tests")
        yield root
    finally:
        psynet_asset.list_files_in_s3_bucket__cached.cache_clear()


def bot_class(headless=None):
    if headless is None:
        headless_env = os.getenv("HEADLESS", default="FALSE").upper()
        assert headless_env in ["TRUE", "FALSE"]
        headless = headless_env == "TRUE"

    class PYTEST_BOT_CLASS(BotBase):
        def sign_up(self):
            """Accept HIT, give consent and start experiment.

            This uses Selenium to click through buttons on the ad,
            consent, and instruction pages.
            """
            try:
                self.driver.set_window_size(1024, 768)

                self.driver.get(self.URL)
                logger.info("Loaded ad page.")

                # First ensure the page is fully loaded
                WebDriverWait(self.driver, 10).until(
                    lambda d: page_loaded(d), message="Page failed to load completely"
                )
                logger.info("Page fully loaded.")

                # Then check for the button
                begin = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "button.btn-primary")),
                    message="Begin experiment button not found or not clickable",
                )

                # Scroll button into view and wait until it's actually visible
                self.driver.execute_script(
                    "arguments[0].scrollIntoView({block: 'center'});", begin
                )

                # Wait until the button is actually in view
                WebDriverWait(self.driver, 10).until(
                    lambda d: d.execute_script(
                        """
                        const rect = arguments[0].getBoundingClientRect();
                        return (
                            rect.top >= 0 &&
                            rect.left >= 0 &&
                            rect.bottom <= window.innerHeight &&
                            rect.right <= window.innerWidth
                        );
                    """,
                        begin,
                    ),
                    message="Button failed to scroll into view",
                )

                try:
                    begin.click()
                except ElementClickInterceptedException:
                    _debug_click_interception(self.driver, begin)
                    raise

                logger.info("Clicked begin experiment button.")

                experiment = get_experiment()
                if experiment.start_experiment_in_popup_window:
                    WebDriverWait(self.driver, 10).until(
                        lambda d: len(d.window_handles) == 2
                    )
                    self.driver.switch_to.window(self.driver.window_handles[-1])
                    logger.info("Switched to experiment popup.")
                    self.driver.set_window_size(1024, 768)
                else:
                    self.driver.set_window_size(1024, 1024)

                consent = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.ID, "consent"))
                )
                consent.click()
                logger.info("Clicked consent button.")

                # Extract unique_id from URL to set participant_id on bot (required for Dallinger v12.0.0+)
                WebDriverWait(self.driver, 10).until(
                    lambda d: "unique_id" in d.current_url
                )
                url = self.driver.current_url
                query_params = parse.parse_qs(parse.urlparse(url).query)
                unique_id = self.get_from_query(query_params, ["unique_id"])
                participant = Participant.query.filter_by(unique_id=unique_id).first()
                self.participant_id = str(participant.id)

                return True
            except TimeoutException:
                logger.error("Error during experiment sign up.")
                return False

        def sign_off(self):
            try:
                logger.info("Clicked submit questionnaire button.")
                self.driver.switch_to.window(self.driver.window_handles[0])
                self.driver.set_window_size(1024, 768)
                logger.info("Switched back to initial window.")
                return True
            except TimeoutException:
                logger.error("Error during experiment sign off.")
                return False

        @cached_property
        def driver(self):
            return create_psynet_chrome_driver(headless=headless)

    return PYTEST_BOT_CLASS


def page_loaded(driver):
    return driver.execute_script("return document.readyState == 'complete'")


def psynet_page_ready(driver):
    """Return whether the current PsyNet page lifecycle is ready."""
    return driver.execute_script(
        """
        const psynet = window.psynet;
        if (!psynet || psynet.nextPagePending === true) {
            return false;
        }
        // New in-place timeline pages expose an explicit lifecycle readiness
        // flag. The DOM marker confirms that the swapped fragment has updated
        // the visible page body, and pageUuid is needed for transition checks.
        if (typeof psynet.pageReady !== "undefined") {
            return psynet.pageReady === true &&
                document.querySelector("#main-body[data-page-ready]") !== null &&
                typeof window.pageUuid !== "undefined";
        }
        // Legacy full-page loads do not define pageReady; pageLoaded is the
        // older PsyNet lifecycle signal. Keep this fallback until those tests
        // move fully to the in-place timeline contract.
        return psynet.pageLoaded === true &&
            typeof window.pageUuid !== "undefined";
        """
    )


def psynet_loaded(driver):
    """Backward-compatible alias for page lifecycle readiness."""
    return psynet_page_ready(driver)


def next_page(driver, button_identifier, by=By.ID, finished=False, max_wait=10.0):
    def get_uuid():
        return driver.execute_script("return window.pageUuid")

    def find_button():
        return driver.find_element(by, button_identifier)

    def target_ready_to_click():
        try:
            button = find_button()
        except NoSuchElementException:
            return False
        return button.is_displayed() and button.is_enabled()

    wait_until(
        psynet_page_ready,
        max_wait=max_wait,
        error_message="Page never became ready.",
        driver=driver,
    )
    wait_until(
        target_ready_to_click,
        max_wait=max_wait,
        error_message=f"Button {button_identifier!r} never became ready to click.",
    )

    old_uuid = get_uuid()
    find_button().click()
    if finished:
        wait_until(
            lambda: "recruiter-exit" in driver.current_url,
            max_wait=max_wait,
            error_message="Never reached the recruiter-exit route, seems like the experiment never finished.",
        )
    else:
        if driver.current_url == "http://localhost:5000/error-page":
            raise RuntimeError(
                "Unexpectedly hit an error page, check the server logs for details."
            )

        wait_until(
            lambda: psynet_page_ready(driver) and get_uuid() != old_uuid,
            max_wait=max_wait,
            error_message="Failed to load new page.",
        )


def click_finish_button(driver):
    next_page(driver, "Finish", finished=True)


@pytest.fixture
def deployment_info():
    from psynet import deployment_info

    deployment_info.reset()
    deployment_info.init(
        redeploying_from_archive=False,
        mode="debug",
        is_local_deployment=True,
        is_ssh_deployment=False,
        server="local",
        app="local",
    )
    deployment_info.write(deployment_id="Test deployment")
    yield
    deployment_info.delete()


@pytest.fixture(scope="class")
def experiment_directory(request):
    return request.param


loaded_experiment_directory = None


@pytest.fixture(scope="class")
def in_experiment_directory(experiment_directory):
    global loaded_experiment_directory
    if (
        loaded_experiment_directory is not None
        and loaded_experiment_directory != experiment_directory
    ):
        raise RuntimeError(
            "Tried to run tests in two different experiment directories in the same testing session "
            f"('{loaded_experiment_directory}' and '{experiment_directory}'. "
            "This is not supported, because it is hard to unload an experiment fully without contaminating "
            "the next one. If you are seeing this error in the PsyNet test suite, you should make sure your test "
            "is located in the tests/isolated directory, and make sure that each test file only accesses a single "
            "experiment directory."
        )
    loaded_experiment_directory = experiment_directory
    redis_vars.clear()
    cleanup_error = None
    with working_directory(experiment_directory):
        try:
            with scaffold_missing_files():
                # In-repo demos/tests use PsyNet's shared development .venv, so
                # skip Dallinger's constraints regeneration. Standalone temp
                # experiment dirs still need the env override when constraints
                # are absent.
                original_skip_dependency_check = os.getenv("SKIP_DEPENDENCY_CHECK")
                if is_in_repo_experiment() or not Path("constraints.txt").exists():
                    os.environ["SKIP_DEPENDENCY_CHECK"] = "1"
                try:
                    yield experiment_directory
                finally:
                    if original_skip_dependency_check is None:
                        os.environ.pop("SKIP_DEPENDENCY_CHECK", None)
                    else:
                        os.environ["SKIP_DEPENDENCY_CHECK"] = (
                            original_skip_dependency_check
                        )
        except Exception as exc:
            cleanup_error = exc
    clean_sys_modules()
    clear_all_caches()
    if cleanup_error is not None:
        raise cleanup_error


@pytest.fixture(scope="class")
def skip_constraints_check():
    original = os.getenv("SKIP_DEPENDENCY_CHECK", None)
    os.environ["SKIP_DEPENDENCY_CHECK"] = "1"
    yield
    if original is None:
        del os.environ["SKIP_DEPENDENCY_CHECK"]
    else:
        os.environ["SKIP_DEPENDENCY_CHECK"] = original


# dallinger_clear_workers = pytest_dallinger.clear_workers.__wrapped__


@pytest.fixture(scope="class")
def clear_workers():
    def _zap():
        kills = [["pkill", "-f", "heroku"]]
        for kill in kills:
            try:
                subprocess.check_call(kill)
            except Exception as e:
                if e.returncode != 1:
                    raise

    _zap()
    yield
    _zap()


pytest_dallinger.clear_workers = clear_workers


def patch_pexpect_error_reporter(p):
    p.str_last_chars = 2000
    # original_reporter = pexpect.spawn.__str__
    #
    # def __str__(self):
    #     original = original_reporter(self)
    #     new = "\n".join(
    #         [
    #             "~~~",
    #             "Full error context:",
    #             "",
    #             self.before[-10000:],
    #             "~~~",
    #         ]
    #     )
    #     return original + "\n\n" + new
    #
    # pexpect.spawn.__str__ = __str__


@pytest.fixture(scope="class")
def debug_experiment(
    request,
    env,
    clear_workers,
    in_experiment_directory,
    db_session,
    skip_constraints_check,
):
    """
    This overrides the debug_experiment fixture in Dallinger to
    use PsyNet debug instead. Note that we use legacy mode for now.
    """
    print(f"Launching experiment in directory '{in_experiment_directory}'...")
    # db_session already reset the database for this test class. Brief pause so
    # any lingering teardown from the previous class can finish before launch.
    time.sleep(0.5)
    kill_psynet_chrome_processes()
    kill_chromedriver_processes()

    timeout = 60

    get_experiment()

    config = get_config()
    if not config.ready:
        config.load()

    p = pexpect.spawn(
        "psynet",
        ["debug", "local", "--legacy", "--no-browsers"],
        env={
            **env,
            "dashboard_user": "test_admin",
            "dashboard_password": "test_password",
        },
        encoding="utf-8",
    )
    patch_pexpect_error_reporter(p)
    p.logfile = sys.stdout
    p.timeout = timeout

    try:
        p.expect_exact("Experiment launch complete!", timeout=timeout)

        # The config file in server_working_directory has a few extra parameters
        # that we need to set in order to simulate the real experiment server as well as possible.
        server_working_directory = redis_vars.get("server_working_directory")
        config.load_from_file(os.path.join(server_working_directory, "config.txt"))

        yield p
    finally:
        # Wait for the server (and orphaned workers) to fully stop before the
        # next test class resets the database; a short Ctrl-C + log flush is
        # not enough and can leave backends holding locks during drop_all.
        try:
            _stop_debug_experiment_process(p)
        finally:
            kill_psynet_chrome_processes()
            kill_chromedriver_processes()
            clear_all_caches()


dallinger.pytest_dallinger.debug_experiment = debug_experiment


def _stop_debug_experiment_process(process):
    """Flush logs best-effort, then always stop the debug process and workers."""
    try:
        flush_output(process, timeout=0.1)
    except (OSError, pexpect.exceptions.EOF) as err:
        logger.warning("Error while flushing debug experiment output: %s", err)
    except Exception:
        logger.exception("Unexpected error while flushing debug experiment output")

    try:
        stop_local_debug_process(process)
    except (OSError, pexpect.exceptions.EOF) as err:
        logger.warning("Error while stopping the debug experiment process: %s", err)
    except Exception:
        logger.exception("Unexpected error while stopping the debug experiment process")


@pytest.fixture(scope="class")
def launched_experiment(debug_experiment):
    return get_experiment()


@pytest.fixture(scope="class")
def debug_server_process(debug_experiment):
    return debug_experiment


def terminate_other_postgres_connections():
    """
    Terminate other backends of the current role connected to the test database.

    Used only as a deadlock-retry backstop: the primary mitigation is waiting
    for the previous experiment server to fully stop in ``debug_experiment``
    teardown. If a rare leftover session still holds locks during ``drop_all``,
    terminating those backends clears them before the next attempt.

    Only backends owned by the current database role are targeted: terminating
    other roles' backends would require extra privileges (raising
    ``InsufficientPrivilege`` otherwise) and could kill sessions unrelated to
    the test run, such as a developer's ``psql`` shell.

    Closes local sessions and disposes the engine's connection pool first, so
    that this process's own idle pooled connections are not terminated out
    from under it. Connections checked out elsewhere in the process would
    still be terminated, so this must only run when no other component holds
    a database connection (as is the case at the test-setup call sites).
    """
    from sqlalchemy import text
    from sqlalchemy.orm.session import close_all_sessions

    close_all_sessions()
    db.engine.dispose()

    with db.engine.connect() as con:
        con.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = current_database() AND pid <> pg_backend_pid() "
                "AND usename = current_user"
            )
        )


# Postgres SQLSTATE code for "deadlock detected"; matching on the code rather
# than the error message keeps detection independent of the server's locale.
DEADLOCK_PGCODE = "40P01"


def _is_deadlock_error(err):
    """Check whether a SQLAlchemy error wraps a Postgres deadlock."""
    return getattr(err.orig, "pgcode", None) == DEADLOCK_PGCODE


def init_db_with_retries(max_attempts=3, wait_sec=2.0):
    """
    Reset the database for a test, retrying if a deadlock is detected.

    The primary mitigation for between-test deadlocks is waiting for the
    previous experiment server to fully stop in ``debug_experiment`` teardown.
    On deadlock, terminate leftover same-role backends and retry; that
    termination is intentionally not done on the happy path.

    Calls ``dallinger.db.init_db``, which is PsyNet's patched version
    (``psynet.data`` is imported by this module for that side effect). That
    wrapper closes sessions before ``drop_all``.
    """
    import dallinger.db

    for attempt in range(1, max_attempts + 1):
        try:
            return dallinger.db.init_db(drop_all=True)
        except sqlalchemy.exc.OperationalError as err:
            if not _is_deadlock_error(err) or attempt == max_attempts:
                raise
            logger.warning(
                "Deadlock detected while resetting the database "
                "(attempt %d/%d); terminating leftover connections and retrying...",
                attempt,
                max_attempts,
            )
            terminate_other_postgres_connections()
            time.sleep(wait_sec)


@pytest.fixture(scope="class")
def db_session(in_experiment_directory):
    import dallinger.db

    # The drop_all call can hang without this; see:
    # https://stackoverflow.com/questions/13882407/sqlalchemy-blocked-on-dropping-tables
    dallinger.db.session.close()
    session = init_db_with_retries()
    yield session
    session.rollback()
    session.close()


dallinger.pytest_dallinger.db_session = db_session


@pytest.fixture(scope="class")
def imported_experiment(launched_experiment):
    return import_local_experiment()


@pytest.fixture(scope="class")
def experiment_module(imported_experiment):
    return imported_experiment["module"]


@pytest.fixture(scope="class")
def experiment_class(imported_experiment):
    return imported_experiment["class"]


@pytest.fixture(scope="class")
def experiment_object(experiment_class):
    return experiment_class()


# @pytest.fixture
# def prepopulated_database(in_experiment_directory):
#     from psynet.command_line import run_prepare_in_subprocess
#     from psynet.experiment import ExperimentConfig
#
#     database_is_populated = ExperimentConfig.query.count() > 0
#     if not database_is_populated:
#         db.session.commit()
#         run_prepare_in_subprocess()


@pytest.fixture(scope="class")
def participant(launched_experiment):
    from psynet.bot import Bot

    return Bot()


@pytest.fixture(scope="class")
def node(launched_experiment):
    nodes = Node.query.all()
    return [n for n in nodes if n.definition is not None][0]


@pytest.fixture(scope="class")
def network(launched_experiment):
    return TrialNetwork.query.all()[0]


@pytest.fixture(scope="class")
def trial_class(experiment_module):
    return experiment_module.AnimalTrial


@pytest.fixture
def trial_maker(experiment_module):
    return experiment_module.trial_maker


@pytest.fixture(scope="class")
def trial(launched_experiment, trial_class, node, participant):
    t = trial_class(
        experiment=launched_experiment,
        node=node,
        participant=participant,
        propagate_failure=False,
        is_repeat_trial=False,
    )
    db.session.add(t)
    db.session.commit()
    return t


@pytest.fixture
def deployment_id():
    from psynet.experiment import Experiment

    id_ = "Test deployment"
    old_id = Experiment.deployment_id
    Experiment.deployment_id = id_
    yield id_
    Experiment.deployment_id = old_id


# def assert_logs_contain(text, process, regex=False, timeout=5):
#     try:
#         if regex:
#             process.expect(text, timeout=timeout)
#         else:
#             process.expect_exact(text, timeout=timeout)
#     except (pexpect.EOF, pexpect.TIMEOUT):
#         print("Failed to find match in server logs.")
#         # print("History:")
#         # wrapper = textwrap.TextWrapper(initial_indent=4, subsequent_indent=4)
#         # print(wrapper.fill(str(process.before)))
#         raise


def path_to_demo_experiment(demo):
    return (
        Path(__file__)
        .parent.parent.joinpath("demos/experiments")
        .joinpath(demo)
        .__str__()
    )


def path_to_demo_feature(demo):
    return (
        Path(__file__).parent.parent.joinpath("demos/features").joinpath(demo).__str__()
    )


def path_to_test_experiment(experiment):
    return (
        Path(__file__)
        .parent.parent.joinpath("tests/experiments")
        .joinpath(experiment)
        .__str__()
    )


nodes_1 = [
    StaticNode(
        definition={"animal": animal},
        block=block,
    )
    for animal in ["cats", "dogs", "fish", "ponies"]
    for block in ["A", "B", "C"]
]


class AnimalTrial(StaticTrial):
    """
    A trial class for use in tests.
    """

    time_estimate = 3

    def show_trial(self, experiment, participant):
        animal = self.definition["animal"]
        return ModularPage(
            "animal_trial",
            f"How much do you like {animal}?",
            PushButtonControl(
                ["Not at all", "A little", "Very much"],
            ),
            time_estimate=self.time_estimate,
        )


nodes_2 = [
    StaticNode(
        definition={"color": color},
        block=block,
    )
    for color in ["red", "green", "blue", "orange"]
    for block in ["A", "B", "C"]
]


class ColorTrial(StaticTrial):
    """
    A trial class for use in tests.
    """

    time_estimate = 3

    def show_trial(self, experiment, participant):
        color = self.definition["color"]
        return ModularPage(
            "color_trial",
            f"How much do you like {color}?",
            PushButtonControl(
                ["Not at all", "A little", "Very much"],
            ),
            time_estimate=self.time_estimate,
        )


# A trial maker for use in tests
trial_maker_1 = StaticTrialMaker(
    id_="animals",
    trial_class=AnimalTrial,
    nodes=nodes_1,
    expected_trials_per_participant=6,
    max_trials_per_block=2,
    allow_repeated_nodes=True,
    balance_across_nodes=True,
    check_performance_at_end=False,
    check_performance_every_trial=False,
    target_n_participants=1,
    target_trials_per_node=None,
    recruit_mode="n_participants",
    n_repeat_trials=3,
)

# A trial maker for use in tests
trial_maker_2 = StaticTrialMaker(
    id_="colors",
    trial_class=ColorTrial,
    nodes=nodes_2,
    expected_trials_per_participant=6,
    max_trials_per_block=2,
    allow_repeated_nodes=True,
    balance_across_nodes=True,
    check_performance_at_end=False,
    check_performance_every_trial=False,
    target_n_participants=1,
    target_trials_per_node=None,
    recruit_mode="n_participants",
    n_repeat_trials=3,
)


def _debug_click_interception(driver, element):
    """Debug what's intercepting a click on an element.

    Parameters
    ----------
    driver : WebDriver
        The Selenium WebDriver instance
    element : WebElement
        The element that failed to be clicked

    Returns
    -------
    None
        Logs debug information about what's intercepting the click
    """
    location = element.location
    size = element.size
    click_x = location["x"] + size["width"] // 2
    click_y = location["y"] + size["height"] // 2

    # Log viewport size and scroll position
    viewport_size = driver.execute_script(
        """
        return {
            width: window.innerWidth,
            height: window.innerHeight,
            scrollX: window.scrollX,
            scrollY: window.scrollY
        };
    """
    )
    logger.error(f"Viewport size and scroll: {viewport_size}")

    # Check if element is in viewport
    is_in_viewport = driver.execute_script(
        """
        const rect = arguments[0].getBoundingClientRect();
        return {
            isVisible: rect.width > 0 && rect.height > 0,
            isInViewport: (
                rect.top >= 0 &&
                rect.left >= 0 &&
                rect.bottom <= window.innerHeight &&
                rect.right <= window.innerWidth
            ),
            rect: {
                top: rect.top,
                left: rect.left,
                bottom: rect.bottom,
                right: rect.right
            }
        };
    """,
        element,
    )
    logger.error(f"Element viewport status: {is_in_viewport}")

    # Get element at click coordinates
    element_at_point = driver.execute_script(
        """
        return document.elementFromPoint(arguments[0], arguments[1]);
        """,
        click_x,
        click_y,
    )

    # Get all elements that overlap with our button
    overlapping_elements = driver.execute_script(
        """
        const button = arguments[0];
        const buttonRect = button.getBoundingClientRect();
        const elements = document.elementsFromPoint(
            buttonRect.left + buttonRect.width/2,
            buttonRect.top + buttonRect.height/2
        );
        return elements.map(el => ({
            tag: el.tagName,
            id: el.id,
            class: el.className,
            text: el.textContent?.trim()
        }));
        """,
        element,
    )

    logger.error(f"Button location: {location}, size: {size}")
    logger.error(
        f"Element at click point: {element_at_point.get_attribute('outerHTML') if element_at_point else 'None'}"
    )
    logger.error(f"Overlapping elements: {overlapping_elements}")


@pytest.fixture(params=["local", "s3"])
def artifact_storage(request, tmp_path, mock_s3_root):
    if request.param == "local":
        yield LocalArtifactStorage(str(tmp_path))
    elif request.param == "s3":
        bucket_name = "psynet-tests"
        root = "artifacts"
        yield S3ArtifactStorage(root, bucket_name)
