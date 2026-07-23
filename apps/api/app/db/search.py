"""Full-text search support for the service catalogue.

The `services.search_vector` column is maintained by a database trigger rather than
by application code. That choice is deliberate: any write path — an API handler, a
migration, a manual correction in psql — keeps search correct, and the vector can
never drift from the row it describes.

Weights follow relevance: a term in the title should outrank the same term buried
in a long description.

    A  title        highest
    B  summary, tags
    C  description  lowest
"""
from __future__ import annotations

# Search is configured for English stemming. When locale-specific catalogues are
# added this becomes a per-row configuration column rather than a constant.
SEARCH_CONFIG = "english"

CREATE_SEARCH_VECTOR_FUNCTION = f"""
CREATE OR REPLACE FUNCTION services_search_vector_update()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('{SEARCH_CONFIG}', coalesce(NEW.title, '')), 'A') ||
        setweight(to_tsvector('{SEARCH_CONFIG}', coalesce(NEW.summary, '')), 'B') ||
        setweight(
            to_tsvector(
                '{SEARCH_CONFIG}',
                coalesce(array_to_string(NEW.tags, ' '), '')
            ),
            'B'
        ) ||
        setweight(to_tsvector('{SEARCH_CONFIG}', coalesce(NEW.description, '')), 'C');
    RETURN NEW;
END
$$;
"""

DROP_SEARCH_VECTOR_FUNCTION = "DROP FUNCTION IF EXISTS services_search_vector_update();"

CREATE_SEARCH_VECTOR_TRIGGER = """
CREATE TRIGGER services_search_vector_trigger
BEFORE INSERT OR UPDATE OF title, summary, description, tags
ON services
FOR EACH ROW
EXECUTE FUNCTION services_search_vector_update();
"""

DROP_SEARCH_VECTOR_TRIGGER = (
    "DROP TRIGGER IF EXISTS services_search_vector_trigger ON services;"
)

# Forces the trigger to fire for every existing row when it is first installed.
BACKFILL_SEARCH_VECTORS = "UPDATE services SET title = title;"
