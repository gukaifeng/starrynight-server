package main

import (
	"context"
	"errors"
	"flag"
	"github.com/gin-gonic/gin"
	"github.com/gukaifeng/starrynight-server/internal/api"
	"github.com/gukaifeng/starrynight-server/internal/config"
	"github.com/gukaifeng/starrynight-server/internal/store"
	"github.com/redis/go-redis/v9"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"
)

func main() {
	if e := run(); e != nil {
		slog.Error("startup failed", "error", e)
		os.Exit(1)
	}
}
func run() error {
	gin.SetMode(gin.ReleaseMode)
	schema := flag.String("openapi", "", "write OpenAPI and exit (no network or database required)")
	flag.Parse()
	if *schema != "" {
		cache := redis.NewClient(&redis.Options{Addr: "127.0.0.1:0"})
		defer cache.Close()
		app, err := api.New(config.Config{SessionLifetime: 30 * 24 * time.Hour}, &store.Store{}, cache)
		if err != nil {
			return err
		}
		data, err := app.OpenAPI()
		if err != nil {
			return err
		}
		return os.WriteFile(*schema, append(data, '\n'), 0644)
	}
	slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stdout, nil)))
	c, e := config.Load()
	if e != nil {
		return e
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	db, e := store.Open(ctx, c.DatabaseURL, c.PoolSize)
	if e != nil {
		return errors.New("cannot connect to PostgreSQL")
	}
	defer db.Pool.Close()
	ro, e := redis.ParseURL(c.RedisURL)
	if e != nil {
		return errors.New("invalid Redis URL")
	}
	ro.DialTimeout = 3 * time.Second
	ro.ReadTimeout = 2 * time.Second
	ro.WriteTimeout = 2 * time.Second
	ro.PoolSize = 24
	cache := redis.NewClient(ro)
	defer cache.Close()
	if e = cache.Ping(ctx).Err(); e != nil {
		return errors.New("cannot connect to Redis")
	}
	app, e := api.New(c, db, cache)
	if e != nil {
		return e
	}
	srv := &http.Server{Addr: c.Listen, Handler: app.Router, ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 15 * time.Second, WriteTimeout: 30 * time.Second, IdleTimeout: 60 * time.Second, MaxHeaderBytes: 16 * 1024}
	errs := make(chan error, 1)
	go func() {
		slog.Info("platform listening", "address", c.Listen, "environment", c.Environment)
		errs <- srv.ListenAndServe()
	}()
	select {
	case e = <-errs:
		if !errors.Is(e, http.ErrServerClosed) {
			return e
		}
	case <-ctx.Done():
	}
	shutdown, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	return srv.Shutdown(shutdown)
}
