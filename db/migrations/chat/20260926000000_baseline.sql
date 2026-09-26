-- migrate:up
-- The schema as of the move to migrations. Idempotent, so a database created by the
-- old db/init scripts adopts it without changes. The chat_user role itself is created
-- outside migrations (Terraform in production, db/init locally).

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS threads (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    uid                 text NOT NULL,
    title               text,
    summary             text,
    summarized_through  bigint,
    working_set         jsonb NOT NULL DEFAULT '{}',
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS messages (
    seq             bigserial PRIMARY KEY,
    client_msg_id   uuid,
    thread_id       uuid NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    uid             text NOT NULL,
    role            text NOT NULL CHECK (role IN ('user','assistant','tool')),
    content         jsonb NOT NULL,
    compact         jsonb,
    token_count     int NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS messages_thread_id_seq_idx ON messages (thread_id, seq);
CREATE UNIQUE INDEX IF NOT EXISTS messages_thread_id_client_msg_id_idx
    ON messages (thread_id, client_msg_id) WHERE client_msg_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS user_preferences (
    uid               text PRIMARY KEY,
    default_currency  char(3),
    language          text NOT NULL DEFAULT 'en',
    notes             jsonb NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS usage_counters (
    uid       text NOT NULL,
    day       date NOT NULL,
    turns     int NOT NULL DEFAULT 0,
    receipts  int NOT NULL DEFAULT 0,
    tokens    bigint NOT NULL DEFAULT 0,
    PRIMARY KEY (uid, day)
);

ALTER TABLE threads ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS own_rows ON threads;
CREATE POLICY own_rows ON threads USING (uid = current_setting('app.uid'));

ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS own_rows ON messages;
CREATE POLICY own_rows ON messages USING (uid = current_setting('app.uid'));

ALTER TABLE user_preferences ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS own_rows ON user_preferences;
CREATE POLICY own_rows ON user_preferences USING (uid = current_setting('app.uid'));

ALTER TABLE usage_counters ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS own_rows ON usage_counters;
CREATE POLICY own_rows ON usage_counters USING (uid = current_setting('app.uid'));

GRANT SELECT, INSERT, UPDATE, DELETE ON threads, messages, user_preferences, usage_counters TO chat_user;
GRANT USAGE ON SEQUENCE messages_seq_seq TO chat_user;

-- Only chat_user may connect (app_user can't read this database).
DO $$
BEGIN
    EXECUTE format('REVOKE CONNECT ON DATABASE %I FROM PUBLIC', current_database());
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO chat_user', current_database());
END $$;

-- migrate:down
-- The baseline is never rolled back: that would drop every user's data.
