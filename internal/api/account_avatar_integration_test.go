package api_test

import (
	"bytes"
	"context"
	"encoding/json"
	"github.com/gukaifeng/starrynight-server/internal/store"
	"image"
	"image/color"
	"image/png"
	"regexp"
	"strings"
	"testing"
)

func TestPublicHandlesAndPrivateAvatarPersistence(t *testing.T) {
	s := setup(t)
	a, b := s.register(), s.register()
	if !regexp.MustCompile(`^XY[0-9]{12}$`).MatchString(a.User.StarryID) || a.User.StarryID == b.User.StarryID {
		t.Fatal("invalid public handles")
	}
	if a.User.Profile["avatar"] != "starry-cat-v1" {
		t.Fatal("default avatar missing")
	}
	s.call("PATCH", "/v1/me", a.Token, map[string]any{"expected_version": a.User.Version, "patch": map[string]any{"starry_id": b.User.StarryID}}, 422)
	if _, err := s.db.Pool.Exec(context.Background(), "UPDATE users SET starry_id=$2 WHERE id=$1", a.User.ID, b.User.StarryID); err == nil || !strings.Contains(err.Error(), "starry id is not editable") {
		t.Fatal("mutable public handle")
	}
	picture := image.NewRGBA(image.Rect(0, 0, 80, 60))
	picture.Set(40, 30, color.RGBA{80, 130, 210, 255})
	var input bytes.Buffer
	png.Encode(&input, picture)
	upload := map[string]any{"expected_version": a.User.Version, "image": input.Bytes()}
	s.call("PUT", "/v1/me/avatar", "", upload, 401)
	var updated store.Document
	json.Unmarshal(s.call("PUT", "/v1/me/avatar", a.Token, upload, 200), &updated)
	s.call("PUT", "/v1/me/avatar", a.Token, upload, 409)
	var avatar store.AccountAvatar
	json.Unmarshal(s.call("GET", "/v1/me/avatar", a.Token, nil, 200), &avatar)
	if len(avatar.Image) == 0 || updated.Data["avatar"] != "upload:"+avatar.SHA256 {
		t.Fatal("avatar not persisted")
	}
	decoded, format, err := image.DecodeConfig(bytes.NewReader(avatar.Image))
	if err != nil || format != "jpeg" || decoded.Width != 256 || decoded.Height != 256 {
		t.Fatal("image not normalized")
	}
	s.call("GET", "/v1/me/avatar", b.Token, nil, 404)
	s.call("PATCH", "/v1/me", b.Token, map[string]any{"expected_version": b.User.Version, "patch": map[string]any{"avatar": "upload:" + avatar.SHA256}}, 422)
	s.call("PUT", "/v1/me/avatar", a.Token, map[string]any{"expected_version": updated.Version, "image": []byte("not an image")}, 422)
	var user store.User
	json.Unmarshal(s.call("GET", "/v1/me", a.Token, nil, 200), &user)
	if user.ID != a.User.ID || user.StarryID != a.User.StarryID {
		t.Fatal("avatar changed identity")
	}
	s.call("DELETE", "/v1/me", a.Token, map[string]any{"password": password, "confirmation": "DELETE"}, 200)
	var remaining int
	s.db.Pool.QueryRow(context.Background(), "SELECT count(*) FROM account_avatars WHERE user_id=$1", a.User.ID).Scan(&remaining)
	if remaining != 0 {
		t.Fatal("avatar survives account deletion")
	}
}
