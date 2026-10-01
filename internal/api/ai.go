package api

import (
	"context"
	"github.com/danielgtaylor/huma/v2"
	"net/http"
	"net/http/httputil"
	"net/url"
	"regexp"
	"strings"
	"time"
)

// The Python inference worker is private. Only explicitly listed user routes
// pass this gateway; voice design, usage/admin APIs and arbitrary URLs do not.
var aiConversation = regexp.MustCompile(`^/v1/ai/conversations/([a-zA-Z0-9_-]{1,120})/messages(?:/[a-fA-F0-9-]{36}/(?:audio|translation))?$`)
var aiASR = regexp.MustCompile(`^/v1/ai/asr/([a-zA-Z0-9_-]{1,120})$`)
var aiProfile = regexp.MustCompile(`^/v1/ai/characters/([a-zA-Z0-9_-]{1,120})/profile$`)
var aiInspector = regexp.MustCompile(`^/v1/ai/testing/characters/([a-zA-Z0-9_-]{1,120})/inspector$`)
var aiReactions = regexp.MustCompile(`^/v1/ai/conversations/([a-zA-Z0-9_-]{1,120})/reactions/(?:prepare|pause|status)$`)
var aiSuggestions = regexp.MustCompile(`^/v1/ai/conversations/([a-zA-Z0-9_-]{1,120})/suggestions/(?:prepare|status)$`)
var aiReset = regexp.MustCompile(`^/v1/ai/conversations/([a-zA-Z0-9_-]{1,120})$`)
var aiOpening = regexp.MustCompile(`^/v1/ai/conversations/([a-zA-Z0-9_-]{1,120})/opening$`)

func aiRoute(method, path, environment string) (character string, allowed bool) {
	if match := aiOpening.FindStringSubmatch(path); match != nil {
		return match[1], method == http.MethodPost
	}
	if match := aiReset.FindStringSubmatch(path); match != nil {
		return match[1], method == http.MethodDelete
	}
	if path == "/v1/ai/status" {
		return "", method == http.MethodGet
	}
	if match := aiConversation.FindStringSubmatch(path); match != nil {
		return match[1], method == http.MethodPost || (method == http.MethodDelete && strings.HasSuffix(path, "/messages"))
	}
	if match := aiASR.FindStringSubmatch(path); match != nil {
		return match[1], method == http.MethodGet
	}
	if match := aiReactions.FindStringSubmatch(path); match != nil {
		return match[1], method == http.MethodPost
	}
	if match := aiSuggestions.FindStringSubmatch(path); match != nil {
		return match[1], method == http.MethodPost
	}
	if match := aiProfile.FindStringSubmatch(path); match != nil {
		return match[1], method == http.MethodGet
	}
	if match := aiInspector.FindStringSubmatch(path); match != nil {
		return match[1], method == http.MethodPost && (environment == "development" || environment == "test")
	}
	return "", false
}

func (s *Server) documentAIRoutes() {
	for _, route := range []struct{ method, path, id, description string }{
		{"GET", "/v1/ai/status", "ai-status", "Private worker readiness; does not invoke a paid provider."},
		{"GET", "/v1/ai/characters/{character}/profile", "ai-public-profile", "Explicit public persona fields only."},
		{"POST", "/v1/ai/testing/characters/{character}/inspector", "ai-test-inspector", "Read-only owner-scoped configuration inspection. Available only in development/test environments with worker inspection explicitly enabled; otherwise 404. Never invokes a paid provider."},
		{"POST", "/v1/ai/conversations/{character}/messages", "ai-reply", "SSE reply/audio events. Existing worker request schema; account identity is supplied by this gateway."},
		{"POST", "/v1/ai/conversations/{character}/reactions/prepare", "ai-prepare-reactions", "Prepare one real AI draft per eligible gesture, idle or entry scenario. preparation_scope=entry warms only the upcoming introduction/return; active warms the current role. Unused drafts are not conversation history."},
		{"POST", "/v1/ai/conversations/{character}/suggestions/prepare", "ai-prepare-suggestions", "Generate three ranked user replies to source_message_id, then prepare one answer per option in rank order. Nothing is published until the exact option is chosen with quick_reply_id."},
		{"POST", "/v1/ai/conversations/{character}/suggestions/status", "ai-suggestion-status", "Read the ranked choices for the latest AI turn. No paid generation."},
		{"POST", "/v1/ai/conversations/{character}/reactions/pause", "ai-pause-reactions", "Cancel preparation for this session lease; retains completed, unexpired drafts."},
		{"POST", "/v1/ai/conversations/{character}/reactions/status", "ai-reaction-status", "Read-only availability for the current context; does not start generation."},
		{"POST", "/v1/ai/conversations/{character}/messages/{message}/translation", "ai-translate", "Translate visible segments of an owned assistant message to zh-Hans, zh-Hant or en, preserving ids/kinds/order. Read-only; cached by account, message, source and language. Does not alter context or audio."},
		{"POST", "/v1/ai/conversations/{character}/messages/{message}/audio", "ai-audio", "SSE audio replay for an existing worker message."},
		{"DELETE", "/v1/ai/conversations/{character}/messages", "ai-clear-context", "Clear worker context. Account archive has its own clear endpoint."},
		{"DELETE", "/v1/ai/conversations/{character}", "ai-delete-conversation", "Erase worker conversation and memories; requires reset_id UUID query. Idempotent."},
		{"POST", "/v1/ai/conversations/{character}/opening", "ai-register-opening", "Register an already-played bundled first meeting. No paid model invocation."},
		{"GET", "/v1/ai/asr/{character}", "ai-asr", "WebSocket upgrade for ASR; stream protocol remains owned by the AI worker."},
	} {
		op := &huma.Operation{Method: route.method, Path: route.path, OperationID: route.id, Description: route.description, Tags: []string{"AI worker"}, Security: []map[string][]string{{"session": {}}}, Responses: map[string]*huma.Response{"200": {Description: "Worker response; SSE where documented"}, "401": {Description: "Session required"}, "503": {Description: "Worker unconfigured or unavailable"}}}
		for _, name := range []string{"character", "message"} {
			if strings.Contains(route.path, "{"+name+"}") {
				op.Parameters = append(op.Parameters, &huma.Param{Name: name, In: "path", Required: true, Schema: &huma.Schema{Type: "string"}})
			}
		}
		if route.id == "ai-delete-conversation" {
			minimum := float64(0)
			op.Parameters = append(op.Parameters,
				&huma.Param{Name: "reset_id", In: "query", Required: true, Schema: &huma.Schema{Type: "string", Format: "uuid"}},
				&huma.Param{Name: "reset_version", In: "query", Schema: &huma.Schema{Type: "integer", Minimum: &minimum}, Description: "Monotonic version returned by the account conversation reset."})
		}
		if route.id == "ai-asr" {
			op.Responses["101"] = &huma.Response{Description: "Switching protocols"}
		}
		s.API.OpenAPI().AddOperation(op)
	}
}

func newAIProxy(target *url.URL, token string, transport http.RoundTripper) *httputil.ReverseProxy {
	return &httputil.ReverseProxy{
		Transport:     transport,
		FlushInterval: -1, // SSE events must not wait for an application buffer.
		Rewrite: func(p *httputil.ProxyRequest) {
			p.SetURL(target)
			p.Out.URL.Path = strings.Replace(p.In.URL.Path, "/v1/ai/", "/v1/", 1)
			p.Out.URL.RawPath = ""
			p.Out.Header.Set("Authorization", "Bearer "+token)
			user := principal(p.In.Context()).ID
			// Stable account identity across devices, derived exclusively from
			// the revocable platform session. Ignore forged client headers.
			p.Out.Header.Set("X-Starry-Installation", user)
			p.Out.Header.Set("X-Starry-Account", user)
			p.Out.Header.Del("Cookie")
		},
		ErrorHandler: func(w http.ResponseWriter, r *http.Request, err error) {
			http.Error(w, "AI worker unavailable", http.StatusBadGateway)
		},
	}
}

func (s *Server) aiRoutes() {
	target, _ := url.Parse(s.Config.AIUpstream)
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.ResponseHeaderTimeout = 20 * time.Second
	transport.MaxIdleConnsPerHost = 32
	proxy := newAIProxy(target, s.Config.AIServiceToken, transport)
	s.Router.With(s.session).Handle("/v1/ai/*", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if principal(r.Context()).ID == "" {
			http.Error(w, "sign in required", 401)
			return
		}
		character, allowed := aiRoute(r.Method, r.URL.Path, s.Config.Environment)
		if !allowed {
			http.NotFound(w, r)
			return
		}
		if s.Config.AIUpstream == "" {
			http.Error(w, "AI worker not configured", 503)
			return
		}
		if character != "" {
			if _, err := s.Store.Character(r.Context(), principal(r.Context()).ID, character); err != nil {
				http.Error(w, "character unavailable", 404)
				return
			}
		}
		ctx, cancel := context.WithTimeout(r.Context(), 180*time.Second)
		defer cancel()
		// Override the regular API's short write deadline for SSE/WebSocket.
		_ = http.NewResponseController(w).SetWriteDeadline(time.Now().Add(180 * time.Second))
		r.Body = http.MaxBytesReader(w, r.Body, 8<<20)
		proxy.ServeHTTP(w, r.WithContext(ctx))
	}))
}
