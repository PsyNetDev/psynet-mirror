import logging
import secrets
from datetime import datetime, timedelta
from typing import List, Tuple, Union

import psutil
from dallinger.utils import classproperty

from . import deployment_info
from .redis import redis_vars
from .utils import format_bytes, format_timedelta, get_config, get_logger

logger = get_logger()


class Notifier:
    """
    Notifier class to handle notifications.
    """

    def notify(self, msg: str):
        raise NotImplementedError()

    @staticmethod
    def url(label: str, url: str):
        return f"{label}: {url}"

    @staticmethod
    def combine(*args):
        return "\n".join(args)

    @staticmethod
    def bold(msg: str):
        """
        Null implementation
        """
        return msg

    def get_username(self):
        return None

    @classproperty
    def deployment_information(self):
        return deployment_info.read_all()

    @classmethod
    def format_credentials(cls, label, url, username, password):
        msg = cls.url(cls.bold(label), url)
        if username is not None:
            msg += f"\nUsername: `{username}`"
        if password is not None:
            msg += f"\nPassword: `{password}`"
        return msg

    @classproperty
    def exp(cls):
        from .experiment import get_experiment

        return get_experiment()

    @property
    def python_dependencies(self):
        """
        List of Python dependencies required by the notifier.
        """
        return []

    @property
    def launch_message(self):
        username = self.get_username()
        if username is not None:
            msg = f"@{username} launched experiment "
        else:
            msg = "Launched experiment "
        msg += f'"{self.exp.label}" (`{self.deployment_information["secret"]}`)'
        if self.deployment_information["is_local_deployment"]:
            msg = f"{msg} locally"
        elif self.deployment_information["is_ssh_deployment"]:
            msg = f"{msg} to {self.deployment_information['server']} with app name `{self.deployment_information['app']}`"
        else:
            msg = (
                f"{msg} to Heroku with app name `{self.deployment_information['app']}`"
            )
        return msg

    @property
    def dashboard_credentials_message(self):
        config = get_config()
        dashboard_user = config.get("dashboard_user", "admin")
        dashboard_password = config.get("dashboard_password", secrets.token_urlsafe(8))
        return self.format_credentials(
            "Experiment dashboard",
            self.exp.dashboard_url,
            dashboard_user,
            dashboard_password,
        )

    @property
    def logs_message(self):
        config = get_config()
        dashboard_password = config.get("dashboard_password", secrets.token_urlsafe(8))
        logs_url = f"https://logs.{self.deployment_information['server']}"
        return self.format_credentials(
            "Server logs",
            logs_url,
            "dallinger",
            dashboard_password,
        )

    @property
    def credentials_message(self):
        msg = self.dashboard_credentials_message
        if self.deployment_information["is_ssh_deployment"]:
            msg += "\n" + self.logs_message
        return msg

    @property
    def export_url_message(self):
        return self.url(
            "Trigger export",
            f"{self.exp.dashboard_url}/export/trigger?assets=none",
        )

    def on_launch(self):
        self.notify(self.launch_message)
        self.notify(self.dashboard_credentials_message)

    @staticmethod
    def _get_worker_processes() -> List[Tuple[int, psutil.Process]]:
        """
        Get a list of (pid, process) tuples for Gunicorn workers.
        """
        workers = []
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                cmdline = proc.info.get("cmdline", [])
                if not cmdline:
                    cmdline = ""
                else:
                    cmdline = " ".join(cmdline)
                if "dallinger_" in cmdline or "gunicorn" in cmdline:
                    for child in proc.children(recursive=True):
                        workers.append((child.pid, child))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return workers

    def resource_usage_notification(
        self, resource_type, mute_same_warning_for_n_hours, level="warning"
    ):
        msg = self._build_initial_message(level, mute_same_warning_for_n_hours)
        if not self._should_send_notification(
            resource_type, level, mute_same_warning_for_n_hours
        ):
            return
        redis_vars.set(f"last_{resource_type}_{level}", datetime.now())
        msg += self._get_resource_message(resource_type)
        if resource_type in ["ram", "cpu"]:
            msg += self._get_worker_processes_message(resource_type)
        self.notify(msg)

    def _build_initial_message(self, level, mute_same_warning_for_n_hours):
        if level not in ["warning", "danger"]:
            raise ValueError(f"Unknown level: {level}")
        level_title = level[0].upper() + level[1:].lower()
        icon = "⚠️" if level_title == "Warning" else "❌"
        return f"*{level_title}*: {icon}\n(this notification will be muted for {mute_same_warning_for_n_hours} h)"

    def _should_send_notification(
        self, resource_type, level, mute_same_warning_for_n_hours
    ):
        redis_key = f"last_{resource_type}_{level}"
        last_warning = redis_vars.get(redis_key, default=None)
        return not (
            last_warning
            and last_warning
            > datetime.now() - timedelta(hours=mute_same_warning_for_n_hours)
        )

    def _get_resource_message(self, resource_type):
        if resource_type == "ram":
            mem = psutil.virtual_memory()
            return f"Free RAM low: {format_bytes(mem.available)} ({mem.percent}%)"
        elif resource_type == "disk":
            disk = psutil.disk_usage("/")
            return f"Free disk space low: {format_bytes(disk.free)} ({disk.percent}%)"
        elif resource_type == "cpu":
            return f"CPU usage high: {psutil.cpu_percent()}%"
        else:
            raise ValueError(f"Unknown resource type: {resource_type}")

    def _get_worker_processes_message(self, resource_type):
        workers = self._get_worker_processes()
        if not workers:
            return "\n* No workers found"
        workers = sorted(workers, key=lambda w: w[1].memory_info().rss, reverse=True)
        return "".join(
            self._format_worker_message(proc, pid, resource_type)
            for pid, proc in workers
        )

    def _format_worker_message(self, proc, pid, resource_type):
        try:
            running_since = datetime.now() - datetime.fromtimestamp(proc.create_time())
            process_name = (
                f"{proc.name()} ({pid}) running for {format_timedelta(running_since)}"
            )
            if resource_type == "ram":
                mem_pct = proc.memory_info().rss / psutil.virtual_memory().total * 100
                mem_mb = format_bytes(proc.memory_info().rss)
                return f"\n- {process_name} is using {mem_mb} ({mem_pct:.1f}%)"
            elif resource_type == "cpu":
                cpu_pct = proc.cpu_percent()
                return f"\n- {process_name} is using {cpu_pct:.1f}% CPU"
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return ""


class NullNotifier(Notifier):
    nickname = "null"

    def notify(self, msg: str):
        pass


class LoggerNotifier(Notifier):
    nickname = "logger"
    LEVEL2CODE = {
        "info": logging.INFO,
        "debug": logging.DEBUG,
        "warning": logging.WARNING,
        "error": logging.ERROR,
        "critical": logging.CRITICAL,
    }

    def notify(self, msg: str, level="info"):
        assert level in self.LEVEL2CODE.keys()
        code = self.LEVEL2CODE[level]
        logger.log(code, msg)

    @staticmethod
    def bold(msg: str):
        """
        Null implementation
        """
        from psynet.log import bold

        return bold(msg)


SLACK_THREAD_KEY = "slack_thread_id"


class SlackNotifier(Notifier):
    nickname = "slack"

    def __init__(
        self,
    ):
        """
        Initialize the Notifier.
        """
        super().__init__()

        slack_channel_name = get_config().get("slack_channel_name", None)
        if slack_channel_name is None:
            logger.error(
                "`slack_channel_name` is not set in the config and is required for the Slack notifier"
            )

        slack_bot_token = get_config().get("slack_bot_token", None)
        if slack_bot_token is None:
            logger.error(
                "`slack_bot_token` is not set in the config and is required for the Slack notifier"
            )

        if not self.exp.needs_internet_access:
            logger.error(
                "`needs_internet_access` is set to False, but internet is required for Slack notifications"
            )

        if not self.exp.is_deployed_experiment:
            logger.error(
                "Slack messages are disabled on `psynet debug`."
                "If you want to receive messages, use `psynet deploy local` or `psynet deploy ssh`"
            )

        experimenter_name = get_config().get("experimenter_name", None)
        if experimenter_name is None:
            # soft warning
            logger.warning(
                "`experimenter_name` is not set in the config, consider setting it to receive @ mentions"
                "and thus notifications"
            )

        self.channel_name = slack_channel_name
        self.bot_token = slack_bot_token
        self.experimenter_name = experimenter_name

    @property
    def client(self):
        from slack_sdk import WebClient

        return WebClient(token=self.bot_token)

    @property
    def python_dependencies(self):
        return super().python_dependencies + ["slack-sdk"]

    def _notify(self, msg, thread_ts=None):
        if not self.slack_available:
            logger.warn(
                "Tried to send a Slack message, but Slack is not available. This shouldn't happen... "
                "You might want to check your Slack configuration settings."
            )
            return
        from slack_sdk.errors import SlackApiError

        try:
            params = {
                "channel": self.channel_name,
                "link_names": True,
                "thread_ts": thread_ts,
            }
            if isinstance(msg, str):
                params["text"] = msg
            else:
                params["text"] = "New message"
                params["blocks"] = msg

            return self.client.chat_postMessage(**params)
        except SlackApiError as e:
            logger.error(f"Error posting message: {e}")

    def get_username(self):
        username = None
        if self.experimenter_name is not None:
            users = self.client.users_list()
            for user in users["members"]:
                if (
                    user.get("real_name", None) == self.experimenter_name
                    or user["name"] == self.experimenter_name
                ):
                    username = user["name"]
                    break
        return username

    @staticmethod
    def url(label: str, url: str):
        return f"<{url}|{label}>"

    @staticmethod
    def bold(msg: str):
        return f"*{msg}*"

    def notify(self, msg: Union[str, List[dict]]):
        thread_ts = redis_vars.get(SLACK_THREAD_KEY, default=None)
        if thread_ts:
            return self._notify(msg, thread_ts)

    @staticmethod
    def combine(*args):
        for arg in args:
            assert isinstance(arg, str)

        def msg_to_section(msg):
            return {"type": "section", "text": {"type": "mrkdwn", "text": msg}}

        blocks = []
        for i, arg in enumerate(args):
            blocks.append(msg_to_section(arg))
            if i < len(args) - 1:
                blocks.append({"type": "divider"})
        return blocks

    @property
    def slack_available(self):
        return (
            self.bot_token is not None
            and self.channel_name is not None
            and self.exp.needs_internet_access
            and self.exp.is_deployed_experiment
        )

    def on_launch(self):
        if not self.slack_available:
            logger.warn(
                "Tried to send a launch message to Slack, but Slack is not available. "
                "This shouldn't happen... "
                "You might want to check your Slack configuration settings."
            )
            return
        response = self._notify(self.launch_message)
        if response is not None:
            redis_vars.set(SLACK_THREAD_KEY, response["ts"])
            self.notify(
                self.combine(
                    self.credentials_message,
                    self.export_url_message,
                )
            )
