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
