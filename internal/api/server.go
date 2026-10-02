package api

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/danielgtaylor/huma/v2"
	"github.com/danielgtaylor/huma/v2/adapters/humagin"
	"github.com/gin-gonic/gin"
	"github.com/go-redis/redis_rate/v10"
	"github.com/google/uuid"
	"github.com/gukaifeng/starrynight-server/internal/assets"
	"github.com/gukaifeng/starrynight-server/internal/config"
	"github.com/gukaifeng/starrynight-server/internal/identity"
	"github.com/gukaifeng/starrynight-server/internal/store"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/redis/go-redis/v9"
	"io"
	"log/slog"
	"math"
	"net"
	"net/http"
	"strconv"
	"strings"
	"time"
)

type actorKey struct{}
type clientIPKey struct{}
type Server struct {
	Config   config.Config
	Store    *store.Store
	Redis    *redis.Client
	Identity *identity.Service
	Router   *gin.Engine
	API      huma.API
	Limiter  *redis_rate.Limiter
	Assets   *assets.Signer
}
type Output[T any] struct{ Body T }
type Mutation struct {
	ExpectedVersion int64          `json:"expected_version" minimum:"0"`
	Patch           map[string]any `json:"patch"`
}
type ListInput struct {
	After string `query:"after" maxLength:"160"`
	Limit int    `query:"limit" minimum:"1" maximum:"200" default:"50"`
}
type IDInput struct {
	ID string `path:"id" maxLength:"120" pattern:"^[a-zA-Z0-9_-]+$"`
}
type Empty struct{}
type OK struct {
	OK bool `json:"ok"`
}

func output[T any](v T, e error) (*Output[T], error) {
	if e != nil {
		return nil, problem(e)
	}
	return &Output[T]{Body: v}, nil
}
func principal(ctx context.Context) store.User { u, _ := ctx.Value(actorKey{}).(store.User); return u }
func problem(e error) error {
	switch {
	case errors.Is(e, store.ErrNotFound):
		return huma.Error404NotFound("resource not found")
	case errors.Is(e, store.ErrConflict), errors.Is(e, store.ErrExists):
		return huma.Error409Conflict(e.Error())
	case errors.Is(e, store.ErrForbidden):
		return huma.Error403Forbidden("operation not permitted")
	case errors.Is(e, identity.ErrCredentials):
		return huma.Error401Unauthorized("invalid credentials or expired session")
	case errors.Is(e, identity.ErrCapacity):
		return huma.Error429TooManyRequests("authentication busy; retry shortly")
	}
	var invalid store.ValidationError
	if errors.As(e, &invalid) {
		return huma.Error422UnprocessableEntity(invalid.Message)
	}
	// Do not log SQL parameters, credentials, request bodies, or private dialogue.
	slog.Error("backend request failed", "error_type", fmt.Sprintf("%T", e))
	return huma.Error503ServiceUnavailable("service temporarily unavailable")
}
func New(c config.Config, db *store.Store, r *redis.Client) (*Server, error) {
	auth, e := identity.New(db, r, c.RedisPrefix, c.SessionLifetime)
	if e != nil {
		return nil, e
	}
	router := gin.New()
	if err := router.SetTrustedProxies([]string{"127.0.0.1/32", "::1/128"}); err != nil {
		return nil, err
	}
	s := &Server{Config: c, Store: db, Redis: r, Identity: auth, Router: router, Limiter: redis_rate.NewLimiter(r)}
	s.Assets, e = assets.NewSigner(c.OSSRegion, c.OSSBucket, c.OSSEndpoint, c.OSSCredentialSource)
	if e != nil {
		return nil, e
	}
	registry := prometheus.NewRegistry()
	durations := prometheus.NewHistogramVec(prometheus.HistogramOpts{Name: "starry_http_duration_seconds", Help: "HTTP latency by route and result", Buckets: prometheus.DefBuckets}, []string{"method", "route", "status"})
	registry.MustRegister(durations, prometheus.NewGoCollector(), prometheus.NewProcessCollector(prometheus.ProcessCollectorOpts{}))
	router.Use(gin.CustomRecoveryWithWriter(io.Discard, func(c *gin.Context, _ any) { c.AbortWithStatus(http.StatusInternalServerError) }))
	router.Use(func(c *gin.Context) {
		c.Request = c.Request.WithContext(context.WithValue(c.Request.Context(), clientIPKey{}, c.ClientIP()))
		c.Header("X-Request-ID", uuid.NewString())
		c.Header("X-Content-Type-Options", "nosniff")
		c.Header("Cache-Control", "no-store")
		start := time.Now()
		c.Next()
		route := c.FullPath()
		if route == "" {
			route = "unmatched"
		}
		durations.WithLabelValues(c.Request.Method, route, strconv.Itoa(c.Writer.Status())).Observe(time.Since(start).Seconds())
	})
	router.GET("/health/live", func(c *gin.Context) { c.JSON(200, gin.H{"status": "ok"}) })
	router.GET("/health/ready", func(c *gin.Context) {
		ctx, cancel := context.WithTimeout(c.Request.Context(), time.Second)
		defer cancel()
		if db.Pool.Ping(ctx) != nil || r.Ping(ctx).Err() != nil {
			c.AbortWithStatus(503)
			return
		}
		c.JSON(200, gin.H{"status": "ready"})
	})
	// Bind metrics to a private listener in production via the reverse proxy.
	router.GET("/metrics", gin.WrapH(promhttp.HandlerFor(registry, promhttp.HandlerOpts{})))
	s.aiRoutes()
	routes := router.Group("")
	routes.Use(func(c *gin.Context) {
		ctx, cancel := context.WithTimeout(c.Request.Context(), 15*time.Second)
		defer cancel()
		c.Request = c.Request.WithContext(ctx)
		c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, 256*1024)
		continued := false
		s.session(http.HandlerFunc(func(_ http.ResponseWriter, r *http.Request) {
			continued = true
			c.Request = r
			c.Next()
		})).ServeHTTP(c.Writer, c.Request)
		if !continued {
			c.Abort()
		}
	})
	cfg := huma.DefaultConfig("StarryNight Platform", "1.0.0")
	if c.Environment == "production" {
		cfg.OpenAPIPath = ""
		cfg.DocsPath = ""
		cfg.SchemasPath = ""
	}
	cfg.Components.SecuritySchemes = map[string]*huma.SecurityScheme{"session": {Type: "http", Scheme: "bearer", Description: "Revocable SCS session; store token in the OS keychain"}}
	s.API = humagin.NewWithGroup(router, routes, cfg)
	s.authRoutes()
	s.accountRoutes()
	s.assetsSupportRoutes()
	s.catalogRoutes()
	s.journalRoutes()
	s.syncRoutes()
	s.goalRoutes()
	s.documentAIRoutes()
	return s, nil
}
func (s *Server) session(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw := r.Header.Get("Authorization")
		token := ""
		if raw != "" {
			if !strings.HasPrefix(raw, "Bearer ") || len(raw) > 256 {
				http.Error(w, "unauthorized", 401)
				return
			}
			token = strings.TrimPrefix(raw, "Bearer ")
		}
		ctx, e := s.Identity.Sessions.Load(r.Context(), token)
		if e != nil {
			http.Error(w, "session store unavailable", 503)
			return
		}
		u := store.User{}
		if token != "" {
			u, e = s.Identity.Principal(ctx)
			if e != nil {
				status := 503
				if errors.Is(e, identity.ErrCredentials) {
					status = 401
				}
				http.Error(w, "session unavailable", status)
				return
			}
			if s.Config.Environment == "production" && u.Guest {
				http.Error(w, "test sessions are unavailable in production", 401)
				return
			}
		}
		ip, _, _ := net.SplitHostPort(r.RemoteAddr)
		if verified, ok := r.Context().Value(clientIPKey{}).(string); ok && verified != "" {
			ip = verified
		}
		key := ip
		if u.ID != "" {
			key = u.ID
		}
		limit := s.Config.RequestRate
		category := "requests:"
		if strings.HasPrefix(r.URL.Path, "/v1/auth/") {
			limit = s.Config.AuthRate
			category = "auth:"
			key = ip
		}
		result, e := s.Limiter.Allow(ctx, s.Config.RedisPrefix+category+key, redis_rate.PerMinute(limit))
		if e != nil {
			http.Error(w, "rate limiter unavailable", 503)
			return
		}
		if result.Allowed == 0 {
			w.Header().Set("Retry-After", strconv.Itoa(max(1, int(math.Ceil(result.RetryAfter.Seconds())))))
			http.Error(w, "rate limited", 429)
			return
		}
		next.ServeHTTP(w, r.WithContext(context.WithValue(ctx, actorKey{}, u)))
	})
}
func (s *Server) required(ctx huma.Context, next func(huma.Context)) {
	if principal(ctx.Context()).ID == "" {
		huma.WriteErr(s.API, ctx, 401, "sign in required")
		return
	}
	next(ctx)
}
func register[I, O any](s *Server, method, path, id string, private bool, handler func(context.Context, *I) (*O, error)) {
	op := huma.Operation{OperationID: id, Method: method, Path: path, MaxBodyBytes: 256 * 1024}
	if private {
		op.Security = []map[string][]string{{"session": {}}}
		op.Middlewares = huma.Middlewares{s.required}
	}
	huma.Register(s.API, op, handler)
}
func (s *Server) OpenAPI() ([]byte, error) { return json.MarshalIndent(s.API.OpenAPI(), "", "  ") }
