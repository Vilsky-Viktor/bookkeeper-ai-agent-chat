-- Chat DB: threads, messages, user_preferences, usage_counters + RLS.
-- Lives on the same Cloud SQL instance / postgres container, separate database,
-- separate role. app_user (bookkeeping DB) cannot read this database and vice versa.

CREATE DATABASE chat;
CREATE ROLE chat_user LOGIN PASSWORD 'chat_pw';

\connect chat

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE threads (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    uid                 text NOT NULL,
    title               text,
    summary             text,
    summarized_through  bigint,
    working_set         jsonb NOT NULL DEFAULT '{}',
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE messages (
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
CREATE INDEX ON messages (thread_id, seq);
CREATE UNIQUE INDEX ON messages (thread_id, client_msg_id) WHERE client_msg_id IS NOT NULL;

CREATE TABLE user_preferences (
    uid               text PRIMARY KEY,
    default_currency  char(3),
    language          text NOT NULL DEFAULT 'en',
    notes             jsonb NOT NULL DEFAULT '{}'
);

CREATE TABLE usage_counters (
    uid       text NOT NULL,
    day       date NOT NULL,
    turns     int NOT NULL DEFAULT 0,
    receipts  int NOT NULL DEFAULT 0,
    tokens    bigint NOT NULL DEFAULT 0,
    PRIMARY KEY (uid, day)
);

ALTER TABLE threads ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_rows ON threads USING (uid = current_setting('app.uid'));

ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_rows ON messages USING (uid = current_setting('app.uid'));

ALTER TABLE user_preferences ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_rows ON user_preferences USING (uid = current_setting('app.uid'));

ALTER TABLE usage_counters ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_rows ON usage_counters USING (uid = current_setting('app.uid'));

GRANT SELECT, INSERT, UPDATE, DELETE ON threads, messages, user_preferences, usage_counters TO chat_user;
GRANT USAGE ON SEQUENCE messages_seq_seq TO chat_user;

REVOKE CONNECT ON DATABASE chat FROM PUBLIC;
GRANT CONNECT ON DATABASE chat TO chat_user;
