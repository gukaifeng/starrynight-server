package store

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/gukaifeng/starrynight-server/internal/content"
	"github.com/gukaifeng/starrynight-server/internal/privatecontent"
	"github.com/jackc/pgx/v5"
	"strings"
	"time"
)

var ErrPrecondition = errors.New("draft has changed; merge the latest version")
var ErrMutationReused = errors.New("mutation identifier was reused with different content")

type DraftSummary struct {
	ID            string    `json:"id"`
	ClientDraftID string    `json:"client_draft_id"`
	TemplateID    string    `json:"template_id,omitempty"`
	Title         string    `json:"title"`
	Version       int64     `json:"version"`
	BaseRevision  *int64    `json:"base_revision,omitempty"`
	UpdatedAt     time.Time `json:"updated_at"`
	Deleted       bool      `json:"deleted"`
}
type SettingDraft struct {
	DraftSummary
	Body content.DraftBody `json:"body"`
}

const draftCols = `id::text,client_draft_id::text,COALESCE(template_id::text,''),title,version,base_revision,updated_at,deleted_at IS NOT NULL`

func scanDraft(row pgx.Row) (DraftSummary, error) {
	var d DraftSummary
	e := row.Scan(&d.ID, &d.ClientDraftID, &d.TemplateID, &d.Title, &d.Version, &d.BaseRevision, &d.UpdatedAt, &d.Deleted)
	return d, classify(e)
}
func draftTitle(d content.DraftBody) string {
	return string([]rune(strings.TrimSpace(d.Document.PublicProfile.Title))[:min(80, len([]rune(strings.TrimSpace(d.Document.PublicProfile.Title))))])
}
func (s *Store) SettingDrafts(ctx context.Context, user, after string, limit int) (Page[DraftSummary], error) {
	p := Page[DraftSummary]{Items: []DraftSummary{}}
	rows, e := s.Pool.Query(ctx, `SELECT `+draftCols+` FROM setting_drafts WHERE owner_id=$1 AND deleted_at IS NULL AND id::text>$2 ORDER BY id LIMIT $3`, user, after, limit+1)
	if e != nil {
		return p, e
	}
	defer rows.Close()
	for rows.Next() {
		d, e := scanDraft(rows)
		if e != nil {
			return p, e
		}
		p.Items = append(p.Items, d)
	}
	if len(p.Items) > limit {
		p.Items = p.Items[:limit]
		p.Next = p.Items[limit-1].ID
	}
	return p, rows.Err()
}
func (s *Store) SettingDraft(ctx context.Context, k *privatecontent.Keyring, user, id string) (SettingDraft, error) {
	var out SettingDraft
	var env privatecontent.Envelope
	e := s.Pool.QueryRow(ctx, `SELECT `+draftCols+`,source_envelope FROM setting_drafts WHERE id=$1 AND owner_id=$2 AND deleted_at IS NULL`, id, user).Scan(&out.ID, &out.ClientDraftID, &out.TemplateID, &out.Title, &out.Version, &out.BaseRevision, &out.UpdatedAt, &out.Deleted, &env)
	if e != nil {
		return out, classify(e)
	}
	plain, e := k.Decrypt(env, privatecontent.Binding(user, "draft", id, out.Version))
	if e != nil {
		return out, e
	}
	e = json.Unmarshal(plain, &out.Body)
	return out, e
}

type DraftMutation struct {
	MutationID      string            `json:"mutation_id"`
	ClientDraftID   string            `json:"client_draft_id"`
	ExpectedVersion int64             `json:"expected_version"`
	Body            content.DraftBody `json:"body"`
}

func receipt(ctx context.Context, tx pgx.Tx, user, resource, mutation, hash string, result any) (bool, error) {
	var existing string
	var raw []byte
	e := tx.QueryRow(ctx, `SELECT request_hash,result FROM content_mutation_receipts WHERE owner_id=$1 AND resource_id=$2 AND mutation_id=$3`, user, resource, mutation).Scan(&existing, &raw)
	if errors.Is(e, pgx.ErrNoRows) {
		return false, nil
	}
	if e != nil {
		return false, e
	}
	if hash != existing {
		return false, ErrMutationReused
	}
	return true, json.Unmarshal(raw, result)
}
func putReceipt(ctx context.Context, tx pgx.Tx, user, resource, mutation, hash string, result any) error {
	b, e := json.Marshal(result)
	if e != nil {
		return e
	}
	_, e = tx.Exec(ctx, `INSERT INTO content_mutation_receipts(owner_id,resource_id,mutation_id,request_hash,result) VALUES($1,$2,$3,$4,$5)`, user, resource, mutation, hash, json.RawMessage(b))
	return e
}
func (s *Store) SaveSettingDraft(ctx context.Context, k *privatecontent.Keyring, user, id string, m DraftMutation) (DraftSummary, error) {
	var out DraftSummary
	if e := content.ValidateDraft(m.Body); e != nil {
		return out, ValidationError{e.Error()}
	}
	resource := id
	if id == "" {
		resource = "new-draft:" + m.ClientDraftID
	}
	hash := content.Hash(m)
	e := s.write(ctx, user, func(tx pgx.Tx) error {
		// Authentication/owner lock precedes receipt lookup. Saved receipts contain
		// metadata only: encrypted source is never duplicated in plaintext here.
		if found, e := receipt(ctx, tx, user, resource, m.MutationID, hash, &out); e != nil || found {
			return e
		}
		if id == "" {
			if m.ExpectedVersion != 0 {
				return ErrPrecondition
			}
			id = NewID()
			var existing string
			e := tx.QueryRow(ctx, `SELECT id::text FROM setting_drafts WHERE owner_id=$1 AND client_draft_id=$2`, user, m.ClientDraftID).Scan(&existing)
			if e == nil {
				return ErrMutationReused
			}
			if !errors.Is(e, pgx.ErrNoRows) {
				return e
			}
			plain, _ := json.Marshal(m.Body)
			env, e := k.Encrypt(plain, privatecontent.Binding(user, "draft", id, 1))
			if e != nil {
				return e
			}
			out, e = scanDraft(tx.QueryRow(ctx, `INSERT INTO setting_drafts(id,owner_id,client_draft_id,title,source_envelope) VALUES($1,$2,$3,$4,$5) RETURNING `+draftCols, id, user, m.ClientDraftID, draftTitle(m.Body), jsonParam(env)))
			if e != nil {
				return e
			}
		} else {
			current, e := scanDraft(tx.QueryRow(ctx, `SELECT `+draftCols+` FROM setting_drafts WHERE id=$1 AND owner_id=$2 AND deleted_at IS NULL FOR UPDATE`, id, user))
			if e != nil {
				return e
			}
			if current.Version != m.ExpectedVersion {
				return ErrPrecondition
			}
			var previous privatecontent.Envelope
			if e = tx.QueryRow(ctx, `SELECT source_envelope FROM setting_drafts WHERE id=$1 AND owner_id=$2`, id, user).Scan(&previous); e != nil {
				return e
			}
			// Checkpoint keeps the same draft/version AAD; it cannot be moved to a
			// different owner or version. Named checkpoints survive automatic pruning.
			_, e = tx.Exec(ctx, `INSERT INTO setting_draft_checkpoints(id,owner_id,draft_id,draft_version,source_envelope) VALUES($1,$2,$3,$4,$5)`, NewID(), user, id, current.Version, jsonParam(previous))
			if e != nil {
				return e
			}
			_, e = tx.Exec(ctx, `DELETE FROM setting_draft_checkpoints WHERE id IN (SELECT id FROM setting_draft_checkpoints WHERE owner_id=$1 AND draft_id=$2 AND name='' ORDER BY created_at DESC,id DESC OFFSET 20)`, user, id)
			if e != nil {
				return e
			}
			plain, _ := json.Marshal(m.Body)
			env, e := k.Encrypt(plain, privatecontent.Binding(user, "draft", id, current.Version+1))
			if e != nil {
				return e
			}
			out, e = scanDraft(tx.QueryRow(ctx, `UPDATE setting_drafts SET version=version+1,title=$3,source_envelope=$4,updated_at=now() WHERE id=$1 AND owner_id=$2 RETURNING `+draftCols, id, user, draftTitle(m.Body), jsonParam(env)))
			if e != nil {
				return e
			}
		}
		if e := putReceipt(ctx, tx, user, resource, m.MutationID, hash, out); e != nil {
			return e
		}
		return event(ctx, tx, user, "setting_draft", out.ID, false, out)
	})
	return out, e
}
func (s *Store) DeleteSettingDraft(ctx context.Context, user, id, mutation string, version int64) (DraftSummary, error) {
	var out DraftSummary
	hash := content.Hash([]any{"delete", id, version})
	e := s.write(ctx, user, func(tx pgx.Tx) error {
		if found, e := receipt(ctx, tx, user, id, mutation, hash, &out); e != nil || found {
			return e
		}
		current, e := scanDraft(tx.QueryRow(ctx, `SELECT `+draftCols+` FROM setting_drafts WHERE id=$1 AND owner_id=$2 AND deleted_at IS NULL FOR UPDATE`, id, user))
		if e != nil {
			return e
		}
		if current.Version != version {
			return ErrPrecondition
		}
		out, e = scanDraft(tx.QueryRow(ctx, `UPDATE setting_drafts SET version=version+1,deleted_at=now(),updated_at=now() WHERE id=$1 AND owner_id=$2 RETURNING `+draftCols, id, user))
		if e != nil {
			return e
		}
		if e = putReceipt(ctx, tx, user, id, mutation, hash, out); e != nil {
			return e
		}
		return event(ctx, tx, user, "setting_draft", id, true, out)
	})
	return out, e
}

type DraftCheckpoint struct {
	ID        string    `json:"id"`
	Version   int64     `json:"version"`
	Name      string    `json:"name"`
	CreatedAt time.Time `json:"created_at"`
}

func (s *Store) DraftCheckpoints(ctx context.Context, user, id string) ([]DraftCheckpoint, error) {
	if _, e := scanDraft(s.Pool.QueryRow(ctx, `SELECT `+draftCols+` FROM setting_drafts WHERE owner_id=$1 AND id=$2 AND deleted_at IS NULL`, user, id)); e != nil {
		return nil, e
	}
	rows, e := s.Pool.Query(ctx, `SELECT id::text,draft_version,name,created_at FROM setting_draft_checkpoints WHERE owner_id=$1 AND draft_id=$2 ORDER BY created_at DESC,id DESC LIMIT 100`, user, id)
	if e != nil {
		return nil, e
	}
	defer rows.Close()
	out := []DraftCheckpoint{}
	for rows.Next() {
		var c DraftCheckpoint
		if e = rows.Scan(&c.ID, &c.Version, &c.Name, &c.CreatedAt); e != nil {
			return nil, e
		}
		out = append(out, c)
	}
	return out, rows.Err()
}
func (s *Store) DraftCheckpoint(ctx context.Context, k *privatecontent.Keyring, user, id, checkpoint string) (content.DraftBody, error) {
	var version int64
	var env privatecontent.Envelope
	var out content.DraftBody
	e := s.Pool.QueryRow(ctx, `SELECT c.draft_version,c.source_envelope FROM setting_draft_checkpoints c JOIN setting_drafts d ON d.id=c.draft_id AND d.owner_id=c.owner_id WHERE c.owner_id=$1 AND c.draft_id=$2 AND c.id=$3 AND d.deleted_at IS NULL`, user, id, checkpoint).Scan(&version, &env)
	if e != nil {
		return out, classify(e)
	}
	b, e := k.Decrypt(env, privatecontent.Binding(user, "draft", id, version))
	if e != nil {
		return out, e
	}
	e = json.Unmarshal(b, &out)
	return out, e
}
func ETag(version int64) string { return fmt.Sprintf(`"%d"`, version) }
