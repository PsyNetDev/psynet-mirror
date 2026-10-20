"""Say where researchers can read the logs of an app deployed over SSH.

Dallinger runs the Dozzle log viewer, at ``https://logs.<server DNS name>``
(:func:`server_dns_host`), only for classic (Caddy) ingress. Apps with
Cloudflare ingress have no Dozzle, so messages about them give the ``docker
compose logs`` command instead.

The ingress of a new app comes from ``--ingress`` or the server registry's
``default_ingress`` (:func:`server_ingress`). ``psynet deploy ssh`` and
``psynet debug ssh`` record it, the server's DNS name and the logs command in
``deployment_info``, because the app's own messages, such as Slack
notifications, are built on the server, which knows none of them; deployments
without a record count as classic and use the server name. Messages printed
on this computer (:func:`where_to_read_logs`) use the ingress that the command
read from the app's compose file, else that record, and only guess from
``default_ingress`` without either.
"""

import importlib
import ipaddress
import logging
import re
import socket
from pathlib import Path
from shlex import quote
from typing import Optional

logger = logging.getLogger(__name__)

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


def server_dns_host(server_info: dict, dns_host: Optional[str] = None) -> Optional[str]:
    """Return the DNS name that a classic-ingress server serves Dozzle under.

    Dallinger versions with ``servers upgrade`` serve Dozzle under the DNS
    host saved with the server, else the server's hostname, and only for a
    server registered by IP address under the deploy's ``--dns-host``. Older
    versions rewrite the server's Caddyfile on each deploy, so Dozzle follows
    the deploy's ``--dns-host``, else the server's host. ``nip.io`` means
    ``<ip>.nip.io``. A bare IP address is no DNS name, so it gives ``None``.

    Parameters
    ----------
    server_info : dict
        The server's entry in Dallinger's server registry.
    dns_host : str, optional
        The deploy's ``--dns-host`` option, if given.

    Returns
    -------
    str or None
        ``None`` if the entry has no ``host``, as for an unknown server, or
        if the name would be an IP address.
    """
    docker_ssh = importlib.import_module("dallinger.command_line.docker_ssh")

    if "host" not in server_info:
        return None
    host = docker_ssh.split_ssh_host_port(server_info["host"])[0]
    # Only Dallinger/Dallinger#10143 adds ``servers upgrade`` and saved DNS
    # hosts. Remove the ``else`` branch once PsyNet pins a Dallinger with it.
    if "upgrade" in docker_ssh.servers.commands:
        name = server_info.get("dns_host") or (dns_host if _is_ip(host) else None)
    else:
        name = dns_host or server_info.get("dns_host")
    name = name or host
    if name == "nip.io":
        try:
            name = f"{socket.gethostbyname(host)}.nip.io"
        except OSError as e:
            logger.warning(f"Could not look up the IP address of {host}: {e}")
            return None
    return None if _is_ip(name) else name


def _is_ip(host: str) -> bool:
    """Return whether ``host`` is an IP address rather than a DNS name."""
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def dozzle_url(dns_host: Optional[str], ingress: Optional[str]) -> Optional[str]:
    """Return the server's Dozzle URL, or ``None`` if it has none.

    Parameters
    ----------
    dns_host : str, optional
        The server's DNS name, from :func:`server_dns_host`. Without one there
        is no Dozzle address.
    ingress : str, optional
        The app's ingress. Cloudflare ingress has no Dozzle.
    """
    if not dns_host or ingress == INGRESS_CLOUDFLARE:
        return None
    return f"https://logs.{dns_host}"


def recorded_dozzle_url(info: dict) -> Optional[str]:
    """Return the Dozzle URL for the deployment described by ``deployment_info``.

    A recorded ``server_dns_host`` of ``None`` means the server has no Dozzle
    address. Deployments recorded before ``server_dns_host`` was saved use the
    server name.
    """
    return dozzle_url(
        info.get("server_dns_host", info.get("server")), info.get("ingress")
    )


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


def _recorded_deployment(server: str, app: str) -> dict:
    """Return ``deployment_info`` if this directory last deployed ``app`` to ``server``, else ``{}``."""
    from . import deployment_info

    try:
        info = deployment_info.read_all()
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, AssertionError) as e:
        logger.warning(f"Could not read {deployment_info.path}: {e}")
        return {}
    if (info.get("server"), info.get("app")) == (server, app):
        return info
    return {}


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
        app, and failing that is guessed from the server's
        ``default_ingress``, and the description then says so.
    """
    from dallinger.command_line.docker_ssh import CONFIGURED_HOSTS

    server_info = CONFIGURED_HOSTS.get(server, {})
    record = _recorded_deployment(server, app)
    ingress = ingress or record.get("ingress")
    caveat = ""
    if ingress is None:
        ingress = server_ingress(server_info)
        caveat = ", assuming it uses the server's default ingress"
    url = None
    if ingress != INGRESS_CLOUDFLARE:
        if "server_dns_host" in record:
            dns_host = record["server_dns_host"]
        else:
            dns_host = server_dns_host(server_info)
        if "host" not in server_info:
            dns_host = dns_host or server
        url = dozzle_url(dns_host, ingress)
    if url:
        where = f"in Dozzle at {url}"
    elif "host" not in server_info:
        where = "with 'docker compose logs' on the server"
    else:
        where = f"with '{logs_command(server_info, app)}'"
    return where + caveat
