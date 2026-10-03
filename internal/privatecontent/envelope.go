// Package privatecontent protects author source at rest. Public projections
// never need this keyring. Ciphertexts are bound to an exact owner/resource/version.
package privatecontent

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
)

type Envelope struct {
	Version    int    `json:"version"`
	KeyID      string `json:"key_id"`
	WrappedKey string `json:"wrapped_key"`
	Nonce      string `json:"nonce"`
	Ciphertext string `json:"ciphertext"`
}
type Keyring struct {
	active string
	keys   map[string][]byte
}

var ErrInvalid = errors.New("private content could not be authenticated")

// New takes a deployment-managed base64 key map. It copies key material and
// supports older key IDs during rotation; no keys are persisted alongside data.
func New(active string, encoded map[string]string) (*Keyring, error) {
	k := &Keyring{active: active, keys: map[string][]byte{}}
	for id, s := range encoded {
		b, e := base64.StdEncoding.DecodeString(s)
		if e != nil || len(b) != 32 || id == "" {
			return nil, fmt.Errorf("invalid content key configuration")
		}
		k.keys[id] = b
	}
	if k.keys[active] == nil {
		return nil, fmt.Errorf("active content key is missing")
	}
	return k, nil
}
func gcm(key []byte) (cipher.AEAD, error) {
	b, e := aes.NewCipher(key)
	if e != nil {
		return nil, e
	}
	return cipher.NewGCM(b)
}
func seal(key, plain, aad []byte) (nonce, data []byte, err error) {
	a, e := gcm(key)
	if e != nil {
		return nil, nil, e
	}
	n := make([]byte, a.NonceSize())
	if _, e = rand.Read(n); e != nil {
		return nil, nil, e
	}
	return n, a.Seal(nil, n, plain, aad), nil
}
func open(key, nonce, data, aad []byte) ([]byte, error) {
	a, e := gcm(key)
	if e != nil || len(nonce) != a.NonceSize() {
		return nil, ErrInvalid
	}
	p, e := a.Open(nil, nonce, data, aad)
	if e != nil {
		return nil, ErrInvalid
	}
	return p, nil
}
func (k *Keyring) Encrypt(plain []byte, binding string) (Envelope, error) {
	d := make([]byte, 32)
	if _, e := rand.Read(d); e != nil {
		return Envelope{}, e
	}
	aad := []byte("starry/private/v1/" + binding)
	n, c, e := seal(d, plain, aad)
	if e != nil {
		return Envelope{}, e
	}
	wn, w, e := seal(k.keys[k.active], d, append([]byte("wrap/"), aad...))
	if e != nil {
		return Envelope{}, e
	}
	wrapped := append(wn, w...)
	return Envelope{1, k.active, base64.StdEncoding.EncodeToString(wrapped), base64.StdEncoding.EncodeToString(n), base64.StdEncoding.EncodeToString(c)}, nil
}
func (k *Keyring) Decrypt(v Envelope, binding string) ([]byte, error) {
	key := k.keys[v.KeyID]
	if v.Version != 1 || key == nil {
		return nil, ErrInvalid
	}
	w, e := base64.StdEncoding.DecodeString(v.WrappedKey)
	if e != nil || len(w) < 12 {
		return nil, ErrInvalid
	}
	aad := []byte("starry/private/v1/" + binding)
	d, e := open(key, w[:12], w[12:], append([]byte("wrap/"), aad...))
	if e != nil {
		return nil, ErrInvalid
	}
	n, e := base64.StdEncoding.DecodeString(v.Nonce)
	if e != nil {
		return nil, ErrInvalid
	}
	c, e := base64.StdEncoding.DecodeString(v.Ciphertext)
	if e != nil {
		return nil, ErrInvalid
	}
	return open(d, n, c, aad)
}
func Binding(owner, kind, id string, version int64) string {
	// JSON avoids collisions caused by author-controlled separators.
	b, _ := json.Marshal([]any{owner, kind, id, version})
	return string(b)
}
