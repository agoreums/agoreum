"""Joining an organization requires the joiner to agree.

Membership used to be granted directly: an owner named an address and that
account was in the organization. Membership decides who is notified about an
organization's orders and whose name is attached to it, so these tests are
mostly about the absence of the old path rather than the presence of the new one.
"""
from __future__ import annotations

from datetime import timedelta

from app.modules.organizations import service


class TestConsentCannotBeBypassed:
    def test_there_is_no_way_to_add_a_member_directly(self) -> None:
        """The old function is gone rather than deprecated.

        Left in place it would stay one call away, and the next feature that
        needs to attach somebody to an organization would reach for it.
        """
        assert not hasattr(service, "add_member")

    def test_the_api_exposes_no_direct_add(self) -> None:
        from app.main import app

        spec = app.openapi()
        members = spec["paths"].get("/api/v1/orgs/{slug}/members", {})
        assert "post" not in members, "adding a member without asking is not offered"
        assert "get" in members, "listing members is unaffected"

    def test_the_invitation_flow_is_reachable_from_both_sides(self) -> None:
        from app.main import app

        paths = app.openapi()["paths"]
        # The organization's side.
        assert "post" in paths["/api/v1/orgs/{slug}/invitations"]
        assert "get" in paths["/api/v1/orgs/{slug}/invitations"]
        assert "delete" in paths["/api/v1/orgs/{slug}/invitations/{invitation_id}"]
        # The invitee's side, keyed on their session rather than on an
        # organization they are not yet a member of.
        assert "get" in paths["/api/v1/orgs/invitations/mine"]
        assert "post" in paths["/api/v1/orgs/invitations/{invitation_id}/accept"]
        assert "post" in paths["/api/v1/orgs/invitations/{invitation_id}/decline"]


class TestOffersDoNotLastForever:
    def test_an_unanswered_invitation_expires(self) -> None:
        """An offer nobody answers should not sit against an account forever."""
        assert timedelta(days=1) < service.INVITATION_TTL, "long enough to notice"
        assert timedelta(days=30) >= service.INVITATION_TTL, "short enough to lapse"


class TestResolvingAnInvitationOnce:
    def test_acceptance_is_a_conditional_update(self) -> None:
        """Two clicks, or a click and a retry, must not both succeed.

        Asserted on the shape of the query rather than by racing it: the claim
        filters on the invitation still being unanswered and unexpired in the
        same statement that writes the answer, so the database decides the
        winner rather than a read followed by a write.
        """
        import inspect

        source = inspect.getsource(service._claim_invitation)
        assert "update(" in source
        assert "responded_at.is_(None)" in source
        assert "expires_at >" in source, "an expired offer cannot be claimed"
