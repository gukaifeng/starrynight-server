package privatecontent

import (
	"encoding/base64"
	"strings"
	"testing"
)

func TestEnvelopeAuthenticationAndRotation(t *testing.T) {
	old := base64.StdEncoding.EncodeToString([]byte(strings.Repeat("a", 32)))
	next := base64.StdEncoding.EncodeToString([]byte(strings.Repeat("b", 32)))
	k, _ := New("old", map[string]string{"old": old})
	binding := Binding("owner", "draft", "resource", 5)
	e, err := k.Encrypt([]byte("confidential runtime and raw editor text"), binding)
	if err != nil {
		t.Fatal(err)
	}
	r, _ := New("new", map[string]string{"old": old, "new": next})
	if p, err := r.Decrypt(e, binding); err != nil || string(p) != "confidential runtime and raw editor text" {
		t.Fatal("rotation cannot read retained version", err)
	}
	for _, b := range []string{Binding("another-owner", "draft", "resource", 5), Binding("owner", "draft", "another-resource", 5), Binding("owner", "draft", "resource", 6)} {
		if _, err := r.Decrypt(e, b); err == nil {
			t.Fatal("cross-binding ciphertext accepted")
		}
	}
	e.Ciphertext = e.Ciphertext[:len(e.Ciphertext)-4] + "AAAA"
	if _, err := r.Decrypt(e, binding); err == nil {
		t.Fatal("tampering accepted")
	}
	if _, err := New("missing", map[string]string{"old": old}); err == nil {
		t.Fatal("missing active key accepted")
	}
}
