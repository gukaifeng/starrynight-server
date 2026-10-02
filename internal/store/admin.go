package store

import (
	"context"
	"github.com/jackc/pgx/v5"
	"unicode/utf8"
)

// AdminCatalog edits official and user-owned metadata. User-owned writes still
// acquire their account clock and emit the same event as a client mutation.
func (s *Store) AdminCatalog(ctx context.Context, id string, expected int64, patch map[string]any, archive *bool) (Character, error) {
	var owner string
	if e := s.Pool.QueryRow(ctx, "SELECT COALESCE(owner_id::text,'') FROM characters WHERE id=$1", id).Scan(&owner); e != nil {
		return Character{}, classify(e)
	}
	var out Character
	fn := func(tx pgx.Tx) error {
		var e error
		out, e = scanCharacter(tx.QueryRow(ctx, "SELECT "+characterColumns+" FROM characters WHERE id=$1 FOR UPDATE", id))
		if e != nil {
			return e
		}
		if out.OwnerID != owner || out.Version != expected {
			return ErrConflict
		}
		for k, v := range patch {
			switch k {
			case "name":
				t, ok := v.(string)
				if !ok || t == "" || utf8.RuneCountInString(t) > 48 {
					return invalid("名称需要 1–48 个字")
				}
				out.Name = t
			case "description":
				t, ok := v.(string)
				if !ok || utf8.RuneCountInString(t) > 2000 {
					return invalid("介绍过长")
				}
				out.Description = t
			case "visibility":
				t, ok := v.(string)
				if !ok || !oneOf(t, "public", "private", "unlisted") {
					return invalid("无效可见性")
				}
				out.Visibility = t
			case "data":
				m, ok := v.(map[string]any)
				if !ok {
					return invalid("data 必须是对象")
				}
				out.Data, e = merge(out.Data, m)
				if e != nil {
					return e
				}
				out.Data, e = publicCharacterData(out.Data)
				if e != nil {
					return e
				}
			default:
				return invalid("不允许编辑 " + k)
			}
		}
		if archive == nil {
			out, e = scanCharacter(tx.QueryRow(ctx, `UPDATE characters SET name=$2,description=$3,visibility=$4,data=$5,version=version+1,updated_at=now() WHERE id=$1 RETURNING `+characterColumns, id, out.Name, out.Description, out.Visibility, out.Data))
		} else {
			out, e = scanCharacter(tx.QueryRow(ctx, `UPDATE characters SET deleted=$2,version=version+1,updated_at=now() WHERE id=$1 RETURNING `+characterColumns, id, *archive))
		}
		if e != nil {
			return e
		}
		if owner != "" {
			return event(ctx, tx, owner, "character", id, archive != nil && *archive, out)
		}
		return nil
	}
	if owner != "" {
		e := s.write(ctx, owner, fn)
		return out, e
	}
	tx, e := s.Pool.Begin(ctx)
	if e != nil {
		return out, e
	}
	defer tx.Rollback(ctx)
	if e = fn(tx); e == nil {
		e = tx.Commit(ctx)
	}
	return out, e
}
func (s *Store) AdminAuthor(ctx context.Context, id string, expected int64, patch map[string]any) (Author, error) {
	var user string
	if e := s.Pool.QueryRow(ctx, "SELECT COALESCE(user_id::text,'') FROM authors WHERE id=$1", id).Scan(&user); e != nil {
		return Author{}, classify(e)
	}
	if user != "" {
		return s.PatchAuthor(ctx, user, expected, patch)
	}
	tx, e := s.Pool.Begin(ctx)
	if e != nil {
		return Author{}, e
	}
	defer tx.Rollback(ctx)
	var a Author
	if e = tx.QueryRow(ctx, "SELECT id,data,version FROM authors WHERE id=$1 FOR UPDATE", id).Scan(&a.ID, &a.Data, &a.Version); e != nil {
		return a, e
	}
	if a.Version != expected {
		return a, ErrConflict
	}
	a.Data, e = merge(a.Data, patch)
	if e != nil {
		return a, e
	}
	if e = validateProfile(a.Data, true); e != nil {
		return a, e
	}
	a.Version++
	_, e = tx.Exec(ctx, "UPDATE authors SET data=$2,version=$3,updated_at=now() WHERE id=$1", id, a.Data, a.Version)
	if e == nil {
		e = tx.Commit(ctx)
	}
	return a, e
}
