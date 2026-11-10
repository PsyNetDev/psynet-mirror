"""The demo's regrouper, which keeps last round's partners apart and alternates roles.

It lives in its own module so that tests can import it without the experiment.
"""

from psynet.sync import Regrouper


def last_partner_id(participant):
    """Return the ID of the player's partner in their latest pair, or ``None``."""
    pairs = [
        link.sync_group
        for link in participant.sync_group_links
        if link.sync_group.group_type == "pair"
    ]
    if not pairs:
        return None
    latest = max(pairs, key=lambda pair: pair.id)
    # All links, as both players have left the pair by the next split.
    partners = [
        link.participant_id
        for link in latest.participant_links
        if link.participant_id != participant.id
    ]
    return partners[0] if partners else None


def is_rematch(a, b):
    """Return whether either player's latest partner was the other.

    Both directions count: after a sit-out, ``a``'s latest partner can be
    ``b`` while ``b`` has played someone else since.
    """
    return last_partner_id(a) == b.id or last_partner_id(b) == a.id


def times_held(participant, role):
    """Return how often the player has held ``role``, from their stored pair links."""
    return sum(link.role == role for link in participant.sync_group_links)


class PairingRegrouper(Regrouper):
    def form_groups(self, members, within_group=None):
        """Pair players as by default, retrying so that nobody meets last round's partner."""
        for _ in range(20):
            pairs = super().form_groups(members, within_group)
            if not any(is_rematch(a, b) for a, b in pairs):
                break
        return pairs

    def assign_roles(self, members, within_group=None):
        """Give each role to whoever has held it least often, so roles alternate."""
        roles = {}
        for role in self.roles:
            free = [m for m in members if m not in roles]
            roles[min(free, key=lambda m: times_held(m, role))] = role
        return roles
