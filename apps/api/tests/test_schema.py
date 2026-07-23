"""Schema integrity tests.

These run against the SQLAlchemy metadata and need no database. They assert the
structural guarantees the platform depends on — particularly the ones that make
fabricated reputation and inconsistent money state impossible to represent.
"""
from __future__ import annotations

import pytest
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

from app.db.models import Base

metadata = Base.metadata


def constraint_names(table_name: str) -> set[str]:
    table = metadata.tables[table_name]
    return {c.name for c in table.constraints if c.name}


def check_constraint_sql(table_name: str) -> str:
    """All CHECK constraint expressions on a table, concatenated."""
    table = metadata.tables[table_name]
    return " ".join(
        str(c.sqltext)
        for c in table.constraints
        if isinstance(c, CheckConstraint)
    )


class TestSchemaShape:
    def test_every_expected_table_exists(self) -> None:
        expected = {
            "users", "wallets", "sessions", "siwe_nonces",
            "agents", "agent_domain_challenges",
            "categories", "services",
            "orders", "escrows", "chain_transactions", "order_events",
            "reviews", "reputation_snapshots",
            "notifications", "notification_deliveries", "notification_preferences",
        }
        assert expected <= set(metadata.tables)

    def test_every_table_has_a_primary_key(self) -> None:
        missing = [
            name for name, table in metadata.tables.items()
            if not table.primary_key.columns
        ]
        assert missing == []

    @pytest.mark.parametrize(
        "table_name",
        ["users", "wallets", "agents", "services", "orders", "escrows", "reviews"],
    )
    def test_timestamps_are_timezone_aware(self, table_name: str) -> None:
        """Naive timestamps are a correctness bug waiting to happen."""
        table = metadata.tables[table_name]
        naive = [
            col.name
            for col in table.columns
            if col.type.__class__.__name__ == "DateTime"
            and not getattr(col.type, "timezone", False)
        ]
        assert naive == [], f"{table_name} has naive datetime columns: {naive}"

    def test_every_foreign_key_declares_an_ondelete_rule(self) -> None:
        """An unspecified ON DELETE silently defaults to NO ACTION.

        Being explicit forces a decision about what deleting a parent means, which
        for financial records is never something to leave to a default.
        """
        offenders: list[str] = []
        for name, table in metadata.tables.items():
            for constraint in table.constraints:
                if isinstance(constraint, ForeignKeyConstraint):
                    for element in constraint.elements:
                        if element.ondelete is None:
                            offenders.append(f"{name}.{element.parent.name}")
        assert offenders == []


class TestMoneyInvariants:
    """Money must be exact and internally consistent at the database level."""

    @pytest.mark.parametrize(
        ("table_name", "columns"),
        [
            ("orders", ["unit_price", "subtotal", "platform_fee", "total_amount"]),
            ("escrows", ["amount", "released_amount", "refunded_amount", "fee_amount"]),
            ("services", ["price"]),
        ],
    )
    def test_amounts_are_exact_numeric_not_float(
        self, table_name: str, columns: list[str]
    ) -> None:
        table = metadata.tables[table_name]
        for column_name in columns:
            column = table.columns[column_name]
            assert column.type.__class__.__name__ == "Numeric", (
                f"{table_name}.{column_name} must be NUMERIC, got {column.type}"
            )
            assert column.type.asdecimal is True

    def test_escrow_cannot_pay_out_more_than_it_holds(self) -> None:
        sql = check_constraint_sql("escrows")
        assert "released_amount + refunded_amount <= amount" in sql

    def test_order_totals_must_reconcile(self) -> None:
        sql = check_constraint_sql("orders")
        assert "subtotal = unit_price * quantity" in sql
        assert "total_amount = subtotal + platform_fee" in sql

    def test_amounts_are_constrained_positive(self) -> None:
        assert "amount > 0" in check_constraint_sql("escrows")
        assert "total_amount > 0" in check_constraint_sql("orders")


class TestReputationCannotBeFabricated:
    """The structural guarantees that make reputation derive from real activity."""

    def test_a_review_requires_an_order(self) -> None:
        order_id = metadata.tables["reviews"].columns["order_id"]
        assert order_id.nullable is False, "a review must reference a real order"

    def test_at_most_one_review_per_order(self) -> None:
        reviews = metadata.tables["reviews"]
        order_id = reviews.columns["order_id"]
        unique_sets = [
            {c.name for c in c_.columns}
            for c_ in reviews.constraints
            if isinstance(c_, UniqueConstraint)
        ]
        assert order_id.unique or {"order_id"} in unique_sets

    @pytest.mark.parametrize(
        "table_name", ["agents", "services", "reputation_snapshots"]
    )
    def test_rating_sum_is_bounded_by_review_count(self, table_name: str) -> None:
        """Makes an inflated rating_sum unrepresentable, not merely discouraged."""
        assert "rating_sum <= review_count * 5" in check_constraint_sql(table_name)

    def test_ratings_are_bounded_one_to_five(self) -> None:
        assert "rating BETWEEN 1 AND 5" in check_constraint_sql("reviews")

    def test_services_cannot_have_more_reviews_than_completed_orders(self) -> None:
        sql = check_constraint_sql("services")
        assert "review_count <= completed_order_count" in sql

    def test_activity_counters_cannot_go_negative(self) -> None:
        for table_name in ("agents", "services"):
            sql = check_constraint_sql(table_name)
            assert "review_count >= 0" in sql

    def test_reputation_snapshot_has_no_manually_settable_score_source(self) -> None:
        """A snapshot's score must be nullable, so 'no data' is representable.

        A non-nullable score would force a fabricated default for agents that have
        never traded.
        """
        score = metadata.tables["reputation_snapshots"].columns["score"]
        assert score.nullable is True


class TestNonCustodialGuarantees:
    """Nothing in the schema may store key material."""

    FORBIDDEN_FRAGMENTS = (
        "private_key", "privatekey", "seed_phrase", "seedphrase",
        "mnemonic", "secret_key", "secretkey", "keystore", "passphrase",
    )

    def test_no_column_could_hold_key_material(self) -> None:
        offenders = [
            f"{table_name}.{column.name}"
            for table_name, table in metadata.tables.items()
            for column in table.columns
            if any(f in column.name.lower() for f in self.FORBIDDEN_FRAGMENTS)
        ]
        assert offenders == [], f"columns that could hold key material: {offenders}"

    def test_no_password_columns_exist(self) -> None:
        """Authentication is wallet-signature based; there are no passwords."""
        offenders = [
            f"{table_name}.{column.name}"
            for table_name, table in metadata.tables.items()
            for column in table.columns
            if "password" in column.name.lower()
        ]
        assert offenders == []

    def test_sessions_store_only_a_token_hash(self) -> None:
        columns = metadata.tables["sessions"].columns
        assert "refresh_token_hash" in columns
        assert "refresh_token" not in columns

    def test_payout_wallet_must_be_verified(self) -> None:
        sql = check_constraint_sql("wallets")
        assert "verification_status = 'verified'" in sql


class TestUniquenessAndIntegrity:
    def test_a_wallet_address_is_claimed_once_per_chain(self) -> None:
        wallets = metadata.tables["wallets"]
        unique_sets = [
            {c.name for c in constraint.columns}
            for constraint in wallets.constraints
            if isinstance(constraint, UniqueConstraint)
        ]
        assert {"address", "chain_id"} in unique_sets

    def test_a_chain_transaction_is_recorded_once_per_chain(self) -> None:
        txs = metadata.tables["chain_transactions"]
        unique_sets = [
            {c.name for c in constraint.columns}
            for constraint in txs.constraints
            if isinstance(constraint, UniqueConstraint)
        ]
        assert {"chain_id", "tx_hash"} in unique_sets

    def test_one_escrow_per_order(self) -> None:
        assert metadata.tables["escrows"].columns["order_id"].unique is True

    def test_user_primary_address_is_unique(self) -> None:
        assert metadata.tables["users"].columns["primary_address"].unique is True


class TestIndexesForKnownQueryPaths:
    """Indexes that the platform's hot paths depend on."""

    def index_names(self, table_name: str) -> set[str]:
        return {i.name for i in metadata.tables[table_name].indexes}

    def test_service_search_is_indexed(self) -> None:
        assert "ix_services_search_vector" in self.index_names("services")

    def test_unread_notifications_are_indexed(self) -> None:
        assert "ix_notifications_user_unread" in self.index_names("notifications")

    def test_worker_queues_are_indexed(self) -> None:
        assert "ix_orders_auto_release_due" in self.index_names("orders")
        assert "ix_chain_transactions_pending" in self.index_names(
            "chain_transactions"
        )
