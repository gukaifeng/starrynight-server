package api

import (
	"context"
	"github.com/gukaifeng/starrynight-server/internal/content"
	"github.com/gukaifeng/starrynight-server/internal/store"
)

type PairInput struct {
	Body struct {
		CharacterID       string         `json:"character_id" minLength:"1" maxLength:"120"`
		SettingID         string         `json:"setting_id" format:"uuid"`
		CharacterRevision int64          `json:"character_revision,omitempty" minimum:"0"`
		SettingRevision   int64          `json:"setting_revision,omitempty" minimum:"0"`
		Parameters        map[string]any `json:"parameters"`
	}
}
type CreateInstanceInput struct {
	Body struct {
		MutationID        string         `json:"mutation_id" format:"uuid"`
		CharacterID       string         `json:"character_id" minLength:"1" maxLength:"120"`
		SettingID         string         `json:"setting_id" format:"uuid"`
		CharacterRevision int64          `json:"character_revision,omitempty" minimum:"0"`
		SettingRevision   int64          `json:"setting_revision,omitempty" minimum:"0"`
		Parameters        map[string]any `json:"parameters"`
	}
}
type InstanceActionInput struct {
	IDInput
	IfMatch string `header:"If-Match" required:"true"`
	Body    struct {
		MutationID string `json:"mutation_id" format:"uuid"`
		Hidden     bool   `json:"hidden,omitempty"`
	}
}

func (s *Server) instanceRoutes() {
	registerContent(s, "GET", "/v2/characters/{id}", "v2-character-core", false, func(ctx context.Context, in *IDInput) (*Output[content.CharacterCore], error) {
		v, e := s.Store.CharacterCore(ctx, principal(ctx).ID, in.ID, 0)
		return output(v, e)
	})
	registerContent(s, "POST", "/v2/character-settings/resolve", "v2-resolve-pair", false, func(ctx context.Context, in *PairInput) (*Output[store.ResolvedPair], error) {
		v, e := s.Store.ResolvePair(ctx, principal(ctx).ID, in.Body.CharacterID, in.Body.SettingID, in.Body.CharacterRevision, in.Body.SettingRevision, in.Body.Parameters)
		return output(v, e)
	})
	registerContent(s, "POST", "/v2/conversations", "v2-instance-create", true, func(ctx context.Context, in *CreateInstanceInput) (*DraftOutput[store.ConversationInstance], error) {
		v, e := s.Store.CreateConversationInstance(ctx, principal(ctx).ID, store.InstanceCreate{MutationID: in.Body.MutationID, CharacterID: in.Body.CharacterID, SettingID: in.Body.SettingID, CharacterRevision: in.Body.CharacterRevision, SettingRevision: in.Body.SettingRevision, Parameters: in.Body.Parameters})
		if e != nil {
			return nil, problem(e)
		}
		return &DraftOutput[store.ConversationInstance]{ETag: store.ETag(v.Version), Body: v}, nil
	})
	type InstancesInput struct {
		ListInput
		Character     string `query:"character_id" maxLength:"120"`
		IncludeHidden bool   `query:"include_hidden"`
	}
	registerContent(s, "GET", "/v2/conversations", "v2-instance-list", true, func(ctx context.Context, in *InstancesInput) (*Output[store.Page[store.ConversationInstance]], error) {
		v, e := s.Store.ConversationInstances(ctx, principal(ctx).ID, in.Character, in.After, in.IncludeHidden, in.Limit)
		return output(v, e)
	})
	registerContent(s, "GET", "/v2/conversations/{id}", "v2-instance-get", true, func(ctx context.Context, in *IDInput) (*DraftOutput[store.ConversationInstance], error) {
		v, e := s.Store.ConversationInstance(ctx, principal(ctx).ID, in.ID)
		if e != nil {
			return nil, problem(e)
		}
		return &DraftOutput[store.ConversationInstance]{ETag: store.ETag(v.Version), Body: v}, nil
	})
	registerContent(s, "PATCH", "/v2/conversations/{id}", "v2-instance-hide", true, func(ctx context.Context, in *InstanceActionInput) (*DraftOutput[store.ConversationInstance], error) {
		version, e := expectedETag(in.IfMatch)
		if e != nil {
			return nil, e
		}
		v, e := s.Store.HideConversationInstance(ctx, principal(ctx).ID, in.ID, in.Body.MutationID, in.Body.Hidden, version)
		if e != nil {
			return nil, problem(e)
		}
		return &DraftOutput[store.ConversationInstance]{ETag: store.ETag(v.Version), Body: v}, nil
	})
	registerContent(s, "POST", "/v2/conversations/{id}/reset", "v2-instance-reset", true, func(ctx context.Context, in *InstanceActionInput) (*DraftOutput[store.ConversationInstance], error) {
		version, e := expectedETag(in.IfMatch)
		if e != nil {
			return nil, e
		}
		v, e := s.Store.ResetConversationInstance(ctx, principal(ctx).ID, in.ID, in.Body.MutationID, version)
		if e != nil {
			return nil, problem(e)
		}
		return &DraftOutput[store.ConversationInstance]{ETag: store.ETag(v.Version), Body: v}, nil
	})
	type MessagesInput struct {
		IDInput
		After int64 `query:"after" minimum:"0"`
		Limit int   `query:"limit" minimum:"1" maximum:"200" default:"50"`
	}
	registerContent(s, "GET", "/v2/conversations/{id}/messages", "v2-instance-messages", true, func(ctx context.Context, in *MessagesInput) (*Output[store.Page[store.InstanceMessage]], error) {
		v, e := s.Store.InstanceMessages(ctx, principal(ctx).ID, in.ID, in.After, in.Limit)
		return output(v, e)
	})
}
