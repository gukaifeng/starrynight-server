package assets

import (
	"fmt"
	"path"
	"regexp"
)

// Immutable release metadata: changing any byte requires a new version.
type Manifest struct {
	SchemaVersion  int            `json:"schema_version"`
	CharacterID    string         `json:"character_id"`
	ReleaseID      string         `json:"release_id"`
	Version        int64          `json:"version"`
	Platform       string         `json:"platform"`
	RuntimeVersion string         `json:"runtime_version"`
	Files          []File         `json:"files"`
	Extensions     map[string]any `json:"extensions,omitempty"`
}
type File struct {
	Path      string            `json:"path"`
	ObjectKey string            `json:"object_key,omitempty"`
	Size      int64             `json:"size"`
	SHA256    string            `json:"sha256"`
	URL       string            `json:"url,omitempty"`
	Headers   map[string]string `json:"headers,omitempty"`
}

var safePath = regexp.MustCompile(`^[a-zA-Z0-9_./-]+$`)
var digest = regexp.MustCompile(`^[a-f0-9]{64}$`)

func (m Manifest) Validate() error {
	if m.SchemaVersion != 1 || m.Version < 1 || m.CharacterID == "" || m.ReleaseID == "" || m.RuntimeVersion == "" {
		return fmt.Errorf("incomplete release metadata")
	}
	if m.Platform != "ios" && m.Platform != "ios-simulator" {
		return fmt.Errorf("unsupported release platform")
	}
	if len(m.Files) == 0 || len(m.Files) > 64 {
		return fmt.Errorf("release requires 1..64 files")
	}
	paths := map[string]bool{}
	var bytes int64
	for _, f := range m.Files {
		if !safePath.MatchString(f.Path) || path.Clean(f.Path) != f.Path || f.Path == "." || f.Path == ".." || f.Path[0] == '/' || len(f.Path) > 240 || paths[f.Path] {
			return fmt.Errorf("invalid or duplicate file path")
		}
		if !safePath.MatchString(f.ObjectKey) || path.Clean(f.ObjectKey) != f.ObjectKey || f.ObjectKey[0] == '/' || f.ObjectKey == ".." || len(f.ObjectKey) > 1024 {
			return fmt.Errorf("invalid object key")
		}
		if len(f.Path) >= 3 && f.Path[:3] == "../" || len(f.ObjectKey) >= 3 && f.ObjectKey[:3] == "../" {
			return fmt.Errorf("parent paths are forbidden")
		}
		if f.Size <= 0 || f.Size > 8<<30 || !digest.MatchString(f.SHA256) || f.URL != "" || len(f.Headers) > 0 {
			return fmt.Errorf("invalid file metadata")
		}
		paths[f.Path] = true
		bytes += f.Size
	}
	if bytes > 8<<30 {
		return fmt.Errorf("release exceeds 8 GiB")
	}
	return nil
}
