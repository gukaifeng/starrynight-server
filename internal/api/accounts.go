package api

import (
	"context"
	"crypto/sha256"
	"fmt"
	"github.com/danielgtaylor/huma/v2"
	"github.com/go-redis/redis_rate/v10"
	"github.com/gukaifeng/starrynight-server/internal/identity"
	"github.com/gukaifeng/starrynight-server/internal/store"
	"strings"
)

type Credentials struct {
	Username string `json:"username" minLength:"3" maxLength:"32" pattern:"^[a-zA-Z0-9_]+$"`
	Password string `json:"password" minLength:"12" maxLength:"128"`
}
type RegisterInput struct {
	Body struct {
		Credentials
		DisplayName string `json:"display_name" minLength:"1" maxLength:"48"`
	}
}
type LoginInput struct{ Body Credentials }
type PatchInput struct{ Body Mutation }

func (s *Server) authRoutes() {
	register(s, "GET", "/v1/capabilities", "platform-capabilities", false, func(ctx context.Context, _ *Empty) (*Output[map[string]any], error) {
		return output(map[string]any{"schema_version": 1, "test_guest": s.Config.AllowGuest, "auth_methods": []string{"password"}, "sync": true}, nil)
	})
	register(s, "POST", "/v1/auth/register", "register-account", false, func(ctx context.Context, in *RegisterInput) (*Output[identity.Session], error) {
		name := strings.ToLower(in.Body.Username)
		if e := s.limitLogin(ctx, name); e != nil {
			return nil, e
		}
		old := principal(ctx)
		if old.ID != "" && !old.Guest {
			return nil, huma.Error409Conflict("already signed in")
		}
		hash, e := s.Identity.Hash(ctx, in.Body.Password)
		if e != nil {
			return nil, problem(e)
		}
		var u store.User
		if old.Guest {
			u, e = s.Store.UpgradeGuest(ctx, old.ID, name, hash, in.Body.DisplayName)
		} else {
			u, e = s.Store.CreateUser(ctx, name, hash, in.Body.DisplayName, false)
		}
		if e != nil {
			return nil, problem(e)
		}
		session, e := s.Identity.Issue(ctx, u)
		return output(session, e)
	})
	register(s, "POST", "/v1/auth/login", "login", false, func(ctx context.Context, in *LoginInput) (*Output[identity.Session], error) {
		name := strings.ToLower(in.Body.Username)
		if e := s.limitLogin(ctx, name); e != nil {
			return nil, e
		}
		u, e := s.Identity.Login(ctx, name, in.Body.Password)
		if e != nil {
			return nil, problem(e)
		}
		session, e := s.Identity.Issue(ctx, u)
		return output(session, e)
	})
	register(s, "POST", "/v1/auth/guest", "test-guest", false, func(ctx context.Context, _ *Empty) (*Output[identity.Session], error) {
		if !s.Config.AllowGuest {
			return nil, huma.Error404NotFound("not available")
		}
		if principal(ctx).ID != "" {
			return nil, huma.Error409Conflict("already signed in")
		}
		u, e := s.Store.CreateUser(ctx, "", "", "星夜体验者", true)
		if e != nil {
			return nil, problem(e)
		}
		session, e := s.Identity.Issue(ctx, u)
		return output(session, e)
	})
	register(s, "POST", "/v1/auth/refresh", "rotate-session", true, func(ctx context.Context, _ *Empty) (*Output[identity.Session], error) {
		session, e := s.Identity.Issue(ctx, principal(ctx))
		return output(session, e)
	})
	register(s, "POST", "/v1/auth/logout", "logout", true, func(ctx context.Context, _ *Empty) (*Output[OK], error) {
		e := s.Identity.Sessions.Destroy(ctx)
		return output(OK{true}, e)
	})
}
func (s *Server) limitLogin(ctx context.Context, name string) error {
	key := fmt.Sprintf("%scredential:%x", s.Config.RedisPrefix, sha256.Sum256([]byte(name)))
	r, e := s.Limiter.Allow(ctx, key, redis_rate.PerMinute(10))
	if e != nil {
		return problem(e)
	}
	if r.Allowed == 0 {
		return huma.Error429TooManyRequests("try again shortly")
	}
	return nil
}
func (s *Server) accountRoutes() {
	type RenameInput struct {
		Body struct {
			Username        string `json:"username" minLength:"3" maxLength:"32" pattern:"^[a-zA-Z0-9_]+$"`
			Password        string `json:"password" minLength:"1" maxLength:"128"`
			ExpectedVersion int64  `json:"expected_version" minimum:"1"`
		}
	}
	register(s, "POST", "/v1/me/username", "change-login-name", true, func(ctx context.Context, in *RenameInput) (*Output[identity.Session], error) {
		u := principal(ctx)
		if u.Guest {
			return nil, huma.Error403Forbidden("register first")
		}
		if err := s.limitLogin(ctx, u.Username); err != nil {
			return nil, err
		}
		_, hash, err := s.Store.Credential(ctx, u.Username)
		if err != nil {
			return nil, problem(err)
		}
		if err = s.Identity.Verify(ctx, in.Body.Password, hash); err != nil {
			return nil, problem(err)
		}
		u, err = s.Store.ChangeUsername(ctx, u.ID, hash, strings.ToLower(in.Body.Username), in.Body.ExpectedVersion)
		if err != nil {
			return nil, problem(err)
		}
		v, err := s.Identity.Issue(ctx, u)
		return output(v, err)
	})
	type RevokeInput struct {
		Body struct {
			Password string `json:"password" minLength:"1" maxLength:"128"`
		}
	}
	register(s, "POST", "/v1/me/sessions/revoke", "revoke-other-sessions", true, func(ctx context.Context, in *RevokeInput) (*Output[identity.Session], error) {
		u := principal(ctx)
		if u.Guest {
			return nil, huma.Error403Forbidden("register first")
		}
		if err := s.limitLogin(ctx, u.Username); err != nil {
			return nil, err
		}
		_, hash, err := s.Store.Credential(ctx, u.Username)
		if err != nil {
			return nil, problem(err)
		}
		if err := s.Identity.Verify(ctx, in.Body.Password, hash); err != nil {
			return nil, problem(err)
		}
		u, err = s.Store.RevokeSessions(ctx, u.ID, hash)
		if err != nil {
			return nil, problem(err)
		}
		v, err := s.Identity.Issue(ctx, u)
		return output(v, err)
	})
	register(s, "GET", "/v1/me", "get-account", true, func(ctx context.Context, _ *Empty) (*Output[store.User], error) { return output(principal(ctx), nil) })
	register(s, "PATCH", "/v1/me", "update-profile", true, func(ctx context.Context, in *PatchInput) (*Output[store.Document], error) {
		v, e := s.Store.Profile(ctx, principal(ctx).ID, in.Body.ExpectedVersion, in.Body.Patch)
		return output(v, e)
	})
	register(s, "GET", "/v1/me/settings", "get-settings", true, func(ctx context.Context, _ *Empty) (*Output[store.Document], error) {
		v, e := s.Store.Document(ctx, principal(ctx).ID, "settings", "")
		return output(v, e)
	})
	register(s, "PATCH", "/v1/me/settings", "patch-settings", true, func(ctx context.Context, in *PatchInput) (*Output[store.Document], error) {
		v, e := s.Store.PatchDocument(ctx, principal(ctx).ID, "settings", "", in.Body.ExpectedVersion, in.Body.Patch)
		return output(v, e)
	})
	register(s, "GET", "/v1/me/author", "get-own-author", true, func(ctx context.Context, _ *Empty) (*Output[store.Author], error) {
		v, e := s.Store.MyAuthor(ctx, principal(ctx).ID)
		return output(v, e)
	})
	register(s, "PATCH", "/v1/me/author", "patch-own-author", true, func(ctx context.Context, in *PatchInput) (*Output[store.Author], error) {
		v, e := s.Store.PatchAuthor(ctx, principal(ctx).ID, in.Body.ExpectedVersion, in.Body.Patch)
		return output(v, e)
	})
	type PasswordInput struct {
		Body struct {
			CurrentPassword string `json:"current_password" minLength:"1" maxLength:"128"`
			NewPassword     string `json:"new_password" minLength:"12" maxLength:"128"`
		}
	}
	register(s, "POST", "/v1/me/password", "change-password", true, func(ctx context.Context, in *PasswordInput) (*Output[identity.Session], error) {
		u := principal(ctx)
		if u.Guest {
			return nil, huma.Error403Forbidden("register first")
		}
		if e := s.limitLogin(ctx, u.Username); e != nil {
			return nil, e
		}
		_, oldHash, e := s.Store.Credential(ctx, u.Username)
		if e != nil {
			return nil, problem(e)
		}
		if e = s.Identity.Verify(ctx, in.Body.CurrentPassword, oldHash); e != nil {
			return nil, problem(e)
		}
		hash, e := s.Identity.Hash(ctx, in.Body.NewPassword)
		if e != nil {
			return nil, problem(e)
		}
		if e = s.Store.ChangePassword(ctx, u.ID, oldHash, hash); e != nil {
			return nil, problem(e)
		}
		u.Epoch++
		session, e := s.Identity.Issue(ctx, u)
		return output(session, e)
	})
	type DeleteInput struct {
		Body struct {
			Password     string `json:"password" maxLength:"128"`
			Confirmation string `json:"confirmation" enum:"DELETE"`
		}
	}
	register(s, "DELETE", "/v1/me", "delete-account", true, func(ctx context.Context, in *DeleteInput) (*Output[OK], error) {
		u := principal(ctx)
		if !u.Guest {
			if e := s.limitLogin(ctx, u.Username); e != nil {
				return nil, e
			}
			if _, e := s.Identity.Login(ctx, u.Username, in.Body.Password); e != nil {
				return nil, problem(e)
			}
		}
		if e := s.Store.DeleteUser(ctx, u.ID); e != nil {
			return nil, problem(e)
		}
		return output(OK{true}, s.Identity.Sessions.Destroy(ctx))
	})
	for _, relation := range []struct{ path, kind string }{{"subscriptions", "subscription"}, {"follows", "follow"}} {
		path, kind := relation.path, relation.kind
		register(s, "GET", "/v1/me/"+path, "list-"+path, true, func(ctx context.Context, in *ListInput) (*Output[store.Page[store.Relation]], error) {
			v, e := s.Store.Relations(ctx, principal(ctx).ID, kind, in.After, in.Limit)
			return output(v, e)
		})
		for _, method := range []string{"PUT", "DELETE"} {
			method := method
			register(s, method, "/v1/me/"+path+"/{id}", strings.ToLower(method)+"-"+kind, true, func(ctx context.Context, in *IDInput) (*Output[OK], error) {
				e := s.Store.SetRelation(ctx, principal(ctx).ID, kind, in.ID, method == "PUT")
				return output(OK{true}, e)
			})
		}
	}
}
