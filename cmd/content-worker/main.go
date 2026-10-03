package main

import (
	"context"
	"github.com/gukaifeng/starrynight-server/internal/config"
	"github.com/gukaifeng/starrynight-server/internal/privatecontent"
	"github.com/gukaifeng/starrynight-server/internal/store"
	"github.com/gukaifeng/starrynight-server/internal/tasks"
	"github.com/redis/go-redis/v9"
	"log/slog"
	"os"
	"os/signal"
	"syscall"
)

func main() {
	if e := run(); e != nil {
		slog.Error("content worker stopped", "error_type", "configuration_or_dependency")
		os.Exit(1)
	}
}
func run() error {
	c, e := config.Load()
	if e != nil {
		return e
	}
	k, e := privatecontent.New(c.ContentActiveKey, c.ContentKeys)
	if e != nil {
		return e
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	db, e := store.Open(ctx, c.DatabaseURL, 4)
	if e != nil {
		return e
	}
	defer db.Pool.Close()
	ro, e := redis.ParseURL(c.RedisURL)
	if e != nil {
		return e
	}
	return tasks.New(db, k, ro, c.RedisPrefix).Run(ctx)
}
