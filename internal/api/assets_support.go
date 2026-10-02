package api

import (
	"context"
	"github.com/danielgtaylor/huma/v2"
	"github.com/google/uuid"
	"github.com/gukaifeng/starrynight-server/internal/assets"
	"github.com/gukaifeng/starrynight-server/internal/store"
	"strings"
	"time"
)

func (s *Server) assetsSupportRoutes() {
	type DownloadInput struct {
		ID       string `path:"id" maxLength:"120" pattern:"^[a-zA-Z0-9_-]+$"`
		Platform string `query:"platform" enum:"ios,ios-simulator" default:"ios"`
	}
	type Ticket struct {
		Manifest  assets.Manifest `json:"manifest"`
		ExpiresAt time.Time       `json:"expires_at"`
	}
	register(s, "POST", "/v1/characters/{id}/download", "authorize-character-download", true, func(ctx context.Context, in *DownloadInput) (*Output[Ticket], error) {
		// Check ownership before returning a storage configuration error.
		m, err := s.Store.Release(ctx, principal(ctx).ID, in.ID, in.Platform)
		if err != nil {
			return nil, problem(err)
		}
		if s.Assets == nil {
			return nil, huma.Error503ServiceUnavailable("character storage is not configured")
		}
		ticket, expires, err := s.Assets.Ticket(ctx, m)
		return output(Ticket{ticket, expires}, err)
	})
	type FeedbackInput struct {
		Body struct {
			Category string `json:"category" enum:"bug,suggestion,account,content"`
			Content  string `json:"content" minLength:"1" maxLength:"2000"`
		}
	}
	register(s, "POST", "/v1/me/feedback", "create-feedback", true, func(ctx context.Context, in *FeedbackInput) (*Output[store.SupportTicket], error) {
		content := strings.TrimSpace(in.Body.Content)
		if content == "" {
			return nil, huma.Error422UnprocessableEntity("content is required")
		}
		v, err := s.Store.CreateTicket(ctx, principal(ctx).ID, in.Body.Category, content)
		return output(v, err)
	})
	register(s, "GET", "/v1/me/feedback", "list-feedback", true, func(ctx context.Context, in *ListInput) (*Output[store.Page[store.SupportTicket]], error) {
		if in.After != "" {
			if _, err := uuid.Parse(in.After); err != nil {
				return nil, huma.Error422UnprocessableEntity("invalid cursor")
			}
		}
		v, err := s.Store.Tickets(ctx, principal(ctx).ID, in.After, in.Limit)
		return output(v, err)
	})
}
