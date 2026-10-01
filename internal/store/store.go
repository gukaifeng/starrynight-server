package store

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"
	"time"
)

var ErrNotFound = errors.New("resource not found")
var ErrConflict = errors.New("version conflict; pull latest before retrying")
var ErrForbidden = errors.New("operation not permitted")
var ErrExists = errors.New("username unavailable")

type Store struct{ Pool *pgxpool.Pool }
type Document struct {
	SchemaVersion int            `json:"schema_version"`
	Version       int64          `json:"version"`
	Data          map[string]any `json:"data"`
}
type User struct {
	ID       string         `json:"id"`
	Username string         `json:"username"`
	Guest    bool           `json:"guest"`
	Version  int64          `json:"version"`
	Profile  map[string]any `json:"profile"`
	Epoch    int64          `json:"-"`
}
type Change struct {
	Revision   int64           `json:"revision"`
	Kind       string          `json:"kind"`
	ResourceID string          `json:"resource_id"`
	Deleted    bool            `json:"deleted"`
	Data       json.RawMessage `json:"data"`
}
type Page[T any] struct {
	Items []T    `json:"items"`
	Next  string `json:"next_cursor,omitempty"`
}

func NewID() string { return uuid.Must(uuid.NewV7()).String() }
func Open(ctx context.Context, url string, max int32) (*Store, error) {
	c, e := pgxpool.ParseConfig(url)
	if e != nil {
		return nil, e
	}
	c.MaxConns = max
	c.MinConns = 2
	c.MaxConnLifetime = 30 * time.Minute
	c.MaxConnLifetimeJitter = 5 * time.Minute
	c.MaxConnIdleTime = 5 * time.Minute
	c.ConnConfig.ConnectTimeout = 5 * time.Second
	c.ConnConfig.RuntimeParams["statement_timeout"] = "5000"
	c.ConnConfig.RuntimeParams["idle_in_transaction_session_timeout"] = "10000"
	// Works with PgBouncer transaction pooling, without session prepared state.
	c.ConnConfig.DefaultQueryExecMode = pgx.QueryExecModeExec
	c.AfterConnect = func(ctx context.Context, conn *pgx.Conn) error {
		conn.TypeMap().RegisterDefaultPgType(map[string]any{}, "jsonb")
		return nil
	}
	p, e := pgxpool.NewWithConfig(ctx, c)
	if e != nil {
		return nil, e
	}
	if e = p.Ping(ctx); e != nil {
		p.Close()
		return nil, e
	}
	return &Store{p}, nil
}
func classify(e error) error {
	if errors.Is(e, pgx.ErrNoRows) {
		return ErrNotFound
	}
	var p *pgconn.PgError
	if errors.As(e, &p) && p.Code == "23505" {
		return ErrExists
	}
	return e
}
func (s *Store) write(ctx context.Context, user string, fn func(pgx.Tx) error) error {
	tx, e := s.Pool.Begin(ctx)
	if e != nil {
		return e
	}
	defer tx.Rollback(ctx)
	// Per-account lock makes feed revisions commit ordered; different accounts
	// are fully concurrent. A global sequence alone can skip late commits.
	var n int64
	if e = tx.QueryRow(ctx, "SELECT revision FROM account_clocks WHERE user_id=$1 FOR UPDATE", user).Scan(&n); e != nil {
		return classify(e)
	}
	if e = fn(tx); e != nil {
		return classify(e)
	}
	return tx.Commit(ctx)
}
func event(ctx context.Context, tx pgx.Tx, user, kind, id string, deleted bool, value any) error {
	raw, e := json.Marshal(value)
	if e != nil {
		return e
	}
	_, e = tx.Exec(ctx, `WITH n AS (UPDATE account_clocks SET revision=revision+1 WHERE user_id=$1 RETURNING revision)
		INSERT INTO changes(user_id,revision,kind,resource_id,deleted,data) SELECT $1,revision,$2,$3,$4,$5 FROM n`, user, kind, id, deleted, json.RawMessage(raw))
	return e
}
func (s *Store) Changes(ctx context.Context, user string, after int64, limit int) (Page[Change], error) {
	page := Page[Change]{Items: []Change{}}
	rows, e := s.Pool.Query(ctx, `SELECT revision,kind,resource_id,deleted,data FROM changes WHERE user_id=$1 AND revision>$2 ORDER BY revision LIMIT $3`, user, after, limit+1)
	if e != nil {
		return page, e
	}
	defer rows.Close()
	bytes := 0
	for rows.Next() {
		var c Change
		if e = rows.Scan(&c.Revision, &c.Kind, &c.ResourceID, &c.Deleted, &c.Data); e != nil {
			return page, e
		}
		if len(page.Items) > 0 && (len(page.Items) == limit || bytes+len(c.Data) > 1<<20) {
			page.Next = fmt.Sprint(page.Items[len(page.Items)-1].Revision)
			break
		}
		bytes += len(c.Data)
		page.Items = append(page.Items, c)
	}
	return page, rows.Err()
}
