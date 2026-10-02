-- +goose Up
-- Identity is immutable independently of editable login names and profile JSON.
-- +goose StatementBegin
CREATE FUNCTION prevent_account_id_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.id IS DISTINCT FROM OLD.id THEN RAISE EXCEPTION 'account id is immutable'; END IF;
 RETURN NEW;
END $$;
-- +goose StatementEnd
CREATE TRIGGER immutable_account_id BEFORE UPDATE OF id ON users FOR EACH ROW EXECUTE FUNCTION prevent_account_id_change();
CREATE TABLE character_releases (
 character_id text NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
 release_id uuid NOT NULL,
 platform text NOT NULL,
 version bigint NOT NULL CHECK(version>0),
 manifest jsonb NOT NULL,
 distributable boolean NOT NULL DEFAULT false,
 published_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(character_id,platform,version),
 UNIQUE(release_id)
);
CREATE TABLE support_tickets (
 id uuid PRIMARY KEY,
 user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 category text NOT NULL,
 content text NOT NULL,
 state text NOT NULL DEFAULT 'open',
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX support_tickets_owner_cursor ON support_tickets(user_id,id);
-- +goose Down
DROP TABLE support_tickets;
DROP TABLE character_releases;
DROP TRIGGER immutable_account_id ON users;
DROP FUNCTION prevent_account_id_change();
