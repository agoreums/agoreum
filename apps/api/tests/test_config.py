"""Settings parsing, especially the env-var shapes only production exercises.

Local development leaves most of these at their defaults, so the parsing paths
that run only when a value actually comes from the environment are the ones that
break in production and nowhere else. This is where CORS origin parsing failed
the first real deployment.
"""
from __future__ import annotations

from app.core.config import Settings


class TestCorsOriginParsing:
    def test_comma_separated_env_value_is_split(self) -> None:
        """The documented production format is a comma-separated string.

        pydantic-settings JSON-decodes list fields at the source layer before
        field validators run, so without NoDecode this raised a parse error and
        the app could not boot. Local dev never caught it — it uses the default.
        """
        s = Settings(
            _env_file=None,
            CORS_ALLOWED_ORIGINS="https://agoreum.xyz,https://www.agoreum.xyz",
        )
        assert s.CORS_ALLOWED_ORIGINS == [
            "https://agoreum.xyz",
            "https://www.agoreum.xyz",
        ]

    def test_single_origin_env_value(self) -> None:
        s = Settings(_env_file=None, CORS_ALLOWED_ORIGINS="https://agoreum.xyz")
        assert s.CORS_ALLOWED_ORIGINS == ["https://agoreum.xyz"]

    def test_whitespace_is_trimmed_and_blanks_dropped(self) -> None:
        s = Settings(
            _env_file=None,
            CORS_ALLOWED_ORIGINS="https://a.xyz , https://b.xyz , ",
        )
        assert s.CORS_ALLOWED_ORIGINS == ["https://a.xyz", "https://b.xyz"]

    def test_default_applies_when_unset(self) -> None:
        s = Settings(_env_file=None)
        assert s.CORS_ALLOWED_ORIGINS == ["http://localhost:3000"]

    def test_a_list_passed_directly_is_preserved(self) -> None:
        """In-code construction (tests, overrides) still accepts a real list."""
        s = Settings(_env_file=None, CORS_ALLOWED_ORIGINS=["https://x.xyz"])
        assert s.CORS_ALLOWED_ORIGINS == ["https://x.xyz"]


class TestAbiPathResolution:
    def test_env_override_wins_over_repo_default(self, monkeypatch, tmp_path) -> None:
        """The container flattens the tree, so the repo-relative default misses.

        CONTRACT_ABI_PATH must take precedence — this was why the indexer
        crash-looped on first deploy, unable to find the ABI.
        """
        from app.chain import escrow
        from app.core.config import settings

        fake = tmp_path / "AgoreumEscrow.abi.json"
        fake.write_text("[]", encoding="utf-8")
        monkeypatch.setattr(settings, "CONTRACT_ABI_PATH", str(fake))
        assert escrow.abi_path() == fake

    def test_default_is_used_when_unset(self, monkeypatch) -> None:
        from app.chain import escrow
        from app.core.config import settings

        monkeypatch.setattr(settings, "CONTRACT_ABI_PATH", None)
        assert escrow.abi_path() == escrow._DEFAULT_ABI_PATH
        # the repo checkout really does have the ABI where the default expects it
        assert escrow.abi_path().exists()
