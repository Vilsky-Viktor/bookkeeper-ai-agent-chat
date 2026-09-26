-- migrate:up
-- The schema as of the move to migrations. Idempotent, so a database created by the
-- old db/init scripts adopts it without changes. The app_user role itself is created
-- outside migrations (Terraform in production, db/init locally).

CREATE EXTENSION IF NOT EXISTS pgcrypto; -- gen_random_uuid()

CREATE TABLE IF NOT EXISTS transactions (
    id                        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    uid                       text NOT NULL,
    occurred_on               date NOT NULL,
    type                      text NOT NULL CHECK (type IN ('expense','income')),
    amount_minor              bigint NOT NULL CHECK (amount_minor > 0),
    currency                  char(3) NOT NULL,
    category                  text NOT NULL,
    description               text, -- merchant/place, if any, belongs in here, not a separate field
    receipt_uri               text,
    batch_id                  uuid,
    created_at                timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS transactions_uid_occurred_on_idx ON transactions (uid, occurred_on DESC);
CREATE INDEX IF NOT EXISTS transactions_uid_currency_category_idx ON transactions (uid, currency, category);

CREATE TABLE IF NOT EXISTS category_corrections (
    uid                 text NOT NULL,
    item_key            text NOT NULL, -- normalized description
    category            text NOT NULL,
    PRIMARY KEY (uid, item_key)
);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    uid                       text NOT NULL,
    key                       text NOT NULL, -- tool_call_id or receipt batch_id
    request_hash              text NOT NULL,
    status                    int NOT NULL,
    response                  jsonb NOT NULL,
    created_at                timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (uid, key)
);

ALTER TABLE transactions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS own_rows ON transactions;
CREATE POLICY own_rows ON transactions USING (uid = current_setting('app.uid'));

ALTER TABLE category_corrections ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS own_rows ON category_corrections;
CREATE POLICY own_rows ON category_corrections USING (uid = current_setting('app.uid'));

ALTER TABLE idempotency_keys ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS own_rows ON idempotency_keys;
CREATE POLICY own_rows ON idempotency_keys USING (uid = current_setting('app.uid'));

GRANT SELECT, INSERT, UPDATE, DELETE ON transactions, category_corrections, idempotency_keys TO app_user;

-- Only app_user may connect (chat_user can't read this database).
DO $$
BEGIN
    EXECUTE format('REVOKE CONNECT ON DATABASE %I FROM PUBLIC', current_database());
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO app_user', current_database());
END $$;

-- migrate:down
-- The baseline is never rolled back: that would drop every user's data.
