-- Bookkeeping DB: transactions, category_corrections, idempotency_keys + RLS.
-- Runs against the default database created by POSTGRES_DB (bookkeeping).

CREATE EXTENSION IF NOT EXISTS pgcrypto; -- gen_random_uuid()

CREATE TABLE transactions (
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
CREATE INDEX ON transactions (uid, occurred_on DESC);
CREATE INDEX ON transactions (uid, currency, category);

CREATE TABLE category_corrections (
    uid                 text NOT NULL,
    item_key            text NOT NULL, -- normalized description
    category            text NOT NULL,
    PRIMARY KEY (uid, item_key)
);

CREATE TABLE idempotency_keys (
    uid                       text NOT NULL,
    key                       text NOT NULL, -- tool_call_id or receipt batch_id
    request_hash              text NOT NULL,
    status                    int NOT NULL,
    response                  jsonb NOT NULL,
    created_at                timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (uid, key)
);
-- purge rows older than 24h with a daily scheduled job (see services/transactions/app/main.py)

ALTER TABLE transactions ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_rows ON transactions
    USING (uid = current_setting('app.uid'));

ALTER TABLE category_corrections ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_rows ON category_corrections
    USING (uid = current_setting('app.uid'));

ALTER TABLE idempotency_keys ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_rows ON idempotency_keys
    USING (uid = current_setting('app.uid'));

CREATE ROLE app_user LOGIN PASSWORD 'app_pw';
GRANT SELECT, INSERT, UPDATE, DELETE ON transactions, category_corrections, idempotency_keys TO app_user;

REVOKE CONNECT ON DATABASE bookkeeping FROM PUBLIC;
GRANT CONNECT ON DATABASE bookkeeping TO app_user;
