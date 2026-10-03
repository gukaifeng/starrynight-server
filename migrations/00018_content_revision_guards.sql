-- +goose Up
-- A creator leaving must revoke future access, not cascade-delete another
-- user's conversation history. The account deletion service scrubs source and
-- detaches the retained public author before removing the account.
ALTER TABLE setting_templates DROP CONSTRAINT setting_templates_owner_id_fkey;
ALTER TABLE setting_templates ADD CONSTRAINT setting_templates_owner_id_fkey FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE setting_releases DROP CONSTRAINT setting_releases_submission_id_fkey;
ALTER TABLE setting_releases ADD CONSTRAINT setting_releases_submission_id_fkey FOREIGN KEY(submission_id) REFERENCES setting_submissions(id) ON DELETE SET NULL;
CREATE TABLE character_revision_secrets (
 character_id text NOT NULL, revision bigint NOT NULL, source_envelope jsonb NOT NULL,
 PRIMARY KEY(character_id,revision), FOREIGN KEY(character_id,revision) REFERENCES character_revisions(character_id,revision) ON DELETE CASCADE
);
-- +goose StatementBegin
CREATE FUNCTION protect_content_revision() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'published source revisions are immutable' USING ERRCODE='23514';
END $$;
-- +goose StatementEnd
CREATE TRIGGER character_revision_immutable BEFORE UPDATE ON character_revisions FOR EACH ROW EXECUTE FUNCTION protect_content_revision();
CREATE TRIGGER setting_revision_immutable BEFORE UPDATE ON setting_revisions FOR EACH ROW EXECUTE FUNCTION protect_content_revision();
CREATE TRIGGER setting_source_immutable BEFORE UPDATE ON setting_revision_secrets FOR EACH ROW EXECUTE FUNCTION protect_content_revision();
CREATE TRIGGER character_source_immutable BEFORE UPDATE ON character_revision_secrets FOR EACH ROW EXECUTE FUNCTION protect_content_revision();
-- submission_id may be nulled by an account-deletion FK; content remains fixed.
CREATE TRIGGER setting_release_immutable BEFORE UPDATE OF id,setting_id,revision,validation_contract,review_receipt,published_at ON setting_releases FOR EACH ROW EXECUTE FUNCTION protect_content_revision();
-- +goose Down
DROP TRIGGER setting_release_immutable ON setting_releases;
DROP TRIGGER setting_source_immutable ON setting_revision_secrets;
DROP TRIGGER character_source_immutable ON character_revision_secrets;
DROP TRIGGER setting_revision_immutable ON setting_revisions;
DROP TRIGGER character_revision_immutable ON character_revisions;
DROP FUNCTION protect_content_revision();
DROP TABLE character_revision_secrets;
ALTER TABLE setting_releases DROP CONSTRAINT setting_releases_submission_id_fkey;
ALTER TABLE setting_releases ADD CONSTRAINT setting_releases_submission_id_fkey FOREIGN KEY(submission_id) REFERENCES setting_submissions(id);
ALTER TABLE setting_templates DROP CONSTRAINT setting_templates_owner_id_fkey;
ALTER TABLE setting_templates ADD CONSTRAINT setting_templates_owner_id_fkey FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE CASCADE;
