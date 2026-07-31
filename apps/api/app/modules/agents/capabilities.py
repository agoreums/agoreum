"""Standardized agent capability metadata.

An agent's `capabilities` column is JSONB so the vocabulary can evolve without a
migration, but it is no longer free-form: it is validated and normalized against
this schema on every write, so discovery and agent-to-agent negotiation can rely
on a consistent shape. Two vocabularies are controlled (modalities and protocols);
skills and languages are open tags, normalized to a predictable form.

Reads are lenient (unknown keys are ignored) so any legacy value still loads;
writes are normalized to exactly these fields.
"""
from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator

MAX_SKILLS = 24
SKILL_MAX_LEN = 40
MAX_LANGUAGES = 24
LANGUAGE_MAX_LEN = 24

_SKILL_STRIP = re.compile(r"[^a-z0-9]+")
_LANGUAGE_ALLOWED = re.compile(r"[^a-z0-9-]+")


class CapabilityModality(StrEnum):
    """A kind of input an agent consumes or output it produces."""

    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    CODE = "code"
    STRUCTURED_DATA = "structured_data"
    FILE = "file"
    EMBEDDING = "embedding"


class CapabilityProtocol(StrEnum):
    """How another party interacts with the agent."""

    REST = "rest"
    WEBHOOK = "webhook"
    MCP = "mcp"
    A2A = "a2a"
    GRAPHQL = "graphql"
    GRPC = "grpc"


def normalize_skill(value: str) -> str:
    """Lowercase, trim, and reduce a skill to a kebab-case tag."""
    slug = _SKILL_STRIP.sub("-", value.strip().lower()).strip("-")
    return slug[:SKILL_MAX_LEN].strip("-")


def normalize_language(value: str) -> str:
    """Lowercase and trim a language tag, keeping letters, digits and hyphens."""
    tag = _LANGUAGE_ALLOWED.sub("-", value.strip().lower()).strip("-")
    return tag[:LANGUAGE_MAX_LEN].strip("-")


def _dedupe(values: list[str]) -> list[str]:
    """Drop empties and duplicates, preserving first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


class AgentCapabilities(BaseModel):
    """The standardized machine-readable description of what an agent can do."""

    # Unknown keys are ignored rather than rejected, so a legacy or slightly-ahead
    # payload still loads; the normalized result only ever holds these fields.
    model_config = ConfigDict(extra="ignore")

    skills: list[str] = []
    input_modalities: list[CapabilityModality] = []
    output_modalities: list[CapabilityModality] = []
    protocols: list[CapabilityProtocol] = []
    languages: list[str] = []

    @field_validator("skills")
    @classmethod
    def _clean_skills(cls, v: list[str]) -> list[str]:
        return _dedupe([normalize_skill(s) for s in v])[:MAX_SKILLS]

    @field_validator("languages")
    @classmethod
    def _clean_languages(cls, v: list[str]) -> list[str]:
        return _dedupe([normalize_language(s) for s in v])[:MAX_LANGUAGES]

    @field_validator("input_modalities", "output_modalities")
    @classmethod
    def _dedupe_modalities(cls, v: list[CapabilityModality]) -> list[CapabilityModality]:
        return list(dict.fromkeys(v))

    @field_validator("protocols")
    @classmethod
    def _dedupe_protocols(cls, v: list[CapabilityProtocol]) -> list[CapabilityProtocol]:
        return list(dict.fromkeys(v))


class VocabularyTerm(BaseModel):
    value: str
    label: str


class CapabilityVocabulary(BaseModel):
    """The controlled vocabularies, so clients and other agents can render and
    validate capability metadata without hardcoding the terms."""

    modalities: list[VocabularyTerm]
    protocols: list[VocabularyTerm]
    limits: dict[str, int]


_MODALITY_LABELS: dict[CapabilityModality, str] = {
    CapabilityModality.TEXT: "Text",
    CapabilityModality.IMAGE: "Image",
    CapabilityModality.AUDIO: "Audio",
    CapabilityModality.VIDEO: "Video",
    CapabilityModality.CODE: "Code",
    CapabilityModality.STRUCTURED_DATA: "Structured data",
    CapabilityModality.FILE: "File",
    CapabilityModality.EMBEDDING: "Embedding",
}

_PROTOCOL_LABELS: dict[CapabilityProtocol, str] = {
    CapabilityProtocol.REST: "REST",
    CapabilityProtocol.WEBHOOK: "Webhook",
    CapabilityProtocol.MCP: "MCP",
    CapabilityProtocol.A2A: "Agent to agent",
    CapabilityProtocol.GRAPHQL: "GraphQL",
    CapabilityProtocol.GRPC: "gRPC",
}


def capability_vocabulary() -> CapabilityVocabulary:
    """The canonical vocabulary, served to UIs and API clients."""
    return CapabilityVocabulary(
        modalities=[
            VocabularyTerm(value=m.value, label=_MODALITY_LABELS[m]) for m in CapabilityModality
        ],
        protocols=[
            VocabularyTerm(value=p.value, label=_PROTOCOL_LABELS[p]) for p in CapabilityProtocol
        ],
        limits={
            "max_skills": MAX_SKILLS,
            "skill_max_length": SKILL_MAX_LEN,
            "max_languages": MAX_LANGUAGES,
            "language_max_length": LANGUAGE_MAX_LEN,
        },
    )
