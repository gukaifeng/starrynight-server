-- +goose Up
CREATE TABLE admin_users (
 id uuid PRIMARY KEY,
 username text NOT NULL UNIQUE CHECK(username ~ '^[a-z0-9_]{3,32}$'),
 password_hash text NOT NULL,
 role text NOT NULL CHECK(role IN ('owner','editor','viewer')),
 disabled boolean NOT NULL DEFAULT false,
 session_epoch bigint NOT NULL DEFAULT 1,
 version bigint NOT NULL DEFAULT 1,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE admin_audit (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 actor_id uuid REFERENCES admin_users ON DELETE SET NULL,
 actor_name text NOT NULL,
 action text NOT NULL,
 resource text NOT NULL,
 target jsonb NOT NULL DEFAULT '{}',
 outcome text NOT NULL,
 request_id uuid NOT NULL,
 occurred_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX admin_audit_page ON admin_audit(id DESC);
ALTER TABLE support_tickets ADD COLUMN version bigint NOT NULL DEFAULT 1;
-- +goose Down
DROP TABLE admin_audit,admin_users;
ALTER TABLE support_tickets DROP COLUMN version;
