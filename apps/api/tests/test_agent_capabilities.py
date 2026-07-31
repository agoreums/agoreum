"""Unit tests for the standardized agent capability vocabulary."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.agents.capabilities import (
    AgentCapabilities,
    CapabilityModality,
    CapabilityProtocol,
    capability_vocabulary,
)


def test_empty_is_valid_and_all_lists() -> None:
    caps = AgentCapabilities()
    assert caps.skills == []
    assert caps.input_modalities == []
    assert caps.protocols == []


def test_legacy_or_unknown_keys_are_ignored_not_rejected() -> None:
    # A pre-existing free-form value must still load rather than error.
    caps = AgentCapabilities.model_validate({"foo": "bar", "skills": ["Research"]})
    assert caps.skills == ["research"]
    assert not hasattr(caps, "foo")


def test_skills_are_normalized_kebab_and_deduped() -> None:
    caps = AgentCapabilities(skills=["Text Generation", "text  generation", "TRANSLATION", ""])
    assert caps.skills == ["text-generation", "translation"]


def test_skill_count_and_length_are_capped() -> None:
    caps = AgentCapabilities(skills=[f"skill-{i}" for i in range(50)])
    assert len(caps.skills) == 24
    long = AgentCapabilities(skills=["x" * 100])
    assert len(long.skills[0]) <= 40


def test_languages_normalized_and_deduped() -> None:
    caps = AgentCapabilities(languages=["English", "english", "zh-Hant"])
    assert caps.languages == ["english", "zh-hant"]


def test_modalities_deduped_and_enum_validated() -> None:
    caps = AgentCapabilities(input_modalities=["text", "text", "image"])
    assert caps.input_modalities == [CapabilityModality.TEXT, CapabilityModality.IMAGE]
    with pytest.raises(ValidationError):
        AgentCapabilities(input_modalities=["not-a-modality"])


def test_protocols_enum_validated() -> None:
    caps = AgentCapabilities(protocols=["rest", "mcp"])
    assert caps.protocols == [CapabilityProtocol.REST, CapabilityProtocol.MCP]
    with pytest.raises(ValidationError):
        AgentCapabilities(protocols=["carrier-pigeon"])


def test_dump_uses_string_enum_values_for_jsonb() -> None:
    caps = AgentCapabilities(input_modalities=["text"], protocols=["mcp"])
    dumped = caps.model_dump(mode="json")
    assert dumped["input_modalities"] == ["text"]
    assert dumped["protocols"] == ["mcp"]
    assert all(isinstance(v, str) for v in dumped["input_modalities"])


def test_vocabulary_lists_every_term() -> None:
    vocab = capability_vocabulary()
    assert {t.value for t in vocab.modalities} == {m.value for m in CapabilityModality}
    assert {t.value for t in vocab.protocols} == {p.value for p in CapabilityProtocol}
    assert vocab.limits["max_skills"] == 24
    for term in vocab.modalities + vocab.protocols:
        assert term.label
