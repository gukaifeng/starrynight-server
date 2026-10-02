-- +goose Up
-- One authoritative PostgreSQL sequence allocates across all API replicas.
-- Retired long aliases remain reserved; UUID ownership never changes.
LOCK TABLE users, account_handles IN ACCESS EXCLUSIVE MODE;
DROP TRIGGER users_protect_handle ON users;
ALTER TABLE users DROP CONSTRAINT users_starry_id_format;
-- A NEW sequence is dropped if this migration rolls back. Never setval the
-- old live allocator: setval itself is not rolled back by PostgreSQL.
CREATE SEQUENCE starry_registration_sequence START WITH 1 NO CYCLE;
SELECT setval('starry_registration_sequence',last_value-100000000000,is_called) FROM starry_handle_sequence;
ALTER TABLE users ALTER COLUMN starry_id SET DEFAULT ('xy' || nextval('starry_registration_sequence')::text);
UPDATE account_handles SET retired_at=now() WHERE retired_at IS NULL;
UPDATE users SET starry_id='xy' || (substring(starry_id FROM 3)::bigint-100000000000)::text;
INSERT INTO account_handles(handle,user_id) SELECT starry_id,id FROM users;
ALTER TABLE users ADD CONSTRAINT users_starry_id_format CHECK (starry_id ~ '^xy[1-9][0-9]{0,18}$');
CREATE TRIGGER users_protect_handle BEFORE UPDATE OF starry_id ON users FOR EACH ROW EXECUTE FUNCTION protect_starry_handle();
UPDATE users SET profile=jsonb_set(profile,'{bio}','"在星夜，遇见温柔。"') WHERE NOT profile ? 'bio';
UPDATE users SET profile=jsonb_set(profile,'{avatar}','"starry-orbit-v1"') WHERE profile->>'avatar' IN ('starry-cat-v1','starry-bunny-v1');

-- +goose Down
-- Never discard reserved aliases or rewind the live registration sequence.
-- +goose StatementBegin
DO $$ BEGIN RAISE EXCEPTION 'Short public handles require a forward migration; reserved aliases cannot be discarded'; END $$;
-- +goose StatementEnd
