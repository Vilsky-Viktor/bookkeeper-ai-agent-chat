-- migrate:up
-- When each correction was last made, so the agent gets the most recent ones once a
-- user has more than it reads (corrections.LIST_LIMIT). Existing rows get the
-- migration time: their relative order is unknown.
ALTER TABLE category_corrections ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();
CREATE INDEX category_corrections_uid_updated_at_idx ON category_corrections (uid, updated_at DESC);

-- migrate:down
DROP INDEX category_corrections_uid_updated_at_idx;
ALTER TABLE category_corrections DROP COLUMN updated_at;
