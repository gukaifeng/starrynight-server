package admin

import (
	"context"
	"crypto/rand"
	"crypto/subtle"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/alexedwards/scs/goredisstore"
	"github.com/alexedwards/scs/v2"
	"github.com/gin-gonic/gin"
	"github.com/go-redis/redis_rate/v10"
	"github.com/google/uuid"
	"github.com/gukaifeng/starrynight-server/internal/assets"
	"github.com/gukaifeng/starrynight-server/internal/billing"
	"github.com/gukaifeng/starrynight-server/internal/identity"
	"github.com/gukaifeng/starrynight-server/internal/store"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/redis/go-redis/v9"
	"io"
	"log/slog"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"
)

type Config struct {
	Origin, WebRoot, AIURL, AIToken, AIClientToken string
	Signer                                         *assets.Signer
	Billing                                        *billing.Client
	Secure                                         bool
	Operations                                     bool
	RuntimeRoot, ReleaseRoot                       string
}
type Principal struct {
	ID       string `json:"id"`
	Username string `json:"username"`
	Role     string `json:"role"`
	Epoch    int64  `json:"-"`
}
type Server struct {
	Router      http.Handler
	DB          *store.Store
	Cache       *redis.Client
	Sessions    *scs.SessionManager
	Auth        *identity.Service
	Config      Config
	Client      *http.Client
	RedisPrefix string
}
type upstreamError struct {
	Code   int
	Detail string
}

func (e upstreamError) Error() string { return e.Detail }

func New(cfg Config, db *store.Store, cache *redis.Client, prefix string) (*Server, error) {
	u, e := url.Parse(cfg.Origin)
	if e != nil || u.Host == "" || u.User != nil || u.Path != "" || u.RawQuery != "" || u.Fragment != "" || (u.Scheme != "https" && !(u.Scheme == "http" && !cfg.Secure && strings.HasPrefix(u.Host, "127.0.0.1:"))) {
		return nil, errors.New("ADMIN_ORIGIN must be an exact HTTPS origin (HTTP loopback only for tests)")
	}
	a, e := identity.New(db, cache, prefix+"admin:", 8*time.Hour)
	if e != nil {
		return nil, e
	}
	sm := scs.New()
	sm.Store = goredisstore.NewWithPrefix(cache, prefix+"admin:session:")
	sm.Lifetime = 8 * time.Hour
	sm.IdleTimeout = 30 * time.Minute
	sm.Cookie.Name = "starry-admin"
	if cfg.Secure {
		sm.Cookie.Name = "__Host-starry-admin"
	}
	sm.Cookie.Path = "/"
	sm.Cookie.HttpOnly = true
	sm.Cookie.Secure = cfg.Secure
	sm.Cookie.SameSite = http.SameSiteStrictMode
	s := &Server{DB: db, Cache: cache, Auth: a, Sessions: sm, Config: cfg, RedisPrefix: prefix, Client: &http.Client{Timeout: 20 * time.Second}}
	r := gin.New()
	_ = r.SetTrustedProxies([]string{"127.0.0.1", "::1"})
	r.Use(gin.Recovery(), s.headers)
	r.GET("/health/ready", s.ready)
	r.POST("/admin-api/v1/login", s.origin, s.login)
	api := r.Group("/admin-api/v1", s.require)
	api.Use(s.csrf)
	api.GET("/session", func(c *gin.Context) {
		c.JSON(200, gin.H{"user": c.MustGet("admin"), "csrf": sm.GetString(c.Request.Context(), "csrf")})
	})
	api.POST("/logout", func(c *gin.Context) {
		if e := sm.Destroy(c.Request.Context()); e != nil {
			fail(c, e)
			return
		}
		c.JSON(200, gin.H{"ok": true})
	})
	api.GET("/resources", func(c *gin.Context) { c.JSON(200, Resources) })
	api.GET("/overview", s.overview)
	api.GET("/billing", s.bills)
	api.GET("/billing/analysis", s.billAnalysis)
	api.GET("/discovery", s.discovery)
	api.GET("/discovery/:id/media/:kind", s.discoveryMedia)
	api.GET("/resources/:resource", s.list)
	api.POST("/resources/:resource/mutate", s.mutate)
	api.POST("/create/:resource", s.create)
	api.GET("/users/:id/avatar", s.avatar)
	api.POST("/users/:id/avatar", s.replaceAvatar)
	api.GET("/record-images/:kind/:id/:variant", s.recordImage)
	api.Any("/ai/*path", s.ai)
	api.GET("/operations", s.operations)
	api.POST("/operations/:unit/restart", s.restart)
	s.managementRoutes(api)
	s.directoryRoutes(api)
	r.NoRoute(func(c *gin.Context) {
		if strings.HasPrefix(c.Request.URL.Path, "/admin-api") || c.Request.Method != "GET" {
			c.JSON(404, gin.H{"error": "接口不存在"})
			return
		}
		name := filepath.Clean("/" + c.Request.URL.Path)
		path := filepath.Join(cfg.WebRoot, name)
		if st, e := os.Stat(path); e != nil || st.IsDir() {
			path = filepath.Join(cfg.WebRoot, "index.html")
		}
		if strings.Contains(name, "/assets/") {
			c.Header("Cache-Control", "public,max-age=31536000,immutable")
		}
		c.File(path)
	})
	s.Router = sm.LoadAndSave(r)
	return s, nil
}
func (s *Server) headers(c *gin.Context) {
	c.Header("X-Content-Type-Options", "nosniff")
	c.Header("Referrer-Policy", "same-origin")
	c.Header("X-Frame-Options", "DENY")
	c.Header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self' data: blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
	c.Header("Cache-Control", "no-store")
	limit := int64(1 << 20)
	if c.Request.Method == "POST" && (c.Request.URL.Path == "/admin-api/v1/library/upload" || c.Request.URL.Path == "/admin-api/v1/objects/upload") {
		limit = 512 << 20
	}
	c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, limit)
	c.Next()
}
func (s *Server) origin(c *gin.Context) {
	if c.GetHeader("Origin") != s.Config.Origin {
		c.AbortWithStatusJSON(403, gin.H{"error": "请从管理平台原页面执行此操作"})
		return
	}
	c.Next()
}
func (s *Server) csrf(c *gin.Context) {
	if c.Request.Method == "GET" || c.Request.Method == "HEAD" {
		c.Next()
		return
	}
	token := s.Sessions.GetString(c.Request.Context(), "csrf")
	if c.GetHeader("Origin") != s.Config.Origin || token == "" || subtle.ConstantTimeCompare([]byte(token), []byte(c.GetHeader("X-CSRF-Token"))) != 1 {
		c.AbortWithStatusJSON(403, gin.H{"error": "页面已过期，请刷新后重试"})
		return
	}
	if s.Config.RuntimeRoot != "" {
		if _, e := os.Stat(filepath.Join(s.Config.RuntimeRoot, "data/admin/maintenance.json")); e == nil {
			c.AbortWithStatusJSON(503, gin.H{"error": "维护任务执行中，暂时不能修改数据"})
			return
		}
	}
	c.Next()
}
func (s *Server) require(c *gin.Context) {
	id := s.Sessions.GetString(c.Request.Context(), "admin_id")
	var p Principal
	var disabled bool
	e := s.DB.Pool.QueryRow(c.Request.Context(), "SELECT id::text,username,role,session_epoch,disabled FROM admin_users WHERE id=$1", idOrNull(id)).Scan(&p.ID, &p.Username, &p.Role, &p.Epoch, &disabled)
	if errors.Is(e, pgx.ErrNoRows) || disabled || id == "" || e == nil && p.Epoch != s.Sessions.GetInt64(c.Request.Context(), "epoch") {
		c.AbortWithStatusJSON(401, gin.H{"error": "请登录管理账户"})
		return
	}
	if e != nil {
		c.AbortWithStatusJSON(503, gin.H{"error": "管理认证暂不可用"})
		return
	}
	c.Set("admin", p)
	c.Next()
}
func idOrNull(v string) any {
	if v == "" {
		return nil
	}
	return v
}
func (s *Server) login(c *gin.Context) {
	limit, e := redis_rate.NewLimiter(s.Cache).Allow(c.Request.Context(), "admin-login:"+c.ClientIP(), redis_rate.PerMinute(10))
	if e != nil {
		c.JSON(503, gin.H{"error": "认证服务暂不可用"})
		return
	}
	if limit.Allowed == 0 {
		c.JSON(429, gin.H{"error": "尝试次数较多，请稍后再试"})
		return
	}
	var body struct {
		Username string `json:"username"`
		Password string `json:"password"`
	}
	if c.ShouldBindJSON(&body) != nil || len(body.Password) > 128 || len(body.Username) > 32 {
		c.JSON(400, gin.H{"error": "请输入有效的账号和密码"})
		return
	}
	var p Principal
	var hash string
	var disabled bool
	e = s.DB.Pool.QueryRow(c.Request.Context(), "SELECT id::text,username,role,session_epoch,password_hash,disabled FROM admin_users WHERE username=$1", strings.ToLower(body.Username)).Scan(&p.ID, &p.Username, &p.Role, &p.Epoch, &hash, &disabled)
	if e != nil && !errors.Is(e, pgx.ErrNoRows) {
		fail(c, e)
		return
	}
	check := s.Auth.Verify(c.Request.Context(), body.Password, hash)
	if errors.Is(check, identity.ErrCapacity) {
		c.JSON(429, gin.H{"error": "认证繁忙，请稍后重试"})
		return
	}
	if check != nil || e != nil || disabled {
		c.JSON(401, gin.H{"error": "账号或密码不正确"})
		return
	}
	if e = s.Sessions.RenewToken(c.Request.Context()); e != nil {
		fail(c, e)
		return
	}
	b := make([]byte, 32)
	if _, e = rand.Read(b); e != nil {
		fail(c, e)
		return
	}
	token := base64.RawURLEncoding.EncodeToString(b)
	s.Sessions.Put(c.Request.Context(), "admin_id", p.ID)
	s.Sessions.Put(c.Request.Context(), "epoch", p.Epoch)
	s.Sessions.Put(c.Request.Context(), "csrf", token)
	c.JSON(200, gin.H{"user": p, "csrf": token})
}
func writable(c *gin.Context, owner bool) bool {
	p := c.MustGet("admin").(Principal)
	if p.Role == "viewer" || owner && p.Role != "owner" {
		c.JSON(403, gin.H{"error": "此操作需要更高管理权限"})
		return false
	}
	return true
}
func fail(c *gin.Context, e error) {
	if c.Request.Context().Err() != nil {
		return
	}
	var upstream upstreamError
	if errors.As(e, &upstream) {
		c.JSON(upstream.Code, gin.H{"error": upstream.Detail})
		return
	}
	var pgerr *pgconn.PgError
	if errors.As(e, &pgerr) {
		slog.Warn("admin database operation failed", "code", pgerr.Code, "message", pgerr.Message)
	}
	code, msg := 500, "操作失败，请刷新后重试"
	var v store.ValidationError
	switch {
	case errors.Is(e, context.DeadlineExceeded):
		code, msg = 503, "查询超时，请缩小搜索范围后重试"
	case errors.Is(e, store.ErrConflict):
		code, msg = 409, "数据已被修改，请刷新后再编辑"
	case errors.Is(e, store.ErrNotFound), errors.Is(e, pgx.ErrNoRows):
		code, msg = 404, "目标不存在"
	case errors.Is(e, store.ErrForbidden):
		code, msg = 403, "此操作不被允许"
	case pgerr != nil && pgerr.Code == "23505":
		code, msg = 409, "目标标识已存在，请刷新后检查"
	case pgerr != nil && pgerr.Code == "23503":
		code, msg = 400, "关联对象不存在，或仍有记录引用它"
	case pgerr != nil && strings.HasPrefix(pgerr.Code, "22"):
		code, msg = 400, "字段格式不正确，请检查标识和内容"
	case errors.As(e, &v):
		code, msg = 400, v.Message
	}
	c.JSON(code, gin.H{"error": msg})
}
func (s *Server) ready(c *gin.Context) {
	ctx, cancel := context.WithTimeout(c.Request.Context(), 3*time.Second)
	defer cancel()
	if s.DB.Pool.Ping(ctx) != nil || s.Cache.Ping(ctx).Err() != nil {
		c.JSON(503, gin.H{"status": "unavailable"})
		return
	}
	c.JSON(200, gin.H{"status": "ok"})
}
func columns(r Resource) string { return strings.Join(r.Fields, ",") }
func keyExpression(r Resource) string {
	xs := []string{}
	for _, k := range r.Keys {
		xs = append(xs, "COALESCE("+k+"::text,'')")
	}
	return "jsonb_build_array(" + strings.Join(xs, ",") + ")::text"
}

type Page struct {
	Items []map[string]any `json:"items"`
	Next  string           `json:"next"`
}

func (s *Server) list(c *gin.Context) {
	r, ok := resource(c.Param("resource"))
	if !ok {
		c.JSON(404, gin.H{"error": "未知分类"})
		return
	}
	ctx := c.Request.Context()
	key := keyExpression(r)
	q := strings.NewReplacer(`\`, `\\`, "%", `\%`, "_", `\_`).Replace(c.Query("q"))
	if len(q) > 200 {
		c.JSON(400, gin.H{"error": "搜索文字过长"})
		return
	}
	// Only explicitly selected fields can be returned or searched. Passwords,
	// tokens and avatar bytes never enter the query projection.
	query := fmt.Sprintf("SELECT to_jsonb(t),%s FROM (SELECT %s FROM %s) t WHERE %s>$1 AND ($2='' OR to_jsonb(t)::text ILIKE $3) ORDER BY %s LIMIT 51", key, columns(r), r.ID, key, key)
	rows, e := s.DB.Pool.Query(ctx, query, c.Query("after"), q, "%"+q+"%")
	if e != nil {
		fail(c, e)
		return
	}
	defer rows.Close()
	page := Page{Items: []map[string]any{}}
	last := ""
	for rows.Next() {
		var data map[string]any
		var cursor string
		if e = rows.Scan(&data, &cursor); e != nil {
			fail(c, e)
			return
		}
		if len(page.Items) == 50 {
			page.Next = last
			break
		}
		last = cursor
		page.Items = append(page.Items, data)
	}
	if e = rows.Err(); e != nil {
		fail(c, e)
		return
	}
	c.JSON(200, page)
}
func (s *Server) overview(c *gin.Context) {
	counts := map[string]int64{}
	for _, r := range Resources {
		var n int64
		if e := s.DB.Pool.QueryRow(c.Request.Context(), "SELECT count(*) FROM "+r.ID).Scan(&n); e != nil {
			fail(c, e)
			return
		}
		counts[r.ID] = n
	}
	states := map[string]bool{"database": s.DB.Pool.Ping(c.Request.Context()) == nil, "redis": s.Cache.Ping(c.Request.Context()).Err() == nil, "admin": true}
	if s.Config.AIURL != "" {
		req, _ := http.NewRequestWithContext(c.Request.Context(), "GET", s.Config.AIURL+"/health", nil)
		resp, e := s.Client.Do(req)
		states["ai"] = e == nil && resp.StatusCode == 200
		if resp != nil {
			resp.Body.Close()
		}
	}
	c.JSON(200, gin.H{"counts": counts, "services": states, "time": time.Now().UTC()})
}
func (s *Server) audit(ctx context.Context, p Principal, request, action, res string, target map[string]string, outcome string) error {
	_, e := s.DB.Pool.Exec(ctx, "INSERT INTO admin_audit(actor_id,actor_name,action,resource,target,outcome,request_id) VALUES($1,$2,$3,$4,$5::jsonb,$6,$7)", p.ID, p.Username, action, res, string(store.JSON(target)), outcome, request)
	return e
}
func (s *Server) record(c *gin.Context, action, res string, target map[string]string, fn func() (any, error)) {
	id := uuid.NewString()
	p := c.MustGet("admin").(Principal)
	if e := s.audit(c.Request.Context(), p, id, action, res, target, "started"); e != nil {
		fail(c, e)
		return
	}
	out, e := fn()
	status := "completed"
	if e != nil {
		status = "failed"
	}
	ctx, cancel := context.WithTimeout(context.WithoutCancel(c.Request.Context()), 3*time.Second)
	defer cancel()
	auditErr := s.audit(ctx, p, id, action, res, target, status)
	if e != nil {
		fail(c, e)
		return
	}
	if auditErr != nil {
		c.JSON(500, gin.H{"error": "操作可能已完成，记录写入失败；请先刷新确认，勿重复提交", "request_id": id})
		return
	}
	c.JSON(200, gin.H{"result": out, "request_id": id})
}

func (s *Server) ai(c *gin.Context) {
	path := c.Param("path")
	if !strings.HasPrefix(path, "/console/") || strings.Contains(path, "..") || strings.Contains(path, "%") || s.Config.AIToken == "" {
		c.JSON(404, gin.H{"error": "推理管理接口未配置"})
		return
	}
	if c.Request.Method != "GET" && !writable(c, true) {
		return
	}
	body, e := io.ReadAll(c.Request.Body)
	if e != nil {
		c.JSON(400, gin.H{"error": "请求过大"})
		return
	}
	call := func() (any, error) {
		req, e := http.NewRequestWithContext(c.Request.Context(), c.Request.Method, s.Config.AIURL+"/v1/admin"+path+"?"+c.Request.URL.RawQuery, strings.NewReader(string(body)))
		if e != nil {
			return nil, e
		}
		req.Header.Set("Authorization", "Bearer "+s.Config.AIToken)
		req.Header.Set("Content-Type", "application/json")
		client := s.Client
		if strings.HasPrefix(path, "/console/voices/") && strings.HasSuffix(path, "/generate") {
			client = &http.Client{Timeout: 120 * time.Second}
		}
		resp, e := client.Do(req)
		if e != nil {
			return nil, errors.New("worker unavailable")
		}
		defer resp.Body.Close()
		var out any
		if e = json.NewDecoder(io.LimitReader(resp.Body, 2<<20)).Decode(&out); e != nil {
			return nil, e
		}
		if resp.StatusCode >= 400 {
			detail := "推理管理操作失败，请刷新后重试"
			if data, ok := out.(map[string]any); ok {
				if text, ok := data["detail"].(string); ok && len(text) < 500 {
					detail = text
				}
			}
			return nil, upstreamError{resp.StatusCode, detail}
		}
		return out, nil
	}
	if c.Request.Method == "GET" {
		out, e := call()
		if c.Writer.Written() {
			return
		}
		if e != nil {
			fail(c, e)
			return
		}
		c.JSON(200, out)
	} else {
		var mutation Mutation
		_ = json.Unmarshal(body, &mutation)
		target := map[string]string{}
		for k, v := range mutation.Keys {
			if len(k) <= 100 && len(v) <= 200 {
				target[k] = v
			}
		}
		s.record(c, c.Request.Method+" "+mutation.Action, "ai"+path, target, call)
	}
}
