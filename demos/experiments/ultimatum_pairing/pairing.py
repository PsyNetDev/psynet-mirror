"""The demo's regrouper, which alternates roles.

It lives in its own module so that tests can import it without the experiment.
"""

from psynet.sync import Regrouper

PAIR = "pair"


def times_held(participant, role):
    """Return how often the player has held ``role``, from their stored pair links."""
    return sum(
        link.role == role
        for link in participant.sync_group_links
        if link.sync_group.group_type == PAIR
    )


class PairingRegrouper(Regrouper):
    def assign_roles(self, members, within_group=None):
        """Give each role to whoever has held it least often, so roles alternate."""
        roles = {}
        for role in self.roles:
            free = [m for m in members if m not in roles]
            roles[min(free, key=lambda m: times_held(m, role))] = role
        return roles
