package config

import (
	"fmt"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
)

type Config struct {
	Environment, Listen, DatabaseURL, RedisURL, RedisPrefix string
	AllowGuest                                              bool
	PoolSize                                                int32
	SessionLifetime                                         time.Duration
	AuthRate, RequestRate                                   int
	AIUpstream, AIServiceToken                              string
}

func Load() (Config, error) {
	c := Config{Environment: env("STARRY_ENV", "development"), Listen: env("STARRY_LISTEN", "127.0.0.1:8090"),
		DatabaseURL: os.Getenv("DATABASE_URL"), RedisURL: env("REDIS_URL", "redis://127.0.0.1:56379/0"), RedisPrefix: env("REDIS_PREFIX", "starry:"),
		AllowGuest: os.Getenv("ALLOW_TEST_GUEST") == "true", PoolSize: 16, SessionLifetime: 30 * 24 * time.Hour, AuthRate: 20, RequestRate: 600}
	c.AIUpstream, c.AIServiceToken = os.Getenv("AI_UPSTREAM_URL"), os.Getenv("AI_SERVICE_TOKEN")
	if value := os.Getenv("DB_POOL_SIZE"); value != "" {
		n, e := strconv.Atoi(value)
		if e != nil || n < 2 || n > 200 {
			return c, fmt.Errorf("DB_POOL_SIZE must be 2..200")
		}
		c.PoolSize = int32(n)
	}
	return c, c.Validate()
}
func (c Config) Validate() error {
	if (c.AIUpstream == "") != (c.AIServiceToken == "") {
		return fmt.Errorf("AI_UPSTREAM_URL and AI_SERVICE_TOKEN must be configured together")
	}
	if c.AIUpstream != "" {
		u, err := url.Parse(c.AIUpstream)
		if err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || (u.Path != "" && u.Path != "/") {
			return fmt.Errorf("invalid AI_UPSTREAM_URL origin")
		}
	}
	if c.Environment != "development" && c.Environment != "test" && c.Environment != "production" {
		return fmt.Errorf("invalid STARRY_ENV")
	}
	if c.DatabaseURL == "" || c.RedisURL == "" {
		return fmt.Errorf("DATABASE_URL and REDIS_URL are required")
	}
	if c.Environment == "production" {
		if c.AllowGuest {
			return fmt.Errorf("test guest authentication is forbidden in production")
		}
		dbURL, err := url.Parse(c.DatabaseURL)
		if err != nil || (dbURL.Scheme != "postgres" && dbURL.Scheme != "postgresql") || len(dbURL.Query()["sslmode"]) != 1 || dbURL.Query().Get("sslmode") != "verify-full" {
			return fmt.Errorf("production PostgreSQL requires sslmode=verify-full")
		}
		if !strings.HasPrefix(c.RedisURL, "rediss://") {
			return fmt.Errorf("production Redis requires TLS")
		}
	}
	return nil
}
func env(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}
