package store

import (
	"context"
	"encoding/json"
	"github.com/gukaifeng/starrynight-server/internal/compatibility"
	"github.com/gukaifeng/starrynight-server/internal/content"
	"github.com/gukaifeng/starrynight-server/internal/privatecontent"
	"github.com/jackc/pgx/v5"
	"strings"
	"time"
)

type PublicSetting struct {
	ID              string                              `json:"id"`
	Revision        int64                               `json:"revision"`
	AuthorID        string                              `json:"author_id"`
	Profile         content.SettingPublicProfile        `json:"public_profile"`
	Requirements    content.Compatibility               `json:"requirements"`
	Language        string                              `json:"language"`
	Goal            string                              `json:"goal"`
	ParameterSchema map[string]content.SettingParameter `json:"parameters"`
	Visibility      string                              `json:"visibility"`
	Availability    string                              `json:"availability"`
	AccessEpoch     int64                               `json:"access_epoch"`
	Owned           bool                                `json:"owned"`
	Favorited       bool                                `json:"favorited"`
}
type Submission struct {
	ID         string                `json:"id"`
	SettingID  string                `json:"setting_id"`
	Revision   int64                 `json:"revision"`
	Visibility string                `json:"target_visibility"`
	Validation string                `json:"validation_status"`
	Review     string                `json:"review_status"`
	Report     content.SettingReport `json:"report"`
	Version    int64                 `json:"version"`
	CreatedAt  time.Time             `json:"created_at"`
}

const submissionCols = `id::text,setting_id::text,revision,target_visibility,validation_status,review_status,report,version,created_at`

func scanSubmission(row pgx.Row) (Submission, error) {
	var out Submission
	e := row.Scan(&out.ID, &out.SettingID, &out.Revision, &out.Visibility, &out.Validation, &out.Review, &out.Report, &out.Version, &out.CreatedAt)
	return out, classify(e)
}
func (s *Store) SubmitSetting(ctx context.Context, k *privatecontent.Keyring, user, draft, mutation, visibility string, version int64) (Submission, error) {
	var out Submission
	if visibility != "private" && visibility != "public" {
		return out, ValidationError{"invalid visibility"}
	}
	hash := content.Hash([]any{"submit", draft, version, visibility})
	resource := "submit:" + draft
	e := s.write(ctx, user, func(tx pgx.Tx) error {
		if found, e := receipt(ctx, tx, user, resource, mutation, hash, &out); e != nil || found {
			return e
		}
		d, e := scanDraft(tx.QueryRow(ctx, `SELECT `+draftCols+` FROM setting_drafts WHERE owner_id=$1 AND id=$2 AND deleted_at IS NULL FOR UPDATE`, user, draft))
		if e != nil {
			return e
		}
		if d.Version != version {
			return ErrPrecondition
		}
		var envelope privatecontent.Envelope
		if e = tx.QueryRow(ctx, `SELECT source_envelope FROM setting_drafts WHERE id=$1 AND owner_id=$2`, draft, user).Scan(&envelope); e != nil {
			return e
		}
		plain, e := k.Decrypt(envelope, privatecontent.Binding(user, "draft", draft, d.Version))
		if e != nil {
			return e
		}
		var body content.DraftBody
		if e = json.Unmarshal(plain, &body); e != nil {
			return e
		}
		setting := d.TemplateID
		var parentVersion int64
		if setting == "" {
			setting = NewID()
			var author string
			if e = tx.QueryRow(ctx, `SELECT id FROM authors WHERE user_id=$1`, user).Scan(&author); e != nil {
				return e
			}
			if _, e = tx.Exec(ctx, `INSERT INTO setting_templates(id,owner_id,author_id) VALUES($1,$2,$3)`, setting, user, author); e != nil {
				return e
			}
			if _, e = tx.Exec(ctx, `UPDATE setting_drafts SET template_id=$1 WHERE id=$2 AND owner_id=$3`, setting, draft, user); e != nil {
				return e
			}
		}
		if e = tx.QueryRow(ctx, `UPDATE setting_templates SET version=version+1,updated_at=now() WHERE id=$1 AND owner_id=$2 RETURNING version`, setting, user).Scan(&parentVersion); e != nil {
			return e
		}
		var revision int64
		if e = tx.QueryRow(ctx, `SELECT COALESCE(max(revision),0)+1 FROM setting_revisions WHERE setting_id=$1`, setting).Scan(&revision); e != nil {
			return e
		}
		doc := body.Document
		pub := PublicSetting{ID: setting, Revision: revision, Profile: doc.PublicProfile, Requirements: doc.Compatibility, Language: doc.Runtime.LanguagePolicy.Default, Goal: doc.Runtime.Goals.Primary, ParameterSchema: doc.ParameterSchema}
		if _, e = tx.Exec(ctx, `INSERT INTO setting_revisions(setting_id,revision,public_document,public_requirements,source_hash,compiler_contract) VALUES($1,$2,$3,$4,$5,$6)`, setting, revision, jsonParam(pub), jsonParam(doc.Compatibility), content.Hash(doc), content.Contract); e != nil {
			return e
		}
		encoded, _ := json.Marshal(doc)
		env, e := k.Encrypt(encoded, privatecontent.Binding(user, "revision", setting, revision))
		if e != nil {
			return e
		}
		if _, e = tx.Exec(ctx, `INSERT INTO setting_revision_secrets(setting_id,revision,source_envelope) VALUES($1,$2,$3)`, setting, revision, jsonParam(env)); e != nil {
			return e
		}
		review := "not_required"
		if visibility == "public" {
			review = "pending"
		}
		id := NewID()
		out, e = scanSubmission(tx.QueryRow(ctx, `INSERT INTO setting_submissions(id,owner_id,setting_id,revision,target_visibility,expected_template_version,review_status) VALUES($1,$2,$3,$4,$5,$6,$7) RETURNING `+submissionCols, id, user, setting, revision, visibility, parentVersion, review))
		if e != nil {
			return e
		}
		job := NewID()
		if _, e = tx.Exec(ctx, `INSERT INTO content_jobs(id,kind,resource_id,owner_id,payload) VALUES($1,'validate_setting',$2,$3,$4)`, job, id, user, map[string]any{"submission_id": id}); e != nil {
			return e
		}
		if _, e = tx.Exec(ctx, `INSERT INTO content_outbox(job_id) VALUES($1)`, job); e != nil {
			return e
		}
		if e = putReceipt(ctx, tx, user, resource, mutation, hash, out); e != nil {
			return e
		}
		return event(ctx, tx, user, "setting_submission", id, false, out)
	})
	return out, e
}
func (s *Store) SettingSubmissions(ctx context.Context, user, after string, limit int) (Page[Submission], error) {
	p := Page[Submission]{Items: []Submission{}}
	rows, e := s.Pool.Query(ctx, `SELECT `+submissionCols+` FROM setting_submissions WHERE owner_id=$1 AND id::text>$2 ORDER BY id LIMIT $3`, user, after, limit+1)
	if e != nil {
		return p, e
	}
	defer rows.Close()
	for rows.Next() {
		v, e := scanSubmission(rows)
		if e != nil {
			return p, e
		}
		p.Items = append(p.Items, v)
	}
	if len(p.Items) > limit {
		p.Items = p.Items[:limit]
		p.Next = p.Items[limit-1].ID
	}
	return p, rows.Err()
}
func (s *Store) SettingSource(ctx context.Context, k *privatecontent.Keyring, user, id string, revision int64) (content.SettingDocument, error) {
	var out content.SettingDocument
	var env privatecontent.Envelope
	e := s.Pool.QueryRow(ctx, `SELECT p.source_envelope FROM setting_revision_secrets p JOIN setting_templates t ON t.id=p.setting_id WHERE t.owner_id=$1 AND p.setting_id=$2 AND p.revision=$3`, user, id, revision).Scan(&env)
	if e != nil {
		return out, classify(e)
	}
	plain, e := k.Decrypt(env, privatecontent.Binding(user, "revision", id, revision))
	if e != nil {
		return out, e
	}
	e = json.Unmarshal(plain, &out)
	return out, e
}
func scanPublicSetting(row pgx.Row) (PublicSetting, error) {
	var out PublicSetting
	var raw []byte
	e := row.Scan(&raw, &out.AuthorID, &out.Visibility, &out.Availability, &out.AccessEpoch, &out.Owned, &out.Favorited)
	if e != nil {
		return out, classify(e)
	}
	var stored PublicSetting
	if e = json.Unmarshal(raw, &stored); e != nil {
		return out, e
	}
	stored.AuthorID = out.AuthorID
	stored.Visibility = out.Visibility
	stored.Availability = out.Availability
	stored.AccessEpoch = out.AccessEpoch
	stored.Owned = out.Owned
	stored.Favorited = out.Favorited
	return stored, nil
}

const publicSettingCols = `r.public_document,t.author_id,t.visibility,t.availability,t.access_epoch,COALESCE(t.owner_id=NULLIF($1,'')::uuid,false),EXISTS(SELECT 1 FROM setting_favorites f WHERE f.user_id=NULLIF($1,'')::uuid AND f.setting_id=t.id)`

func (s *Store) PublicSetting(ctx context.Context, user, id string, revision int64, continuing bool) (PublicSetting, error) {
	return publicSetting(ctx,s.Pool,user,id,revision,continuing)
}
func publicSetting(ctx context.Context,q queryRow,user,id string,revision int64,continuing bool)(PublicSetting,error){return scanPublicSetting(q.QueryRow(ctx,`SELECT `+publicSettingCols+` FROM setting_templates t JOIN setting_revisions r ON r.setting_id=t.id AND r.revision=COALESCE(NULLIF($3,0),t.current_revision) WHERE t.id=$2 AND (t.owner_id=NULLIF($1,'')::uuid OR (t.visibility='public' AND (t.availability='active' OR ($4 AND t.availability='withdrawn'))))`,user,id,revision,continuing))}
func (s *Store) SettingsCatalog(ctx context.Context, user, query, author, after string, mine, favorites bool, limit int) (Page[PublicSetting], error) {
	p := Page[PublicSetting]{Items: []PublicSetting{}}
	search := "%" + strings.NewReplacer(`\`, `\\`, "%", `\%`, "_", `\_`).Replace(query) + "%"
	rows, e := s.Pool.Query(ctx, `SELECT `+publicSettingCols+` FROM setting_templates t JOIN setting_revisions r ON r.setting_id=t.id AND r.revision=t.current_revision WHERE t.id::text>$2 AND (($3 AND t.owner_id=NULLIF($1,'')::uuid) OR (NOT $3 AND t.visibility='public' AND t.availability='active')) AND ($4='' OR t.author_id=$4) AND ($5='' OR r.public_document->'public_profile'->>'title' ILIKE $6 OR r.public_document->'public_profile'->>'synopsis' ILIKE $6) AND (NOT $7 OR EXISTS(SELECT 1 FROM setting_favorites f WHERE f.setting_id=t.id AND f.user_id=NULLIF($1,'')::uuid)) ORDER BY t.id LIMIT $8`, user, after, mine, author, query, search, favorites, limit+1)
	if e != nil {
		return p, e
	}
	defer rows.Close()
	for rows.Next() {
		v, e := scanPublicSetting(rows)
		if e != nil {
			return p, e
		}
		p.Items = append(p.Items, v)
	}
	if len(p.Items) > limit {
		p.Items = p.Items[:limit]
		p.Next = p.Items[limit-1].ID
	}
	return p, rows.Err()
}
func (s *Store) FavoriteSetting(ctx context.Context, user, id string, on bool) error {
	return s.write(ctx, user, func(tx pgx.Tx) error {
		var allowed bool
		if e := tx.QueryRow(ctx, `SELECT true FROM setting_templates WHERE id=$1 AND (owner_id=$2 OR (visibility='public' AND availability='active'))`, id, user).Scan(&allowed); e != nil {
			return e
		}
		var e error
		if on {
			_, e = tx.Exec(ctx, `INSERT INTO setting_favorites(user_id,setting_id) VALUES($1,$2) ON CONFLICT DO NOTHING`, user, id)
		} else {
			_, e = tx.Exec(ctx, `DELETE FROM setting_favorites WHERE user_id=$1 AND setting_id=$2`, user, id)
		}
		if e != nil {
			return e
		}
		return event(ctx, tx, user, "setting_favorite", id, !on, map[string]any{"id": id, "favorited": on})
	})
}
func (s *Store) SettingAccess(ctx context.Context, user, id, action, mutation string, version int64) (Document, error) {
	var out Document
	hash := content.Hash([]any{action, id, version})
	e := s.write(ctx, user, func(tx pgx.Tx) error {
		if found, e := receipt(ctx, tx, user, "access:"+id, mutation, hash, &out); e != nil || found {
			return e
		}
		var v, epoch int64
		var visibility string
		if e := tx.QueryRow(ctx, `SELECT version,access_epoch,visibility FROM setting_templates WHERE id=$1 AND owner_id=$2 FOR UPDATE`, id, user).Scan(&v, &epoch, &visibility); e != nil {
			return e
		}
		if v != version {
			return ErrPrecondition
		}
		availability := "withdrawn"
		switch action {
		case "withdraw":
		case "make-private":
			visibility = "private"
			availability = "active"
			epoch++
		case "revoke":
			availability = "revoked"
			epoch++
		default:
			return ValidationError{"unknown access action"}
		}
		if _, e := tx.Exec(ctx, `UPDATE setting_templates SET visibility=$3,availability=$4,access_epoch=$5,version=version+1,updated_at=now() WHERE owner_id=$1 AND id=$2`, user, id, visibility, availability, epoch); e != nil {
			return e
		}
		if _, e := tx.Exec(ctx, `DELETE FROM setting_public_projection WHERE setting_id=$1`, id); e != nil {
			return e
		}
		// Invalidate pending publication. The parent version changes, so an older
		// validation/review job cannot reopen content after withdrawal.
		if _, e := tx.Exec(ctx, `INSERT INTO content_audit(actor_id,action,resource_id,result) VALUES($1,$2,$3,'allowed')`, user, action, id); e != nil {
			return e
		}
		out = Document{SchemaVersion: 1, Version: v + 1, Data: map[string]any{"id": id, "visibility": visibility, "availability": availability, "access_epoch": epoch}}
		if e := putReceipt(ctx, tx, user, "access:"+id, mutation, hash, out); e != nil {
			return e
		}
		return event(ctx, tx, user, "setting_access", id, false, out)
	})
	return out, e
}
func (s *Store) ValidateSettingSource(ctx context.Context, d content.SettingDocument) (content.SettingReport, error) {
	r := content.Validate(d)
	add := func(path, code, message string) {
		r.Valid = false
		r.Issues = append(r.Issues, content.SettingIssue{Path: path, Code: code, Message: message})
	}
	if e := compatibility.Validate(d.Compatibility.Required); e != nil {
		add("/compatibility/required", "invalid_rule", e.Error())
	}
	for _, rule := range d.Compatibility.Preferred {
		if e := compatibility.Validate(&rule); e != nil {
			add("/compatibility/preferred", "invalid_rule", e.Error())
		}
	}
	// A bounded estimate rejects oversized static source before provider work.
	// This is conservative (UTF-8 bytes), not a false claim of exact tokenization.
	bytes := 0
	for _, b := range d.Runtime.Blocks {
		bytes += len(b.Text)
	}
	scene, _ := json.Marshal(d.Runtime.Scene)
	bytes += len(scene)
	if bytes > 24000 {
		add("/runtime", "prompt_budget", "static source exceeds the configured conservative budget")
	}
	for _, ref := range d.MediaRefs {
		if strings.Contains(ref, "://") || len(ref) > 160 {
			add("/media_refs", "invalid_ref", "use an authorized asset reference, not a URL")
		}
	}
	rows, e := s.Pool.Query(ctx, `SELECT r.public_core FROM character_revisions r JOIN characters c ON c.id=r.character_id WHERE c.visibility='public' AND NOT c.deleted AND r.revision=(SELECT max(revision) FROM character_revisions WHERE character_id=c.id)`)
	if e != nil {
		return r, e
	}
	defer rows.Close()
	matches := 0
	for rows.Next() {
		var fields map[string]any
		if e = rows.Scan(&fields); e != nil {
			return r, e
		}
		v, e := compatibility.Evaluate(d.Compatibility.Required, fields)
		if e == nil && v.Result == compatibility.Match {
			matches++
		}
	}
	if e = rows.Err(); e != nil {
		return r, e
	}
	if matches == 0 {
		add("/compatibility", "no_compatible_character", "no published character is known to satisfy these requirements")
	}
	return r, nil
}
func (s *Store) ValidateSubmission(ctx context.Context, k *privatecontent.Keyring, id string) error {
	var user, setting string
	var revision int64
	e := s.Pool.QueryRow(ctx, `SELECT owner_id::text,setting_id::text,revision FROM setting_submissions WHERE id=$1`, id).Scan(&user, &setting, &revision)
	if e != nil {
		return classify(e)
	}
	d, e := s.SettingSource(ctx, k, user, setting, revision)
	if e != nil {
		return e
	}
	report, e := s.ValidateSettingSource(ctx, d)
	if e != nil {
		return e
	}
	return s.write(ctx, user, func(tx pgx.Tx) error {
		v, e := scanSubmission(tx.QueryRow(ctx, `SELECT `+submissionCols+` FROM setting_submissions WHERE id=$1 AND owner_id=$2 FOR UPDATE`, id, user))
		if e != nil {
			return e
		}
		if v.Validation == "passed" || v.Validation == "failed" {
			return nil
		}
		status := "passed"
		if !report.Valid {
			status = "failed"
		}
		if _, e = tx.Exec(ctx, `UPDATE setting_submissions SET validation_status=$2,report=$3,version=version+1,updated_at=now() WHERE id=$1`, id, status, jsonParam(report)); e != nil {
			return e
		}
		if report.Valid && v.Visibility == "private" {
			// Do not poison the transaction by attempting a stale release. The
			// validation remains useful, but activation requires the captured head.
			var current, expected int64
			if e = tx.QueryRow(ctx, `SELECT t.version,p.expected_template_version FROM setting_templates t JOIN setting_submissions p ON p.setting_id=t.id WHERE p.id=$1 FOR UPDATE OF t`, id).Scan(&current, &expected); e != nil {
				return e
			}
			if current == expected {
				if e = publishSetting(ctx, tx, id, "private", "validator", ""); e != nil {
					return e
				}
			}
		}
		return event(ctx, tx, user, "setting_submission", id, false, map[string]any{"id": id, "validation_status": status})
	})
}
func publishSetting(ctx context.Context, tx pgx.Tx, submission, visibility, actor, reason string) error {
	var setting string
	var revision, parentVersion, expected int64
	var raw []byte
	var author, validation, review string
	e := tx.QueryRow(ctx, `SELECT p.setting_id::text,p.revision,p.expected_template_version,t.version,r.public_document,t.author_id,p.validation_status,p.review_status FROM setting_submissions p JOIN setting_templates t ON t.id=p.setting_id JOIN setting_revisions r ON r.setting_id=p.setting_id AND r.revision=p.revision WHERE p.id=$1 FOR UPDATE OF p,t`, submission).Scan(&setting, &revision, &expected, &parentVersion, &raw, &author, &validation, &review)
	if e != nil {
		return e
	}
	if parentVersion != expected {
		return ErrPrecondition
	}
	if validation != "passed" || (visibility == "public" && review != "approved") {
		return ErrForbidden
	}
	var pub PublicSetting
	if e = json.Unmarshal(raw, &pub); e != nil {
		return e
	}
	if _, e = tx.Exec(ctx, `INSERT INTO setting_releases(id,setting_id,revision,submission_id,validation_contract,review_receipt) VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT(setting_id,revision) DO NOTHING`, NewID(), setting, revision, submission, content.Contract, map[string]any{"actor": actor, "reason": reason, "review": review}); e != nil {
		return e
	}
	if _, e = tx.Exec(ctx, `UPDATE setting_templates SET current_revision=$2,visibility=$3,availability='active',version=version+1,updated_at=now() WHERE id=$1`, setting, revision, visibility); e != nil {
		return e
	}
	if visibility == "public" {
		_, e = tx.Exec(ctx, `INSERT INTO setting_public_projection(setting_id,revision,author_id,title,synopsis,language,data) VALUES($1,$2,$3,$4,$5,$6,$7) ON CONFLICT(setting_id) DO UPDATE SET revision=excluded.revision,title=excluded.title,synopsis=excluded.synopsis,language=excluded.language,data=excluded.data,updated_at=now()`, setting, revision, author, pub.Profile.Title, pub.Profile.Synopsis, pub.Language, jsonParam(pub))
	} else {
		_, e = tx.Exec(ctx, `DELETE FROM setting_public_projection WHERE setting_id=$1`, setting)
	}
	if e != nil {
		return e
	}
	_, e = tx.Exec(ctx, `INSERT INTO content_audit(actor_id,action,resource_id,revision,reason,result) VALUES($1,'release',$2,$3,$4,'allowed')`, actor, setting, revision, reason)
	return e
}
func (s *Store) ReviewSetting(ctx context.Context, actor, submission, decision, reason string, expected int64) error {
	if decision != "approve" && decision != "reject" {
		return ValidationError{"choose approve or reject"}
	}
	if len(strings.TrimSpace(reason)) < 3 {
		return ValidationError{"review reason is required"}
	}
	tx, e := s.Pool.Begin(ctx)
	if e != nil {
		return e
	}
	defer tx.Rollback(ctx)
	v, e := scanSubmission(tx.QueryRow(ctx, `SELECT `+submissionCols+` FROM setting_submissions WHERE id=$1 FOR UPDATE`, submission))
	if e != nil {
		return e
	}
	if v.Version != expected {
		return ErrPrecondition
	}
	if v.Visibility != "public" || v.Review != "pending" || v.Validation != "passed" {
		return ErrForbidden
	}
	state := "approved"
	if decision == "reject" {
		state = "rejected"
	}
	if _, e = tx.Exec(ctx, `UPDATE setting_submissions SET review_status=$2,version=version+1,updated_at=now() WHERE id=$1`, submission, state); e != nil {
		return e
	}
	if state == "approved" {
		if e = publishSetting(ctx, tx, submission, "public", actor, reason); e != nil {
			return e
		}
	}
	if _, e = tx.Exec(ctx, `INSERT INTO content_audit(actor_id,action,resource_id,revision,reason,result) VALUES($1,$2,$3,$4,$5,'allowed')`, actor, "review_"+decision, v.SettingID, v.Revision, reason); e != nil {
		return e
	}
	return tx.Commit(ctx)
}
func (s *Store) CopySettingRevision(ctx context.Context, k *privatecontent.Keyring, user, id, clientID, mutation string, revision int64) (DraftSummary, error) {
	doc, e := s.SettingSource(ctx, k, user, id, revision)
	if e != nil {
		return DraftSummary{}, e
	}
	return s.SaveSettingDraft(ctx, k, user, "", DraftMutation{MutationID: mutation, ClientDraftID: clientID, Body: content.DraftBody{RawFields: map[string]json.RawMessage{}, Document: doc, FieldErrors: map[string]string{}, EditorState: map[string]json.RawMessage{}}})
}
func (s *Store) SettingVersion(ctx context.Context, user, id string) (int64, error) {
	var v int64
	e := s.Pool.QueryRow(ctx, `SELECT version FROM setting_templates WHERE id=$1 AND owner_id=$2`, id, user).Scan(&v)
	return v, classify(e)
}
