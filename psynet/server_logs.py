"""Say where researchers can read the logs of an app deployed over SSH.

Dallinger runs the Dozzle log viewer, at ``https://logs.<server>``, only for
classic (Caddy) ingress. Apps with Cloudflare ingress have no Dozzle, so
messages about them give the ``docker compose logs`` command instead.

The ingress of a new app comes from ``--ingress`` or the server registry's
``default_ingress`` (:func:`server_ingress`). ``psynet deploy ssh`` and
``psynet debug ssh`` record it and the logs command in ``deployment_info``,
because the app's own messages, such as Slack notifications, are built on
the server, which knows neither; deployments without a record count as
classic. Messages printed on this computer (:func:`where_to_read_logs`) use
the ingress that the command read from the app's compose file, else that
record, and only guess from ``default_ingress`` without either.
"""

import re
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
    ``~`` expands to the home directory of whoever runs it, so teammates need
    the key at the same place under their own home.
    """
    path = Path(path).expanduser()
    for candidate, home in (
        (path, Path.home()),
        (path.resolve(), Path.home().resolve()),
    ):
        try:
            return "~/" + quote(str(candidate.relative_to(home)))
        except ValueError:
            pass
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


def compose_ingress(compose: str) -> str:
    """Return the ingress of an app from its ``docker-compose.yml``, whose ``cloudflared`` service only Cloudflare apps have."""
    if re.search(r"(?m)^  cloudflared:", compose):
        return INGRESS_CLOUDFLARE
    return INGRESS_CLASSIC


def _recorded_ingress(server: str, app: str) -> Optional[str]:
    """Return the ingress in ``deployment_info`` if this directory last deployed ``app`` to ``server``."""
    from . import deployment_info

    try:
        info = deployment_info.read_all()
    except FileNotFoundError:
        return None
    if (info.get("server"), info.get("app")) == (server, app):
        return info.get("ingress")
    return None


def where_to_read_logs(server: str, app: str, ingress: Optional[str] = None) -> str:
    """Describe where to read ``app``'s logs, for messages printed on this computer.

    Parameters
    ----------
    server : str
        The configured server name.
    app : str
        The app name.
    ingress : str, optional
        The app's ingress, if the caller read it from the server. Otherwise
        it comes from ``deployment_info`` when this directory deployed the
        app, and failing that is guessed, with a "probably", from the
        server's ``default_ingress``.
    """
    from dallinger.command_line.docker_ssh import CONFIGURED_HOSTS

    server_info = CONFIGURED_HOSTS.get(server, {})
    ingress = ingress or _recorded_ingress(server, app)
    hedge = ""
    if ingress is None:
        ingress, hedge = server_ingress(server_info), "probably "
    url = dozzle_url(server, ingress)
    if url:
        return f"{hedge}in Dozzle at {url}"
    if "host" not in server_info:
        return f"{hedge}with 'docker compose logs' on the server"
    return f"{hedge}with '{logs_command(server_info, app)}'"
