package store

import (
	"context"
	"encoding/json"
	"github.com/gukaifeng/starrynight-server/internal/assets"
	"time"
)

func (s *Store) Release(ctx context.Context, user, character, platform string) (assets.Manifest, error) {
	if _, err := s.Character(ctx, user, character); err != nil {
		return assets.Manifest{}, err
	}
	var m assets.Manifest
	var raw []byte
	err := s.Pool.QueryRow(ctx, `SELECT manifest FROM character_releases WHERE character_id=$1 AND platform=$2 AND distributable ORDER BY version DESC LIMIT 1`, character, platform).Scan(&raw)
	if err != nil {
		return m, classify(err)
	}
	if err = json.Unmarshal(raw, &m); err != nil {
		return m, err
	}
	return m, m.Validate()
}

type SupportTicket struct {
	ID        string    `json:"id"`
	Category  string    `json:"category"`
	Content   string    `json:"content"`
	State     string    `json:"state"`
	CreatedAt time.Time `json:"created_at"`
}

func (s *Store) CreateTicket(ctx context.Context, user, category, content string) (SupportTicket, error) {
	var t SupportTicket
	err := s.Pool.QueryRow(ctx, `INSERT INTO support_tickets(id,user_id,category,content) VALUES($1,$2,$3,$4) RETURNING id::text,category,content,state,created_at`, NewID(), user, category, content).Scan(&t.ID, &t.Category, &t.Content, &t.State, &t.CreatedAt)
	return t, err
}
func (s *Store) Tickets(ctx context.Context, user, after string, limit int) (Page[SupportTicket], error) {
	out := Page[SupportTicket]{Items: []SupportTicket{}}
	var cursor any
	if after != "" {
		cursor = after
	}
	rows, err := s.Pool.Query(ctx, `SELECT id::text,category,content,state,created_at FROM support_tickets WHERE user_id=$1 AND ($2::uuid IS NULL OR id>$2::uuid) ORDER BY id LIMIT $3`, user, cursor, limit+1)
	if err != nil {
		return out, err
	}
	defer rows.Close()
	for rows.Next() {
		var t SupportTicket
		if err = rows.Scan(&t.ID, &t.Category, &t.Content, &t.State, &t.CreatedAt); err != nil {
			return out, err
		}
		out.Items = append(out.Items, t)
	}
	if len(out.Items) > limit {
		out.Items = out.Items[:limit]
		out.Next = out.Items[limit-1].ID
	}
	return out, rows.Err()
}
