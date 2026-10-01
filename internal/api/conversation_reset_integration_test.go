package api_test

import (
	"github.com/google/uuid"
	"github.com/gukaifeng/starrynight-server/internal/store"
	"testing"
	"time"
)

func TestConversationResetFencesOfflineOutbox(t *testing.T) {
	s := setup(t)
	a := s.register()
	b := s.register()
	root := "/v1/conversations/anime-kipfel"
	message := map[string]any{"expected_version": 0, "role": "user", "text": "private old conversation", "created_at": time.Now().UTC(), "data": map[string]any{}}
	s.call("PUT", root+"/messages/"+uuid.NewString(), a.Token, message, 200)
	s.call("PUT", root+"/messages/"+uuid.NewString(), b.Token, message, 200)
	entry := map[string]any{"expected_version": 0, "data": map[string]any{"text": "private remembered detail"}}
	s.call("PUT", root+"/memories/"+uuid.NewString(), a.Token, entry, 200)
	s.call("PUT", root+"/moments/"+uuid.NewString(), a.Token, entry, 200)
	s.call("PATCH", "/v1/characters/anime-kipfel/preferences", a.Token, map[string]any{"expected_version": 0, "patch": map[string]any{
		"profile":     map[string]any{"audio": map[string]any{"speechVolume": 0.7}},
		"greeting":    map[string]any{"lastText": "old greeting"},
		"experiences": map[string]any{"preferences": map[string]any{"nickname": "keep nickname"}, "stories": map[string]any{"secret": "private progress"}},
	}}, 200)
	id := uuid.NewString()
	reset := decode[store.ConversationReset](t, s.call("DELETE", root+"?reset_id="+id, a.Token, nil, 200))
	if reset.ResetID != id || reset.Version != 1 {
		t.Fatal("missing reset epoch")
	}
	for _, kind := range []string{"messages", "memories", "moments"} {
		result := decode[map[string]any](t, s.call("GET", root+"/"+kind, a.Token, nil, 200))
		if len(result["items"].([]any)) != 0 {
			t.Fatal("reset retained " + kind)
		}
	}
	other := decode[store.Page[store.Message]](t, s.call("GET", root+"/messages", b.Token, nil, 200))
	if len(other.Items) != 1 {
		t.Fatal("reset crossed account boundary")
	}
	prefs := decode[store.Document](t, s.call("GET", "/v1/characters/anime-kipfel/preferences", a.Token, nil, 200))
	if prefs.Data["greeting"] != nil || prefs.Data["profile"] == nil {
		t.Fatal("wrong preference preservation")
	}
	exported := decode[store.Page[store.Change]](t, s.call("GET", "/v1/me/export?limit=200", a.Token, nil, 200))
	for _, change := range exported.Items {
		if change.Kind == "message" || change.Kind == "memory" || change.Kind == "moment" {
			t.Fatal("history retained in export")
		}
	}
	// Even unsent entries with new IDs cannot repopulate a reset conversation.
	s.call("PUT", root+"/messages/"+uuid.NewString(), a.Token, message, 409)
	s.call("PUT", root+"/memories/"+uuid.NewString(), a.Token, entry, 409)
	s.call("PATCH", "/v1/characters/anime-kipfel/preferences", a.Token, map[string]any{"expected_version": prefs.Version, "patch": map[string]any{"greeting": "stale"}}, 409)
	message["conversation_reset"] = id
	s.call("PUT", root+"/messages/"+uuid.NewString(), a.Token, message, 200)
	s.call("DELETE", root+"?reset_id="+id, a.Token, nil, 200)
	fresh := decode[store.Page[store.Message]](t, s.call("GET", root+"/messages", a.Token, nil, 200))
	if len(fresh.Items) != 1 {
		t.Fatal("retry deleted newer messages")
	}
	s.call("DELETE", root+"?reset_id=invalid", a.Token, nil, 422)
	s.call("DELETE", root+"?reset_id="+uuid.NewString(), "", nil, 401)
}
