package admin

import (
	"bytes"
	"crypto/sha256"
	_ "embed"
	"encoding/hex"
	"encoding/json"
	"errors"
	"image/jpeg"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

//go:embed artwork/default-avatar.svg
var defaultAvatar []byte

type artworkFile struct {
	Path   string `json:"path"`
	SHA256 string `json:"sha256"`
	Bytes  int64  `json:"bytes"`
}
type artworkCatalog struct {
	Schema     int                               `json:"schema_version"`
	Characters map[string]map[string]artworkFile `json:"characters"`
}

var artworkPath = regexp.MustCompile(`^objects/[a-f0-9]{64}\.jpg$`)

// Artwork is an explicit private import, never an implicit client checkout
// dependency or a proxy for arbitrary remote URLs supplied in a JSON record.
func readArtwork(root, id, variant string) ([]byte, error) {
	base := filepath.Join(root, "data/library/record-images")
	if root == "" {
		return nil, os.ErrNotExist
	}
	manifest, err := openArtworkFile(base, "manifest.json")
	if err != nil {
		return nil, err
	}
	defer manifest.Close()
	var catalog artworkCatalog
	if err = json.NewDecoder(io.LimitReader(manifest, 4<<20)).Decode(&catalog); err != nil || catalog.Schema != 1 {
		return nil, os.ErrNotExist
	}
	entry, ok := catalog.Characters[id][variant]
	if !ok || !artworkPath.MatchString(entry.Path) || entry.Bytes <= 0 || entry.Bytes > 8<<20 || entry.Path != "objects/"+entry.SHA256+".jpg" {
		return nil, os.ErrNotExist
	}
	file, err := openArtworkFile(base, entry.Path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	data, err := io.ReadAll(io.LimitReader(file, (8<<20)+1))
	if err != nil {
		return nil, err
	}
	sum := sha256.Sum256(data)
	config, err := jpeg.DecodeConfig(bytes.NewReader(data))
	if int64(len(data)) != entry.Bytes || hex.EncodeToString(sum[:]) != entry.SHA256 || err != nil || config.Width < 1 || config.Height < 1 || config.Width > 4096 || config.Height > 4096 {
		return nil, os.ErrNotExist
	}
	return data, nil
}

func openArtworkFile(base, relative string) (*os.File, error) {
	if relative != "manifest.json" && !artworkPath.MatchString(relative) {
		return nil, os.ErrNotExist
	}
	// Reject symlinks in the imported tree, including its root and parents.
	path := filepath.Join(base, relative)
	boundary := filepath.Dir(filepath.Dir(filepath.Dir(base)))
	for current := path; ; current = filepath.Dir(current) {
		info, err := os.Lstat(current)
		if err != nil || info.Mode()&os.ModeSymlink != 0 {
			return nil, os.ErrNotExist
		}
		if current == boundary || filepath.Dir(current) == current {
			break
		}
	}
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	info, err := file.Stat()
	if err != nil || !info.Mode().IsRegular() {
		file.Close()
		return nil, os.ErrNotExist
	}
	return file, nil
}

func (s *Server) recordImage(c *gin.Context) {
	id, kind, variant := c.Param("id"), c.Param("kind"), c.Param("variant")
	if len(id) == 0 || len(id) > 200 || strings.ContainsAny(id, "/\\\x00") || (variant != "avatar" && variant != "cover") {
		c.Status(404)
		return
	}
	c.Header("Cache-Control", "no-store")
	switch kind {
	case "user":
		if variant != "avatar" {
			c.Status(404)
			return
		}
		s.userImage(c, id)
	case "author":
		if variant != "avatar" {
			c.Status(404)
			return
		}
		var user string
		if err := s.DB.Pool.QueryRow(c.Request.Context(), "SELECT COALESCE(user_id::text,'') FROM authors WHERE id=$1", id).Scan(&user); err != nil {
			imageError(c, err)
			return
		}
		if user != "" {
			s.userImage(c, user)
			return
		}
		c.Data(200, "image/svg+xml", defaultAvatar)
	case "character":
		seen := map[string]bool{}
		for depth := 0; id != "" && depth < 8 && !seen[id]; depth++ {
			seen[id] = true
			var base string
			var data map[string]any
			// Admin inspection includes archived/private characters, just as
			// the authenticated catalog does. Nothing is added to App routes.
			if err := s.DB.Pool.QueryRow(c.Request.Context(), "SELECT COALESCE(base_id,''),data FROM characters WHERE id=$1", id).Scan(&base, &data); err != nil {
				imageError(c, err)
				return
			}
			candidates := []string{id}
			if runtime, ok := data["runtime_id"].(string); ok && runtime != id {
				candidates = append(candidates, runtime)
			}
			for _, candidate := range candidates {
				if image, err := readArtwork(s.Config.RuntimeRoot, candidate, variant); err == nil {
					c.Data(200, "image/jpeg", image)
					return
				}
			}
			id = base
		}
		c.Status(404)
	default:
		c.Status(404)
	}
}

func (s *Server) userImage(c *gin.Context, id string) {
	if _, err := uuid.Parse(id); err != nil {
		c.Status(404)
		return
	}
	var reference string
	if err := s.DB.Pool.QueryRow(c.Request.Context(), "SELECT COALESCE(profile->>'avatar','') FROM users WHERE id=$1", id).Scan(&reference); err != nil {
		imageError(c, err)
		return
	}
	if strings.HasPrefix(reference, "upload:") {
		avatar, err := s.DB.Avatar(c.Request.Context(), id)
		if err != nil {
			fail(c, err)
			return
		}
		c.Data(200, avatar.ContentType, avatar.Image)
		return
	}
	c.Data(200, "image/svg+xml", defaultAvatar)
}

func imageError(c *gin.Context, err error) {
	if errors.Is(err, pgx.ErrNoRows) {
		c.Status(404)
		return
	}
	fail(c, err)
}
