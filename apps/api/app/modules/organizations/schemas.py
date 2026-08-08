"""Request and response models for organizations."""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.enums import OrgKind, OrgRole

SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")

# Slugs that would collide with routes or impersonate the platform, mirrored from
# the agent slug rules plus the personal-org prefix, which is reserved.
RESERVED_SLUGS = frozenset(
    {
        "admin", "agoreum", "api", "app", "auth", "billing", "dashboard", "docs",
        "help", "login", "logout", "marketplace", "new", "official", "org", "orgs",
        "register", "root", "search", "security", "settings", "signin", "signup",
        "support", "system", "team", "terms", "privacy", "www",
    }
)


def validate_org_slug(value: str) -> str:
    slug = value.strip().lower()
    if not SLUG_PATTERN.match(slug):
        raise ValueError(
            "Must be 2-64 characters: lowercase letters, numbers and hyphens, "
            "starting with a letter or number."
        )
    if slug in RESERVED_SLUGS or slug.startswith("u-"):
        raise ValueError("This name is reserved.")
    return slug


class OrgCreate(BaseModel):
    slug: Annotated[str, Field(min_length=2, max_length=64)]
    name: str = Field(min_length=2, max_length=96)

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        return validate_org_slug(v)


class OrgUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=96)


class OrganizationSummary(BaseModel):
    """An org as seen by one of its members, including that member's own role."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    kind: OrgKind
    # The requesting member's role, and how many members the org has.
    role: OrgRole
    member_count: int


class MemberView(BaseModel):
    user_id: uuid.UUID
    role: OrgRole
    username: str | None
    display_name: str | None
    primary_address: str
    joined_at: datetime


class MemberAdd(BaseModel):
    # The wallet address of a user who has already signed in at least once.
    address: str = Field(min_length=42, max_length=42)
    # Only member or admin may be granted here; owner is granted by a separate,
    # owner-only action.
    role: OrgRole = OrgRole.MEMBER

    @field_validator("address")
    @classmethod
    def _addr(cls, v: str) -> str:
        addr = v.strip().lower()
        if not re.match(r"^0x[0-9a-f]{40}$", addr):
            raise ValueError("Must be a 0x-prefixed 40-hex-character address.")
        return addr

    @field_validator("role")
    @classmethod
    def _role(cls, v: OrgRole) -> OrgRole:
        if v == OrgRole.OWNER:
            raise ValueError("Grant ownership with the dedicated owner action.")
        return v


class MemberRoleUpdate(BaseModel):
    role: OrgRole


class InvitationView(BaseModel):
    """A pending offer, as seen by either side."""

    id: uuid.UUID
    org_id: uuid.UUID
    org_slug: str
    org_name: str
    role: OrgRole
    invited_user_id: uuid.UUID
    expires_at: datetime
    created_at: datetime
