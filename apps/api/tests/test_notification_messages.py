"""The notification catalogue, checked as data rather than read.

A translation set goes wrong quietly. A key missing in one language falls back to
English and looks fine to whoever added it, and a placeholder dropped in
translation produces a message that reads correctly and omits the order reference
that made it useful. Both are asserted here rather than reviewed by eye.
"""
from __future__ import annotations

import pytest

from app.modules.notifications import messages


class TestEveryMessageExistsEverywhere:
    def test_no_locale_is_missing_a_key(self) -> None:
        """A gap here is a silent fallback, which is how half-translated ships."""
        gaps = {
            f"{key}:{locale}"
            for key, catalogue in messages.MESSAGES.items()
            for locale in messages.LOCALES
            if locale not in catalogue
        }
        assert gaps == set()

    def test_the_catalogue_covers_exactly_the_supported_locales(self) -> None:
        for key, catalogue in messages.MESSAGES.items():
            assert set(catalogue) == set(messages.LOCALES), key

    def test_the_fallback_locale_is_complete(self) -> None:
        """Every lookup can land on it, so it cannot have holes."""
        assert messages.FALLBACK in messages.LOCALES
        for key, catalogue in messages.MESSAGES.items():
            assert messages.FALLBACK in catalogue, key

    def test_nothing_is_blank(self) -> None:
        for key, catalogue in messages.MESSAGES.items():
            for locale, (title, body) in catalogue.items():
                assert title.strip(), f"{key}:{locale} title"
                assert body.strip(), f"{key}:{locale} body"


class TestPlaceholdersSurviveTranslation:
    def test_every_locale_uses_the_same_fields(self) -> None:
        """A dropped placeholder reads fine and omits the fact that mattered.

        The English message is the reference, since it is the fallback.
        """
        for key, catalogue in messages.MESSAGES.items():
            title_en, body_en = catalogue[messages.FALLBACK]
            expected = messages.placeholders(title_en) | messages.placeholders(body_en)
            for locale, (title, body) in catalogue.items():
                found = messages.placeholders(title) | messages.placeholders(body)
                assert found == expected, f"{key}:{locale}"

    def test_order_messages_all_carry_the_reference(self) -> None:
        """Without it the recipient cannot tell which order is meant."""
        for key, catalogue in messages.MESSAGES.items():
            if not key.startswith("order."):
                continue
            for locale, (title, body) in catalogue.items():
                fields = messages.placeholders(title) | messages.placeholders(body)
                assert "reference" in fields, f"{key}:{locale}"

    def test_the_verification_message_always_carries_the_link(self) -> None:
        """It is the entire point of that message."""
        for locale, (_, body) in messages.MESSAGES["account.email_verification"].items():
            assert "link" in messages.placeholders(body), locale


class TestRendering:
    def test_a_known_locale_is_used(self) -> None:
        title, _ = messages.render("order.funded", "fr", reference="ORD-7")
        assert "ORD-7" in title
        assert title != messages.MESSAGES["order.funded"]["en"][0].format(
            reference="ORD-7"
        )

    def test_an_unknown_locale_falls_back_to_english(self) -> None:
        title, _ = messages.render("order.funded", "xx", reference="ORD-7")
        assert title == messages.MESSAGES["order.funded"]["en"][0].format(
            reference="ORD-7"
        )

    def test_a_missing_locale_falls_back_to_english(self) -> None:
        title, _ = messages.render("order.funded", None, reference="ORD-7")
        assert "ORD-7" in title

    def test_the_whole_message_falls_back_together(self) -> None:
        """Never a title in one language and a body in another."""
        title, body = messages.render("account.new_signin", "xx", where="w", device="d")
        en_title, en_body = messages.MESSAGES["account.new_signin"]["en"]
        assert title == en_title.format(where="w", device="d")
        assert body == en_body.format(where="w", device="d")

    def test_every_key_renders_in_every_locale(self) -> None:
        """Catches a stray brace or a mistyped field name anywhere in the set."""
        sample = {
            "reference": "ORD-1",
            "link": "https://agoreum.xyz/verify-email?token=x",
            "where": "203.0.113.9",
            "device": "Chrome",
            "role": "member",
            "name": "Acme",
        }
        for key in messages.MESSAGES:
            for locale in messages.LOCALES:
                title, body = messages.render(key, locale, **sample)
                assert "{" not in title, f"{key}:{locale}"
                assert "{" not in body, f"{key}:{locale}"

    def test_an_unknown_key_is_a_programming_error(self) -> None:
        """Loud, because a typo would otherwise send an empty notification."""
        with pytest.raises(KeyError):
            messages.render("order.nonexistent", "en")


class TestLinksMatchTheLanguageOfTheMessage:
    """A localised message with an unlocalised link is half translated.

    Every page lives under a locale segment, so a link without one is resolved
    by the reader's browser rather than by their account. A Japanese email whose
    link opened the English page is the failure this prevents, and it is
    invisible to anyone testing in English.
    """

    def test_a_bare_path_gains_the_recipients_locale(self, monkeypatch) -> None:
        from app.core.config import settings
        monkeypatch.setattr(settings, "APP_URL", "https://agoreum.xyz")

        assert messages.localise_url("https://agoreum.xyz/orders/AGO-1", "ja") == (
            "https://agoreum.xyz/ja/orders/AGO-1"
        )

    def test_a_query_string_survives(self, monkeypatch) -> None:
        """The verification link carries its token this way; losing it would
        make the one message that must work the one that silently cannot."""
        from app.core.config import settings
        monkeypatch.setattr(settings, "APP_URL", "https://agoreum.xyz")

        assert messages.localise_url(
            "https://agoreum.xyz/verify-email?token=abc123", "es"
        ) == "https://agoreum.xyz/es/verify-email?token=abc123"

    def test_a_fragment_survives(self, monkeypatch) -> None:
        from app.core.config import settings
        monkeypatch.setattr(settings, "APP_URL", "https://agoreum.xyz")

        assert messages.localise_url("https://agoreum.xyz/settings#email", "de") == (
            "https://agoreum.xyz/de/settings#email"
        )

    def test_an_already_localised_link_is_left_alone(self, monkeypatch) -> None:
        from app.core.config import settings
        monkeypatch.setattr(settings, "APP_URL", "https://agoreum.xyz")

        for locale in messages.LOCALES:
            url = f"https://agoreum.xyz/{locale}/settings"
            assert messages.localise_url(url, "fr") == url, (
                "a link that already had a locale was prefixed twice"
            )

    def test_an_unknown_locale_falls_back_the_same_way_the_text_does(
        self, monkeypatch
    ) -> None:
        """The link and the body must agree, including when they disagree with
        the request. If render falls back to English, so must the link."""
        from app.core.config import settings
        monkeypatch.setattr(settings, "APP_URL", "https://agoreum.xyz")

        assert messages.localise_url("https://agoreum.xyz/settings", "kl") == (
            f"https://agoreum.xyz/{messages.FALLBACK}/settings"
        )

    def test_a_foreign_link_is_untouched(self, monkeypatch) -> None:
        from app.core.config import settings
        monkeypatch.setattr(settings, "APP_URL", "https://agoreum.xyz")

        for url in (
            "https://sepolia.basescan.org/tx/0xabc",
            "https://example.com/agoreum.xyz/spoof",
            "https://agoreum.xyz.evil.test/settings",
        ):
            assert messages.localise_url(url, "ja") == url, f"rewrote {url}"

    def test_nothing_is_invented_from_nothing(self, monkeypatch) -> None:
        from app.core.config import settings
        monkeypatch.setattr(settings, "APP_URL", "https://agoreum.xyz")

        assert messages.localise_url(None, "ja") is None
        assert messages.localise_url("", "ja") == ""

    def test_a_trailing_slash_on_app_url_does_not_double_up(self, monkeypatch) -> None:
        from app.core.config import settings
        monkeypatch.setattr(settings, "APP_URL", "https://agoreum.xyz/")

        assert messages.localise_url("https://agoreum.xyz/settings", "pt") == (
            "https://agoreum.xyz/pt/settings"
        )

    def test_the_root_url_is_localised_too(self, monkeypatch) -> None:
        from app.core.config import settings
        monkeypatch.setattr(settings, "APP_URL", "https://agoreum.xyz")

        assert messages.localise_url("https://agoreum.xyz", "ko") == (
            "https://agoreum.xyz/ko"
        )

    def test_localising_twice_is_the_same_as_once(self, monkeypatch) -> None:
        """The verification link is localised at both the call site and in
        notify, because it appears in the body and again as the action URL.
        Idempotence is what makes that safe rather than a double prefix."""
        from app.core.config import settings
        monkeypatch.setattr(settings, "APP_URL", "https://agoreum.xyz")

        once = messages.localise_url("https://agoreum.xyz/verify-email?token=t", "ja")
        twice = messages.localise_url(once, "ja")
        assert once == twice == "https://agoreum.xyz/ja/verify-email?token=t"

    def test_a_second_pass_with_a_different_locale_does_not_relabel(
        self, monkeypatch
    ) -> None:
        """If the two passes ever disagreed on locale, the first must win, since
        it is the one the surrounding text was written in."""
        from app.core.config import settings
        monkeypatch.setattr(settings, "APP_URL", "https://agoreum.xyz")

        once = messages.localise_url("https://agoreum.xyz/settings", "ja")
        assert messages.localise_url(once, "de") == "https://agoreum.xyz/ja/settings"
