"""Say where researchers can read the logs of an app deployed over SSH.

Dallinger runs the Dozzle log viewer, at ``https://logs.<server>``, only for
classic (Caddy) ingress. Apps with Cloudflare ingress have no Dozzle, so
messages about them give the ``docker compose logs`` command instead.

The ingress of a new app comes from ``--ingress`` or the server registry's
``default_ingress`` (:func:`server_ingress`). ``psynet deploy ssh`` and
``psynet debug ssh`` record it in ``deployment_info`` so that the app's own
messages, such as Slack notifications, can tell the two apart; deployments
without a record count as classic.
"""

from typing import Optional

INGRESS_CLASSIC = "classic"
INGRESS_CLOUDFLARE = "cloudflare"


def server_ingress(server_info: dict, ingress: Optional[str] = None) -> str:
    """Return ``"classic"`` or ``"cloudflare"`` from ``--ingress`` or the server's ``default_ingress``.

    Parameters
    ----------
    server_info : dict
        The server's entry in Dallinger's server registry.
    ingress : str, optional
        The ``--ingress`` option, if given.
    """
    try:
        from dallinger.command_line.docker_ssh import _resolve_ingress
    except ImportError:  # pragma: no cover - older Dallinger without Cloudflare ingress
        return INGRESS_CLASSIC
    return _resolve_ingress(server_info, ingress)


def dozzle_url(server: str, ingress: Optional[str]) -> Optional[str]:
    """Return the server's Dozzle URL, or ``None`` with Cloudflare ingress, which has no Dozzle."""
    if ingress == INGRESS_CLOUDFLARE:
        return None
    return f"https://logs.{server}"


def logs_command(app: str, ssh_host: str, ssh_user: Optional[str] = None) -> str:
    """Return the ``ssh`` command that follows an app's Compose logs."""
    destination = f"{ssh_user}@{ssh_host}" if ssh_user else ssh_host
    return (
        f'ssh {destination} "docker compose -f ~/dallinger/{app}/docker-compose.yml '
        'logs -f"'
    )


def where_to_read_logs(server: str, app: str) -> str:
    """Describe where to read ``app``'s logs, using the server's ``default_ingress``."""
    from dallinger.command_line.docker_ssh import CONFIGURED_HOSTS

    server_info = CONFIGURED_HOSTS.get(server, {})
    url = dozzle_url(server, server_ingress(server_info))
    if url:
        return f"in Dozzle at {url}"
    command = logs_command(
        app, server_info.get("host", server), server_info.get("user")
    )
    return f"with '{command}'"
