package api_test

import (
	"bufio"
	"context"
	"github.com/gukaifeng/starrynight-server/internal/api"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// Exercises the actual Gin middleware and ResponseWriter, including stream
// cancellation, rather than testing only ReverseProxy in isolation.
func TestGinAIGatewayPreservesAuthenticatedStreamingAndCancellation(t *testing.T) {
	s := setup(t)
	a := s.register()
	received := make(chan bool, 1)
	cancelled := make(chan struct{}, 1)
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		received <- r.Header.Get("X-Starry-Account") == a.User.ID && r.Header.Get("Authorization") == "Bearer fixture-worker-token"
		w.Header().Set("Content-Type", "text/event-stream")
		w.Write([]byte("data: {\"type\":\"fixture\"}\n\n"))
		w.(http.Flusher).Flush()
		<-r.Context().Done()
		cancelled <- struct{}{}
	}))
	defer worker.Close()
	cfg := s.cfg
	cfg.AIUpstream = worker.URL
	cfg.AIServiceToken = "fixture-worker-token"
	app, err := api.New(cfg, s.db, s.redis)
	if err != nil {
		t.Fatal(err)
	}
	gateway := httptest.NewServer(app.Router)
	defer gateway.Close()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	request, _ := http.NewRequestWithContext(ctx, "POST", gateway.URL+"/v1/ai/conversations/anime-kipfel/messages", strings.NewReader(`{"message":"fixture"}`))
	request.Header.Set("Authorization", "Bearer "+a.Token)
	request.Header.Set("X-Starry-Account", "forged-account")
	response, err := http.DefaultClient.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	if response.StatusCode != 200 {
		t.Fatalf("stream status %d", response.StatusCode)
	}
	if line, err := bufio.NewReader(response.Body).ReadString('\n'); err != nil || !strings.HasPrefix(line, "data:") {
		t.Fatal("SSE did not flush through Gin")
	}
	select {
	case valid := <-received:
		if !valid {
			t.Fatal("untrusted identity or credentials reached worker")
		}
	case <-time.After(3 * time.Second):
		t.Fatal("worker did not receive stream")
	}
	cancel()
	response.Body.Close()
	select {
	case <-cancelled:
	case <-time.After(3 * time.Second):
		t.Fatal("cancelled client left AI request running")
	}
}
