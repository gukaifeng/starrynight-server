package api

import (
	"context"
	"github.com/danielgtaylor/huma/v2"
	"github.com/gukaifeng/starrynight-server/internal/store"
)

type CatalogInput struct {
	ListInput
	Query  string `query:"q" maxLength:"100"`
	Author string `query:"author" maxLength:"120"`
	Mine   bool   `query:"mine"`
}
type CharacterBody struct {
	Name        string         `json:"name" minLength:"1" maxLength:"48"`
	Description string         `json:"description" maxLength:"2000"`
	Visibility  string         `json:"visibility" enum:"private,public,unlisted"`
	Data        map[string]any `json:"data"`
}
type CreateCharacterInput struct {
	Body struct {
		CharacterBody
		ID     string `json:"id" pattern:"^character-[a-f0-9-]{36}$"`
		BaseID string `json:"base_id" minLength:"1" maxLength:"120"`
	}
}
type UpdateCharacterInput struct {
	IDInput
	Body struct {
		CharacterBody
		ExpectedVersion int64 `json:"expected_version" minimum:"1"`
	}
}
type PreferenceInput struct {
	IDInput
	Body struct {
		Mutation
		ConversationReset string `json:"conversation_reset,omitempty" maxLength:"36"`
	}
}
type DeleteVersionInput struct {
	IDInput
	Version int64 `query:"version" minimum:"1" required:"true"`
}

func (s *Server) catalogRoutes() {
	register(s, "GET", "/v1/characters", "discover-characters", false, func(ctx context.Context, in *CatalogInput) (*Output[store.Page[store.Character]], error) {
		if in.Mine && principal(ctx).ID == "" {
			return nil, huma.Error401Unauthorized("sign in required")
		}
		v, e := s.Store.Characters(ctx, principal(ctx).ID, in.Query, in.Author, in.After, in.Mine, in.Limit)
		return output(v, e)
	})
	register(s, "GET", "/v1/characters/{id}", "get-character", false, func(ctx context.Context, in *IDInput) (*Output[store.Character], error) {
		v, e := s.Store.Character(ctx, principal(ctx).ID, in.ID)
		return output(v, e)
	})
	register(s, "POST", "/v1/characters", "create-character", true, func(ctx context.Context, in *CreateCharacterInput) (*Output[store.Character], error) {
		v, e := s.Store.CreateCharacter(ctx, principal(ctx).ID, store.Character{ID: in.Body.ID, BaseID: in.Body.BaseID, Name: in.Body.Name, Description: in.Body.Description, Visibility: in.Body.Visibility, Data: in.Body.Data})
		return output(v, e)
	})
	register(s, "PUT", "/v1/characters/{id}", "update-character", true, func(ctx context.Context, in *UpdateCharacterInput) (*Output[store.Character], error) {
		v, e := s.Store.UpdateCharacter(ctx, principal(ctx).ID, store.Character{ID: in.ID, Name: in.Body.Name, Description: in.Body.Description, Visibility: in.Body.Visibility, Data: in.Body.Data}, in.Body.ExpectedVersion)
		return output(v, e)
	})
	register(s, "DELETE", "/v1/characters/{id}", "delete-character", true, func(ctx context.Context, in *DeleteVersionInput) (*Output[OK], error) {
		return output(OK{true}, s.Store.DeleteCharacter(ctx, principal(ctx).ID, in.ID, in.Version))
	})
	register(s, "GET", "/v1/characters/{id}/preferences", "get-character-preferences", true, func(ctx context.Context, in *IDInput) (*Output[store.Document], error) {
		v, e := s.Store.Document(ctx, principal(ctx).ID, "preference", in.ID)
		return output(v, e)
	})
	register(s, "PATCH", "/v1/characters/{id}/preferences", "patch-character-preferences", true, func(ctx context.Context, in *PreferenceInput) (*Output[store.Document], error) {
		v, e := s.Store.PatchDocument(ctx, principal(ctx).ID, "preference", in.ID, in.Body.ExpectedVersion, in.Body.Patch, in.Body.ConversationReset)
		return output(v, e)
	})
	register(s, "GET", "/v1/authors/{id}", "get-author", false, func(ctx context.Context, in *IDInput) (*Output[store.Author], error) {
		v, e := s.Store.Author(ctx, in.ID)
		return output(v, e)
	})
	type WorksInput struct {
		IDInput
		ListInput
	}
	register(s, "GET", "/v1/authors/{id}/characters", "author-works", false, func(ctx context.Context, in *WorksInput) (*Output[store.Page[store.Character]], error) {
		v, e := s.Store.Characters(ctx, "", "", in.ID, in.After, false, in.Limit)
		return output(v, e)
	})
}
