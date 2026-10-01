package store

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	jsonpatch "github.com/evanphx/json-patch/v5"
	"github.com/jackc/pgx/v5"
	"unicode/utf8"
)

type ValidationError struct{ Message string }

func (e ValidationError) Error() string { return e.Message }
func invalid(message string) error      { return ValidationError{message} }
func merge(current, patch map[string]any) (map[string]any, error) {
	a, e := json.Marshal(current)
	if e != nil {
		return nil, e
	}
	b, e := json.Marshal(patch)
	if e != nil {
		return nil, e
	}
	data, e := jsonpatch.MergePatch(a, b)
	if e != nil {
		return nil, e
	}
	if len(data) > 64*1024 {
		return nil, invalid("document exceeds 64 KiB")
	}
	var out map[string]any
	e = json.Unmarshal(data, &out)
	if out == nil && e == nil {
		e = invalid("document must be an object")
	}
	return out, e
}
func validateProfile(value map[string]any, author bool) error {
	nameKey := "display_name"
	if author {
		nameKey = "name"
	}
	for key, max := range map[string]int{nameKey: 48, "bio": 500, "avatar": 200} {
		if v, ok := value[key]; ok {
			t, ok := v.(string)
			if !ok || utf8.RuneCountInString(t) > max {
				return invalid("invalid " + key)
			}
			if key == nameKey && t == "" {
				return invalid("name is required")
			}
		}
	}
	return nil
}
func validateSettings(value map[string]any) error {
	if v, ok := value["chat_font_size"]; ok {
		n, ok := v.(float64)
		if !ok || n < 14 || n > 24 {
			return invalid("chat_font_size must be 14..24")
		}
	}
	for _, k := range []string{"theme", "style", "last_character"} {
		if v, ok := value[k]; ok {
			t, ok := v.(string)
			if !ok || len(t) > 120 {
				return invalid("invalid " + k)
			}
		}
	}
	return nil
}
func (s *Store) Document(ctx context.Context, user, kind, character string) (Document, error) {
	out := Document{SchemaVersion: 1, Data: map[string]any{}}
	query := "SELECT data,version FROM settings WHERE user_id=$1"
	args := []any{user}
	if kind == "preference" {
		query = "SELECT data,version FROM preferences WHERE user_id=$1 AND character_id=$2"
		args = append(args, character)
	}
	e := s.Pool.QueryRow(ctx, query, args...).Scan(&out.Data, &out.Version)
	if errors.Is(e, pgx.ErrNoRows) {
		return out, nil
	}
	return out, e
}
func (s *Store) PatchDocument(ctx context.Context, user, kind, character string, expected int64, patch map[string]any, reset ...string) (Document, error) {
	var out Document
	e := s.write(ctx, user, func(tx pgx.Tx) error {
		table := "settings"
		where := "user_id=$1"
		args := []any{user}
		resource := "settings"
		if kind == "preference" {
			if e := checkConversationReset(ctx, tx, user, character, reset); e != nil {
				return e
			}
			if e := accessible(ctx, tx, user, character); e != nil {
				return e
			}
			table = "preferences"
			where += " AND character_id=$2"
			args = append(args, character)
			resource = character
		}
		current := map[string]any{}
		var version int64
		e := tx.QueryRow(ctx, "SELECT data,version FROM "+table+" WHERE "+where, args...).Scan(&current, &version)
		if e != nil && !errors.Is(e, pgx.ErrNoRows) {
			return e
		}
		if version != expected {
			return ErrConflict
		}
		next, e := merge(current, patch)
		if e != nil {
			return e
		}
		if kind == "settings" {
			if e = validateSettings(next); e != nil {
				return e
			}
		}
		out = Document{1, version + 1, next}
		if kind == "settings" {
			_, e = tx.Exec(ctx, `INSERT INTO settings(user_id,data,version) VALUES($1,$2,$3) ON CONFLICT(user_id) DO UPDATE SET data=$2,version=$3`, user, next, out.Version)
		} else {
			_, e = tx.Exec(ctx, `INSERT INTO preferences(user_id,character_id,data,version) VALUES($1,$2,$3,$4) ON CONFLICT(user_id,character_id) DO UPDATE SET data=$3,version=$4`, user, character, next, out.Version)
		}
		if e != nil {
			return e
		}
		return event(ctx, tx, user, kind, resource, false, out)
	})
	return out, e
}

type Author struct {
	ID        string         `json:"id"`
	Version   int64          `json:"version"`
	Data      map[string]any `json:"data"`
	Followers int64          `json:"followers"`
}

func (s *Store) Author(ctx context.Context, id string) (Author, error) {
	var a Author
	e := s.Pool.QueryRow(ctx, `SELECT id,version,data,(SELECT count(*) FROM follows WHERE author_id=authors.id) FROM authors WHERE id=$1`, id).Scan(&a.ID, &a.Version, &a.Data, &a.Followers)
	return a, classify(e)
}
func (s *Store) MyAuthor(ctx context.Context, user string) (Author, error) {
	var id string
	if e := s.Pool.QueryRow(ctx, `SELECT id FROM authors WHERE user_id=$1`, user).Scan(&id); e != nil {
		return Author{}, classify(e)
	}
	return s.Author(ctx, id)
}
func (s *Store) PatchAuthor(ctx context.Context, user string, expected int64, patch map[string]any) (Author, error) {
	var out Author
	e := s.write(ctx, user, func(tx pgx.Tx) error {
		if e := tx.QueryRow(ctx, `SELECT id,version,data FROM authors WHERE user_id=$1`, user).Scan(&out.ID, &out.Version, &out.Data); e != nil {
			return e
		}
		if out.Version != expected {
			return ErrConflict
		}
		next, e := merge(out.Data, patch)
		if e != nil {
			return e
		}
		if e = validateProfile(next, true); e != nil {
			return e
		}
		out.Data = next
		out.Version++
		if _, e = tx.Exec(ctx, `UPDATE authors SET data=$2,version=$3,updated_at=now() WHERE user_id=$1`, user, next, out.Version); e != nil {
			return e
		}
		return event(ctx, tx, user, "author", out.ID, false, out)
	})
	return out, e
}

type Relation struct {
	ID string `json:"id"`
}

func (s *Store) Relations(ctx context.Context, user, kind, after string, limit int) (Page[Relation], error) {
	table, col := "subscriptions", "character_id"
	if kind == "follow" {
		table, col = "follows", "author_id"
	}
	out := Page[Relation]{Items: []Relation{}}
	rows, e := s.Pool.Query(ctx, fmt.Sprintf("SELECT %s FROM %s WHERE user_id=$1 AND %s>$2 ORDER BY %s LIMIT $3", col, table, col, col), user, after, limit+1)
	if e != nil {
		return out, e
	}
	defer rows.Close()
	for rows.Next() {
		var r Relation
		if e = rows.Scan(&r.ID); e != nil {
			return out, e
		}
		out.Items = append(out.Items, r)
	}
	if len(out.Items) > limit {
		out.Items = out.Items[:limit]
		out.Next = out.Items[limit-1].ID
	}
	return out, rows.Err()
}
func (s *Store) SetRelation(ctx context.Context, user, kind, id string, on bool) error {
	return s.write(ctx, user, func(tx pgx.Tx) error {
		table, col := "subscriptions", "character_id"
		if kind == "follow" {
			table, col = "follows", "author_id"
			if on {
				var own bool
				if e := tx.QueryRow(ctx, "SELECT COALESCE(user_id=$2,false) FROM authors WHERE id=$1", id, user).Scan(&own); e != nil {
					return e
				}
				if own {
					return ErrForbidden
				}
			}
		} else if on {
			if e := accessible(ctx, tx, user, id); e != nil {
				return e
			}
		}
		q := fmt.Sprintf("DELETE FROM %s WHERE user_id=$1 AND %s=$2", table, col)
		if on {
			q = fmt.Sprintf("INSERT INTO %s(user_id,%s) VALUES($1,$2) ON CONFLICT DO NOTHING", table, col)
		}
		result, e := tx.Exec(ctx, q, user, id)
		if e != nil {
			return e
		}
		if result.RowsAffected() == 0 {
			return nil
		}
		return event(ctx, tx, user, kind, id, !on, Relation{id})
	})
}
