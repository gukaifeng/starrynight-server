package store

import (
	"context"
	"encoding/json"
	"github.com/gukaifeng/starrynight-server/internal/assets"
)

// Published independently of account data. Object keys never leave the signer.
type MarketMedia struct {
	Path        string `json:"path"`
	ObjectKey   string `json:"object_key,omitempty"`
	Size        int64  `json:"size"`
	SHA256      string `json:"sha256"`
	ContentType string `json:"content_type"`
	URL         string `json:"url,omitempty"`
}
type MarketListing struct {
	ID             string                 `json:"id"`
	Name           string                 `json:"name"`
	Description    string                 `json:"description"`
	Data           map[string]any         `json:"data"`
	Media          map[string]MarketMedia `json:"media"`
	Delivery       string                 `json:"delivery"`
	DownloadBytes  int64                  `json:"download_bytes"`
	ReleaseVersion int64                  `json:"release_version"`
}

func (s *Store) Marketplace(ctx context.Context, user, query, after, platform string, limit int) (Page[MarketListing], error) {
	page, err := s.Characters(ctx, user, query, "", after, false, limit)
	out := Page[MarketListing]{Items: []MarketListing{}, Next: page.Next}
	if err != nil {
		return out, err
	}
	// Bounded query count; metadata and manifests are read in one batch for the page.
	ids := make([]string, len(page.Items))
	for i, c := range page.Items {
		ids[i] = c.ID
	}
	rows, err := s.Pool.Query(ctx, `SELECT a.character_id,a.data,COALESCE(r.manifest,'{}'::jsonb)
 FROM character_market_assets a LEFT JOIN LATERAL (SELECT manifest FROM character_releases
 WHERE character_id=a.character_id AND platform=$2 AND distributable ORDER BY version DESC LIMIT 1) r ON true
 WHERE a.character_id=ANY($1::text[])`, ids, platform)
	if err != nil {
		return out, err
	}
	defer rows.Close()
	listings := map[string]MarketListing{}
	for rows.Next() {
		var id string
		var raw, release []byte
		if err = rows.Scan(&id, &raw, &release); err != nil {
			return out, err
		}
		var listing MarketListing
		if err = json.Unmarshal(raw, &listing); err != nil {
			return out, err
		}
		var m assets.Manifest
		if err = json.Unmarshal(release, &m); err != nil {
			return out, err
		}
		for _, f := range m.Files {
			listing.DownloadBytes += f.Size
		}
		listing.ReleaseVersion = m.Version
		listings[id] = listing
	}
	if err = rows.Err(); err != nil {
		return out, err
	}
	for _, c := range page.Items {
		if listing, ok := listings[c.ID]; ok {
			listing.ID = c.ID
			listing.Name = c.Name
			listing.Description = c.Description
			out.Items = append(out.Items, listing)
		}
	}
	return out, nil
}
