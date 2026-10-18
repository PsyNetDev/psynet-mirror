"""Say where researchers can read the logs of an app deployed over SSH.

Dallinger runs the Dozzle log viewer, at ``https://logs.<server>``, only for
classic (Caddy) ingress. Apps with Cloudflare ingress have no Dozzle, so
messages about them give the ``docker compose logs`` command instead.

The ingress of a new app comes from ``--ingress`` or the server registry's
``default_ingress`` (:func:`server_ingress`). ``psynet deploy ssh`` and
``psynet debug ssh`` record it and the logs command in ``deployment_info``,
because the app's own messages, such as Slack notifications, are built on
the server, which knows neither; deployments without a record count as
classic.
"""

from pathlib import Path
from shlex import quote
from typing import Optional

INGRESS_CLASSIC = "classic"
INGRESS_CLOUDFLARE = "cloudflare"


def server_ingress(server_info: dict, ingress: Optional[str] = None) -> str:
    """Return the ingress from ``--ingress`` or the server's ``default_ingress``, else classic.

    Parameters
    ----------
    server_info : dict
        The server's entry in Dallinger's server registry.
    ingress : str, optional
        The ``--ingress`` option, if given.
    """
    return (ingress or server_info.get("default_ingress") or INGRESS_CLASSIC).lower()


def dozzle_url(server: str, ingress: Optional[str]) -> Optional[str]:
    """Return the server's Dozzle URL, or ``None`` with Cloudflare ingress, which has no Dozzle."""
    if ingress == INGRESS_CLOUDFLARE:
        return None
    return f"https://logs.{server}"


def _home_relative(path) -> str:
    """Return ``path`` quoted for a shell, as ``~/...`` when it is under the home directory.

    The command reaches Slack and exports, which shouldn't reveal the local
    user name; ``~`` stays outside the quotes so that the shell expands it.
    """
    path = Path(path).expanduser()
    try:
        return "~/" + quote(str(path.relative_to(Path.home())))
    except ValueError:
        return quote(str(path))


def logs_command(server_info: dict, app: str) -> str:
    """Return the ``ssh`` command that follows an app's Compose logs, as Dallinger prints it.

    Parameters
    ----------
    server_info : dict
        The server's entry in Dallinger's server registry; its ``host`` may
        include a port.
    app : str
        The app name.
    """
    from dallinger.command_line.docker_ssh import split_ssh_host_port
    from dallinger.command_line.utils import get_server_pem_path

    host, port = split_ssh_host_port(server_info["host"])
    user = server_info.get("user")
    parts = ["ssh"]
    if port != 22:
        parts += ["-p", str(port)]
    try:
        parts += ["-i", _home_relative(get_server_pem_path())]
    except FileNotFoundError:
        pass  # Without server_pem, ssh falls back to the user's own keys.
    parts.append(quote(f"{user}@{host}" if user else host))
    parts.append(f'"docker compose -f ~/dallinger/{app}/docker-compose.yml logs -f"')
    return " ".join(parts)


def where_to_read_logs(server: str, app: str) -> str:
    """Describe where to read ``app``'s logs, for messages printed on this computer.

    The ingress is a best guess from the server's ``default_ingress``: an app
    deployed with an explicit ``--ingress`` may differ, and finding out would
    take another SSH round trip.
    """
    from dallinger.command_line.docker_ssh import CONFIGURED_HOSTS

    server_info = CONFIGURED_HOSTS.get(server, {})
    url = dozzle_url(server, server_ingress(server_info))
    if url:
        return f"in Dozzle at {url}"
    if "host" not in server_info:
        return "with 'docker compose logs' on the server"
    return f"with '{logs_command(server_info, app)}'"
