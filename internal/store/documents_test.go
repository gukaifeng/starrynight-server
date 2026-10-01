package store

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestMergePatchPreservesFutureFields(t *testing.T) {
	original := map[string]any{"name": "old", "extensions": map[string]any{"future.pose": map[string]any{"enabled": true}}, "audio": map[string]any{"music": 1.0, "speech": 0.8}, "remove": "old"}
	result, e := merge(original, map[string]any{"name": "new", "audio": map[string]any{"music": 0.2}, "remove": nil})
	if e != nil || result["extensions"] == nil || result["audio"].(map[string]any)["speech"] != 0.8 || result["remove"] != nil {
		t.Fatalf("merge patch failed: %v", e)
	}
	if original["name"] != "old" || original["audio"].(map[string]any)["music"] != 1.0 {
		t.Fatal("mutated input")
	}
	if _, e = merge(result, map[string]any{"oversized": strings.Repeat("x", 65537)}); e == nil {
		t.Fatal("oversized document accepted")
	}
	if e = validateSettings(map[string]any{"chat_font_size": 100.0}); e == nil {
		t.Fatal("invalid font accepted")
	}
}

func TestPublicCharacterDoesNotExposeLoginIdentity(t *testing.T) {
	data, e := publicCharacterData(map[string]any{"native": map[string]any{"ownerID": "private-login-id", "authorID": "forged-public-id", "profile": map[string]any{"name": "伙伴"}}, "extensions": map[string]any{"future": true}})
	if e != nil {
		t.Fatal(e)
	}
	c := Character{ID: "fixture", OwnerID: "private-login-id", Data: data, AuthorID: "public-author"}
	b, _ := json.Marshal(c)
	if strings.Contains(string(b), "private-login-id") || strings.Contains(string(b), "forged-public-id") || data["extensions"] == nil {
		t.Fatal("private identity leaked or extension lost")
	}
}
