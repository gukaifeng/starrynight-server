package admin

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"image"
	"image/color"
	"image/jpeg"
	"os"
	"path/filepath"
	"testing"
)

func installArtworkFixture(t *testing.T, root string) []byte {
	t.Helper()
	bitmap := image.NewRGBA(image.Rect(0, 0, 24, 32))
	for y := 0; y < 32; y++ {
		for x := 0; x < 24; x++ {
			bitmap.Set(x, y, color.RGBA{80, 140, 160, 255})
		}
	}
	var encoded bytes.Buffer
	if err := jpeg.Encode(&encoded, bitmap, nil); err != nil {
		t.Fatal(err)
	}
	data := encoded.Bytes()
	digest := sha256.Sum256(data)
	hash := hex.EncodeToString(digest[:])
	entry := artworkFile{Path: "objects/" + hash + ".jpg", SHA256: hash, Bytes: int64(len(data))}
	base := filepath.Join(root, "data/library/record-images")
	if err := os.MkdirAll(filepath.Join(base, "objects"), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(base, entry.Path), data, 0600); err != nil {
		t.Fatal(err)
	}
	manifest, _ := json.Marshal(artworkCatalog{Schema: 1, Characters: map[string]map[string]artworkFile{"anime-kipfel": {"avatar": entry, "cover": entry}}})
	if err := os.WriteFile(filepath.Join(base, "manifest.json"), manifest, 0600); err != nil {
		t.Fatal(err)
	}
	return data
}

func TestArtworkIntegrityAndPrivatePathBoundary(t *testing.T) {
	root := t.TempDir()
	want := installArtworkFixture(t, root)
	got, err := readArtwork(root, "anime-kipfel", "cover")
	if err != nil || !bytes.Equal(got, want) {
		t.Fatalf("valid private artwork failed: %v", err)
	}
	base := filepath.Join(root, "data/library/record-images")
	files, _ := filepath.Glob(filepath.Join(base, "objects", "*.jpg"))
	if err = os.WriteFile(files[0], []byte("tampered"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err = readArtwork(root, "anime-kipfel", "cover"); err == nil {
		t.Fatal("tampered content accepted")
	}
	if _, err = openArtworkFile(base, "../../config/platform.env"); err == nil {
		t.Fatal("arbitrary path accepted")
	}
	if err = os.Remove(files[0]); err != nil {
		t.Fatal(err)
	}
	if err = os.Symlink(filepath.Join(base, "manifest.json"), files[0]); err != nil {
		t.Fatal(err)
	}
	if _, err = readArtwork(root, "anime-kipfel", "cover"); err == nil {
		t.Fatal("symlink accepted")
	}
	if _, err = readArtwork(root, "unknown", "avatar"); err == nil {
		t.Fatal("missing artwork accepted")
	}
}
