-- +goose Up
-- Keep the registration ordinal allocator unchanged across replicas. Reserve
-- previous aliases forever; UUID ownership and registration gaps stay intact.
LOCK TABLE users, account_handles IN ACCESS EXCLUSIVE MODE;
DROP TRIGGER users_protect_handle ON users;
ALTER TABLE users ALTER COLUMN starry_id SET DEFAULT ('xy' || (100000000::numeric + nextval('starry_registration_sequence'))::text);
UPDATE account_handles SET retired_at=now() WHERE retired_at IS NULL;
UPDATE users SET starry_id='xy' || (100000000::numeric + substring(starry_id FROM 3)::numeric)::text;
INSERT INTO account_handles(handle,user_id) SELECT starry_id,id FROM users;
CREATE TRIGGER users_protect_handle BEFORE UPDATE OF starry_id ON users FOR EACH ROW EXECUTE FUNCTION protect_starry_handle();

-- +goose Down
-- +goose StatementBegin
DO $$ BEGIN RAISE EXCEPTION 'Public handles require a forward migration; reserved aliases cannot be discarded'; END $$;
-- +goose StatementEnd
