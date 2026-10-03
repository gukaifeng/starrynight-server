package admin

import (
	"context"
	_ "embed"
	"encoding/json"
	"net/url"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/gukaifeng/starrynight-server/internal/store"
)

// Explicit copy of the App's public curation metadata. No client checkout is
// read at runtime; character definitions and media remain live published data.
//
//go:embed discovery_curation.json
var discoveryCuration json.RawMessage

type discoveryAuthor struct {
	ID   string `json:"id"`
	Name string `json:"name"`
	Bio  string `json:"bio"`
}
type discoveryItem struct {
	store.MarketListing
	Author    discoveryAuthor `json:"author"`
	Creator   bool            `json:"creator"`
	UpdatedAt time.Time       `json:"updated_at"`
	BaseID    string          `json:"base_id,omitempty"`
}

// This is the public App catalogue under an administrator session, not the
// wider inspector catalogue, which also contains private and archived rows.
func (s *Server) discovery(c *gin.Context) {
	platform := c.DefaultQuery("platform", "ios")
	if platform != "ios" && platform != "ios-simulator" {
		fail(c, bad("请选择 iPhone 或模拟器平台"))
		return
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 15*time.Second)
	defer cancel()
	characters := []store.Character{}
	listings := map[string]store.MarketListing{}
	after := ""
	for {
		page, err := s.DB.Characters(ctx, "", "", "", after, false, 200)
		if err != nil {
			fail(c, err)
			return
		}
		market, err := s.DB.Marketplace(ctx, "", "", after, platform, 200)
		if err != nil {
			fail(c, err)
			return
		}
		characters = append(characters, page.Items...)
		for _, item := range market.Items {
			listings[item.ID] = item
		}
		if len(characters) > 10000 || page.Next != "" && page.Next <= after {
			fail(c, bad("发现内容超过完整读取范围，请联系维护人员"))
			return
		}
		if page.Next == "" {
			break
		}
		after = page.Next
	}
	authorIDs := []string{}
	for _, character := range characters {
		authorIDs = append(authorIDs, character.AuthorID)
	}
	authors := map[string]discoveryAuthor{}
	rows, err := s.DB.Pool.Query(ctx, `SELECT id,COALESCE(data->>'name',''),COALESCE(data->>'bio','') FROM authors WHERE id=ANY($1::text[])`, authorIDs)
	if err != nil {
		fail(c, err)
		return
	}
	for rows.Next() {
		var author discoveryAuthor
		if err = rows.Scan(&author.ID, &author.Name, &author.Bio); err != nil {
			rows.Close()
			fail(c, err)
			return
		}
		authors[author.ID] = author
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		fail(c, err)
		return
	}
	items := []discoveryItem{}
	for _, character := range characters {
		listing, published := listings[character.ID]
		creator := character.OwnerID != ""
		if !published {
			if !creator {
				continue
			}
			// Public user creations can inherit a base before publishing their
			// own preview references. Private drafts never enter this query.
			base := listings[character.BaseID]
			listing = store.MarketListing{ID: character.ID, Name: character.Name, Description: character.Description, Data: base.Data, Media: base.Media, Delivery: base.Delivery}
		}
		listing.Media = discoveryMedia(listing.ID, listing.Media)
		items = append(items, discoveryItem{MarketListing: listing, Author: authors[character.AuthorID], Creator: creator, UpdatedAt: character.UpdatedAt, BaseID: character.BaseID})
	}
	c.JSON(200, gin.H{"items": items, "curation": discoveryCuration, "platform": platform, "complete": true})
}

func discoveryMedia(id string, media map[string]store.MarketMedia) map[string]store.MarketMedia {
	out := map[string]store.MarketMedia{}
	for kind, entry := range media {
		if !contains([]string{"cover", "avatar", "audition", "video"}, kind) {
			continue
		}
		entry.ObjectKey = ""
		entry.URL = "/admin-api/v1/discovery/" + url.PathEscape(id) + "/media/" + kind
		out[kind] = entry
	}
	return out
}

// Media is resolved from immutable catalogue references, never from a browser
// URL or arbitrary OSS key. Same-origin streaming works with the console CSP.
func (s *Server) discoveryMedia(c *gin.Context) {
	kind := c.Param("kind")
	if !contains([]string{"cover", "avatar", "audition", "video"}, kind) {
		c.Status(404)
		return
	}
	var key string
	err := s.DB.Pool.QueryRow(c.Request.Context(), `SELECT COALESCE(NULLIF(a.data->'media'->$2->>'object_key',''),b.data->'media'->$2->>'object_key','')
	FROM characters c LEFT JOIN character_market_assets a ON a.character_id=c.id
	LEFT JOIN characters base ON base.id=c.base_id AND base.visibility='public' AND NOT base.deleted
	LEFT JOIN character_market_assets b ON b.character_id=base.id
	WHERE c.id=$1 AND c.visibility='public' AND NOT c.deleted`, c.Param("id"), kind).Scan(&key)
	if err != nil || key == "" {
		c.Status(404)
		return
	}
	if s.Config.Signer == nil {
		c.JSON(503, gin.H{"error": "尚未配置角色预览存储"})
		return
	}
	s.serveOSSObject(c, key, true)
}
