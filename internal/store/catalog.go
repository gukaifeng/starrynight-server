package store

import (
	"context"
	"github.com/jackc/pgx/v5"
	"strings"
	"time"
)

type Character struct {
	OwnerID     string         `json:"-"`
	Owned       bool           `json:"owned"`
	ID          string         `json:"id"`
	AuthorID    string         `json:"author_id"`
	BaseID      string         `json:"base_id"`
	Visibility  string         `json:"visibility"`
	Name        string         `json:"name"`
	Description string         `json:"description"`
	Data        map[string]any `json:"data"`
	Version     int64          `json:"version"`
	UpdatedAt   time.Time      `json:"updated_at"`
}

const characterColumns = `id,author_id,COALESCE(base_id,''),visibility,name,description,data,version,updated_at,COALESCE(owner_id::text,'')`

func scanCharacter(row pgx.Row) (Character, error) {
	var c Character
	e := row.Scan(&c.ID, &c.AuthorID, &c.BaseID, &c.Visibility, &c.Name, &c.Description, &c.Data, &c.Version, &c.UpdatedAt, &c.OwnerID)
	return c, classify(e)
}

type queryRow interface {
	QueryRow(context.Context, string, ...any) pgx.Row
}

func accessible(ctx context.Context, q queryRow, user, id string) error {
	var found bool
	e := q.QueryRow(ctx, `SELECT true FROM characters WHERE id=$1 AND NOT deleted AND (visibility IN ('public','unlisted') OR owner_id=NULLIF($2,'')::uuid)`, id, user).Scan(&found)
	return classify(e)
}
func (s *Store) Character(ctx context.Context, user, id string) (Character, error) {
	c, e := scanCharacter(s.Pool.QueryRow(ctx, `SELECT `+characterColumns+` FROM characters WHERE id=$1 AND NOT deleted AND (visibility IN ('public','unlisted') OR owner_id=NULLIF($2,'')::uuid)`, id, user))
	c.Owned = user != "" && c.OwnerID == user
	return c, e
}
func (s *Store) Characters(ctx context.Context, user, query, author, after string, mine bool, limit int) (Page[Character], error) {
	page := Page[Character]{Items: []Character{}}
	// Escape LIKE metacharacters: a search query is text, not a wildcard pattern.
	search := "%" + strings.NewReplacer(`\`, `\\`, "%", `\%`, "_", `\_`).Replace(query) + "%"
	rows, e := s.Pool.Query(ctx, `SELECT `+characterColumns+` FROM characters WHERE NOT deleted AND id>$1
        AND (($2 AND owner_id=NULLIF($3,'')::uuid) OR (NOT $2 AND visibility='public'))
        AND ($4='' OR author_id=$4) AND ($5='' OR (name || ' ' || description) ILIKE $6)
        ORDER BY id LIMIT $7`, after, mine, user, author, query, search, limit+1)
	if e != nil {
		return page, e
	}
	defer rows.Close()
	for rows.Next() {
		c, e := scanCharacter(rows)
		if e != nil {
			return page, e
		}
		c.Owned = user != "" && c.OwnerID == user
		page.Items = append(page.Items, c)
	}
	if len(page.Items) > limit {
		page.Items = page.Items[:limit]
		page.Next = page.Items[limit-1].ID
	}
	return page, rows.Err()
}
func (s *Store) CreateCharacter(ctx context.Context, user string, c Character) (Character, error) {
	var out Character
	data, err := publicCharacterData(c.Data)
	if err != nil {
		return out, err
	}
	c.Data = data
	e := s.write(ctx, user, func(tx pgx.Tx) error {
		if e := accessible(ctx, tx, user, c.BaseID); e != nil {
			return e
		}
		var author string
		if e := tx.QueryRow(ctx, "SELECT id FROM authors WHERE user_id=$1", user).Scan(&author); e != nil {
			return ErrForbidden
		}
		var e error
		out, e = scanCharacter(tx.QueryRow(ctx, `INSERT INTO characters(id,owner_id,author_id,base_id,visibility,name,description,data) VALUES($1,$2,$3,$4,$5,$6,$7,$8) RETURNING `+characterColumns, c.ID, user, author, c.BaseID, c.Visibility, c.Name, c.Description, c.Data))
		if e != nil {
			return e
		}
		out.Owned = true
		return event(ctx, tx, user, "character", c.ID, false, out)
	})
	return out, e
}
func (s *Store) UpdateCharacter(ctx context.Context, user string, c Character, expected int64) (Character, error) {
	var out Character
	e := s.write(ctx, user, func(tx pgx.Tx) error {
		var e error
		out, e = scanCharacter(tx.QueryRow(ctx, "SELECT "+characterColumns+" FROM characters WHERE id=$1 AND owner_id=$2 AND NOT deleted", c.ID, user))
		if e != nil {
			return e
		}
		if out.Version != expected {
			return ErrConflict
		}
		data, e := merge(out.Data, c.Data)
		if e != nil {
			return e
		}
		data, e = publicCharacterData(data)
		if e != nil {
			return e
		}
		out, e = scanCharacter(tx.QueryRow(ctx, `UPDATE characters SET name=$3,description=$4,visibility=$5,data=$6,version=version+1,updated_at=now() WHERE id=$1 AND owner_id=$2 RETURNING `+characterColumns, c.ID, user, c.Name, c.Description, c.Visibility, data))
		if e != nil {
			return e
		}
		out.Owned = true
		return event(ctx, tx, user, "character", c.ID, false, out)
	})
	return out, e
}

func publicCharacterData(input map[string]any) (map[string]any, error) {
	data, err := merge(map[string]any{}, input)
	if err != nil {
		return nil, err
	}
	if native, ok := data["native"].(map[string]any); ok {
		// Native account IDs are private joins, never public marketplace data.
		delete(native, "ownerID")
		delete(native, "authorID")
	}
	return data, nil
}
func (s *Store) DeleteCharacter(ctx context.Context, user, id string, expected int64) error {
	return s.write(ctx, user, func(tx pgx.Tx) error {
		var v int64
		if e := tx.QueryRow(ctx, `SELECT version FROM characters WHERE id=$1 AND owner_id=$2 AND NOT deleted`, id, user).Scan(&v); e != nil {
			return e
		}
		if v != expected {
			return ErrConflict
		}
		if _, e := tx.Exec(ctx, `UPDATE characters SET deleted=true,version=version+1,updated_at=now() WHERE id=$1 AND owner_id=$2`, id, user); e != nil {
			return e
		}
		return event(ctx, tx, user, "character", id, true, map[string]any{"id": id, "version": v + 1})
	})
}
