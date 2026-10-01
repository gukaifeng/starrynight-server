-- +goose Up
CREATE INDEX messages_account_sequence ON messages(user_id, sequence);
ALTER TABLE entries ADD COLUMN deleted boolean NOT NULL DEFAULT false;

-- +goose Down
DROP INDEX messages_account_sequence;
ALTER TABLE entries DROP COLUMN deleted;
