package store

import (
	"context"
	"encoding/json"
	"github.com/gukaifeng/starrynight-server/internal/compatibility"
	"github.com/gukaifeng/starrynight-server/internal/content"
	"github.com/jackc/pgx/v5"
	"strconv"
	"time"
)

type ConversationInstance struct {
	ID                string         `json:"id"`
	CharacterID       string         `json:"character_id"`
	CharacterRevision int64          `json:"character_revision"`
	SettingID         string         `json:"setting_id"`
	SettingRevision   int64          `json:"setting_revision"`
	Parameters        map[string]any `json:"parameters"`
	Snapshot          map[string]any `json:"binding_snapshot"`
	ConfigVersion     int64          `json:"config_version"`
	ResetEpoch        int64          `json:"reset_epoch"`
	Version           int64          `json:"version"`
	Hidden            bool           `json:"hidden"`
	Legacy            bool           `json:"legacy"`
	UpdatedAt         time.Time      `json:"updated_at"`
}

const instanceCols = `id::text,character_id,character_revision,setting_id::text,setting_revision,parameters,binding_snapshot,config_version,reset_epoch,version,hidden,legacy,updated_at`

func scanInstance(row pgx.Row) (ConversationInstance, error) {
	var v ConversationInstance
	e := row.Scan(&v.ID, &v.CharacterID, &v.CharacterRevision, &v.SettingID, &v.SettingRevision, &v.Parameters, &v.Snapshot, &v.ConfigVersion, &v.ResetEpoch, &v.Version, &v.Hidden, &v.Legacy, &v.UpdatedAt)
	return v, classify(e)
}
func (s *Store) ConversationInstance(ctx context.Context, user, id string) (ConversationInstance, error) {
	return scanInstance(s.Pool.QueryRow(ctx, `SELECT `+instanceCols+` FROM conversation_instances WHERE user_id=$1 AND id=$2`, user, id))
}
func (s *Store) ConversationInstances(ctx context.Context, user, character, after string, includeHidden bool, limit int) (Page[ConversationInstance], error) {
	p := Page[ConversationInstance]{Items: []ConversationInstance{}}
	rows, e := s.Pool.Query(ctx, `SELECT `+instanceCols+` FROM conversation_instances WHERE user_id=$1 AND ($2='' OR character_id=$2) AND id::text>$3 AND ($4 OR NOT hidden) ORDER BY id LIMIT $5`, user, character, after, includeHidden, limit+1)
	if e != nil {
		return p, e
	}
	defer rows.Close()
	for rows.Next() {
		v, e := scanInstance(rows)
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

type ResolvedPair struct {
	Character     content.CharacterCore    `json:"character"`
	Setting       PublicSetting            `json:"setting"`
	Parameters    map[string]any           `json:"parameters"`
	Compatibility compatibility.Evaluation `json:"compatibility"`
	Language      string                   `json:"language"`
	CanStart      bool                     `json:"can_start"`
}

func (s *Store) CharacterCore(ctx context.Context, user, id string, revision int64) (content.CharacterCore, error) {
	return characterCore(ctx, s.Pool, user, id, revision)
}
func characterCore(ctx context.Context, q queryRow, user, id string, revision int64) (content.CharacterCore, error) {
	var out content.CharacterCore
	var name string
	var rev int64
	e := q.QueryRow(ctx, `SELECT r.public_core,r.revision,c.name FROM character_revisions r JOIN characters c ON c.id=r.character_id WHERE c.id=$2 AND NOT c.deleted AND (c.visibility IN ('public','unlisted') OR c.owner_id=NULLIF($1,'')::uuid) AND r.revision=COALESCE(NULLIF($3,0),(SELECT max(revision) FROM character_revisions WHERE character_id=c.id))`, user, id, revision).Scan(&out, &rev, &name)
	out.ID = id
	out.Revision = rev
	out.Name = name
	return out, classify(e)
}
func (s *Store) ResolvePair(ctx context.Context, user, character, setting string, charRev, settingRev int64, input map[string]any) (ResolvedPair, error) {
	return resolvePair(ctx, s.Pool, user, character, setting, charRev, settingRev, input)
}
func resolvePair(ctx context.Context, q queryRow, user, character, setting string, charRev, settingRev int64, input map[string]any) (ResolvedPair, error) {
	var out ResolvedPair
	c, e := characterCore(ctx, q, user, character, charRev)
	if e != nil {
		return out, e
	}
	p, e := publicSetting(ctx, q, user, setting, settingRev, false)
	if e != nil {
		return out, e
	}
	if p.Availability != "active" {
		return out, ErrForbidden
	}
	var released bool
	if e = q.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM setting_releases WHERE setting_id=$1 AND revision=$2)`, setting, p.Revision).Scan(&released); e != nil {
		return out, e
	}
	if !released {
		return out, ErrForbidden
	}
	params, e := content.ResolveParameters(p.ParameterSchema, input)
	if e != nil {
		return out, ValidationError{e.Error()}
	}
	raw, _ := json.Marshal(c)
	var fields map[string]any
	_ = json.Unmarshal(raw, &fields)
	v, e := compatibility.Evaluate(p.Requirements.Required, fields)
	if e != nil {
		return out, ValidationError{e.Error()}
	}
	lang := p.Language
	if value, ok := params["language"].(string); ok {
		lang = value
	}
	// Spoken language capability is a fixed contract even when no extra author
	// requirements exist. Height is story metadata only; no camera math here.
	rule := content.Rule{Field: "capabilities.spoken_languages", Op: "contains_all", Value: []string{lang}}
	language, e := compatibility.Evaluate(&rule, fields)
	if e != nil {
		return out, e
	}
	if language.Result != compatibility.Match {
		v.Result = language.Result
		v.Reasons = append(v.Reasons, language.Reasons...)
	}
	out = ResolvedPair{Character: c, Setting: p, Parameters: params, Compatibility: v, Language: lang, CanStart: v.Result == compatibility.Match}
	return out, nil
}

type InstanceCreate struct {
	MutationID        string         `json:"mutation_id"`
	CharacterID       string         `json:"character_id"`
	SettingID         string         `json:"setting_id"`
	CharacterRevision int64          `json:"character_revision,omitempty"`
	SettingRevision   int64          `json:"setting_revision,omitempty"`
	Parameters        map[string]any `json:"parameters"`
}

func (s *Store) CreateConversationInstance(ctx context.Context, user string, in InstanceCreate) (ConversationInstance, error) {
	var out ConversationInstance
	hash := content.Hash(in)
	e := s.write(ctx, user, func(tx pgx.Tx) error {
		if found, e := receipt(ctx, tx, user, "new-instance", in.MutationID, hash, &out); e != nil || found {
			return e
		}
		pair, e := resolvePair(ctx, tx, user, in.CharacterID, in.SettingID, in.CharacterRevision, in.SettingRevision, in.Parameters)
		if e != nil {
			return e
		}
		if !pair.CanStart {
			return ValidationError{"the character does not satisfy this setting's requirements"}
		}
		// Resolve uses immutable revisions. Lock immediate policy until commit so
		// revocation cannot race a new instance acceptance.
		var epoch int64
		var visibility string
		var owner *string
		if e = tx.QueryRow(ctx, `SELECT access_epoch,visibility,owner_id::text FROM setting_templates WHERE id=$1 AND availability='active' FOR SHARE`, in.SettingID).Scan(&epoch, &visibility, &owner); e != nil {
			return e
		}
		if visibility != "public" && (owner == nil || *owner != user) {
			return ErrForbidden
		}
		snapshot := map[string]any{"character_name": pair.Character.Name, "setting_title": pair.Setting.Profile.Title, "language": pair.Language, "access_epoch": epoch, "compiler_contract": content.Contract, "asset_release": pair.Character.AssetRelease}
		out, e = scanInstance(tx.QueryRow(ctx, `INSERT INTO conversation_instances(id,user_id,character_id,character_revision,setting_id,setting_revision,parameters,binding_snapshot) VALUES($1,$2,$3,$4,$5,$6,$7,$8) RETURNING `+instanceCols, NewID(), user, in.CharacterID, pair.Character.Revision, in.SettingID, pair.Setting.Revision, pair.Parameters, snapshot))
		if e != nil {
			return e
		}
		if e = putReceipt(ctx, tx, user, "new-instance", in.MutationID, hash, out); e != nil {
			return e
		}
		return event(ctx, tx, user, "conversation_instance", out.ID, false, out)
	})
	return out, e
}
func (s *Store) HideConversationInstance(ctx context.Context, user, id, mutation string, hidden bool, expected int64) (ConversationInstance, error) {
	var out ConversationInstance
	hash := content.Hash([]any{"hide", hidden, expected})
	e := s.write(ctx, user, func(tx pgx.Tx) error {
		if found, e := receipt(ctx, tx, user, "instance:"+id, mutation, hash, &out); e != nil || found {
			return e
		}
		v, e := scanInstance(tx.QueryRow(ctx, `SELECT `+instanceCols+` FROM conversation_instances WHERE id=$1 AND user_id=$2 FOR UPDATE`, id, user))
		if e != nil {
			return e
		}
		if v.Version != expected {
			return ErrPrecondition
		}
		out, e = scanInstance(tx.QueryRow(ctx, `UPDATE conversation_instances SET hidden=$3,version=version+1,updated_at=now() WHERE id=$1 AND user_id=$2 RETURNING `+instanceCols, id, user, hidden))
		if e != nil {
			return e
		}
		if e = putReceipt(ctx, tx, user, "instance:"+id, mutation, hash, out); e != nil {
			return e
		}
		return event(ctx, tx, user, "conversation_instance", id, false, out)
	})
	return out, e
}
func (s *Store) ResetConversationInstance(ctx context.Context, user, id, mutation string, expected int64) (ConversationInstance, error) {
	var out ConversationInstance
	hash := content.Hash([]any{"reset", expected})
	e := s.write(ctx, user, func(tx pgx.Tx) error {
		if found, e := receipt(ctx, tx, user, "instance:"+id, mutation, hash, &out); e != nil || found {
			return e
		}
		v, e := scanInstance(tx.QueryRow(ctx, `SELECT `+instanceCols+` FROM conversation_instances WHERE user_id=$1 AND id=$2 FOR UPDATE`, user, id))
		if e != nil {
			return e
		}
		if v.Version != expected {
			return ErrPrecondition
		}
		if _, e = tx.Exec(ctx, `UPDATE conversation_turns SET status='cancelled',fence=fence+1,updated_at=now() WHERE user_id=$1 AND conversation_id=$2 AND status IN ('accepted','running')`, user, id); e != nil {
			return e
		}
		for _, table := range []string{"conversation_messages", "conversation_state", "conversation_translations", "prepared_candidates", "opening_receipts", "conversation_turn_events"} {
			if _, e = tx.Exec(ctx, `DELETE FROM `+table+` WHERE user_id=$1 AND conversation_id=$2`, user, id); e != nil {
				return e
			}
		}
		if _, e = tx.Exec(ctx, `UPDATE conversation_turns SET request_data='{}',result='{}',status=CASE WHEN status IN ('accepted','running') THEN 'cancelled' ELSE status END WHERE user_id=$1 AND conversation_id=$2`, user, id); e != nil {
			return e
		}
		out, e = scanInstance(tx.QueryRow(ctx, `UPDATE conversation_instances SET reset_epoch=reset_epoch+1,config_version=config_version+1,version=version+1,next_sequence=1,hidden=false,updated_at=now() WHERE user_id=$1 AND id=$2 RETURNING `+instanceCols, user, id))
		if e != nil {
			return e
		}
		if e = putReceipt(ctx, tx, user, "instance:"+id, mutation, hash, out); e != nil {
			return e
		}
		return event(ctx, tx, user, "conversation_instance", id, false, out)
	})
	return out, e
}

type InstanceMessage struct {
	ID        string         `json:"id"`
	Sequence  int64          `json:"sequence"`
	TurnID    string         `json:"turn_id,omitempty"`
	Role      string         `json:"role"`
	Text      string         `json:"text"`
	Data      map[string]any `json:"data"`
	Delivery  string         `json:"delivery_status"`
	Source    string         `json:"source"`
	CreatedAt time.Time      `json:"created_at"`
}

func (s *Store) InstanceMessages(ctx context.Context, user, id string, after int64, limit int) (Page[InstanceMessage], error) {
	p := Page[InstanceMessage]{Items: []InstanceMessage{}}
	if _, e := s.ConversationInstance(ctx, user, id); e != nil {
		return p, e
	}
	rows, e := s.Pool.Query(ctx, `SELECT id::text,sequence,COALESCE(turn_id::text,''),role,text,data,delivery_status,source,created_at FROM conversation_messages WHERE user_id=$1 AND conversation_id=$2 AND sequence>$3 ORDER BY sequence LIMIT $4`, user, id, after, limit+1)
	if e != nil {
		return p, e
	}
	defer rows.Close()
	for rows.Next() {
		var v InstanceMessage
		if e = rows.Scan(&v.ID, &v.Sequence, &v.TurnID, &v.Role, &v.Text, &v.Data, &v.Delivery, &v.Source, &v.CreatedAt); e != nil {
			return p, e
		}
		p.Items = append(p.Items, v)
	}
	if len(p.Items) > limit {
		p.Items = p.Items[:limit]
		p.Next = strconv.FormatInt(p.Items[limit-1].Sequence, 10)
	}
	return p, rows.Err()
}
