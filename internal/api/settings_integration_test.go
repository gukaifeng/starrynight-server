package api_test

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"github.com/google/uuid"
	"github.com/gukaifeng/starrynight-server/internal/api"
	"github.com/gukaifeng/starrynight-server/internal/content"
	"github.com/gukaifeng/starrynight-server/internal/privatecontent"
	"github.com/gukaifeng/starrynight-server/internal/store"
	"github.com/gukaifeng/starrynight-server/internal/tasks"
	"github.com/redis/go-redis/v9"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"
)

func settingSuite(t *testing.T) (*suite, *privatecontent.Keyring) {
	s := setup(t)
	s.cfg.SettingPlatform = true
	s.cfg.ContentActiveKey = "fixture-key"
	s.cfg.ContentKeys = map[string]string{"fixture-key": base64.StdEncoding.EncodeToString([]byte(strings.Repeat("k", 32)))}
	for i, old := range s.servers {
		old.Close()
		a, e := api.New(s.cfg, s.db, s.redis)
		if e != nil {
			t.Fatal(e)
		}
		s.servers[i] = httptest.NewServer(a.Router)
	}
	k, e := privatecontent.New(s.cfg.ContentActiveKey, s.cfg.ContentKeys)
	if e != nil {
		t.Fatal(e)
	}
	_, e = s.db.Pool.Exec(context.Background(), `INSERT INTO character_revisions(character_id,revision,public_core,capability_snapshot,source_hash) VALUES('anime-chiffon',1,'{"id":"anime-chiffon","identity":{"gender":"female"},"capabilities":{"spoken_languages":["en","zh"]}}','{}','fixture') ON CONFLICT DO NOTHING`)
	if e != nil {
		t.Fatal(e)
	}
	return s, k
}
func fixtureDraft(t *testing.T) content.DraftBody {
	b, e := os.ReadFile("../../api/contracts/fixtures/setting-v1.json")
	if e != nil {
		t.Fatal(e)
	}
	var d content.SettingDocument
	if e = json.Unmarshal(b, &d); e != nil {
		t.Fatal(e)
	}
	return content.DraftBody{RawFields: map[string]json.RawMessage{"invalid_number": json.RawMessage(`"-"`), "long_source": json.RawMessage(`"private-source-canary"`)}, Document: d, FieldErrors: map[string]string{}, EditorState: map[string]json.RawMessage{}}
}
func (s *suite) conditional(instance int, method, path, token, etag string, body any, want int) []byte {
	s.t.Helper()
	b, _ := json.Marshal(body)
	req, _ := http.NewRequest(method, s.servers[instance].URL+path, bytes.NewReader(b))
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	if etag != "" {
		req.Header.Set("If-Match", etag)
	}
	r, e := s.servers[instance].Client().Do(req)
	if e != nil {
		s.t.Fatal(e)
	}
	defer r.Body.Close()
	raw, _ := io.ReadAll(r.Body)
	if r.StatusCode != want {
		s.t.Fatalf("%s %s want %d got %d: %.800s", method, path, want, r.StatusCode, raw)
	}
	return raw
}
func TestSettingDraftCASReceiptsAndSourceIsolation(t *testing.T) {
	s, k := settingSuite(t)
	a, b := s.register(), s.register()
	body := fixtureDraft(t)
	// Exercise the repository directly as well: driver failures must not be
	// obscured by the deliberately sanitized public error response.
	if _, err := s.db.SaveSettingDraft(context.Background(), k, a.User.ID, "", store.DraftMutation{MutationID: uuid.NewString(), ClientDraftID: uuid.NewString(), Body: body}); err != nil {
		t.Fatal(err)
	}
	create := map[string]any{"mutation_id": uuid.NewString(), "client_draft_id": uuid.NewString(), "body": body}
	first := decode[store.DraftSummary](t, s.call("POST", "/v2/me/setting-drafts", a.Token, create, 200))
	again := decode[store.DraftSummary](t, s.call("POST", "/v2/me/setting-drafts", a.Token, create, 200))
	if first != again {
		t.Fatal("lost create acknowledgment was not idempotent")
	}
	path := "/v2/me/setting-drafts/" + first.ID
	s.call("GET", path, b.Token, nil, 404)
	s.call("GET", path, "", nil, 401)
	d := decode[store.SettingDraft](t, s.call("GET", path, a.Token, nil, 200))
	if string(d.Body.RawFields["invalid_number"]) != `"-"` {
		t.Fatal("incomplete field lost")
	}
	body.Document.PublicProfile.Title = "New title"
	mutation := map[string]any{"mutation_id": uuid.NewString(), "body": body}
	second := decode[store.DraftSummary](t, s.conditional(0, "PUT", path, a.Token, `"1"`, mutation, 200))
	replay := decode[store.DraftSummary](t, s.conditional(1, "PUT", path, a.Token, `"1"`, mutation, 200))
	if second != replay {
		t.Fatal("lost save acknowledgment failed across nodes")
	}
	mutation["mutation_id"] = uuid.NewString()
	s.conditional(1, "PUT", path, a.Token, `"1"`, mutation, 412)
	s.conditional(1, "PUT", path, a.Token, `W/"2"`, mutation, 428)
	s.conditional(1, "PUT", path, b.Token, `"2"`, mutation, 404)
	checkpoints := decode[[]store.DraftCheckpoint](t, s.call("GET", path+"/checkpoints", a.Token, nil, 200))
	if len(checkpoints) != 1 {
		t.Fatal("checkpoint missing")
	}
	old := decode[content.DraftBody](t, s.call("GET", path+"/checkpoints/"+checkpoints[0].ID, a.Token, nil, 200))
	if old.Document.PublicProfile.Title == "New title" {
		t.Fatal("checkpoint was overwritten")
	}
	var leaked bool
	e := s.db.Pool.QueryRow(context.Background(), `SELECT EXISTS(SELECT 1 FROM content_mutation_receipts WHERE owner_id=$1 AND result::text LIKE '%private-source-canary%') OR EXISTS(SELECT 1 FROM changes WHERE user_id=$1 AND data::text LIKE '%private-source-canary%')`, a.User.ID).Scan(&leaked)
	if e != nil || leaked {
		t.Fatal("source copied into plaintext receipts/feed", e)
	}
	s.conditional(0, "DELETE", path, a.Token, `"2"`, map[string]any{"mutation_id": uuid.NewString()}, 200)
	s.call("GET", path, a.Token, nil, 404)
	s.conditional(0, "PUT", path, a.Token, `"2"`, mutation, 404)
}
func TestSettingFrozenPublicationWithdrawalAndQueue(t *testing.T) {
	s, k := settingSuite(t)
	a, b := s.register(), s.register()
	body := fixtureDraft(t)
	d := decode[store.DraftSummary](t, s.call("POST", "/v2/me/setting-drafts", a.Token, map[string]any{"mutation_id": uuid.NewString(), "client_draft_id": uuid.NewString(), "body": body}, 200))
	path := "/v2/me/setting-drafts/" + d.ID
	request := map[string]any{"mutation_id": uuid.NewString(), "visibility": "public"}
	sub := decode[store.Submission](t, s.conditional(0, "POST", path+"/submit", a.Token, `"1"`, request, 200))
	body.Document.Runtime.Blocks["teaching-rule"] = content.SettingBlock{Kind: "instruction", Purpose: "teaching", Text: "Changed after submission"}
	s.conditional(0, "PUT", path, a.Token, `"1"`, map[string]any{"mutation_id": uuid.NewString(), "body": body}, 200)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	ro, e := redis.ParseURL(os.Getenv("TEST_REDIS_URL"))
	if e != nil {
		t.Fatal(e)
	}
	w := tasks.New(s.db, k, ro, s.cfg.RedisPrefix)
	done := make(chan error, 1)
	go func() { done <- w.Run(ctx) }()
	defer func() {
		cancel()
		if e := <-done; e != nil {
			t.Error(e)
		}
	}()
	deadline := time.Now().Add(10 * time.Second)
	for time.Now().Before(deadline) {
		p, e := s.db.SettingSubmissions(context.Background(), a.User.ID, "", 10)
		if e != nil {
			t.Fatal(e)
		}
		if p.Items[0].Validation == "passed" {
			sub = p.Items[0]
			break
		}
		time.Sleep(50 * time.Millisecond)
	}
	if sub.Validation != "passed" {
		t.Fatal("durable outbox did not complete publication validation")
	}
	s.call("GET", "/v2/settings/"+sub.SettingID, b.Token, nil, 404)
	if e = s.db.ReviewSetting(context.Background(), "fixture-admin", sub.ID, "approve", "Reviewed fixture source", sub.Version); e != nil {
		t.Fatal(e)
	}
	public := s.call("GET", "/v2/settings/"+sub.SettingID, "", nil, 200)
	if bytes.Contains(public, []byte("teaching-rule")) || bytes.Contains(public, []byte("Changed after submission")) || bytes.Contains(public, []byte("private-source-canary")) {
		t.Fatal("public source leak")
	}
	create := map[string]any{"mutation_id": uuid.NewString(), "character_id": "anime-chiffon", "setting_id": sub.SettingID, "parameters": map[string]any{"level": "B1"}}
	instance := decode[store.ConversationInstance](t, s.call("POST", "/v2/conversations", b.Token, create, 200))
	duplicate := decode[store.ConversationInstance](t, s.call("POST", "/v2/conversations", b.Token, create, 200))
	if instance.ID != duplicate.ID {
		t.Fatal("duplicate instance from lost acknowledgment")
	}
	create["mutation_id"] = uuid.NewString()
	parallel := decode[store.ConversationInstance](t, s.call("POST", "/v2/conversations", b.Token, create, 200))
	if parallel.ID == instance.ID {
		t.Fatal("same pair cannot have parallel stories")
	}
	s.call("GET", "/v2/conversations/"+instance.ID, a.Token, nil, 404)
	for _, i := range []store.ConversationInstance{instance, parallel} {
		if _, e = s.db.Pool.Exec(context.Background(), `INSERT INTO conversation_messages(id,user_id,conversation_id,sequence,role,text,data,source) VALUES($1,$2,$3,1,'user','independent story','{}','fixture')`, uuid.NewString(), b.User.ID, i.ID); e != nil {
			t.Fatal(e)
		}
	}
	s.conditional(0, "POST", "/v2/conversations/"+instance.ID+"/reset", b.Token, `"1"`, map[string]any{"mutation_id": uuid.NewString()}, 200)
	if len(decode[store.Page[store.InstanceMessage]](t, s.call("GET", "/v2/conversations/"+instance.ID+"/messages", b.Token, nil, 200)).Items) != 0 {
		t.Fatal("reset kept messages")
	}
	if len(decode[store.Page[store.InstanceMessage]](t, s.call("GET", "/v2/conversations/"+parallel.ID+"/messages", b.Token, nil, 200)).Items) != 1 {
		t.Fatal("reset removed a parallel story")
	}
	source := s.call("GET", "/v2/me/settings/"+sub.SettingID+"/revisions/1/source", a.Token, nil, 200)
	if bytes.Contains(source, []byte("Changed after submission")) {
		t.Fatal("draft edit mutated frozen revision")
	}
	s.call("GET", "/v2/me/settings/"+sub.SettingID+"/revisions/1/source", b.Token, nil, 404)
	s.call("PUT", "/v2/me/setting-favorites/"+sub.SettingID, b.Token, nil, 200)
	v, e := s.db.SettingVersion(context.Background(), a.User.ID, sub.SettingID)
	if e != nil {
		t.Fatal(e)
	}
	s.conditional(0, "POST", "/v2/me/settings/"+sub.SettingID+"/access/make-private", a.Token, store.ETag(v), map[string]any{"mutation_id": uuid.NewString()}, 200)
	s.call("GET", "/v2/settings/"+sub.SettingID, b.Token, nil, 404)
	if _, e = s.db.PublicSetting(context.Background(), b.User.ID, sub.SettingID, 1, true); e == nil {
		t.Fatal("pinned revision bypassed revocation")
	}
	if err := s.db.DeleteUser(context.Background(), a.User.ID); err != nil {
		t.Fatal("creator account deletion blocked by released content", err)
	}
	if len(decode[store.Page[store.InstanceMessage]](t, s.call("GET", "/v2/conversations/"+parallel.ID+"/messages", b.Token, nil, 200)).Items) != 1 {
		t.Fatal("creator deletion destroyed a consumer's journal")
	}
}
