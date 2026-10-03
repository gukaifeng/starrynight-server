package api

import (
	"context"
	"github.com/danielgtaylor/huma/v2"
	"github.com/gukaifeng/starrynight-server/internal/compatibility"
	"github.com/gukaifeng/starrynight-server/internal/content"
	"github.com/gukaifeng/starrynight-server/internal/store"
	"strconv"
	"strings"
)

type DraftOutput[T any] struct {
	ETag string `header:"ETag"`
	Body T
}
type DraftCreateInput struct {
	Body struct {
		MutationID    string            `json:"mutation_id" format:"uuid"`
		ClientDraftID string            `json:"client_draft_id" format:"uuid"`
		Body          content.DraftBody `json:"body"`
	}
}
type DraftSaveInput struct {
	IDInput
	IfMatch string `header:"If-Match" required:"true"`
	Body    struct {
		MutationID string            `json:"mutation_id" format:"uuid"`
		Body       content.DraftBody `json:"body"`
	}
}
type DraftActionInput struct {
	IDInput
	IfMatch string `header:"If-Match" required:"true"`
	Body    struct {
		MutationID string `json:"mutation_id" format:"uuid"`
		Visibility string `json:"visibility,omitempty" enum:"private,public"`
	}
}

func expectedETag(raw string) (int64, error) {
	if len(raw) < 3 || raw[0] != '"' || raw[len(raw)-1] != '"' {
		return 0, huma.Error428PreconditionRequired("use the exact strong ETag from the latest draft")
	}
	n, e := strconv.ParseInt(raw[1:len(raw)-1], 10, 64)
	if e != nil || n < 1 {
		return 0, huma.Error428PreconditionRequired("a valid draft ETag is required")
	}
	return n, nil
}
func (s *Server) contentEnabled(ctx huma.Context, next func(huma.Context)) {
	if !s.Config.SettingPlatform || s.ContentKeys == nil {
		huma.WriteErr(s.API, ctx, 503, "setting platform is not enabled")
		return
	}
	next(ctx)
}
func registerContent[I, O any](s *Server, method, path, id string, private bool, handler func(context.Context, *I) (*O, error)) {
	op := huma.Operation{OperationID: id, Method: method, Path: path, MaxBodyBytes: 256 * 1024, Middlewares: huma.Middlewares{s.contentEnabled}}
	if strings.HasPrefix(id, "v2-draft-") {
		op.MaxBodyBytes = 600 * 1024
	}
	if private {
		op.Security = []map[string][]string{{"session": {}}}
		op.Middlewares = append(op.Middlewares, s.required)
	}
	huma.Register(s.API, op, handler)
}
func (s *Server) settingRoutes() {
	registerContent(s, "GET", "/v2/setting-form-schema", "v2-setting-form-schema", false, func(ctx context.Context, in *Empty) (*Output[map[string]any], error) {
		return output(map[string]any{"contract": content.Contract, "schema_version": 1, "fixed_fields": compatibility.Fields(), "max_draft_bytes": content.MaxDraftBytes, "public_sections": []string{"title", "synopsis", "experience", "cover_asset_id"}, "private_sections": []string{"scene", "goals", "language_policy", "blocks", "opening_policy"}}, nil)
	})
	registerContent(s, "GET", "/v2/me/setting-drafts", "v2-draft-list", true, func(ctx context.Context, in *ListInput) (*Output[store.Page[store.DraftSummary]], error) {
		v, e := s.Store.SettingDrafts(ctx, principal(ctx).ID, in.After, in.Limit)
		return output(v, e)
	})
	registerContent(s, "GET", "/v2/me/setting-drafts/{id}", "v2-draft-get", true, func(ctx context.Context, in *IDInput) (*DraftOutput[store.SettingDraft], error) {
		v, e := s.Store.SettingDraft(ctx, s.ContentKeys, principal(ctx).ID, in.ID)
		if e != nil {
			return nil, problem(e)
		}
		return &DraftOutput[store.SettingDraft]{ETag: store.ETag(v.Version), Body: v}, nil
	})
	registerContent(s, "POST", "/v2/me/setting-drafts", "v2-draft-create", true, func(ctx context.Context, in *DraftCreateInput) (*DraftOutput[store.DraftSummary], error) {
		v, e := s.Store.SaveSettingDraft(ctx, s.ContentKeys, principal(ctx).ID, "", store.DraftMutation{MutationID: in.Body.MutationID, ClientDraftID: in.Body.ClientDraftID, Body: in.Body.Body})
		if e != nil {
			return nil, problem(e)
		}
		return &DraftOutput[store.DraftSummary]{ETag: store.ETag(v.Version), Body: v}, nil
	})
	registerContent(s, "PUT", "/v2/me/setting-drafts/{id}", "v2-draft-save", true, func(ctx context.Context, in *DraftSaveInput) (*DraftOutput[store.DraftSummary], error) {
		n, e := expectedETag(in.IfMatch)
		if e != nil {
			return nil, e
		}
		v, e := s.Store.SaveSettingDraft(ctx, s.ContentKeys, principal(ctx).ID, in.ID, store.DraftMutation{MutationID: in.Body.MutationID, ExpectedVersion: n, Body: in.Body.Body})
		if e != nil {
			return nil, problem(e)
		}
		return &DraftOutput[store.DraftSummary]{ETag: store.ETag(v.Version), Body: v}, nil
	})
	registerContent(s, "DELETE", "/v2/me/setting-drafts/{id}", "v2-draft-delete", true, func(ctx context.Context, in *DraftActionInput) (*DraftOutput[store.DraftSummary], error) {
		n, e := expectedETag(in.IfMatch)
		if e != nil {
			return nil, e
		}
		v, e := s.Store.DeleteSettingDraft(ctx, principal(ctx).ID, in.ID, in.Body.MutationID, n)
		if e != nil {
			return nil, problem(e)
		}
		return &DraftOutput[store.DraftSummary]{ETag: store.ETag(v.Version), Body: v}, nil
	})
	registerContent(s, "POST", "/v2/me/setting-drafts/{id}/validate", "v2-draft-validate", true, func(ctx context.Context, in *IDInput) (*Output[content.SettingReport], error) {
		d, e := s.Store.SettingDraft(ctx, s.ContentKeys, principal(ctx).ID, in.ID)
		if e != nil {
			return nil, problem(e)
		}
		v, e := s.Store.ValidateSettingSource(ctx, d.Body.Document)
		return output(v, e)
	})
	registerContent(s, "POST", "/v2/me/setting-drafts/{id}/submit", "v2-draft-submit", true, func(ctx context.Context, in *DraftActionInput) (*Output[store.Submission], error) {
		n, e := expectedETag(in.IfMatch)
		if e != nil {
			return nil, e
		}
		v, e := s.Store.SubmitSetting(ctx, s.ContentKeys, principal(ctx).ID, in.ID, in.Body.MutationID, in.Body.Visibility, n)
		return output(v, e)
	})
	registerContent(s, "GET", "/v2/me/setting-drafts/{id}/checkpoints", "v2-draft-checkpoints", true, func(ctx context.Context, in *IDInput) (*Output[[]store.DraftCheckpoint], error) {
		v, e := s.Store.DraftCheckpoints(ctx, principal(ctx).ID, in.ID)
		return output(v, e)
	})
	type CheckpointInput struct {
		IDInput
		Checkpoint string `path:"checkpoint" format:"uuid"`
	}
	registerContent(s, "GET", "/v2/me/setting-drafts/{id}/checkpoints/{checkpoint}", "v2-draft-checkpoint-get", true, func(ctx context.Context, in *CheckpointInput) (*Output[content.DraftBody], error) {
		v, e := s.Store.DraftCheckpoint(ctx, s.ContentKeys, principal(ctx).ID, in.ID, in.Checkpoint)
		return output(v, e)
	})
	registerContent(s, "GET", "/v2/me/setting-submissions", "v2-setting-submissions", true, func(ctx context.Context, in *ListInput) (*Output[store.Page[store.Submission]], error) {
		v, e := s.Store.SettingSubmissions(ctx, principal(ctx).ID, in.After, in.Limit)
		return output(v, e)
	})
	type SettingsList struct {
		CatalogInput
		Favorites bool `query:"favorites"`
	}
	registerContent(s, "GET", "/v2/settings", "v2-settings-catalog", false, func(ctx context.Context, in *SettingsList) (*Output[store.Page[store.PublicSetting]], error) {
		if (in.Mine || in.Favorites) && principal(ctx).ID == "" {
			return nil, huma.Error401Unauthorized("sign in required")
		}
		v, e := s.Store.SettingsCatalog(ctx, principal(ctx).ID, in.Query, in.Author, in.After, in.Mine, in.Favorites, in.Limit)
		return output(v, e)
	})
	registerContent(s, "GET", "/v2/settings/{id}", "v2-setting-get", false, func(ctx context.Context, in *IDInput) (*Output[store.PublicSetting], error) {
		v, e := s.Store.PublicSetting(ctx, principal(ctx).ID, in.ID, 0, false)
		return output(v, e)
	})
	type RevisionInput struct {
		IDInput
		Revision int64 `path:"revision" minimum:"1"`
	}
	registerContent(s, "GET", "/v2/me/settings/{id}/revisions/{revision}/source", "v2-setting-source", true, func(ctx context.Context, in *RevisionInput) (*Output[content.SettingDocument], error) {
		v, e := s.Store.SettingSource(ctx, s.ContentKeys, principal(ctx).ID, in.ID, in.Revision)
		return output(v, e)
	})
	registerContent(s, "PUT", "/v2/me/setting-favorites/{id}", "v2-setting-favorite", true, func(ctx context.Context, in *IDInput) (*Output[OK], error) {
		return output(OK{true}, s.Store.FavoriteSetting(ctx, principal(ctx).ID, in.ID, true))
	})
	registerContent(s, "DELETE", "/v2/me/setting-favorites/{id}", "v2-setting-unfavorite", true, func(ctx context.Context, in *IDInput) (*Output[OK], error) {
		return output(OK{true}, s.Store.FavoriteSetting(ctx, principal(ctx).ID, in.ID, false))
	})
	type AccessInput struct {
		DraftActionInput
		Action string `path:"action" enum:"withdraw,make-private,revoke"`
	}
	registerContent(s, "POST", "/v2/me/settings/{id}/access/{action}", "v2-setting-access", true, func(ctx context.Context, in *AccessInput) (*Output[store.Document], error) {
		n, e := expectedETag(in.IfMatch)
		if e != nil {
			return nil, e
		}
		v, e := s.Store.SettingAccess(ctx, principal(ctx).ID, in.ID, in.Action, in.Body.MutationID, n)
		return output(v, e)
	})
}
