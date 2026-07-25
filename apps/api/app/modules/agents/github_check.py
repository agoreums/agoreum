"""Proof-of-GitHub-control check.

The operator publishes the challenge token in the description of a public gist
under the account they are claiming. This reads that account's public gists from
the GitHub API and only reports success once it observes the token.

Anyone can create a gist with any text, but only the account's owner can create
one *as that account*, so a token found under `login`'s gists proves control of
`login`. The request always targets a fixed, trusted host (api.github.com), so
unlike the domain well-known fetch there is no server-side request forgery surface.
"""
from __future__ import annotations

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

HTTP_TIMEOUT_SECONDS = 8.0
GIST_FILENAME = "agoreum-verification.txt"


async def check_gist(login: str, token: str) -> tuple[bool, str | None]:
    """Return (found, error). Never reports found without seeing the token."""
    url = f"https://api.github.com/users/{login}/gists?per_page=100"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "agoreum-verification",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            resp = await client.get(url, headers=headers)
    except Exception:
        logger.info("github_verification_unreachable", extra={"login": login})
        return False, "GitHub could not be reached. Try again shortly."

    if resp.status_code == 404:
        return False, "That GitHub account was not found."
    if resp.status_code in (403, 429):
        return False, "GitHub's rate limit was reached. Try again in a few minutes."
    if resp.status_code != 200:
        return False, f"GitHub returned an unexpected status ({resp.status_code})."

    try:
        gists = resp.json()
    except ValueError:
        return False, "GitHub returned an unreadable response."

    for gist in gists:
        if token in (gist.get("description") or ""):
            return True, None
        # A file named for the token also proves it, in case the operator put it
        # there rather than in the description.
        for filename in (gist.get("files") or {}):
            if token in filename:
                return True, None

    return False, (
        "The verification token was not found in a public gist under that account. "
        f"Create a public gist with the token as its description (or as a file named "
        f"{GIST_FILENAME}), then try again."
    )
