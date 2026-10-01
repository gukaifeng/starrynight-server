package store

import (
	"context"
	"encoding/json"
	"github.com/jackc/pgx/v5"
)

func scanUser(row pgx.Row) (User, error) {
	var u User
	e := row.Scan(&u.ID, &u.Username, &u.Guest, &u.Version, &u.Profile, &u.Epoch)
	return u, classify(e)
}

const userColumns = `id::text,COALESCE(username,''),guest,version,profile,session_epoch`

func (s *Store) User(ctx context.Context, id string) (User, error) {
	return scanUser(s.Pool.QueryRow(ctx, "SELECT "+userColumns+" FROM users WHERE id=$1", id))
}
func (s *Store) Credential(ctx context.Context, username string) (User, string, error) {
	var u User
	var hash string
	e := s.Pool.QueryRow(ctx, "SELECT "+userColumns+",password_hash FROM users WHERE username=$1 AND NOT guest", username).Scan(&u.ID, &u.Username, &u.Guest, &u.Version, &u.Profile, &u.Epoch, &hash)
	return u, hash, classify(e)
}
func (s *Store) CreateUser(ctx context.Context, username, hash, name string, guest bool) (User, error) {
	id := NewID()
	var u User
	tx, e := s.Pool.Begin(ctx)
	if e != nil {
		return u, e
	}
	defer tx.Rollback(ctx)
	var nameArg, hashArg any = username, hash
	if guest {
		nameArg = nil
		hashArg = nil
	}
	u, e = scanUser(tx.QueryRow(ctx, `INSERT INTO users(id,username,password_hash,guest,profile) VALUES($1,$2,$3,$4,$5) RETURNING `+userColumns, id, nameArg, hashArg, guest, map[string]any{"display_name": name, "avatar": "moon"}))
	if e != nil {
		return u, e
	}
	if _, e = tx.Exec(ctx, `INSERT INTO account_clocks(user_id) VALUES($1)`, id); e != nil {
		return u, e
	}
	if _, e = tx.Exec(ctx, `INSERT INTO settings(user_id,data) VALUES($1,'{"theme":"silver","style":"glass","chat_font_size":15,"last_character":"anime-kipfel"}')`, id); e != nil {
		return u, e
	}
	if _, e = tx.Exec(ctx, `INSERT INTO subscriptions(user_id,character_id) VALUES($1,'anime-kipfel')`, id); e != nil {
		return u, e
	}
	if e = createAuthor(ctx, tx, id, name); e != nil {
		return u, e
	}
	if e = event(ctx, tx, id, "account", id, false, u); e != nil {
		return u, e
	}
	if e = event(ctx, tx, id, "settings", "settings", false, Document{1, 1, map[string]any{"theme": "silver", "style": "glass", "chat_font_size": 15, "last_character": "anime-kipfel"}}); e != nil {
		return u, e
	}
	if e = event(ctx, tx, id, "subscription", "anime-kipfel", false, map[string]any{"id": "anime-kipfel"}); e != nil {
		return u, e
	}
	return u, tx.Commit(ctx)
}
func createAuthor(ctx context.Context, tx pgx.Tx, id, name string) error {
	a := Author{ID: "author-" + NewID(), Version: 1, Data: map[string]any{"name": name, "bio": "把想象中的伙伴，带到你身边。", "avatar": "moon"}}
	result, e := tx.Exec(ctx, `INSERT INTO authors(id,user_id,data) VALUES($1,$2,$3) ON CONFLICT(user_id) DO NOTHING`, a.ID, id, a.Data)
	if e != nil {
		return e
	}
	if result.RowsAffected() == 0 {
		return nil
	}
	return event(ctx, tx, id, "author", a.ID, false, a)
}
func (s *Store) UpgradeGuest(ctx context.Context, id, username, hash, name string) (User, error) {
	var u User
	e := s.write(ctx, id, func(tx pgx.Tx) error {
		var e error
		u, e = scanUser(tx.QueryRow(ctx, `UPDATE users SET username=$2,password_hash=$3,guest=false,profile=profile || jsonb_build_object('display_name',$4::text),version=version+1,session_epoch=session_epoch+1 WHERE id=$1 AND guest RETURNING `+userColumns, id, username, hash, name))
		if e != nil {
			return e
		}
		if e = createAuthor(ctx, tx, id, name); e != nil {
			return e
		}
		return event(ctx, tx, id, "account", id, false, u)
	})
	return u, e
}
func (s *Store) ChangePassword(ctx context.Context, id, oldHash, newHash string) error {
	return s.write(ctx, id, func(tx pgx.Tx) error {
		result, e := tx.Exec(ctx, `UPDATE users SET password_hash=$3,session_epoch=session_epoch+1 WHERE id=$1 AND password_hash=$2 AND NOT guest`, id, oldHash, newHash)
		if e != nil {
			return e
		}
		if result.RowsAffected() != 1 {
			return ErrConflict
		}
		return nil
	})
}
func (s *Store) DeleteUser(ctx context.Context, id string) error {
	return s.write(ctx, id, func(tx pgx.Tx) error {
		// Remove subscriptions to works first; base character descendants retain
		// their source ID by restricting deletion until the owner unpublishes.
		// Physical removal of a source must not cascade into another user's work.
		_, e := tx.Exec(ctx, `UPDATE characters SET base_id=NULL WHERE base_id IN(SELECT id FROM characters WHERE owner_id=$1)`, id)
		if e != nil {
			return e
		}
		_, e = tx.Exec(ctx, `DELETE FROM characters WHERE owner_id=$1`, id)
		if e != nil {
			return e
		}
		_, e = tx.Exec(ctx, `DELETE FROM users WHERE id=$1`, id)
		return e
	})
}
func (s *Store) Profile(ctx context.Context, id string, expected int64, patch map[string]any) (Document, error) {
	var out Document
	e := s.write(ctx, id, func(tx pgx.Tx) error {
		var current map[string]any
		var version int64
		if e := tx.QueryRow(ctx, "SELECT profile,version FROM users WHERE id=$1", id).Scan(&current, &version); e != nil {
			return e
		}
		if version != expected {
			return ErrConflict
		}
		next, e := merge(current, patch)
		if e != nil {
			return e
		}
		if e = validateProfile(next, false); e != nil {
			return e
		}
		out = Document{1, version + 1, next}
		if _, e = tx.Exec(ctx, "UPDATE users SET profile=$2,version=version+1 WHERE id=$1", id, next); e != nil {
			return e
		}
		return event(ctx, tx, id, "profile", id, false, out)
	})
	return out, e
}

// Export returns individually paged sync events. The HTTP streaming export uses
// this same account-scoped feed, including tombstones and versioned extensions.
func (s *Store) ExportPage(ctx context.Context, id string, after int64) (Page[Change], error) {
	return s.Changes(ctx, id, after, 200)
}
func JSON(value any) json.RawMessage { b, _ := json.Marshal(value); return b }
