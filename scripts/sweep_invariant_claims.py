"""Find claims that assert an invariant, so each can be re-checked.

The hedged-language sweep already run on this project looked for uncertainty:
"not tested", "worth confirming", "we assume". This is its inverse and, on the
evidence of 2026-08-21, the more dangerous half. A hedge invites a check. A
confident claim closes the question, and it goes on closing it long after the
code underneath has changed.

The instance that prompted this: `recompute` said it refreshed the cached
counters "so the fast read path and the authoritative computation cannot drift
apart". True when written, checked against the agent, and false about the
service from the moment a second path started incrementing service counters.
Nothing was watching, because the sentence read like a settled fact.

This only lists candidates. Every hit needs a person to go and look, which is
the entire point: the output is a worklist, not a verdict.
"""
import ast
import re
from pathlib import Path

ROOT = Path(".")
CODE_DIRS = ["apps/api/app", "apps/web/src", "scripts", "contracts/src"]

# Phrases that assert rather than describe. Deliberately narrow: "always" and
# "never" alone match far too much prose to be a worklist anybody works.
CLAIMS = re.compile(
    r"\b("
    r"cannot (?:drift|disagree|be|happen|exist|reach|move|change|overflow|fail)"
    r"|can never\b|could never\b|is impossible\b|are impossible\b"
    r"|kept in sync|stay in sync|stays in sync|in lockstep"
    r"|single source of truth|one source of truth|only source"
    r"|the only (?:thing|place|path|way|caller|code path)"
    r"|nothing (?:else )?(?:can|else|reads|writes|calls|touches)"
    r"|no other (?:path|code|caller|place|way)"
    r"|guaranteed to\b|guarantees that\b"
    r"|by construction\b"
    r"|must always\b|will always\b|always the\b"
    r")",
    re.IGNORECASE,
)


def comment_blocks(path: Path):
    """Yield (line, text) for docstrings and comment runs."""
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix == ".py":
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node)
                if doc:
                    yield getattr(node, 'lineno', 1), doc
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                yield i, stripped
    else:
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("//", "*", "/*")):
                yield i, stripped


hits = []
scanned = 0
for directory in CODE_DIRS:
    base = ROOT / directory
    if not base.exists():
        continue
    for path in sorted(base.rglob("*")):
        if path.suffix not in {".py", ".ts", ".tsx", ".sol"} or "node_modules" in str(path):
            continue
        scanned += 1
        for line, block in comment_blocks(path):
            for match in CLAIMS.finditer(block):
                snippet = " ".join(block.split())
                start = max(0, match.start() - 70)
                hits.append((str(path).replace("\\", "/"), line, match.group(1).lower(),
                             snippet[start:start + 190]))

print(f"files scanned: {scanned}")
print(f"invariant claims found: {len(hits)}\n")

by_phrase = {}
for _, _, phrase, _ in hits:
    by_phrase[phrase] = by_phrase.get(phrase, 0) + 1
for phrase, n in sorted(by_phrase.items(), key=lambda x: -x[1]):
    print(f"  {n:3}  {phrase}")

print("\n--- candidates ---")
for path, line, phrase, snippet in hits:
    print(f"\n{path}:{line}  [{phrase}]")
    print(f"   {snippet}")
