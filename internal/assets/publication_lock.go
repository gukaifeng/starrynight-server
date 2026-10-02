package assets

import (
	"context"
	"github.com/jackc/pgx/v5/pgxpool"
	"time"
)

// Serialize publication against administrative object deletion across nodes.
// A session lock holds one connection only for these uncommon control actions.
func LockPublication(ctx context.Context, pool *pgxpool.Pool) (func(), error) {
	conn, err := pool.Acquire(ctx)
	if err != nil {
		return nil, err
	}
	if _, err = conn.Exec(ctx, "SELECT pg_advisory_lock(73450126002)"); err != nil {
		conn.Release()
		return nil, err
	}
	return func() {
		cleanup, cancel := context.WithTimeout(context.Background(), 3*time.Second)
		defer cancel()
		if _, err := conn.Exec(cleanup, "SELECT pg_advisory_unlock(73450126002)"); err != nil {
			_ = conn.Conn().Close(cleanup)
		}
		conn.Release()
	}, nil
}
