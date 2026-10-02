package api_test

import (
	"context"
	"encoding/json"
	"github.com/gukaifeng/starrynight-server/internal/assets"
	"github.com/gukaifeng/starrynight-server/internal/identity"
	"github.com/gukaifeng/starrynight-server/internal/store"
	"strings"
	"testing"
)

func TestEditableAccountIdentityAndFeedbackIsolation(t *testing.T) {
	s := setup(t)
	a, b := s.register(), s.register()
	s.call("PATCH", "/v1/me", a.Token, map[string]any{"expected_version": a.User.Version, "patch": map[string]any{"id": b.User.ID}}, 422)
	var changed store.Document
	json.Unmarshal(s.call("PATCH", "/v1/me", a.Token, map[string]any{"expected_version": a.User.Version, "patch": map[string]any{"display_name": "New nickname", "gender": "other", "bio": "New bio"}}, 200), &changed)
	var renamed identity.Session
	loginName := "renamed_" + strings.ReplaceAll(a.User.ID, "-", "")[:20]
	json.Unmarshal(s.call("POST", "/v1/me/username", a.Token, map[string]any{"expected_version": changed.Version, "username": loginName, "password": password}, 200), &renamed)
	if renamed.User.ID != a.User.ID || renamed.User.Username != loginName {
		t.Fatal("renaming changed immutable identity")
	}
	s.call("GET", "/v1/me", a.Token, nil, 401)
	s.call("POST", "/v1/auth/login", "", map[string]any{"username": a.User.Username, "password": password}, 401)
	s.call("POST", "/v1/auth/login", "", map[string]any{"username": loginName, "password": password}, 200)
	s.call("POST", "/v1/me/feedback", "", map[string]any{"category": "bug", "content": "fixture"}, 401)
	s.call("POST", "/v1/me/feedback", renamed.Token, map[string]any{"category": "bug", "content": "fixture"}, 200)
	var page store.Page[store.SupportTicket]
	json.Unmarshal(s.call("GET", "/v1/me/feedback", b.Token, nil, 200), &page)
	if len(page.Items) != 0 {
		t.Fatal("feedback leaked across accounts")
	}
	var revoked identity.Session
	json.Unmarshal(s.call("POST", "/v1/me/sessions/revoke", renamed.Token, map[string]any{"password": password}, 200), &revoked)
	s.call("GET", "/v1/me", renamed.Token, nil, 401)
	s.call("GET", "/v1/me", revoked.Token, nil, 200)
	_, err := s.db.Pool.Exec(context.Background(), "UPDATE users SET id=$2 WHERE id=$1", a.User.ID, store.NewID())
	if err == nil || !strings.Contains(err.Error(), "account id is immutable") {
		t.Fatal("database allowed identity mutation")
	}
}
func TestCharacterDownloadsRequireLoginVisibilityAndPublishedRelease(t *testing.T) {
	s := setup(t)
	a, b := s.register(), s.register()
	var role store.Character
	json.Unmarshal(s.call("POST", "/v1/characters", a.Token, map[string]any{"id": "character-" + store.NewID(), "name": "Fixture private role", "description": "Private download fixture", "base_id": "anime-kipfel", "visibility": "private", "data": map[string]any{}}, 200), &role)
	m := assets.Manifest{SchemaVersion: 1, CharacterID: role.ID, ReleaseID: store.NewID(), Version: 1, Platform: "ios", RuntimeVersion: "xcp/1", Files: []assets.File{{Path: "character.bundle", ObjectKey: "roles/fixture.bundle", Size: 100, SHA256: strings.Repeat("b", 64)}}}
	manifestJSON, err := json.Marshal(m)
	if err != nil {
		t.Fatal(err)
	}
	_, err = s.db.Pool.Exec(context.Background(), "INSERT INTO character_releases(character_id,release_id,platform,version,manifest,distributable) VALUES($1,$2,'ios',1,$3::jsonb,true)", role.ID, m.ReleaseID, string(manifestJSON))
	if err != nil {
		t.Fatal(err)
	}
	endpoint := "/v1/characters/" + role.ID + "/download"
	s.call("POST", endpoint, "", nil, 401)
	s.call("POST", endpoint, b.Token, nil, 404)
	s.call("POST", endpoint, a.Token, nil, 503) // Owner is authorized, OSS is deliberately unconfigured in this suite.
	s.call("POST", "/v1/characters/anime-kipfel/download", a.Token, nil, 404)
}

func TestImportedCharacterCatalogSupportsAccountSubscriptions(t *testing.T) {
	s := setup(t)
	a := s.register()
	var list store.Page[store.Character]
	if err := json.Unmarshal(s.call("GET", "/v1/characters?limit=200", "", nil, 200), &list); err != nil {
		t.Fatal(err)
	}
	if len(list.Items) != 41 {
		t.Fatalf("expected 41 bundled character identities, got %d", len(list.Items))
	}
	s.call("GET", "/v1/characters/anime-kipfel-v111", "", nil, 200)
	s.call("PUT", "/v1/me/subscriptions/anime-airi", a.Token, nil, 200)
	s.call("GET", "/v1/characters/anime-airi/preferences", a.Token, nil, 200)
	s.call("GET", "/v1/me/feedback?after=invalid", a.Token, nil, 422)
}
