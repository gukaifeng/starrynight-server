-- +goose Up
-- Additive cutover: legacy journals stay intact until the checked import runs.
CREATE TABLE character_revisions (
 character_id text NOT NULL REFERENCES characters(id), revision bigint NOT NULL CHECK(revision>0),
 public_core jsonb NOT NULL, capability_snapshot jsonb NOT NULL, source_hash text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(character_id,revision)
);
CREATE TABLE setting_templates (
 id uuid PRIMARY KEY, owner_id uuid REFERENCES users(id) ON DELETE CASCADE,
 author_id text NOT NULL REFERENCES authors(id), visibility text NOT NULL DEFAULT 'private' CHECK(visibility IN ('private','public')),
 availability text NOT NULL DEFAULT 'draft' CHECK(availability IN ('draft','active','withdrawn','revoked')),
 access_epoch bigint NOT NULL DEFAULT 1, current_revision bigint, version bigint NOT NULL DEFAULT 1,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX setting_templates_owner ON setting_templates(owner_id,id);
CREATE TABLE setting_drafts (
 id uuid PRIMARY KEY, owner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 template_id uuid REFERENCES setting_templates(id), client_draft_id uuid NOT NULL,
 base_revision bigint, version bigint NOT NULL DEFAULT 1,
 title text NOT NULL DEFAULT '', source_envelope jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), deleted_at timestamptz,
 UNIQUE(owner_id,id), UNIQUE(owner_id,client_draft_id)
);
CREATE INDEX setting_drafts_owner ON setting_drafts(owner_id,id) WHERE deleted_at IS NULL;
CREATE TABLE setting_draft_checkpoints (
 id uuid PRIMARY KEY, owner_id uuid NOT NULL, draft_id uuid NOT NULL, draft_version bigint NOT NULL,
 name text NOT NULL DEFAULT '', source_envelope jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(owner_id,draft_id) REFERENCES setting_drafts(owner_id,id) ON DELETE CASCADE
);
CREATE INDEX setting_checkpoints_recent ON setting_draft_checkpoints(owner_id,draft_id,created_at DESC);
CREATE TABLE setting_revisions (
 setting_id uuid NOT NULL REFERENCES setting_templates(id) ON DELETE CASCADE, revision bigint NOT NULL,
 public_document jsonb NOT NULL, public_requirements jsonb NOT NULL,
 source_hash text NOT NULL, compiler_contract text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(setting_id,revision)
);
CREATE TABLE setting_revision_secrets (
 setting_id uuid NOT NULL, revision bigint NOT NULL, source_envelope jsonb NOT NULL,
 FOREIGN KEY(setting_id,revision) REFERENCES setting_revisions(setting_id,revision) ON DELETE CASCADE,
 PRIMARY KEY(setting_id,revision)
);
ALTER TABLE setting_templates ADD CONSTRAINT setting_template_revision FOREIGN KEY(id,current_revision) REFERENCES setting_revisions(setting_id,revision) DEFERRABLE INITIALLY DEFERRED;
CREATE TABLE setting_submissions (
 id uuid PRIMARY KEY, owner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 setting_id uuid NOT NULL, revision bigint NOT NULL, target_visibility text NOT NULL CHECK(target_visibility IN ('private','public')),
 expected_template_version bigint NOT NULL, validation_status text NOT NULL DEFAULT 'pending' CHECK(validation_status IN ('pending','running','passed','failed')),
 review_status text NOT NULL CHECK(review_status IN ('not_required','pending','approved','rejected')),
 report jsonb NOT NULL DEFAULT '{}', version bigint NOT NULL DEFAULT 1,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(setting_id,revision) REFERENCES setting_revisions(setting_id,revision)
);
CREATE INDEX setting_submission_pending ON setting_submissions(created_at,id) WHERE validation_status='pending';
CREATE TABLE setting_releases (
 id uuid PRIMARY KEY, setting_id uuid NOT NULL, revision bigint NOT NULL,
 submission_id uuid UNIQUE REFERENCES setting_submissions(id), validation_contract text NOT NULL,
 review_receipt jsonb NOT NULL DEFAULT '{}', published_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(setting_id,revision) REFERENCES setting_revisions(setting_id,revision), UNIQUE(setting_id,revision)
);
CREATE TABLE setting_public_projection (
 setting_id uuid PRIMARY KEY REFERENCES setting_templates(id) ON DELETE CASCADE,
 revision bigint NOT NULL, author_id text NOT NULL REFERENCES authors(id),
 title text NOT NULL, synopsis text NOT NULL, language text NOT NULL,
 data jsonb NOT NULL, updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX setting_projection_search ON setting_public_projection USING gin((title || ' ' || synopsis) gin_trgm_ops);
CREATE TABLE setting_favorites (
 user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE, setting_id uuid NOT NULL REFERENCES setting_templates(id) ON DELETE CASCADE,
 created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(user_id,setting_id)
);
CREATE TABLE conversation_instances (
 id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 character_id text NOT NULL, character_revision bigint NOT NULL,
 setting_id uuid NOT NULL, setting_revision bigint NOT NULL,
 parameters jsonb NOT NULL DEFAULT '{}', binding_snapshot jsonb NOT NULL DEFAULT '{}',
 config_version bigint NOT NULL DEFAULT 1, reset_epoch bigint NOT NULL DEFAULT 1, version bigint NOT NULL DEFAULT 1,
 next_sequence bigint NOT NULL DEFAULT 1, hidden boolean NOT NULL DEFAULT false,
 legacy boolean NOT NULL DEFAULT false, legacy_reset_id text NOT NULL DEFAULT '',
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(user_id,id), FOREIGN KEY(character_id,character_revision) REFERENCES character_revisions(character_id,revision),
 FOREIGN KEY(setting_id,setting_revision) REFERENCES setting_revisions(setting_id,revision)
);
CREATE INDEX conversation_instances_recent ON conversation_instances(user_id,updated_at DESC,id);
CREATE TABLE conversation_migration_map (
 user_id uuid NOT NULL, character_id text NOT NULL, conversation_id uuid NOT NULL,
 evidence jsonb NOT NULL DEFAULT '{}', migrated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(user_id,character_id), FOREIGN KEY(user_id,conversation_id) REFERENCES conversation_instances(user_id,id) ON DELETE CASCADE
);
CREATE TABLE conversation_turns (
 id uuid PRIMARY KEY, user_id uuid NOT NULL, conversation_id uuid NOT NULL,
 client_request_id uuid NOT NULL, request_hash text NOT NULL, trigger text NOT NULL,
 status text NOT NULL DEFAULT 'accepted', epoch bigint NOT NULL, config_version bigint NOT NULL,
 fence bigint NOT NULL DEFAULT 0, next_event_sequence bigint NOT NULL DEFAULT 1,
 request_data jsonb NOT NULL DEFAULT '{}', result jsonb NOT NULL DEFAULT '{}', error_code text NOT NULL DEFAULT '',
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(user_id,conversation_id,client_request_id), UNIQUE(user_id,conversation_id,id),
 FOREIGN KEY(user_id,conversation_id) REFERENCES conversation_instances(user_id,id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX conversation_turn_active ON conversation_turns(conversation_id) WHERE status IN ('accepted','running');
CREATE TABLE conversation_turn_events (
 user_id uuid NOT NULL, conversation_id uuid NOT NULL, turn_id uuid NOT NULL, sequence bigint NOT NULL,
 data jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(turn_id,sequence),
 FOREIGN KEY(user_id,conversation_id,turn_id) REFERENCES conversation_turns(user_id,conversation_id,id) ON DELETE CASCADE
);
CREATE TABLE conversation_messages (
 id uuid NOT NULL, user_id uuid NOT NULL, conversation_id uuid NOT NULL, sequence bigint NOT NULL, turn_id uuid,
 role text NOT NULL CHECK(role IN ('user','assistant')), text text NOT NULL, data jsonb NOT NULL,
 delivery_status text NOT NULL DEFAULT 'complete', source text NOT NULL, version bigint NOT NULL DEFAULT 1,
 created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(user_id,conversation_id,id), UNIQUE(conversation_id,sequence),
 FOREIGN KEY(user_id,conversation_id) REFERENCES conversation_instances(user_id,id) ON DELETE CASCADE,
 FOREIGN KEY(user_id,conversation_id,turn_id) REFERENCES conversation_turns(user_id,conversation_id,id)
);
CREATE INDEX conversation_message_search ON conversation_messages USING gin(text gin_trgm_ops);
CREATE TABLE conversation_state (
 user_id uuid NOT NULL, conversation_id uuid NOT NULL, epoch bigint NOT NULL, kind text NOT NULL, id text NOT NULL,
 data jsonb NOT NULL, version bigint NOT NULL DEFAULT 1, updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(user_id,conversation_id,epoch,kind,id), FOREIGN KEY(user_id,conversation_id) REFERENCES conversation_instances(user_id,id) ON DELETE CASCADE
);
CREATE TABLE prepared_candidates (
 id uuid PRIMARY KEY, user_id uuid NOT NULL, conversation_id uuid NOT NULL, epoch bigint NOT NULL, trigger text NOT NULL,
 context_hash text NOT NULL, status text NOT NULL CHECK(status IN ('preparing','ready','consumed','expired','failed')),
 manifest jsonb NOT NULL DEFAULT '{}', expires_at timestamptz NOT NULL, used_by_turn uuid, fence bigint NOT NULL DEFAULT 0,
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(user_id,conversation_id) REFERENCES conversation_instances(user_id,id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX prepared_active_slot ON prepared_candidates(user_id,conversation_id,epoch,trigger,context_hash) WHERE status IN ('preparing','ready');
CREATE TABLE opening_receipts (
 user_id uuid NOT NULL, conversation_id uuid NOT NULL, epoch bigint NOT NULL, opening_id text NOT NULL, message_id uuid NOT NULL,
 used_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(user_id,conversation_id,epoch),
 FOREIGN KEY(user_id,conversation_id) REFERENCES conversation_instances(user_id,id) ON DELETE CASCADE
);
CREATE TABLE conversation_translations (
 user_id uuid NOT NULL, conversation_id uuid NOT NULL, epoch bigint NOT NULL, source_kind text NOT NULL, source_id text NOT NULL,
 source_hash text NOT NULL, locale text NOT NULL, contract text NOT NULL, segments jsonb NOT NULL,
 PRIMARY KEY(user_id,conversation_id,epoch,source_kind,source_id,source_hash,locale,contract),
 FOREIGN KEY(user_id,conversation_id) REFERENCES conversation_instances(user_id,id) ON DELETE CASCADE
);
CREATE TABLE content_mutation_receipts (
 owner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE, resource_id text NOT NULL, mutation_id uuid NOT NULL,
 request_hash text NOT NULL, result jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(owner_id,resource_id,mutation_id)
);
CREATE TABLE content_jobs (
 id uuid PRIMARY KEY, kind text NOT NULL, resource_id text NOT NULL, owner_id uuid REFERENCES users(id) ON DELETE CASCADE,
 payload jsonb NOT NULL, status text NOT NULL DEFAULT 'pending', fence bigint NOT NULL DEFAULT 0, attempts int NOT NULL DEFAULT 0,
 lease_until timestamptz, retry_at timestamptz NOT NULL DEFAULT now(), last_error text NOT NULL DEFAULT '',
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX content_jobs_pending ON content_jobs(retry_at,id) WHERE status IN ('pending','retry');
CREATE TABLE content_outbox (
 job_id uuid PRIMARY KEY REFERENCES content_jobs(id) ON DELETE CASCADE,
 delivered_at timestamptz, attempts int NOT NULL DEFAULT 0, next_attempt_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE content_audit (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, actor_id text NOT NULL, action text NOT NULL,
 resource_id text NOT NULL, revision bigint, reason text NOT NULL DEFAULT '', result text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
-- +goose Down
DROP TABLE content_audit,content_outbox,content_jobs,content_mutation_receipts,conversation_translations,opening_receipts,prepared_candidates,conversation_state,conversation_messages,conversation_turn_events,conversation_turns,conversation_migration_map,conversation_instances,setting_favorites,setting_public_projection,setting_releases,setting_submissions;
ALTER TABLE setting_templates DROP CONSTRAINT setting_template_revision;
DROP TABLE setting_revision_secrets,setting_revisions,setting_draft_checkpoints,setting_drafts,setting_templates,character_revisions;
