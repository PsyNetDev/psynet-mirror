import json
import logging
import os
import shutil
import tempfile
import time

from psynet.command_line import (
    list_chromedriver_processes,
    list_psynet_chrome_processes,
)

logger = logging.getLogger(__name__)


def _append_debug_log(location, message, data):
    payload = {
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }

    try:
        print(f"PSYNET_CHROME_DEBUG {json.dumps(payload, default=str)}", flush=True)
    except Exception:
        logger.warning("Failed to emit Chrome debug event.", exc_info=True)


def _find_chrome_binary():
    for binary in [
        "google-chrome",
        "google-chrome-stable",
        "chrome",
        "chromium",
        "chromium-browser",
    ]:
        path = shutil.which(binary)
        if path:
            return path
    for path in ["/opt/chrome-linux64/chrome", "/usr/bin/google-chrome"]:
        if os.path.exists(path):
            return path
    return None


def _count_psynet_chrome_profiles():
    try:
        tmp_dir = tempfile.gettempdir()
        return len(
            [name for name in os.listdir(tmp_dir) if name.startswith("psynet-chrome-")]
        )
    except Exception:
        logger.warning(
            "Failed to count temporary PsyNet Chrome profiles.",
            exc_info=True,
        )
        return None


def _get_chrome_dependencies():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    return webdriver, Options, Service


def _cleanup_failed_launch_artifacts(user_data_dir, chromedriver_log_path):
    shutil.rmtree(user_data_dir, ignore_errors=True)
    if (
        os.path.exists(chromedriver_log_path)
        and os.getenv("PSYNET_KEEP_CHROMEDRIVER_LOGS", "0") != "1"
    ):
        try:
            os.remove(chromedriver_log_path)
        except OSError:
            pass


def create_psynet_chrome_driver(headless):
    webdriver, options_class, service_class = _get_chrome_dependencies()
    ci_chromedriver_path = (
        shutil.which("chromedriver") if os.getenv("CI") is not None else None
    )
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        chrome_options = options_class()
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--remote-debugging-pipe")

        user_data_dir = tempfile.mkdtemp(prefix="psynet-chrome-")
        chrome_options.add_argument(f"--user-data-dir={user_data_dir}")

        chrome_binary = _find_chrome_binary()
        if chrome_binary:
            chrome_options.binary_location = chrome_binary

        if headless:
            chrome_options.add_argument("--headless=new")

        fd, chromedriver_log_path = tempfile.mkstemp(
            prefix="psynet-chromedriver-", suffix=".log"
        )
        os.close(fd)
        chromedriver_verbose = os.getenv(
            "PSYNET_CHROMEDRIVER_VERBOSE", "1" if os.getenv("CI") else "0"
        )
        service_kwargs = {
            "log_output": chromedriver_log_path,
            "service_args": ["--verbose"] if chromedriver_verbose == "1" else None,
        }
        if ci_chromedriver_path:
            service_kwargs["executable_path"] = ci_chromedriver_path
        service = service_class(
            **service_kwargs,
        )

        tmp_usage = shutil.disk_usage(tempfile.gettempdir())
        _append_debug_log(
            location="psynet/testing/chrome_driver.py:create_driver:before_launch",
            message="Preparing Chrome launch",
            data={
                "attempt": attempt,
                "maxAttempts": max_attempts,
                "headless": headless,
                "chromeBinary": chrome_binary,
                "tmpFreeBytes": tmp_usage.free,
                "tmpChromeProfileCount": _count_psynet_chrome_profiles(),
                "chromeProcessCount": len(list_psynet_chrome_processes()),
                "chromedriverProcessCount": len(list_chromedriver_processes()),
                "chromedriverVerbose": chromedriver_verbose,
                "chromedriverPath": ci_chromedriver_path,
                "chromedriverLogPath": chromedriver_log_path,
            },
        )

        try:
            driver = webdriver.Chrome(options=chrome_options, service=service)
        except Exception as e:
            chromedriver_log_excerpt = None
            if os.path.exists(chromedriver_log_path):
                try:
                    with open(chromedriver_log_path, "r", encoding="utf-8") as f:
                        chromedriver_log_excerpt = f.read()[-4000:]
                except Exception:
                    logger.warning(
                        "Failed to read chromedriver log excerpt.",
                        exc_info=True,
                    )
            _append_debug_log(
                location="psynet/testing/chrome_driver.py:create_driver:launch_exception",
                message="Chrome launch failed",
                data={
                    "attempt": attempt,
                    "maxAttempts": max_attempts,
                    "exceptionType": type(e).__name__,
                    "exceptionMessage": str(e),
                    "headless": headless,
                    "chromeBinary": chrome_binary,
                    "tmpChromeProfileCount": _count_psynet_chrome_profiles(),
                    "chromedriverLogPath": chromedriver_log_path,
                    "chromedriverLogExcerpt": chromedriver_log_excerpt,
                },
            )
            if attempt < max_attempts:
                _cleanup_failed_launch_artifacts(user_data_dir, chromedriver_log_path)
                logger.warning(
                    "Chrome failed to start (attempt %d/%d), retrying...",
                    attempt,
                    max_attempts,
                )
                time.sleep(2)
                continue
            shutil.rmtree(user_data_dir, ignore_errors=True)
            raise

        _append_debug_log(
            location="psynet/testing/chrome_driver.py:create_driver:launch_success",
            message="Chrome launched successfully",
            data={
                "attempt": attempt,
                "maxAttempts": max_attempts,
                "sessionId": driver.session_id,
                "browserVersion": driver.capabilities.get("browserVersion"),
                "chromedriverVersion": driver.capabilities.get("chrome", {}).get(
                    "chromedriverVersion"
                ),
                "tmpChromeProfileCount": _count_psynet_chrome_profiles(),
                "chromedriverLogPath": chromedriver_log_path,
            },
        )
        break

    original_quit = driver.quit
    cleanup_done = False

    def quit_with_cleanup():
        nonlocal cleanup_done
        try:
            return original_quit()
        finally:
            if not cleanup_done:
                cleanup_done = True
                shutil.rmtree(user_data_dir, ignore_errors=True)
                if (
                    os.path.exists(chromedriver_log_path)
                    and os.getenv("PSYNET_KEEP_CHROMEDRIVER_LOGS", "0") != "1"
                ):
                    try:
                        os.remove(chromedriver_log_path)
                    except OSError:
                        pass
                _append_debug_log(
                    location="psynet/testing/chrome_driver.py:create_driver:quit_cleanup",
                    message="Cleaned Chrome session artifacts",
                    data={
                        "userDataDir": user_data_dir,
                        "userDataDirExistsAfterCleanup": os.path.exists(user_data_dir),
                        "tmpChromeProfileCount": _count_psynet_chrome_profiles(),
                    },
                )

    driver.quit = quit_with_cleanup
    driver.set_window_size(1024, 768)

    return driver
