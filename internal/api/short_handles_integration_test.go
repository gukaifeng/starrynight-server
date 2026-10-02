package api_test

import (
	"context"
	"database/sql"
	"fmt"
	"github.com/gukaifeng/starrynight-server/internal/store"
	"github.com/gukaifeng/starrynight-server/migrations"
	"github.com/jackc/pgx/v5"
	"github.com/pressly/goose/v3"
	"net/url"
	"os"
	"regexp"
	"sync"
	"testing"
)

func TestShortHandleMigrationPreservesIdentityAndAllocation(t *testing.T) {
	s := setup(t)
	ctx := context.Background()
	schema := "handles_" + regexp.MustCompile(`[^a-z0-9]`).ReplaceAllString(store.NewID(), "")
	quoted := pgx.Identifier{schema}.Sanitize()
	if _, err := s.db.Pool.Exec(ctx, "CREATE SCHEMA "+quoted); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { s.db.Pool.Exec(ctx, "DROP SCHEMA "+quoted+" CASCADE") })
	dsn, err := url.Parse(os.Getenv("TEST_DATABASE_URL"))
	if err != nil {
		t.Fatal(err)
	}
	query := dsn.Query()
	query.Set("search_path", schema+",public")
	dsn.RawQuery = query.Encode()
	db, err := sql.Open("pgx", dsn.String())
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	var actualSchema string
	if err = db.QueryRowContext(ctx, "SELECT current_schema()").Scan(&actualSchema); err != nil || actualSchema != schema {
		t.Fatal("migration fixture schema not isolated", err)
	}
	provider, err := goose.NewProvider(goose.DialectPostgres, db, migrations.Files, goose.WithTableName(schema+".goose_db_version"))
	if err != nil {
		t.Fatal(err)
	}
	if _, err = provider.UpTo(ctx, 10); err != nil {
		t.Fatal(err)
	}
	id := store.NewID()
	old := ""
	if err = db.QueryRowContext(ctx, `INSERT INTO users(id,guest,profile) VALUES($1,true,'{"bio":"custom bio","avatar":"starry-bunny-v1"}') RETURNING starry_id`, id).Scan(&old); err != nil {
		t.Fatal(err)
	}
	var skipped int64
	if err = db.QueryRowContext(ctx, "SELECT nextval('starry_handle_sequence')").Scan(&skipped); err != nil {
		t.Fatal(err)
	}
	if _, err = provider.UpTo(ctx, 11); err != nil {
		t.Fatal(err)
	}
	var current, bio, avatar string
	if err = db.QueryRowContext(ctx, "SELECT starry_id,profile->>'bio',profile->>'avatar' FROM users WHERE id=$1", id).Scan(&current, &bio, &avatar); err != nil {
		t.Fatal(err)
	}
	if current != "xy1" || bio != "custom bio" || avatar != "starry-orbit-v1" {
		t.Fatalf("migration lost identity/profile: %s %s %s", current, bio, avatar)
	}
	var retained bool
	if err = db.QueryRowContext(ctx, "SELECT user_id=$2 AND retired_at IS NOT NULL FROM account_handles WHERE handle=$1", old, id).Scan(&retained); err != nil || !retained {
		t.Fatal("old alias not retained", err)
	}
	var next string
	if err = db.QueryRowContext(ctx, "INSERT INTO users(id,guest) VALUES($1,true) RETURNING starry_id", store.NewID()).Scan(&next); err != nil {
		t.Fatal(err)
	}
	if next != "xy3" {
		t.Fatal("registration allocator was rewound", next)
	}
}

func TestShortHandlesAreUniqueAcrossConcurrentDatabasePools(t *testing.T) {
	s := setup(t)
	ctx := context.Background()
	other, err := store.Open(ctx, os.Getenv("TEST_DATABASE_URL"), 4)
	if err != nil {
		t.Fatal(err)
	}
	defer other.Pool.Close()
	const count = 24
	type result struct {
		user store.User
		err  error
	}
	outputs := make(chan result, count)
	var workers sync.WaitGroup
	for i := 0; i < count; i++ {
		workers.Add(1)
		go func(index int) {
			defer workers.Done()
			db := s.db
			if index%2 == 1 {
				db = other
			}
			u, e := db.CreateUser(ctx, "", "", "Replica fixture", true)
			outputs <- result{u, e}
		}(i)
	}
	workers.Wait()
	close(outputs)
	seen := map[string]bool{}
	ids := []string{}
	for out := range outputs {
		if out.err != nil {
			t.Error(out.err)
			continue
		}
		ids = append(ids, out.user.ID)
		if seen[out.user.StarryID] || !regexp.MustCompile(`^xy[1-9][0-9]*$`).MatchString(out.user.StarryID) {
			t.Errorf("invalid/duplicate %s", out.user.StarryID)
		}
		seen[out.user.StarryID] = true
	}
	t.Cleanup(func() {
		for _, id := range ids {
			s.db.DeleteUser(ctx, id)
		}
	})
	if len(seen) != count {
		t.Fatal(fmt.Sprintf("expected %d unique allocations, got %d", count, len(seen)))
	}
}
