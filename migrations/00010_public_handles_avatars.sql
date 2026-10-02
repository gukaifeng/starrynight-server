-- +goose Up
-- UUID remains the permanent ownership/authentication key. The public handle is
-- a distinct alias; retired aliases are reserved for a future rename workflow.
CREATE SEQUENCE starry_handle_sequence START WITH 100000000001 MAXVALUE 999999999999 NO CYCLE;
ALTER TABLE users ADD COLUMN starry_id text NOT NULL DEFAULT ('XY' || nextval('starry_handle_sequence')::text);
ALTER TABLE users ADD CONSTRAINT users_starry_id_unique UNIQUE(starry_id);
ALTER TABLE users ADD CONSTRAINT users_starry_id_format CHECK (starry_id ~ '^XY[0-9]{12}$');
CREATE TABLE account_handles (
    handle text PRIMARY KEY,
    user_id uuid REFERENCES users(id) ON DELETE SET NULL,
    assigned_at timestamptz NOT NULL DEFAULT now(),
    retired_at timestamptz
);
CREATE UNIQUE INDEX account_handles_current ON account_handles(user_id) WHERE retired_at IS NULL;
INSERT INTO account_handles(handle,user_id) SELECT starry_id,id FROM users;
-- +goose StatementBegin
CREATE FUNCTION reserve_starry_handle() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO account_handles(handle,user_id) VALUES(NEW.starry_id,NEW.id);
    RETURN NEW;
END;
$$;
CREATE FUNCTION protect_starry_handle() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.starry_id IS DISTINCT FROM OLD.starry_id THEN
        RAISE EXCEPTION 'starry id is not editable';
    END IF;
    RETURN NEW;
END;
$$;
-- +goose StatementEnd
CREATE TRIGGER users_reserve_handle AFTER INSERT ON users FOR EACH ROW EXECUTE FUNCTION reserve_starry_handle();
CREATE TRIGGER users_protect_handle BEFORE UPDATE OF starry_id ON users FOR EACH ROW EXECUTE FUNCTION protect_starry_handle();
UPDATE users SET profile=jsonb_set(profile,'{avatar}','"starry-cat-v1"') WHERE COALESCE(profile->>'avatar','moon')='moon';
CREATE TABLE account_avatars (
    user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    sha256 text NOT NULL CHECK (sha256 ~ '^[a-f0-9]{64}$'),
    content_type text NOT NULL CHECK (content_type='image/jpeg'),
    image bytea NOT NULL CHECK (octet_length(image)>0 AND octet_length(image)<=131072),
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- +goose Down
DROP TABLE account_avatars;
DROP TRIGGER users_protect_handle ON users;
DROP TRIGGER users_reserve_handle ON users;
DROP FUNCTION protect_starry_handle();
DROP FUNCTION reserve_starry_handle();
DROP TABLE account_handles;
ALTER TABLE users DROP COLUMN starry_id;
DROP SEQUENCE starry_handle_sequence;
