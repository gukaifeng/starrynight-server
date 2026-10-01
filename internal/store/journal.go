package store

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/jackc/pgx/v5"
	"strings"
	"time"
)

type Conversation struct {
	CharacterID string    `json:"character_id"`
	Hidden      bool      `json:"hidden"`
	Pinned      bool      `json:"pinned"`
	Version     int64     `json:"version"`
	UpdatedAt   time.Time `json:"updated_at"`
}
type Message struct {
	ID          string         `json:"id"`
	CharacterID string         `json:"character_id"`
	Sequence    int64          `json:"sequence"`
	Role        string         `json:"role"`
	Text        string         `json:"text"`
	CreatedAt   time.Time      `json:"created_at"`
	Data        map[string]any `json:"data"`
	Version     int64          `json:"version"`
}
type Entry struct {
	ID          string         `json:"id"`
	CharacterID string         `json:"character_id"`
	Kind        string         `json:"kind"`
	Data        map[string]any `json:"data"`
	Version     int64          `json:"version"`
}

const convCols = `character_id,hidden,pinned,version,updated_at`
const messageCols = `id::text,character_id,sequence,role,text,created_at,data,version`

func (s *Store) ClearMessages(ctx context.Context, user, character string) error {
	return s.write(ctx, user, func(tx pgx.Tx) error {
		if _, err := tx.Exec(ctx, `DELETE FROM messages WHERE user_id=$1 AND character_id=$2`, user, character); err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, `DELETE FROM changes WHERE user_id=$1 AND kind='message' AND split_part(resource_id,'/',1)=$2`, user, character); err != nil {
			return err
		}
		// A single ordered event avoids one tombstone per historical message.
		return event(ctx, tx, user, "conversation_clear", character, false, map[string]any{"cleared_at": time.Now().UTC()})
	})
}

func scanConv(r pgx.Row) (Conversation, error) {
	var c Conversation
	e := r.Scan(&c.CharacterID, &c.Hidden, &c.Pinned, &c.Version, &c.UpdatedAt)
	return c, e
}
func scanMessage(r pgx.Row) (Message, error) {
	var m Message
	e := r.Scan(&m.ID, &m.CharacterID, &m.Sequence, &m.Role, &m.Text, &m.CreatedAt, &m.Data, &m.Version)
	return m, e
}
func ensureConversation(ctx context.Context, tx pgx.Tx, user, char string) error {
	if e := accessible(ctx, tx, user, char); e != nil {
		return e
	}
	row, e := scanConv(tx.QueryRow(ctx, `INSERT INTO conversations(user_id,character_id) VALUES($1,$2) ON CONFLICT DO NOTHING RETURNING `+convCols, user, char))
	if errors.Is(e, pgx.ErrNoRows) {
		return nil
	}
	if e != nil {
		return e
	}
	return event(ctx, tx, user, "conversation", char, false, row)
}
func (s *Store) Conversations(ctx context.Context, user, after string, limit int) (Page[Conversation], error) {
	page := Page[Conversation]{Items: []Conversation{}}
	rows, e := s.Pool.Query(ctx, `SELECT `+convCols+` FROM conversations WHERE user_id=$1 AND character_id>$2 ORDER BY character_id LIMIT $3`, user, after, limit+1)
	if e != nil {
		return page, e
	}
	defer rows.Close()
	for rows.Next() {
		c, e := scanConv(rows)
		if e != nil {
			return page, e
		}
		page.Items = append(page.Items, c)
	}
	if len(page.Items) > limit {
		page.Items = page.Items[:limit]
		page.Next = page.Items[limit-1].CharacterID
	}
	return page, rows.Err()
}
func (s *Store) SetConversation(ctx context.Context, user, char string, expected int64, hidden, pinned bool) (Conversation, error) {
	var out Conversation
	e := s.write(ctx, user, func(tx pgx.Tx) error {
		old, e := scanConv(tx.QueryRow(ctx, `SELECT `+convCols+` FROM conversations WHERE user_id=$1 AND character_id=$2`, user, char))
		if e != nil && !errors.Is(e, pgx.ErrNoRows) {
			return e
		}
		if old.Version != expected {
			return ErrConflict
		}
		if e = accessible(ctx, tx, user, char); e != nil {
			return e
		}
		out, e = scanConv(tx.QueryRow(ctx, `INSERT INTO conversations(user_id,character_id,hidden,pinned,version) VALUES($1,$2,$3,$4,$5)
            ON CONFLICT(user_id,character_id) DO UPDATE SET hidden=$3,pinned=$4,version=$5 RETURNING `+convCols, user, char, hidden, pinned, expected+1))
		if e != nil {
			return e
		}
		return event(ctx, tx, user, "conversation", char, false, out)
	})
	return out, e
}
func (s *Store) Messages(ctx context.Context, user, char, query string, after int64, limit int) (Page[Message], error) {
	out := Page[Message]{Items: []Message{}}
	search := "%" + strings.NewReplacer(`\`, `\\`, "%", `\%`, "_", `\_`).Replace(query) + "%"
	rows, e := s.Pool.Query(ctx, `SELECT `+messageCols+` FROM messages WHERE user_id=$1 AND ($2='' OR character_id=$2) AND sequence>$3
        AND ($4='' OR text ILIKE $6) ORDER BY sequence LIMIT $5`, user, char, after, query, limit+1, search)
	if e != nil {
		return out, e
	}
	defer rows.Close()
	for rows.Next() {
		m, e := scanMessage(rows)
		if e != nil {
			return out, e
		}
		out.Items = append(out.Items, m)
	}
	if len(out.Items) > limit {
		out.Items = out.Items[:limit]
		out.Next = fmt.Sprint(out.Items[limit-1].Sequence)
	}
	return out, rows.Err()
}
func (s *Store) PutMessage(ctx context.Context, user string, m Message, expected int64, reset ...string) (Message, error) {
	var out Message
	e := s.write(ctx, user, func(tx pgx.Tx) error {
		if e := ensureConversation(ctx, tx, user, m.CharacterID); e != nil {
			return e
		}
		if e := checkConversationReset(ctx, tx, user, m.CharacterID, reset); e != nil {
			return e
		}
		old, e := scanMessage(tx.QueryRow(ctx, `SELECT `+messageCols+` FROM messages WHERE user_id=$1 AND character_id=$2 AND id=$3`, user, m.CharacterID, m.ID))
		if e != nil && !errors.Is(e, pgx.ErrNoRows) {
			return e
		}
		// A retried acknowledgement must not create a duplicate turn or event.
		if old.Version > 0 && old.Role == m.Role && old.Text == m.Text && bytes.Equal(JSON(old.Data), JSON(m.Data)) {
			out = old
			return nil
		}
		if old.Version != expected {
			return ErrConflict
		}
		out, e = scanMessage(tx.QueryRow(ctx, `INSERT INTO messages(user_id,character_id,id,role,text,created_at,data,version) VALUES($1,$2,$3,$4,$5,$6,$7,$8)
            ON CONFLICT(user_id,character_id,id) DO UPDATE SET role=$4,text=$5,data=$7,version=$8 RETURNING `+messageCols, user, m.CharacterID, m.ID, m.Role, m.Text, m.CreatedAt, m.Data, expected+1))
		if e != nil {
			return e
		}
		if old.Version == 0 {
			c, e := scanConv(tx.QueryRow(ctx, `UPDATE conversations SET hidden=false,version=version+1,updated_at=now() WHERE user_id=$1 AND character_id=$2 RETURNING `+convCols, user, m.CharacterID))
			if e != nil {
				return e
			}
			if e = event(ctx, tx, user, "conversation", m.CharacterID, false, c); e != nil {
				return e
			}
		}
		return event(ctx, tx, user, "message", m.CharacterID+"/"+m.ID, false, out)
	})
	return out, e
}
func (s *Store) Entries(ctx context.Context, user, char, kind, after string, limit int) (Page[Entry], error) {
	page := Page[Entry]{Items: []Entry{}}
	rows, e := s.Pool.Query(ctx, `SELECT id::text,character_id,kind,data,version FROM entries WHERE user_id=$1 AND character_id=$2 AND kind=$3 AND NOT deleted AND id>COALESCE(NULLIF($4,'')::uuid,'00000000-0000-0000-0000-000000000000'::uuid) ORDER BY id LIMIT $5`, user, char, kind, after, limit+1)
	if e != nil {
		return page, e
	}
	defer rows.Close()
	for rows.Next() {
		var v Entry
		if e = rows.Scan(&v.ID, &v.CharacterID, &v.Kind, &v.Data, &v.Version); e != nil {
			return page, e
		}
		page.Items = append(page.Items, v)
	}
	if len(page.Items) > limit {
		page.Items = page.Items[:limit]
		page.Next = page.Items[limit-1].ID
	}
	return page, rows.Err()
}
func (s *Store) PutEntry(ctx context.Context, user string, v Entry, expected int64, reset ...string) (Entry, error) {
	e := s.write(ctx, user, func(tx pgx.Tx) error {
		if e := ensureConversation(ctx, tx, user, v.CharacterID); e != nil {
			return e
		}
		if e := checkConversationReset(ctx, tx, user, v.CharacterID, reset); e != nil {
			return e
		}
		var old int64
		var data json.RawMessage
		e := tx.QueryRow(ctx, `SELECT version,data FROM entries WHERE user_id=$1 AND character_id=$2 AND kind=$3 AND id=$4`, user, v.CharacterID, v.Kind, v.ID).Scan(&old, &data)
		if e != nil && !errors.Is(e, pgx.ErrNoRows) {
			return e
		}
		if old != expected {
			return ErrConflict
		}
		if len(JSON(v.Data)) > 16384 {
			return invalid("entry exceeds 16 KiB")
		}
		v.Version = expected + 1
		if _, e = tx.Exec(ctx, `INSERT INTO entries(user_id,character_id,kind,id,data,version) VALUES($1,$2,$3,$4,$5,$6)
            ON CONFLICT(user_id,character_id,kind,id) DO UPDATE SET data=$5,version=$6,deleted=false`, user, v.CharacterID, v.Kind, v.ID, v.Data, v.Version); e != nil {
			return e
		}
		return event(ctx, tx, user, v.Kind, v.CharacterID+"/"+v.ID, false, v)
	})
	return v, e
}
func (s *Store) DeleteEntry(ctx context.Context, user, char, kind, id string, expected int64) error {
	return s.write(ctx, user, func(tx pgx.Tx) error {
		var v int64
		if e := tx.QueryRow(ctx, `SELECT version FROM entries WHERE user_id=$1 AND character_id=$2 AND kind=$3 AND id=$4`, user, char, kind, id).Scan(&v); e != nil {
			return e
		}
		if v != expected {
			return ErrConflict
		}
		if _, e := tx.Exec(ctx, `UPDATE entries SET deleted=true,version=version+1 WHERE user_id=$1 AND character_id=$2 AND kind=$3 AND id=$4`, user, char, kind, id); e != nil {
			return e
		}
		return event(ctx, tx, user, kind, char+"/"+id, true, map[string]any{"id": id, "character_id": char, "version": v + 1})
	})
}
