package api

import (
	"context"
	"github.com/danielgtaylor/huma/v2"
	"github.com/google/uuid"
	"github.com/gukaifeng/starrynight-server/internal/store"
	"time"
)

type CharacterPath struct {
	Character string `path:"character" maxLength:"120" pattern:"^[a-zA-Z0-9_-]+$"`
}
type MessagePath struct {
	CharacterPath
	ID string `path:"id" format:"uuid"`
}

func (s *Server) journalRoutes() {
	type ResetInput struct {
		CharacterPath
		ResetID string `query:"reset_id" format:"uuid" required:"true"`
	}
	register(s, "DELETE", "/v1/conversations/{character}", "delete-conversation-and-memory", true, func(ctx context.Context, in *ResetInput) (*Output[store.ConversationReset], error) {
		v, e := s.Store.ResetConversation(ctx, principal(ctx).ID, in.Character, in.ResetID)
		return output(v, e)
	})
	register(s, "DELETE", "/v1/conversations/{character}/messages", "clear-conversation-messages", true, func(ctx context.Context, in *CharacterPath) (*Output[OK], error) {
		return output(OK{true}, s.Store.ClearMessages(ctx, principal(ctx).ID, in.Character))
	})
	register(s, "GET", "/v1/conversations", "list-conversations", true, func(ctx context.Context, in *ListInput) (*Output[store.Page[store.Conversation]], error) {
		v, e := s.Store.Conversations(ctx, principal(ctx).ID, in.After, in.Limit)
		return output(v, e)
	})
	type ConversationInput struct {
		CharacterPath
		Body struct {
			ExpectedVersion int64 `json:"expected_version" minimum:"0"`
			Hidden          bool  `json:"hidden"`
			Pinned          bool  `json:"pinned"`
		}
	}
	register(s, "PUT", "/v1/conversations/{character}", "update-conversation", true, func(ctx context.Context, in *ConversationInput) (*Output[store.Conversation], error) {
		v, e := s.Store.SetConversation(ctx, principal(ctx).ID, in.Character, in.Body.ExpectedVersion, in.Body.Hidden, in.Body.Pinned)
		return output(v, e)
	})
	type MessageListInput struct {
		CharacterPath
		After int64  `query:"after" minimum:"0"`
		Limit int    `query:"limit" minimum:"1" maximum:"200" default:"50"`
		Query string `query:"q" maxLength:"100"`
	}
	register(s, "GET", "/v1/conversations/{character}/messages", "list-messages", true, func(ctx context.Context, in *MessageListInput) (*Output[store.Page[store.Message]], error) {
		v, e := s.Store.Messages(ctx, principal(ctx).ID, in.Character, in.Query, in.After, in.Limit)
		return output(v, e)
	})
	type SearchInput struct {
		After int64  `query:"after" minimum:"0"`
		Limit int    `query:"limit" minimum:"1" maximum:"200" default:"50"`
		Query string `query:"q" minLength:"1" maxLength:"100" required:"true"`
	}
	register(s, "GET", "/v1/me/messages", "search-messages", true, func(ctx context.Context, in *SearchInput) (*Output[store.Page[store.Message]], error) {
		v, e := s.Store.Messages(ctx, principal(ctx).ID, "", in.Query, in.After, in.Limit)
		return output(v, e)
	})
	type MessageInput struct {
		MessagePath
		Body struct {
			ExpectedVersion   int64          `json:"expected_version" minimum:"0"`
			Role              string         `json:"role" enum:"user,assistant"`
			Text              string         `json:"text" maxLength:"32000"`
			CreatedAt         time.Time      `json:"created_at"`
			ConversationReset string         `json:"conversation_reset,omitempty" maxLength:"36"`
			Data              map[string]any `json:"data"`
		}
	}
	register(s, "PUT", "/v1/conversations/{character}/messages/{id}", "save-message", true, func(ctx context.Context, in *MessageInput) (*Output[store.Message], error) {
		if in.Body.CreatedAt.After(time.Now().Add(24*time.Hour)) || in.Body.CreatedAt.Year() < 2000 {
			return nil, huma.Error422UnprocessableEntity("invalid created_at")
		}
		v, e := s.Store.PutMessage(ctx, principal(ctx).ID, store.Message{ID: in.ID, CharacterID: in.Character, Role: in.Body.Role, Text: in.Body.Text, CreatedAt: in.Body.CreatedAt, Data: in.Body.Data}, in.Body.ExpectedVersion, in.Body.ConversationReset)
		return output(v, e)
	})
	for _, entry := range []struct{ path, kind string }{{"memories", "memory"}, {"moments", "moment"}} {
		path, kind := entry.path, entry.kind
		type EntriesInput struct {
			CharacterPath
			ListInput
		}
		register(s, "GET", "/v1/conversations/{character}/"+path, "list-"+path, true, func(ctx context.Context, in *EntriesInput) (*Output[store.Page[store.Entry]], error) {
			if in.After != "" {
				if _, err := uuid.Parse(in.After); err != nil {
					return nil, huma.Error422UnprocessableEntity("invalid cursor")
				}
			}
			v, e := s.Store.Entries(ctx, principal(ctx).ID, in.Character, kind, in.After, in.Limit)
			return output(v, e)
		})
		type EntryInput struct {
			MessagePath
			Body struct {
				ExpectedVersion   int64          `json:"expected_version" minimum:"0"`
				Data              map[string]any `json:"data"`
				ConversationReset string         `json:"conversation_reset,omitempty" maxLength:"36"`
			}
		}
		register(s, "PUT", "/v1/conversations/{character}/"+path+"/{id}", "save-"+kind, true, func(ctx context.Context, in *EntryInput) (*Output[store.Entry], error) {
			v, e := s.Store.PutEntry(ctx, principal(ctx).ID, store.Entry{ID: in.ID, CharacterID: in.Character, Kind: kind, Data: in.Body.Data}, in.Body.ExpectedVersion, in.Body.ConversationReset)
			return output(v, e)
		})
		type DeleteEntryInput struct {
			MessagePath
			Version int64 `query:"version" minimum:"1" required:"true"`
		}
		register(s, "DELETE", "/v1/conversations/{character}/"+path+"/{id}", "delete-"+kind, true, func(ctx context.Context, in *DeleteEntryInput) (*Output[OK], error) {
			return output(OK{true}, s.Store.DeleteEntry(ctx, principal(ctx).ID, in.Character, kind, in.ID, in.Version))
		})
	}
}
func (s *Server) syncRoutes() {
	type SyncInput struct {
		After int64 `query:"after" minimum:"0"`
		Limit int   `query:"limit" minimum:"1" maximum:"200" default:"100"`
	}
	register(s, "GET", "/v1/sync", "sync-changes", true, func(ctx context.Context, in *SyncInput) (*Output[store.Page[store.Change]], error) {
		v, e := s.Store.Changes(ctx, principal(ctx).ID, in.After, in.Limit)
		return output(v, e)
	})
	// Export is cursor-paged too: callers can stream arbitrarily large journals
	// to their own file without an unbounded server response or memory spike.
	register(s, "GET", "/v1/me/export", "export-account-data", true, func(ctx context.Context, in *SyncInput) (*Output[store.Page[store.Change]], error) {
		v, e := s.Store.Changes(ctx, principal(ctx).ID, in.After, in.Limit)
		return output(v, e)
	})
}
