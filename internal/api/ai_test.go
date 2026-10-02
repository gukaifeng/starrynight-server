package api

import (
	"context"
	"github.com/gukaifeng/starrynight-server/internal/store"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
)

type fixtureTransport func(*http.Request) (*http.Response, error)

func (f fixtureTransport) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func TestAIAllowlistAndTrustedIdentity(t *testing.T) {
	for _, c := range []struct {
		method, path string
		allowed      bool
	}{
		{"GET", "/v1/ai/status", true},
		{"POST", "/v1/ai/conversations/anime-kipfel/messages/11111111-1111-1111-1111-111111111111/translation", true},
		{"DELETE", "/v1/ai/conversations/anime-kipfel/messages/11111111-1111-1111-1111-111111111111/translation", false}, {"POST", "/v1/ai/conversations/anime-kipfel/messages", true},
		{"DELETE", "/v1/ai/conversations/anime-kipfel/messages", true}, {"GET", "/v1/ai/asr/anime-kipfel", true},
		{"POST", "/v1/ai/admin/usage", false}, {"GET", "/v1/ai/admin/usage", false},
		{"POST", "/v1/ai/characters/anime-kipfel/voice-designs", false},
		{"GET", "/v1/ai/characters/anime-kipfel/profile", true},
		{"POST", "/v1/ai/characters/anime-kipfel/profile", false},
		{"POST", "/v1/ai/testing/characters/anime-kipfel/inspector", true},
		{"POST", "/v1/ai/conversations/anime-kipfel/reactions/prepare", true},
		{"POST", "/v1/ai/conversations/anime-kipfel/reactions/pause", true},
		{"POST", "/v1/ai/conversations/anime-kipfel/reactions/status", true},
		{"POST", "/v1/ai/conversations/anime-kipfel/suggestions/prepare", true},
		{"POST", "/v1/ai/conversations/anime-kipfel/suggestions/status", true},
		{"GET", "/v1/ai/conversations/anime-kipfel/suggestions/status", false},
		{"POST", "/v1/ai/conversations/anime-kipfel/suggestions/delete", false},
		{"GET", "/v1/ai/conversations/anime-kipfel/reactions/prepare", false},
		{"POST", "/v1/ai/conversations/../reactions/prepare", false},
		{"GET", "/v1/ai/testing/characters/anime-kipfel/inspector", false},
		{"POST", "/v1/ai/testing/characters/../inspector", false},
		{"POST", "/v1/ai/conversations/../messages", false}, {"GET", "/v1/ai/conversations/anime-kipfel/messages", false},
	} {
		if _, ok := aiRoute(c.method, c.path, "development"); ok != c.allowed {
			t.Fatalf("allowlist: %s %s", c.method, c.path)
		}
	}
	if _, ok := aiRoute("POST", "/v1/ai/testing/characters/anime-kipfel/inspector", "production"); ok {
		t.Fatal("production must never proxy test-only AI configuration")
	}
	target, _ := url.Parse("http://private-worker:8091")
	proxy := newAIProxy(target, "worker-only-fixture", fixtureTransport(func(r *http.Request) (*http.Response, error) {
		if r.URL.Host != "private-worker:8091" || r.URL.Path != "/v1/conversations/anime-kipfel/messages" {
			t.Fatal("wrong upstream")
		}
		if r.Header.Get("X-Starry-Account") != "account-from-session" || r.Header.Get("X-Starry-Installation") != "account-from-session" {
			t.Fatal("forged identity forwarded")
		}
		if r.Header.Get("Authorization") != "Bearer worker-only-fixture" || r.Header.Get("Cookie") != "" || r.Header.Get("X-Forwarded-For") != "" {
			t.Fatal("credential/header boundary failed")
		}
		if r.Header.Get("X-Starry-Gateway-Timing") != "" || r.Header.Get("X-Starry-Voice-Trace") == "forged" || r.Header.Get("X-Starry-Voice-Trace") == "" {
			t.Fatal("voice diagnostics trusted-header boundary failed")
		}
		if r.Context().Value(actorKey{}).(store.User).ID != "account-from-session" {
			t.Fatal("context lost")
		}
		return &http.Response{StatusCode: 200, Header: http.Header{"Content-Type": []string{"text/event-stream"}}, Body: io.NopCloser(strings.NewReader("data: fixture\n\n"))}, nil
	}))
	request := httptest.NewRequest("POST", "http://platform/v1/ai/conversations/anime-kipfel/messages", strings.NewReader(`{}`))
	request.Header.Set("Authorization", "Bearer user-fixture")
	request.Header.Set("X-Starry-Account", "spoofed")
	request.Header.Set("X-Starry-Installation", "spoofed")
	request.Header.Set("Cookie", "secret=fixture")
	request.Header.Set("X-Forwarded-For", "spoofed")
	request.Header.Set("X-Starry-Gateway-Timing", `{"authorization_ms":123}`)
	request.Header.Set("X-Starry-Voice-Trace", "forged")
	request = request.WithContext(context.WithValue(request.Context(), actorKey{}, store.User{ID: "account-from-session"}))
	recorder := httptest.NewRecorder()
	proxy.ServeHTTP(recorder, request)
	if recorder.Code != 200 || recorder.Body.String() != "data: fixture\n\n" || !recorder.Flushed {
		t.Fatal("SSE forwarding failed")
	}
}

func TestAIProxyCancellationAndSafeError(t *testing.T) {
	target, _ := url.Parse("http://private-worker:8091")
	proxy := newAIProxy(target, "private-fixture", fixtureTransport(func(r *http.Request) (*http.Response, error) {
		if r.Context().Err() != context.Canceled {
			t.Fatal("cancellation lost")
		}
		return nil, context.Canceled
	}))
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	request := httptest.NewRequest("GET", "http://platform/v1/ai/status", nil).WithContext(ctx)
	recorder := httptest.NewRecorder()
	proxy.ServeHTTP(recorder, request)
	if recorder.Code != 502 || strings.Contains(recorder.Body.String(), "private-fixture") {
		t.Fatal("unsafe upstream error")
	}
}
