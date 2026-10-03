package admin

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"github.com/alexedwards/argon2id"
	"github.com/google/uuid"
	"github.com/gukaifeng/starrynight-server/internal/store"
	"github.com/gukaifeng/starrynight-server/migrations"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/pressly/goose/v3"
	"github.com/redis/go-redis/v9"
	"io"
	"net/http"
	"net/http/cookiejar"
	"net/http/httptest"
	"net/url"
	"os"
	"strings"
	"testing"
	"time"
)

func TestConsoleAuthenticationAndBusinessEdits(t *testing.T) {
	if os.Getenv("STARRY_INTEGRATION") != "1" {
		t.Skip("real PostgreSQL / Redis integration")
	}
	ctx := context.Background()
	dbURL := os.Getenv("TEST_DATABASE_URL")
	u, e := url.Parse(dbURL)
	if e != nil || !strings.HasSuffix(u.Path, "_test") {
		t.Fatal("dedicated test DB required")
	}
	conn, e := sql.Open("pgx", dbURL)
	if e != nil {
		t.Fatal(e)
	}
	defer conn.Close()
	provider, e := goose.NewProvider(goose.DialectPostgres, conn, migrations.Files)
	if e != nil {
		t.Fatal(e)
	}
	if _, e = provider.Up(ctx); e != nil {
		t.Fatal(e)
	}
	db, e := store.Open(ctx, dbURL, 8)
	if e != nil {
		t.Fatal(e)
	}
	defer db.Pool.Close()
	ro, e := redis.ParseURL(os.Getenv("TEST_REDIS_URL"))
	if e != nil {
		t.Fatal(e)
	}
	cache := redis.NewClient(ro)
	defer cache.Close()
	prefix := "admin-test:" + uuid.NewString() + ":"
	defer func() {
		iter := cache.Scan(ctx, 0, prefix+"*", 100).Iterator()
		for iter.Next(ctx) {
			cache.Del(ctx, iter.Val())
		}
	}()
	password := "fixture-admin-password"
	hash, e := argon2id.CreateHash(password, argon2id.DefaultParams)
	if e != nil {
		t.Fatal(e)
	}
	owner, viewer := uuid.NewString(), uuid.NewString()
	ownerName := "o_" + strings.ReplaceAll(uuid.NewString(), "-", "")[:15]
	viewerName := "v_" + strings.ReplaceAll(uuid.NewString(), "-", "")[:15]
	for i, id := range []string{owner, viewer} {
		name, role := ownerName, "owner"
		if i == 1 {
			name, role = viewerName, "viewer"
		}
		if _, e = db.Pool.Exec(ctx, "INSERT INTO admin_users(id,username,password_hash,role) VALUES($1,$2,$3,$4)", id, name, hash, role); e != nil {
			t.Fatal(e)
		}
	}
	defer func() {
		db.Pool.Exec(ctx, "DELETE FROM admin_audit WHERE actor_id IN ($1,$2)", owner, viewer)
		db.Pool.Exec(ctx, "DELETE FROM admin_users WHERE id IN ($1,$2)", owner, viewer)
	}()
	artworkRoot := t.TempDir()
	artwork := installArtworkFixture(t, artworkRoot)
	app, e := New(Config{AIToken: "private-cache-fixture", Origin: "http://127.0.0.1:18100", WebRoot: t.TempDir(), RuntimeRoot: artworkRoot}, db, cache, prefix)
	if e != nil {
		t.Fatal(e)
	}
	srv := httptest.NewServer(app.Router)
	defer srv.Close()
	other, e := New(app.Config, db, cache, prefix)
	if e != nil {
		t.Fatal(e)
	}
	replica := httptest.NewServer(other.Router)
	defer replica.Close()
	jar, _ := cookiejar.New(nil)
	client := &http.Client{Jar: jar}
	csrf := ""
	request := func(base, method, path string, body any, origin, token string) (int, []byte) {
		t.Helper()
		data, _ := json.Marshal(body)
		req, _ := http.NewRequest(method, base+"/admin-api/v1"+path, bytes.NewReader(data))
		req.Header.Set("Content-Type", "application/json")
		if origin != "" {
			req.Header.Set("Origin", origin)
		}
		req.Header.Set("X-CSRF-Token", token)
		resp, e := client.Do(req)
		if e != nil {
			t.Fatal(e)
		}
		defer resp.Body.Close()
		out, _ := io.ReadAll(resp.Body)
		return resp.StatusCode, out
	}
	assert := func(got, want int, data []byte) {
		t.Helper()
		if got != want {
			t.Fatalf("status %d want %d: %s", got, want, data)
		}
	}
	code, data := request(srv.URL, "GET", "/resources", nil, "", "")
	assert(code, 401, data)
	code, data = request(srv.URL, "GET", "/billing?month=2026-10", nil, "", "")
	assert(code, 401, data)
	code, data = request(srv.URL, "GET", "/billing/analysis?month=2026-10", nil, "", "")
	assert(code, 401, data)
	code, data = request(srv.URL, "GET", "/directory/users", nil, "", "")
	assert(code, 401, data)
	for _, path := range []string{"/discovery", "/discovery/anime-kipfel/media/cover", "/objects?folders=true", "/objects/detail?key=models/a.glb"} {
		code, data = request(srv.URL, "GET", path, nil, "", "")
		assert(code, 401, data)
	}
	code, data = request(srv.URL, "GET", "/record-images/character/anime-kipfel/avatar", nil, "", "")
	assert(code, 401, data)
	code, data = request(srv.URL, "POST", "/login", map[string]string{"username": ownerName, "password": password}, "https://evil.test", "")
	assert(code, 403, data)
	code, data = request(srv.URL, "POST", "/login", map[string]string{"username": ownerName, "password": password}, app.Config.Origin, "")
	assert(code, 200, data)
	var session struct {
		CSRF string `json:"csrf"`
	}
	json.Unmarshal(data, &session)
	csrf = session.CSRF
	code, data = request(srv.URL, "GET", "/billing?month="+time.Now().In(time.FixedZone("Shanghai", 8*3600)).Format("2006-01"), nil, "", "")
	assert(code, 200, data)
	if !bytes.Contains(data, []byte(`"NotConfigured"`)) || bytes.Contains(data, []byte(`"status":"ready"`)) {
		t.Fatal("unconfigured billing claimed successful amounts")
	}
	testBillingReports(t, app, func(path string) (int, []byte) { return request(srv.URL, "GET", path, nil, "", "") })
	testDiscoveryAndBucket(t, app, func(path string) (int, []byte) { return request(srv.URL, "GET", path, nil, "", "") })
	code, data = request(srv.URL, "GET", "/record-images/character/anime-kipfel/cover", nil, "", "")
	assert(code, 200, data)
	if !bytes.Equal(data, artwork) {
		t.Fatal("wrong character artwork served")
	}
	code, data = request(srv.URL, "GET", "/record-images/character/missing/avatar", nil, "", "")
	assert(code, 404, data)

	// Inspector handles never expose a bearer key or JSON credentials.
	cacheKey := prefix + "config:fixture"
	cache.Set(ctx, cacheKey, `{"count":3,"api_key":"PRIVATE_CACHE_SECRET"}`, 0)
	code, data = request(srv.URL, "GET", "/cache?cursor=0", nil, "", "")
	assert(code, 200, data)
	var listing struct {
		Items []map[string]any `json:"items"`
	}
	json.Unmarshal(data, &listing)
	var handle string
	for _, r := range listing.Items {
		if r["key"] == cacheKey {
			handle = r["id"].(string)
			if r["ttl_seconds"] != float64(-1) {
				t.Fatal("persistent TTL lost")
			}
		}
	}
	if handle == "" || strings.Contains(handle, cacheKey) {
		t.Fatal("opaque cache handle missing")
	}
	code, data = request(srv.URL, "GET", "/cache/detail?id="+url.QueryEscape(handle), nil, "", "")
	assert(code, 200, data)
	if strings.Contains(string(data), "PRIVATE_CACHE_SECRET") {
		t.Fatal("JSON credential exposed")
	}
	var detail map[string]any
	json.Unmarshal(data, &detail)
	clear := map[string]any{"id": handle, "version": detail["version"], "confirmed": true}
	cache.Set(ctx, cacheKey, "changed", 0)
	code, data = request(srv.URL, "POST", "/cache/clear", clear, app.Config.Origin, csrf)
	assert(code, 400, data)
	code, data = request(srv.URL, "GET", "/cache/detail?id="+url.QueryEscape(handle), nil, "", "")
	assert(code, 200, data)
	json.Unmarshal(data, &detail)
	clear["version"] = detail["version"]
	code, data = request(srv.URL, "POST", "/cache/clear", clear, app.Config.Origin, csrf)
	assert(code, 200, data)
	if cache.Exists(ctx, cacheKey).Val() != 0 {
		t.Fatal("targeted cache clear failed")
	}
	code, data = request(srv.URL, "GET", "/cache/detail?id=forged", nil, "", "")
	assert(code, 400, data)

	code, data = request(replica.URL, "GET", "/session", nil, "", "")
	assert(code, 200, data)
	for _, r := range Resources {
		t.Log("read resource", r.ID)
		code, data = request(srv.URL, "GET", "/resources/"+r.ID, nil, "", "")
		assert(code, 200, data)
		if strings.Contains(string(data), "password_hash") {
			t.Fatal("password hash exposed")
		}
	}
	u2, e := db.CreateUser(ctx, "test_"+strings.ReplaceAll(uuid.NewString(), "-", "")[:16], hash, "before", false)
	if e != nil {
		t.Fatal(e)
	}
	defer db.DeleteUser(ctx, u2.ID)
	t.Run("entity directories and exact scopes", func(t *testing.T) {
		testEntityDirectories(t, db, u2.ID, func(path string) (int, []byte) {
			return request(srv.URL, "GET", path, nil, "", "")
		})
	})
	t.Run("worker owners link only to real accounts", func(t *testing.T) {
		unknown := uuid.NewString()
		worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.Header.Get("Authorization") != "Bearer private-cache-fixture" || r.URL.Path != "/v1/admin/console/relationships" || r.URL.Query().Get("character") != "anime-kipfel" {
				t.Error("worker credential or exact scope missing")
				w.WriteHeader(403)
				return
			}
			json.NewEncoder(w).Encode(Page{Items: []map[string]any{{"owner": u2.ID, "character": "anime-kipfel", "messages": 3}, {"owner": unknown, "character": "anime-kipfel"}, {"owner": "legacy-owner", "character": "anime-kipfel"}}})
		}))
		defer worker.Close()
		cfg := app.Config
		cfg.AIURL = worker.URL
		withAI, err := New(cfg, db, cache, prefix)
		if err != nil {
			t.Fatal(err)
		}
		gateway := httptest.NewServer(withAI.Router)
		defer gateway.Close()
		code, data := request(gateway.URL, "GET", "/directory/ai-relationships?character_id=anime-kipfel", nil, "", "")
		assert(code, 200, data)
		var page Page
		if json.Unmarshal(data, &page) != nil || len(page.Items) != 3 {
			t.Fatal("invalid worker relationships")
		}
		if page.Items[0]["account_exists"] != true || page.Items[0]["user_id"] != u2.ID || page.Items[0]["character_name"] == "" {
			t.Fatal("known account not hydrated")
		}
		if page.Items[1]["account_exists"] != false || page.Items[2]["account_exists"] != false {
			t.Fatal("legacy owner guessed to be an account")
		}
		if bytes.Contains(data, []byte("private-cache-fixture")) {
			t.Fatal("worker credential exposed")
		}
	})
	body := Mutation{Keys: map[string]string{"id": u2.ID}, Values: map[string]any{"profile": map[string]any{"display_name": "after"}}, Expected: u2.Version, Action: "edit"}
	code, data = request(srv.URL, "POST", "/resources/users/mutate", body, app.Config.Origin, "")
	assert(code, 403, data)
	code, data = request(srv.URL, "POST", "/resources/users/mutate", body, app.Config.Origin, csrf)
	assert(code, 200, data)
	updated, e := db.User(ctx, u2.ID)
	if e != nil || updated.Profile["display_name"] != "after" {
		t.Fatal("business edit did not persist")
	}
	var events int
	db.Pool.QueryRow(ctx, "SELECT count(*) FROM changes WHERE user_id=$1 AND kind='profile' AND data->'data'->>'display_name'='after'", u2.ID).Scan(&events)
	if events != 1 {
		t.Fatal("missing account sync event")
	}
	code, data = request(srv.URL, "POST", "/resources/users/mutate", body, app.Config.Origin, csrf)
	assert(code, 409, data)
	code, data = request(srv.URL, "POST", "/resources/users/mutate", Mutation{Keys: body.Keys, Values: map[string]any{"starry_id": "xy100000000"}, Expected: updated.Version}, app.Config.Origin, csrf)
	assert(code, 400, data)
	code, data = request(srv.URL, "GET", "/record-images/user/"+u2.ID+"/avatar", nil, "", "")
	assert(code, 200, data)
	if !bytes.Equal(data, defaultAvatar) {
		t.Fatal("default avatar missing")
	}
	if _, e := db.ReplaceAvatar(ctx, u2.ID, updated.Version, artwork); e != nil {
		t.Fatal(e)
	}
	photo, e := db.Avatar(ctx, u2.ID)
	if e != nil {
		t.Fatal(e)
	}
	code, data = request(srv.URL, "GET", "/record-images/user/"+u2.ID+"/avatar", nil, "", "")
	assert(code, 200, data)
	if !bytes.Equal(data, photo.Image) {
		t.Fatal("uploaded avatar not used")
	}
	var authorID string
	if e = db.Pool.QueryRow(ctx, "SELECT id FROM authors WHERE user_id=$1", u2.ID).Scan(&authorID); e != nil {
		t.Fatal(e)
	}
	code, data = request(srv.URL, "GET", "/record-images/author/"+authorID+"/avatar", nil, "", "")
	assert(code, 200, data)
	if !bytes.Equal(data, photo.Image) {
		t.Fatal("author did not inherit account avatar")
	}
	child := "image-child-" + uuid.NewString()
	if _, e = db.Pool.Exec(ctx, "INSERT INTO characters(id,author_id,base_id,visibility,name,data) VALUES($1,'starry-studio','anime-kipfel','private','image-child','{}')", child); e != nil {
		t.Fatal(e)
	}
	defer db.Pool.Exec(ctx, "DELETE FROM characters WHERE id=$1", child)
	code, data = request(srv.URL, "GET", "/record-images/character/"+child+"/avatar", nil, "", "")
	assert(code, 200, data)
	if !bytes.Equal(data, artwork) {
		t.Fatal("base character artwork not inherited")
	}
	// A worker outage after PostgreSQL reset must be retryable with the same
	// receipt, even though the conversation version advanced in the first try.
	var calls int
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		if r.Header.Get("X-Starry-Account") != u2.ID || r.Header.Get("X-Starry-Installation") != u2.ID || r.Header.Get("Authorization") != "Bearer worker-fixture" {
			t.Error("worker identity not derived from account")
		}
		w.Header().Set("Content-Type", "application/json")
		if calls == 1 {
			w.WriteHeader(503)
		}
		io.WriteString(w, `{"cleared":true}`)
	}))
	defer upstream.Close()
	app.Config.AIURL = upstream.URL
	app.Config.AIClientToken = "worker-fixture"
	conv, e := db.SetConversation(ctx, u2.ID, "anime-kipfel", 0, false, false)
	if e != nil {
		t.Fatal(e)
	}
	reset := Mutation{Keys: map[string]string{"user_id": u2.ID, "character_id": "anime-kipfel"}, Action: "reset", Confirm: true, Expected: conv.Version, ResetID: uuid.NewString()}
	code, data = request(srv.URL, "POST", "/resources/conversations/mutate", reset, app.Config.Origin, csrf)
	assert(code, 400, data)
	code, data = request(srv.URL, "POST", "/resources/conversations/mutate", reset, app.Config.Origin, csrf)
	assert(code, 200, data)
	if calls != 2 {
		t.Fatal("reset retry did not reach worker")
	}
	// Official catalogue updates are versioned too and cannot change IDs.
	charID := "admin-test-" + uuid.NewString()
	_, e = db.Pool.Exec(ctx, "INSERT INTO characters(id,author_id,visibility,name,description,data) VALUES($1,'starry-studio','private','before','','{}')", charID)
	if e != nil {
		t.Fatal(e)
	}
	defer db.Pool.Exec(ctx, "DELETE FROM characters WHERE id=$1", charID)
	previewKey := "characters/" + charID + "/previews/fixture/avatar.png"
	_, e = db.Pool.Exec(ctx, `INSERT INTO character_market_assets(character_id,data) VALUES($1,jsonb_build_object('media',jsonb_build_object('avatar',jsonb_build_object('object_key',$2::text))))`, charID, previewKey)
	if e != nil {
		t.Fatal(e)
	}
	refs, e := app.objectReferences(ctx, previewKey)
	if e != nil || len(refs) != 1 || refs[0]["kind"] != "marketplace" || refs[0]["character_id"] != charID {
		t.Fatalf("marketplace preview deletion protection missing: %v %v", refs, e)
	}
	refs, e = app.objectReferences(ctx, previewKey+"-unused")
	if e != nil || len(refs) != 0 {
		t.Fatalf("unreferenced object incorrectly protected: %v %v", refs, e)
	}
	code, data = request(srv.URL, "GET", "/resources/character_market_assets", nil, "", "")
	assert(code, 200, data)
	charBody := Mutation{Keys: map[string]string{"id": charID}, Values: map[string]any{"name": "after", "visibility": "public"}, Expected: 1}
	code, data = request(srv.URL, "POST", "/resources/characters/mutate", charBody, app.Config.Origin, csrf)
	assert(code, 200, data)
	code, data = request(srv.URL, "POST", "/resources/characters/mutate", charBody, app.Config.Origin, csrf)
	assert(code, 409, data)
	code, data = request(srv.URL, "POST", "/resources/changes/mutate", Mutation{Action: "edit"}, app.Config.Origin, csrf)
	assert(code, 400, data)
	code, data = request(srv.URL, "POST", "/logout", map[string]any{}, app.Config.Origin, csrf)
	assert(code, 200, data)
	code, data = request(srv.URL, "POST", "/login", map[string]string{"username": viewerName, "password": password}, app.Config.Origin, "")
	assert(code, 200, data)
	json.Unmarshal(data, &session)
	csrf = session.CSRF
	code, data = request(srv.URL, "GET", "/billing?month=2026-10", nil, "", "")
	assert(code, 403, data)
	code, data = request(srv.URL, "GET", "/billing/analysis?month=2026-10", nil, "", "")
	assert(code, 403, data)
	code, data = request(srv.URL, "GET", "/objects?folders=true", nil, "", "")
	assert(code, 403, data)
	code, data = request(srv.URL, "GET", "/objects/detail?key=models/a.glb", nil, "", "")
	assert(code, 403, data)
	code, data = request(srv.URL, "GET", "/discovery", nil, "", "")
	assert(code, 200, data)
	code, data = request(srv.URL, "POST", "/resources/users/mutate", body, app.Config.Origin, csrf)
	assert(code, 403, data)
	code, data = request(srv.URL, "GET", "/cache", nil, "", "")
	assert(code, 403, data)
	code, data = request(srv.URL, "GET", "/runtime/config", nil, "", "")
	assert(code, 403, data)
	if _, e = db.Pool.Exec(ctx, "UPDATE admin_users SET session_epoch=session_epoch+1 WHERE id=$1", viewer); e != nil {
		t.Fatal(e)
	}
	code, data = request(replica.URL, "GET", "/session", nil, "", "")
	assert(code, 401, data)
	var auditCount int
	db.Pool.QueryRow(ctx, "SELECT count(*) FROM admin_audit WHERE actor_id=$1", owner).Scan(&auditCount)
	if auditCount < 4 {
		t.Fatal("audit missing")
	}
	var leaked bool
	db.Pool.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM admin_audit WHERE target::text LIKE $1)", "%"+password+"%").Scan(&leaked)
	if leaked {
		t.Fatal("credential in audit")
	}
}
func TestOriginValidation(t *testing.T) {
	for _, origin := range []string{"", "https://example.com/path", "http://example.com", "https://u:p@example.com", "https://example.com?x=1"} {
		_, e := New(Config{Origin: origin, Secure: true}, &store.Store{}, redis.NewClient(&redis.Options{Addr: "127.0.0.1:0"}), "test:")
		if e == nil {
			t.Fatalf("accepted bad origin %s", origin)
		}
	}
}
