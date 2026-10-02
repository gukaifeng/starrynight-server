package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"github.com/alexedwards/argon2id"
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/gukaifeng/starrynight-server/internal/admin"
	"github.com/gukaifeng/starrynight-server/internal/assets"
	"github.com/gukaifeng/starrynight-server/internal/config"
	"github.com/gukaifeng/starrynight-server/internal/store"
	"github.com/redis/go-redis/v9"
	"io"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"regexp"
	"strings"
	"syscall"
	"time"
)

func main() {
	if e := run(); e != nil {
		slog.Error("admin failed", "error", e)
		os.Exit(1)
	}
}
func run() error {
	bootstrap := flag.Bool("bootstrap", false, "create first owner; password from stdin")
	username := flag.String("username", "owner", "first owner username")
	validate := flag.Bool("validate-config", false, "validate platform config and connection readiness")
	flag.Parse()
	cfg, e := config.Load()
	if e != nil {
		return e
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	db, e := store.Open(ctx, cfg.DatabaseURL, 4)
	if e != nil {
		return errors.New("admin PostgreSQL unavailable")
	}
	defer db.Pool.Close()
	if *validate {
		options, err := redis.ParseURL(cfg.RedisURL)
		if err != nil {
			return errors.New("invalid Redis URL")
		}
		client := redis.NewClient(options)
		defer client.Close()
		check, cancel := context.WithTimeout(ctx, 10*time.Second)
		defer cancel()
		if db.Pool.Ping(check) != nil || client.Ping(check).Err() != nil {
			return errors.New("database or session storage not ready")
		}
		return nil
	}
	if *bootstrap {
		data, e := io.ReadAll(io.LimitReader(os.Stdin, 130))
		if e != nil {
			return e
		}
		password := strings.TrimSpace(string(data))
		if len(password) < 12 || len(password) > 128 || !regexp.MustCompile(`^[a-z0-9_]{3,32}$`).MatchString(*username) {
			return errors.New("invalid bootstrap username/password")
		}
		hash, e := argon2id.CreateHash(password, argon2id.DefaultParams)
		if e != nil {
			return e
		}
		tx, e := db.Pool.Begin(ctx)
		if e != nil {
			return e
		}
		defer tx.Rollback(ctx)
		if _, e = tx.Exec(ctx, "SELECT pg_advisory_xact_lock(74831920)"); e != nil {
			return e
		}
		var n int
		if e = tx.QueryRow(ctx, "SELECT count(*) FROM admin_users").Scan(&n); e != nil {
			return e
		}
		if n > 0 {
			return errors.New("administrators already exist; bootstrap refuses replacement")
		}
		_, e = tx.Exec(ctx, "INSERT INTO admin_users(id,username,password_hash,role) VALUES($1,$2,$3,'owner')", uuid.NewString(), *username, hash)
		if e == nil {
			e = tx.Commit(ctx)
		}
		return e
	}
	listen := os.Getenv("ADMIN_LISTEN")
	if listen == "" {
		listen = "127.0.0.1:8100"
	}
	host, _, e := net.SplitHostPort(listen)
	if e != nil || host != "127.0.0.1" {
		return errors.New("admin must bind IPv4 loopback")
	}
	origin := os.Getenv("ADMIN_ORIGIN")
	root := os.Getenv("ADMIN_WEB_ROOT")
	if root == "" {
		root = "admin-web/dist"
	}
	if _, e = os.Stat(root + "/index.html"); e != nil {
		return errors.New("compiled admin frontend missing")
	}
	token := ""
	if path := os.Getenv("STARRY_AI_CONFIG"); path != "" {
		data, e := os.ReadFile(path)
		if e != nil {
			return errors.New("admin cannot read private AI config")
		}
		var v struct {
			Token string `json:"admin_token"`
		}
		if e = json.Unmarshal(data, &v); e != nil {
			return errors.New("invalid private AI config")
		}
		token = v.Token
	}
	ro, e := redis.ParseURL(cfg.RedisURL)
	if e != nil {
		return errors.New("invalid Redis URL")
	}
	ro.DialTimeout = 3 * time.Second
	ro.ReadTimeout = 2 * time.Second
	ro.WriteTimeout = 2 * time.Second
	ro.PoolSize = 12
	cache := redis.NewClient(ro)
	defer cache.Close()
	if e = cache.Ping(ctx).Err(); e != nil {
		return errors.New("admin Redis unavailable")
	}
	gin.SetMode(gin.ReleaseMode)
	signer, e := assets.NewSigner(cfg.OSSRegion, cfg.OSSBucket, cfg.OSSEndpoint, cfg.OSSCredentialSource)
	if e != nil {
		return e
	}
	app, e := admin.New(admin.Config{Origin: origin, Secure: strings.HasPrefix(origin, "https://"), WebRoot: root, AIURL: cfg.AIUpstream, AIToken: token, AIClientToken: cfg.AIServiceToken, Signer: signer, Operations: os.Getenv("ADMIN_SYSTEMD") == "true", RuntimeRoot: os.Getenv("ADMIN_RUNTIME_ROOT"), ReleaseRoot: os.Getenv("ADMIN_RELEASE_ROOT")}, db, cache, cfg.RedisPrefix)
	if e != nil {
		return e
	}
	srv := &http.Server{Addr: listen, Handler: app.Router, ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 15 * time.Second, WriteTimeout: 150 * time.Second, IdleTimeout: 60 * time.Second, MaxHeaderBytes: 16 << 10}
	errs := make(chan error, 1)
	go func() { slog.Info("admin listening", "address", listen); errs <- srv.ListenAndServe() }()
	select {
	case e = <-errs:
		if !errors.Is(e, http.ErrServerClosed) {
			return fmt.Errorf("admin listener: %w", e)
		}
	case <-ctx.Done():
	}
	shutdown, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	return srv.Shutdown(shutdown)
}
