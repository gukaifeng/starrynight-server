package store

import (
	"context"
	"errors"
	"github.com/jackc/pgx/v5"
	"time"
)

type ConversationReset struct {
	ResetID   string    `json:"reset_id"`
	Version   int64     `json:"version"`
	ClearedAt time.Time `json:"cleared_at"`
}

// Called inside the account's serialized transaction, before every journal write.
// Older clients can write until the first reset; thereafter they must acknowledge
// the reset from /v1/sync. Retrying an old outbox cannot resurrect deleted content.
func checkConversationReset(ctx context.Context, tx pgx.Tx, user, character string, reset []string) error {
	var current string
	err := tx.QueryRow(ctx, `SELECT reset_id::text FROM conversation_resets WHERE user_id=$1 AND character_id=$2 ORDER BY version DESC LIMIT 1`, user, character).Scan(&current)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return err
	}
	provided := ""
	if len(reset) > 0 {
		provided = reset[0]
	}
	if provided != current {
		return ErrConflict
	}
	return nil
}

func (s *Store) ResetConversation(ctx context.Context, user, character, id string) (ConversationReset, error) {
	var out ConversationReset
	err := s.write(ctx, user, func(tx pgx.Tx) error {
		err := tx.QueryRow(ctx, `SELECT reset_id::text,version,cleared_at FROM conversation_resets WHERE user_id=$1 AND character_id=$2 AND reset_id=$3`, user, character, id).Scan(&out.ResetID, &out.Version, &out.ClearedAt)
		if err == nil {
			return nil
		} // Same confirmed request is idempotent.
		if !errors.Is(err, pgx.ErrNoRows) {
			return err
		}
		if err = ensureConversation(ctx, tx, user, character); err != nil {
			return err
		}
		if err = tx.QueryRow(ctx, `INSERT INTO conversation_resets(user_id,character_id,reset_id,version)
            SELECT $1,$2,$3,COALESCE(MAX(version),0)+1 FROM conversation_resets WHERE user_id=$1 AND character_id=$2
            RETURNING reset_id::text,version,cleared_at`, user, character, id).Scan(&out.ResetID, &out.Version, &out.ClearedAt); err != nil {
			return err
		}
		for _, query := range []string{
			`DELETE FROM messages WHERE user_id=$1 AND character_id=$2`,
			`DELETE FROM entries WHERE user_id=$1 AND character_id=$2`,
			`DELETE FROM changes WHERE user_id=$1 AND ((kind IN ('message','memory','moment') AND split_part(resource_id,'/',1)=$2) OR (kind='preference' AND resource_id=$2))`,
		} {
			if _, err = tx.Exec(ctx, query, user, character); err != nil {
				return err
			}
		}
		// Preserve explicit user preferences. Clear history-derived state and
		// replace its change payload, so export/sync do not retain old memories.
		doc := Document{SchemaVersion: 1, Data: map[string]any{}}
		err = tx.QueryRow(ctx, `SELECT data,version FROM preferences WHERE user_id=$1 AND character_id=$2`, user, character).Scan(&doc.Data, &doc.Version)
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return err
		}
		delete(doc.Data, "greeting")
		if experience, ok := doc.Data["experiences"].(map[string]any); ok {
			doc.Data["experiences"] = map[string]any{"preferences": experience["preferences"], "stories": map[string]any{}, "moments": []any{}, "suggestions": []any{}, "reviewedMemorySources": []any{}}
		}
		doc.Version++
		if _, err = tx.Exec(ctx, `INSERT INTO preferences(user_id,character_id,data,version) VALUES($1,$2,$3,$4)
            ON CONFLICT(user_id,character_id) DO UPDATE SET data=$3,version=$4`, user, character, doc.Data, doc.Version); err != nil {
			return err
		}
		// Reset comes first; a client drops its stale outbox before applying the
		// sanitized preference and hidden-list state in this same sync stream.
		if err = event(ctx, tx, user, "conversation_reset", character, false, out); err != nil {
			return err
		}
		if err = event(ctx, tx, user, "preference", character, false, doc); err != nil {
			return err
		}
		c, err := scanConv(tx.QueryRow(ctx, `UPDATE conversations SET hidden=true,version=version+1,updated_at=now() WHERE user_id=$1 AND character_id=$2 RETURNING `+convCols, user, character))
		if err != nil {
			return err
		}
		return event(ctx, tx, user, "conversation", character, false, c)
	})
	return out, err
}
