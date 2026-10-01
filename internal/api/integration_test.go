package api_test

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"github.com/google/uuid"
	"github.com/gukaifeng/starrynight-server/internal/api"
	"github.com/gukaifeng/starrynight-server/internal/config"
	"github.com/gukaifeng/starrynight-server/internal/identity"
	"github.com/gukaifeng/starrynight-server/internal/store"
	"github.com/gukaifeng/starrynight-server/migrations"
	"github.com/jackc/pgx/v5/pgxpool"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/pressly/goose/v3"
	"github.com/redis/go-redis/v9"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"sort"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

const password = "fixture-password-2026"

type suite struct {
	t       *testing.T
	db      *store.Store
	redis   *redis.Client
	servers []*httptest.Server
	cfg     config.Config
	users   []string
}

func setup(t *testing.T) *suite {
	t.Helper()
	if os.Getenv("STARRY_INTEGRATION") != "1" {
		t.Skip("set STARRY_INTEGRATION=1 with real PostgreSQL and Redis")
	}
	url := os.Getenv("TEST_DATABASE_URL")
	pc, e := pgxpool.ParseConfig(url)
	if e != nil || !strings.HasSuffix(pc.ConnConfig.Database, "_test") {
		t.Fatal("TEST_DATABASE_URL must name a dedicated *_test database")
	}
	conn, e := sql.Open("pgx", url)
	if e != nil {
		t.Fatal(e)
	}
	defer conn.Close()
	provider, e := goose.NewProvider(goose.DialectPostgres, conn, migrations.Files)
	if e != nil {
		t.Fatal(e)
	}
	if _, e = provider.Up(context.Background()); e != nil {
		t.Fatal(e)
	}
	db, e := store.Open(context.Background(), url, 8)
	if e != nil {
		t.Fatal(e)
	}
	options, e := redis.ParseURL(os.Getenv("TEST_REDIS_URL"))
	if e != nil {
		t.Fatal(e)
	}
	cache := redis.NewClient(options)
	if e = cache.Ping(context.Background()).Err(); e != nil {
		t.Fatal(e)
	}
	prefix := "test:" + uuid.NewString() + ":"
	cfg := config.Config{Environment: "test", AllowGuest: true, DatabaseURL: url, RedisPrefix: prefix, SessionLifetime: time.Hour, AuthRate: 10000, RequestRate: 10000}
	s := &suite{t: t, db: db, redis: cache, cfg: cfg}
	for range 2 {
		app, e := api.New(cfg, db, cache)
		if e != nil {
			t.Fatal(e)
		}
		s.servers = append(s.servers, httptest.NewServer(app.Router))
	}
	t.Cleanup(func() {
		for _, server := range s.servers {
			server.Close()
		}
		for _, id := range s.users {
			_ = db.DeleteUser(context.Background(), id)
		}
		iterator := cache.Scan(context.Background(), 0, prefix+"*", 100).Iterator()
		for iterator.Next(context.Background()) {
			cache.Del(context.Background(), iterator.Val())
		}
		cache.Close()
		db.Pool.Close()
	})
	return s
}
func (s *suite) request(instance int, method, path, token string, body any) (int, []byte) {
	s.t.Helper()
	var data []byte
	if body != nil {
		data, _ = json.Marshal(body)
	}
	req, e := http.NewRequest(method, s.servers[instance].URL+path, bytes.NewReader(data))
	if e != nil {
		s.t.Fatal(e)
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	// Client-supplied account headers must never choose the authenticated owner.
	req.Header.Set("X-Starry-Account", "forged-other-account")
	r, e := s.servers[instance].Client().Do(req)
	if e != nil {
		s.t.Fatal(e)
	}
	defer r.Body.Close()
	b, e := io.ReadAll(r.Body)
	if e != nil {
		s.t.Fatal(e)
	}
	return r.StatusCode, b
}
func (s *suite) call(method, path, token string, body any, want int) []byte {
	s.t.Helper()
	status, b := s.request(0, method, path, token, body)
	if status != want {
		s.t.Fatalf("%s %s: expected %d, got %d: %.600s", method, path, want, status, b)
	}
	return b
}
func decode[T any](t *testing.T, data []byte) T {
	t.Helper()
	var value T
	if e := json.Unmarshal(data, &value); e != nil {
		t.Fatal(e)
	}
	return value
}
func (s *suite) register() identity.Session {
	name := "test_" + strings.ReplaceAll(uuid.NewString(), "-", "")[:20]
	v := decode[identity.Session](s.t, s.call("POST", "/v1/auth/register", "", map[string]any{"username": name, "password": password, "display_name": "测试伙伴"}, 200))
	s.users = append(s.users, v.User.ID)
	return v
}
func TestAccountAndJournalIsolation(t *testing.T) {
	s := setup(t)
	a, b := s.register(), s.register()
	s.call("GET", "/v1/me", "", nil, 401)
	s.call("GET", "/v1/me", "invalid", nil, 401)
	status, data := s.request(1, "GET", "/v1/me", a.Token, nil)
	if status != 200 || decode[store.User](t, data).ID != a.User.ID {
		t.Fatal("shared session did not work on the other API replica")
	}
	var hash string
	if e := s.db.Pool.QueryRow(context.Background(), "SELECT password_hash FROM users WHERE id=$1", a.User.ID).Scan(&hash); e != nil || !strings.HasPrefix(hash, "$argon2id$") {
		t.Fatal("password was not hashed")
	}
	s.call("POST", "/v1/auth/register", "", map[string]any{"username": strings.ToUpper(a.User.Username), "password": password, "display_name": "重复"}, 409)
	s.call("POST", "/v1/auth/login", "", map[string]any{"username": a.User.Username, "password": "incorrect-password"}, 401)
	settings := decode[store.Document](t, s.call("GET", "/v1/me/settings", a.Token, nil, 200))
	settings = decode[store.Document](t, s.call("PATCH", "/v1/me/settings", a.Token, map[string]any{"expected_version": settings.Version, "patch": map[string]any{"theme": "ocean", "default_nickname": "小星", "extensions": map[string]any{"future.audio": map[string]any{"spatial": true}}}}, 200))
	s.call("PATCH", "/v1/me/settings", a.Token, map[string]any{"expected_version": 1, "patch": map[string]any{"theme": "ember"}}, 409)
	settings = decode[store.Document](t, s.call("PATCH", "/v1/me/settings", a.Token, map[string]any{"expected_version": settings.Version, "patch": map[string]any{"chat_font_size": 19}}, 200))
	if settings.Data["extensions"] == nil || settings.Data["theme"] != "ocean" || settings.Data["default_nickname"] != "小星" {
		t.Fatal("merge patch lost future fields")
	}
	other := decode[store.Document](t, s.call("GET", "/v1/me/settings", b.Token, nil, 200))
	if other.Data["theme"] != "silver" || other.Data["default_nickname"] != nil {
		t.Fatal("settings leaked between accounts")
	}
	settings = decode[store.Document](t, s.call("PATCH", "/v1/me/settings", a.Token, map[string]any{"expected_version": settings.Version, "patch": map[string]any{"default_nickname": ""}}, 200))
	status, data = s.request(1, "GET", "/v1/me/settings", a.Token, nil)
	if status != 200 || decode[store.Document](t, data).Data["default_nickname"] != "" {
		t.Fatal("cleared nickname did not persist across API replicas")
	}
	author := decode[store.Author](t, s.call("GET", "/v1/me/author", a.Token, nil, 200))
	s.call("PUT", "/v1/me/follows/"+author.ID, a.Token, nil, 403)
	s.call("PUT", "/v1/me/follows/"+author.ID, b.Token, nil, 200)
	s.call("PUT", "/v1/me/follows/"+author.ID, b.Token, nil, 200)
	public := decode[store.Author](t, s.call("GET", "/v1/authors/"+author.ID, "", nil, 200))
	if public.Followers != 1 {
		t.Fatal("duplicate follow counted twice")
	}
	character := "character-" + uuid.NewString()
	create := map[string]any{"id": character, "base_id": "anime-kipfel", "name": "私人角色", "description": "只属于 A", "visibility": "private", "data": map[string]any{"schema_version": 1}}
	s.call("POST", "/v1/characters", a.Token, create, 200)
	s.call("GET", "/v1/characters/"+character, b.Token, nil, 404)
	s.call("PUT", "/v1/characters/"+character, b.Token, map[string]any{"name": "冒名修改", "description": "", "visibility": "public", "data": map[string]any{}, "expected_version": 1}, 404)
	s.call("PUT", "/v1/characters/"+character, a.Token, map[string]any{"name": "已发布伙伴", "description": "公开介绍", "visibility": "public", "data": map[string]any{}, "expected_version": 1}, 200)
	s.call("GET", "/v1/characters/"+character, b.Token, nil, 200)
	s.call("PUT", "/v1/me/subscriptions/"+character, b.Token, nil, 200)
	id := uuid.NewString()
	path := "/v1/conversations/anime-kipfel/messages/" + id
	message := map[string]any{"expected_version": 0, "role": "user", "text": "这是 A 的私密记忆", "created_at": time.Now().UTC(), "data": map[string]any{"source": "client-import"}}
	first := decode[store.Message](t, s.call("PUT", path, a.Token, message, 200))
	again := decode[store.Message](t, s.call("PUT", path, a.Token, message, 200))
	if first.Sequence != again.Sequence || first.Version != again.Version {
		t.Fatal("duplicate message")
	}
	otherMessages := decode[store.Page[store.Message]](t, s.call("GET", "/v1/conversations/anime-kipfel/messages", b.Token, nil, 200))
	if len(otherMessages.Items) != 0 {
		t.Fatal("message leaked")
	}
	conv := decode[store.Page[store.Conversation]](t, s.call("GET", "/v1/conversations", a.Token, nil, 200)).Items[0]
	s.call("PUT", "/v1/conversations/anime-kipfel", a.Token, map[string]any{"expected_version": conv.Version, "hidden": true, "pinned": false}, 200)
	if len(decode[store.Page[store.Message]](t, s.call("GET", "/v1/conversations/anime-kipfel/messages", a.Token, nil, 200)).Items) != 1 {
		t.Fatal("hide deleted messages")
	}
	for i := range 5 {
		message["text"] = fmt.Sprint("后续消息", i)
		s.call("PUT", "/v1/conversations/anime-kipfel/messages/"+uuid.NewString(), a.Token, message, 200)
	}
	conv = decode[store.Page[store.Conversation]](t, s.call("GET", "/v1/conversations", a.Token, nil, 200)).Items[0]
	if conv.Hidden {
		t.Fatal("new message did not restore conversation")
	}
	count := 0
	cursor := ""
	seen := map[string]bool{}
	for {
		page := decode[store.Page[store.Message]](t, s.call("GET", "/v1/conversations/anime-kipfel/messages?limit=2&after="+cursorOrZero(cursor), a.Token, nil, 200))
		for _, v := range page.Items {
			if seen[v.ID] {
				t.Fatal("duplicate page item")
			}
			seen[v.ID] = true
			count++
		}
		cursor = page.Next
		if cursor == "" {
			break
		}
	}
	if count != 6 {
		t.Fatalf("pagination lost messages: %d", count)
	}
	memoryPath := "/v1/conversations/anime-kipfel/memories/" + uuid.NewString()
	s.call("PUT", memoryPath, a.Token, map[string]any{"expected_version": 0, "data": map[string]any{"text": "喜欢雨天"}}, 200)
	s.call("DELETE", memoryPath+"?version=2", a.Token, nil, 409)
	s.call("DELETE", memoryPath+"?version=1", a.Token, nil, 200)
	changes := decode[store.Page[store.Change]](t, s.call("GET", "/v1/sync?limit=200", a.Token, nil, 200))
	found := false
	for i, c := range changes.Items {
		if i > 0 && c.Revision != changes.Items[i-1].Revision+1 {
			t.Fatal("sync feed has a gap")
		}
		if c.Kind == "memory" && c.Deleted {
			found = true
		}
	}
	if !found {
		t.Fatal("missing deletion tombstone")
	}
	s.call("GET", "/v1/me/export", a.Token, nil, 200)
	s.call("GET", "/v1/conversations/anime-kipfel/memories?after=invalid", a.Token, nil, 422)
	s.call("PUT", memoryPath, a.Token, map[string]any{"expected_version": 0, "data": map[string]any{"text": "stale recreation"}}, 409)
	s.call("DELETE", "/v1/conversations/anime-kipfel/messages", a.Token, nil, 200)
	cleared := decode[store.Page[store.Message]](t, s.call("GET", "/v1/conversations/anime-kipfel/messages", a.Token, nil, 200))
	if len(cleared.Items) != 0 {
		t.Fatal("clear retained active messages")
	}
	exported := decode[store.Page[store.Change]](t, s.call("GET", "/v1/me/export", a.Token, nil, 200))
	for _, change := range exported.Items {
		if change.Kind == "message" {
			t.Fatal("clear retained message bodies in sync/export")
		}
	}

}
func cursorOrZero(v string) string {
	if v == "" {
		return "0"
	}
	return v
}
func TestGuestUpgradeSessionRevocationAndCAS(t *testing.T) {
	s := setup(t)
	guest := decode[identity.Session](t, s.call("POST", "/v1/auth/guest", "", nil, 200))
	s.users = append(s.users, guest.User.ID)
	s.call("PATCH", "/v1/me/settings", guest.Token, map[string]any{"expected_version": 1, "patch": map[string]any{"theme": "forest"}}, 200)
	name := "test_" + strings.ReplaceAll(uuid.NewString(), "-", "")[:20]
	account := decode[identity.Session](t, s.call("POST", "/v1/auth/register", guest.Token, map[string]any{"username": name, "password": password, "display_name": "正式伙伴"}, 200))
	if account.User.ID != guest.User.ID || account.User.Guest {
		t.Fatal("guest migration changed owner")
	}
	s.call("GET", "/v1/me", guest.Token, nil, 401)
	document := decode[store.Document](t, s.call("GET", "/v1/me/settings", account.Token, nil, 200))
	if document.Data["theme"] != "forest" {
		t.Fatal("guest settings lost")
	}
	var successes, conflicts atomic.Int32
	var wg sync.WaitGroup
	for i := range 20 {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			status, _ := s.request(i%2, "PATCH", "/v1/me/settings", account.Token, map[string]any{"expected_version": document.Version, "patch": map[string]any{"race_winner": i}})
			switch status {
			case 200:
				successes.Add(1)
			case 409:
				conflicts.Add(1)
			default:
				t.Errorf("unexpected CAS status %d", status)
			}
		}(i)
	}
	wg.Wait()
	if successes.Load() != 1 || conflicts.Load() != 19 {
		t.Fatalf("lost-update protection failed: success %d, conflicts %d", successes.Load(), conflicts.Load())
	}
	rotated := decode[identity.Session](t, s.call("POST", "/v1/auth/refresh", account.Token, nil, 200))
	s.call("GET", "/v1/me", account.Token, nil, 401)
	login := decode[identity.Session](t, s.call("POST", "/v1/auth/login", "", map[string]any{"username": name, "password": password}, 200))
	changed := decode[identity.Session](t, s.call("POST", "/v1/me/password", rotated.Token, map[string]any{"current_password": password, "new_password": "new-fixture-password-2026"}, 200))
	s.call("GET", "/v1/me", login.Token, nil, 401)
	s.call("GET", "/v1/me", rotated.Token, nil, 401)
	s.call("POST", "/v1/auth/logout", changed.Token, nil, 200)
	s.call("GET", "/v1/me", changed.Token, nil, 401)
	final := decode[identity.Session](t, s.call("POST", "/v1/auth/login", "", map[string]any{"username": name, "password": "new-fixture-password-2026"}, 200))
	s.call("DELETE", "/v1/me", final.Token, map[string]any{"password": "new-fixture-password-2026", "confirmation": "DELETE"}, 200)
	s.call("GET", "/v1/me", final.Token, nil, 401)
}

// This is a bounded functional workload, not a claim about production capacity.
// Run with real PostgreSQL and Redis; it never contacts an AI provider.
func TestReplicaWorkload(t *testing.T) {
	s := setup(t)
	const accounts = 16
	const requests = 320
	sessions := make([]identity.Session, accounts)
	for i := range sessions {
		sessions[i] = decode[identity.Session](t, s.call("POST", "/v1/auth/guest", "", nil, 200))
		s.users = append(s.users, sessions[i].User.ID)
	}
	timings := make([]time.Duration, requests)
	var failures atomic.Int32
	jobs := make(chan int)
	var workers sync.WaitGroup
	started := time.Now()
	for range 32 {
		workers.Go(func() {
			for i := range jobs {
				session := sessions[i%accounts]
				begin := time.Now()
				status, _ := s.request(i%2, "PUT", "/v1/conversations/anime-kipfel/messages/"+uuid.NewString(), session.Token, map[string]any{
					"expected_version": 0, "role": "user", "text": "workload fixture", "created_at": time.Now().UTC(), "data": map[string]any{"fixture": true},
				})
				timings[i] = time.Since(begin)
				if status != 200 {
					failures.Add(1)
				}
			}
		})
	}
	for i := range requests {
		jobs <- i
	}
	close(jobs)
	workers.Wait()
	elapsed := time.Since(started)
	if failures.Load() != 0 {
		t.Fatalf("workload failures: %d", failures.Load())
	}
	for _, session := range sessions {
		page := decode[store.Page[store.Message]](t, s.call("GET", "/v1/conversations/anime-kipfel/messages?limit=200", session.Token, nil, 200))
		if len(page.Items) != requests/accounts {
			t.Fatal("cross-account write loss or leakage")
		}
	}
	sort.Slice(timings, func(i, j int) bool { return timings[i] < timings[j] })
	t.Logf("two replicas / 32 clients / 16 accounts: %d writes in %s, %.1f requests/s, p50=%s p95=%s p99=%s; local functional workload only", requests, elapsed, float64(requests)/elapsed.Seconds(), timings[requests/2], timings[requests*95/100], timings[requests*99/100])
}
