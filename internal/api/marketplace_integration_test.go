package api_test

import (
	"context"
	"encoding/json"
	"github.com/gukaifeng/starrynight-server/internal/assets"
	"github.com/gukaifeng/starrynight-server/internal/store"
	"strings"
	"testing"
)

func TestStorefrontUsesPublishedMetadataAndPlatformSize(t *testing.T) {
	s := setup(t)
	ctx := context.Background()
	listing := store.MarketListing{ID: "anime-fiona", Delivery: "oss", Data: map[string]any{"audition_text": "Hello"}, Media: map[string]store.MarketMedia{"cover": {Path: "cover.jpg", ObjectKey: "characters/anime-fiona/preview/cover.jpg", Size: 50, SHA256: strings.Repeat("a", 64), ContentType: "image/jpeg"}}}
	raw, _ := json.Marshal(listing)
	if _, err := s.db.Pool.Exec(ctx, "INSERT INTO character_market_assets(character_id,data) VALUES($1,$2::jsonb)", listing.ID, string(raw)); err != nil {
		t.Fatal(err)
	}
	m := assets.Manifest{SchemaVersion: 1, CharacterID: listing.ID, ReleaseID: store.NewID(), Version: 3, Platform: "ios", RuntimeVersion: "starry-runtime/1", Files: []assets.File{{Path: "character.zip", ObjectKey: "characters/anime-fiona/3/character.zip", Size: 12345, SHA256: strings.Repeat("b", 64)}}}
	payload, _ := json.Marshal(m)
	if _, err := s.db.Pool.Exec(ctx, "INSERT INTO character_releases(character_id,release_id,platform,version,manifest,distributable) VALUES($1,$2,'ios',3,$3::jsonb,true)", m.CharacterID, m.ReleaseID, string(payload)); err != nil {
		t.Fatal(err)
	}
	page := decode[store.Page[store.MarketListing]](t, s.call("GET", "/v1/store/characters?limit=200", "", nil, 200))
	if len(page.Items) != 1 || page.Items[0].DownloadBytes != 12345 || page.Items[0].ReleaseVersion != 3 {
		t.Fatal("wrong store release projection")
	}
	if page.Items[0].Media["cover"].ObjectKey != "" {
		t.Fatal("public response leaked storage keys")
	}
	sim := decode[store.Page[store.MarketListing]](t, s.call("GET", "/v1/store/characters?platform=ios-simulator", "", nil, 200))
	if len(sim.Items) != 1 || sim.Items[0].DownloadBytes != 0 {
		t.Fatal("used device package for simulator")
	}
	s.call("GET", "/v1/store/characters?platform=android", "", nil, 422)
	s.call("POST", "/v1/characters/anime-fiona/download", "", nil, 401)
}
