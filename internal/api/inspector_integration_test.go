package api_test

import (
	"context"
	"github.com/gukaifeng/starrynight-server/internal/api"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
)

func TestProductionInspectorSessionGrantAndReadOnlyGoals(t *testing.T) {
	s := setup(t)
	developer, ordinary := s.register(), s.register()
	var calls atomic.Int32
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		if r.Header.Get("X-Starry-Account") != developer.User.ID || r.Header.Get("Authorization") != "Bearer fixture-worker-token" {
			t.Error("untrusted inspector identity reached worker")
		}
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"sections":[]}`))
	}))
	defer worker.Close()
	cfg := s.cfg
	cfg.Environment = "production"
	cfg.AIInspectorAccounts = []string{developer.User.ID}
	cfg.AIUpstream = worker.URL
	cfg.AIServiceToken = "fixture-worker-token"
	app, err := api.New(cfg, s.db, s.redis)
	if err != nil {
		t.Fatal(err)
	}
	gateway := httptest.NewServer(app.Router)
	defer gateway.Close()
	before, err := s.db.Goals(context.Background(), developer.User.ID, "anime-kipfel")
	if err != nil {
		t.Fatal(err)
	}
	for _, check := range []struct {
		token  string
		status int
	}{{developer.Token, 200}, {ordinary.Token, 404}, {"", 401}} {
		request, _ := http.NewRequest("POST", gateway.URL+"/v1/ai/testing/characters/anime-kipfel/inspector", strings.NewReader(`{}`))
		if check.token != "" {
			request.Header.Set("Authorization", "Bearer "+check.token)
		}
		request.Header.Set("X-Starry-Account", developer.User.ID)
		response, err := http.DefaultClient.Do(request)
		if err != nil {
			t.Fatal(err)
		}
		response.Body.Close()
		if response.StatusCode != check.status {
			t.Fatalf("inspector status %d, want %d", response.StatusCode, check.status)
		}
	}
	if calls.Load() != 1 {
		t.Fatal("unapproved inspector request reached worker")
	}
	after, err := s.db.Goals(context.Background(), developer.User.ID, "anime-kipfel")
	if err != nil || before.Version != after.Version {
		t.Fatal("read-only inspection persisted goals")
	}
}
