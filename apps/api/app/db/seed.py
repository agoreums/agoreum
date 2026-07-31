"""Reference data.

This module seeds **taxonomy only**, the marketplace's category structure, which
is curated platform configuration rather than user activity.

It deliberately creates no users, agents, services, orders, reviews, or
transactions. Those must only ever come from real participants doing real things;
inventing them would corrupt every number the platform reports.

Seeding is idempotent: running it twice makes no second change.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.services.models import Category

logger = get_logger(__name__)


@dataclass(frozen=True)
class CategorySeed:
    slug: str
    name: str
    description: str
    children: tuple[CategorySeed, ...] = field(default_factory=tuple)


# The initial taxonomy describes the kinds of work autonomous agents actually sell.
# It is intentionally shallow (one level of nesting) so the marketplace stays
# navigable, and will be revised as real listing patterns emerge.
CATEGORY_TREE: tuple[CategorySeed, ...] = (
    CategorySeed(
        slug="data-and-research",
        name="Data & Research",
        description="Gathering, extracting, enriching, and analysing information.",
        children=(
            CategorySeed(
                slug="web-research",
                name="Web Research",
                description="Sourcing and synthesising information from public sources.",
            ),
            CategorySeed(
                slug="data-extraction",
                name="Data Extraction",
                description="Turning unstructured documents and pages into structured data.",
            ),
            CategorySeed(
                slug="data-analysis",
                name="Data Analysis",
                description="Statistical analysis, modelling, and reporting over datasets.",
            ),
        ),
    ),
    CategorySeed(
        slug="content-and-language",
        name="Content & Language",
        description="Producing, editing, and transforming written and spoken material.",
        children=(
            CategorySeed(
                slug="writing-and-editing",
                name="Writing & Editing",
                description="Drafting, rewriting, and editing long- and short-form content.",
            ),
            CategorySeed(
                slug="translation",
                name="Translation",
                description="Translation and localisation between human languages.",
            ),
            CategorySeed(
                slug="summarization",
                name="Summarisation",
                description="Condensing documents, transcripts, and conversations.",
            ),
        ),
    ),
    CategorySeed(
        slug="software-and-engineering",
        name="Software & Engineering",
        description="Writing, reviewing, testing, and operating software.",
        children=(
            CategorySeed(
                slug="code-generation",
                name="Code Generation",
                description="Implementing features, scripts, and integrations.",
            ),
            CategorySeed(
                slug="code-review",
                name="Code Review",
                description="Reviewing changes for correctness, security, and quality.",
            ),
            CategorySeed(
                slug="testing-and-qa",
                name="Testing & QA",
                description="Authoring test suites and validating behaviour.",
            ),
            CategorySeed(
                slug="devops-and-infrastructure",
                name="DevOps & Infrastructure",
                description="Deployment pipelines, infrastructure, and operational tooling.",
            ),
        ),
    ),
    CategorySeed(
        slug="automation-and-workflows",
        name="Automation & Workflows",
        description="Executing multi-step processes and orchestrating other agents.",
        children=(
            CategorySeed(
                slug="process-automation",
                name="Process Automation",
                description="Running repeatable business and technical processes.",
            ),
            CategorySeed(
                slug="agent-orchestration",
                name="Agent Orchestration",
                description="Coordinating multiple agents to complete composite tasks.",
            ),
            CategorySeed(
                slug="monitoring-and-alerting",
                name="Monitoring & Alerting",
                description="Watching systems or data sources and reporting on change.",
            ),
        ),
    ),
    CategorySeed(
        slug="media",
        name="Media",
        description="Generating and processing images, audio, and video.",
        children=(
            CategorySeed(
                slug="image-generation",
                name="Image Generation & Editing",
                description="Producing and modifying visual assets.",
            ),
            CategorySeed(
                slug="audio-and-speech",
                name="Audio & Speech",
                description="Transcription, synthesis, and audio processing.",
            ),
            CategorySeed(
                slug="video",
                name="Video",
                description="Video generation, editing, and analysis.",
            ),
        ),
    ),
    CategorySeed(
        slug="blockchain-and-web3",
        name="Blockchain & Web3",
        description="On-chain analysis, contract work, and protocol integration.",
        children=(
            CategorySeed(
                slug="onchain-analytics",
                name="On-Chain Analytics",
                description="Analysing addresses, contracts, and transaction flow.",
            ),
            CategorySeed(
                slug="smart-contract-development",
                name="Smart Contract Development",
                description="Writing and reviewing contracts for EVM networks.",
            ),
            CategorySeed(
                slug="protocol-integration",
                name="Protocol Integration",
                description="Integrating applications with on-chain protocols.",
            ),
        ),
    ),
)


async def seed_categories(session: AsyncSession) -> int:
    """Insert any categories that do not already exist.

    Returns the number of categories created. Existing rows are left untouched, so
    edits made in production are never overwritten by a redeploy.
    """
    existing = set(
        (await session.execute(select(Category.slug))).scalars().all()
    )
    created = 0

    for index, parent_seed in enumerate(CATEGORY_TREE):
        parent = await _get_or_create(
            session, parent_seed, parent_id=None, sort_order=index, existing=existing
        )
        if parent is not None:
            created += 1
        # Resolve the parent id whether it was just created or already present.
        parent_id = (
            await session.execute(
                select(Category.id).where(Category.slug == parent_seed.slug)
            )
        ).scalar_one()

        for child_index, child_seed in enumerate(parent_seed.children):
            child = await _get_or_create(
                session,
                child_seed,
                parent_id=parent_id,
                sort_order=child_index,
                existing=existing,
            )
            if child is not None:
                created += 1

    logger.info("categories_seeded", extra={"created": created})
    return created


async def _get_or_create(
    session: AsyncSession,
    seed: CategorySeed,
    *,
    parent_id,
    sort_order: int,
    existing: set[str],
) -> Category | None:
    if seed.slug in existing:
        return None

    category = Category(
        slug=seed.slug,
        name=seed.name,
        description=seed.description,
        parent_id=parent_id,
        sort_order=sort_order,
        is_active=True,
    )
    session.add(category)
    # Flush so the id is available for children in the same transaction.
    await session.flush()
    existing.add(seed.slug)
    return category
