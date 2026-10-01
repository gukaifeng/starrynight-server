package main

import (
	"context"
	"database/sql"
	"fmt"
	"github.com/gukaifeng/starrynight-server/migrations"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/pressly/goose/v3"
	"github.com/pressly/goose/v3/lock"
	"os"
	"time"
)

func main() {
	if e := run(); e != nil {
		fmt.Fprintln(os.Stderr, "migration failed:", e)
		os.Exit(1)
	}
}
func run() error {
	db, e := sql.Open("pgx", os.Getenv("DATABASE_URL"))
	if e != nil {
		return e
	}
	defer db.Close()
	db.SetMaxOpenConns(2)
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()
	// Goose provider uses a PostgreSQL advisory session lock, so two deploy jobs
	// cannot migrate concurrently. API replicas never migrate on startup.
	locker, e := lock.NewPostgresSessionLocker()
	if e != nil {
		return e
	}
	provider, e := goose.NewProvider(goose.DialectPostgres, db, migrations.Files, goose.WithSessionLocker(locker))
	if e != nil {
		return e
	}
	_, e = provider.Up(ctx)
	return e
}
