import os

import pytest

from psynet.testing import chrome_driver


class FakeOptions:
    def __init__(self):
        self.arguments = []
        self.binary_location = None

    def add_argument(self, argument):
        self.arguments.append(argument)


class FakeService:
    def __init__(self, log_output, service_args, executable_path=None):
        self.log_output = log_output
        self.service_args = service_args
        self.executable_path = executable_path


class FakeDriver:
    def __init__(self):
        self.session_id = "session-id"
        self.capabilities = {
            "browserVersion": "1.0",
            "chrome": {"chromedriverVersion": "1.0"},
        }
        self.quit_calls = 0
        self.window_sizes = []

    def quit(self):
        self.quit_calls += 1

    def set_window_size(self, width, height):
        self.window_sizes.append((width, height))


class FakeWebDriver:
    def __init__(self, driver=None, launch_error=None):
        self.driver = driver
        self.launch_error = launch_error
        self.last_options = None
        self.last_service = None

    def Chrome(self, options, service):
        self.last_options = options
        self.last_service = service
        if self.launch_error is not None:
            raise self.launch_error
        return self.driver


@pytest.fixture
def chrome_paths(tmp_path, monkeypatch):
    profile_path = tmp_path / "profile"
    profile_path.mkdir()
    log_path = tmp_path / "chromedriver.log"
    log_path.write_text("chromedriver output", encoding="utf-8")

    def fake_mkdtemp(prefix):
        assert prefix == "psynet-chrome-"
        return str(profile_path)

    def fake_mkstemp(prefix, suffix):
        assert prefix == "psynet-chromedriver-"
        assert suffix == ".log"
        fd = os.open(log_path, os.O_RDWR | os.O_CREAT)
        return fd, str(log_path)

    monkeypatch.setattr(chrome_driver.tempfile, "mkdtemp", fake_mkdtemp)
    monkeypatch.setattr(chrome_driver.tempfile, "mkstemp", fake_mkstemp)
    return profile_path, log_path


def test_create_chrome_driver_cleans_artifacts_on_quit(chrome_paths, monkeypatch):
    profile_path, log_path = chrome_paths

    fake_driver = FakeDriver()
    fake_webdriver = FakeWebDriver(driver=fake_driver)

    monkeypatch.setenv("PSYNET_CHROMEDRIVER_VERBOSE", "1")
    monkeypatch.delenv("PSYNET_KEEP_CHROMEDRIVER_LOGS", raising=False)
    monkeypatch.setattr(
        chrome_driver,
        "_get_chrome_dependencies",
        lambda: (fake_webdriver, FakeOptions, FakeService),
    )

    driver = chrome_driver.create_psynet_chrome_driver(headless=True)

    assert "--disable-dev-shm-usage" in fake_webdriver.last_options.arguments
    assert "--no-sandbox" in fake_webdriver.last_options.arguments
    assert "--disable-gpu" in fake_webdriver.last_options.arguments
    assert "--remote-debugging-pipe" in fake_webdriver.last_options.arguments
    assert "--headless=new" in fake_webdriver.last_options.arguments
    assert f"--user-data-dir={profile_path}" in fake_webdriver.last_options.arguments
    assert fake_webdriver.last_service.log_output == str(log_path)
    assert fake_webdriver.last_service.service_args == ["--verbose"]
    assert profile_path.exists()
    assert log_path.exists()
    assert fake_driver.window_sizes == [(1024, 768)]

    driver.quit()
    driver.quit()

    assert not profile_path.exists()
    assert not log_path.exists()
    assert fake_driver.quit_calls == 2


def test_create_chrome_driver_preserves_log_when_configured(chrome_paths, monkeypatch):
    profile_path, log_path = chrome_paths

    fake_driver = FakeDriver()
    fake_webdriver = FakeWebDriver(driver=fake_driver)

    monkeypatch.setenv("PSYNET_CHROMEDRIVER_VERBOSE", "1")
    monkeypatch.setenv("PSYNET_KEEP_CHROMEDRIVER_LOGS", "1")
    monkeypatch.setattr(
        chrome_driver,
        "_get_chrome_dependencies",
        lambda: (fake_webdriver, FakeOptions, FakeService),
    )

    driver = chrome_driver.create_psynet_chrome_driver(headless=False)
    driver.quit()

    assert not profile_path.exists()
    assert log_path.exists()


def test_create_chrome_driver_cleans_profile_on_launch_error(chrome_paths, monkeypatch):
    profile_path, log_path = chrome_paths

    fake_webdriver = FakeWebDriver(launch_error=RuntimeError("boom"))

    monkeypatch.setattr(
        chrome_driver,
        "_get_chrome_dependencies",
        lambda: (fake_webdriver, FakeOptions, FakeService),
    )

    with pytest.raises(RuntimeError, match="boom"):
        chrome_driver.create_psynet_chrome_driver(headless=False)

    assert not profile_path.exists()
    assert log_path.exists()


def test_create_chrome_driver_retries_until_success(tmp_path, monkeypatch):
    profile_paths = []
    log_paths = []
    sleep_calls = []
    fake_driver = FakeDriver()
    attempts = {"count": 0}

    def fake_mkdtemp(prefix):
        assert prefix == "psynet-chrome-"
        profile_path = tmp_path / f"profile-{len(profile_paths)}"
        profile_path.mkdir()
        profile_paths.append(profile_path)
        return str(profile_path)

    def fake_mkstemp(prefix, suffix):
        assert prefix == "psynet-chromedriver-"
        assert suffix == ".log"
        log_path = tmp_path / f"chromedriver-{len(log_paths)}.log"
        fd = os.open(log_path, os.O_RDWR | os.O_CREAT)
        log_paths.append(log_path)
        return fd, str(log_path)

    def chrome(options, service):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("boom")
        return fake_driver

    fake_webdriver = FakeWebDriver()
    fake_webdriver.Chrome = chrome

    monkeypatch.setattr(chrome_driver.tempfile, "mkdtemp", fake_mkdtemp)
    monkeypatch.setattr(chrome_driver.tempfile, "mkstemp", fake_mkstemp)
    monkeypatch.setattr(chrome_driver.time, "sleep", sleep_calls.append)
    monkeypatch.delenv("PSYNET_KEEP_CHROMEDRIVER_LOGS", raising=False)
    monkeypatch.setattr(
        chrome_driver,
        "_get_chrome_dependencies",
        lambda: (fake_webdriver, FakeOptions, FakeService),
    )

    driver = chrome_driver.create_psynet_chrome_driver(headless=False)

    assert attempts["count"] == 3
    assert sleep_calls == [2, 2]
    assert len(profile_paths) == 3
    assert len(log_paths) == 3
    assert not profile_paths[0].exists()
    assert not profile_paths[1].exists()
    assert not log_paths[0].exists()
    assert not log_paths[1].exists()
    assert profile_paths[2].exists()
    assert log_paths[2].exists()

    driver.quit()

    assert not profile_paths[2].exists()
    assert not log_paths[2].exists()


def test_create_chrome_driver_pins_chromedriver_in_ci(chrome_paths, monkeypatch):
    _, log_path = chrome_paths
    fake_driver = FakeDriver()
    fake_webdriver = FakeWebDriver(driver=fake_driver)

    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("PSYNET_CHROMEDRIVER_VERBOSE", "1")
    monkeypatch.setattr(
        chrome_driver.shutil,
        "which",
        lambda name: {
            "chrome": "/usr/local/bin/chrome",
            "chromedriver": "/usr/local/bin/chromedriver",
        }.get(name),
    )
    monkeypatch.setattr(
        chrome_driver,
        "_get_chrome_dependencies",
        lambda: (fake_webdriver, FakeOptions, FakeService),
    )

    driver = chrome_driver.create_psynet_chrome_driver(headless=True)

    assert fake_webdriver.last_options.binary_location == "/usr/local/bin/chrome"
    assert fake_webdriver.last_service.executable_path == "/usr/local/bin/chromedriver"
    assert fake_webdriver.last_service.log_output == str(log_path)

    driver.quit()
