package identity

import (
	"context"
	"errors"
	"github.com/alexedwards/argon2id"
	"github.com/alexedwards/scs/goredisstore"
	"github.com/alexedwards/scs/v2"
	"github.com/gukaifeng/starrynight-server/internal/store"
	"github.com/redis/go-redis/v9"
	"time"
)

var ErrCredentials = errors.New("invalid username or password")
var ErrCapacity = errors.New("authentication busy; retry shortly")

type Service struct {
	Sessions *scs.SessionManager
	Store    *store.Store
	slots    chan struct{}
	dummy    string
}
type Session struct {
	Token     string     `json:"token"`
	ExpiresAt time.Time  `json:"expires_at"`
	User      store.User `json:"user"`
}

func New(db *store.Store, r *redis.Client, prefix string, lifetime time.Duration) (*Service, error) {
	sessions := scs.New()
	sessions.Store = goredisstore.NewWithPrefix(r, prefix+"session:")
	sessions.Lifetime = lifetime
	dummy, e := argon2id.CreateHash("not-a-login-credential", argon2id.DefaultParams)
	return &Service{sessions, db, make(chan struct{}, 2), dummy}, e
}
func (s *Service) Hash(ctx context.Context, password string) (string, error) {
	select {
	case s.slots <- struct{}{}:
		defer func() { <-s.slots }()
	default:
		return "", ErrCapacity
	}
	if e := ctx.Err(); e != nil {
		return "", e
	}
	return argon2id.CreateHash(password, argon2id.DefaultParams)
}
func (s *Service) Verify(ctx context.Context, password, hash string) error {
	select {
	case s.slots <- struct{}{}:
		defer func() { <-s.slots }()
	default:
		return ErrCapacity
	}
	if e := ctx.Err(); e != nil {
		return e
	}
	if hash == "" {
		hash = s.dummy
	}
	match, e := argon2id.ComparePasswordAndHash(password, hash)
	if e != nil {
		return e
	}
	if !match {
		return ErrCredentials
	}
	return nil
}
func (s *Service) Login(ctx context.Context, username, password string) (store.User, error) {
	u, hash, e := s.Store.Credential(ctx, username)
	if e != nil && !errors.Is(e, store.ErrNotFound) {
		return u, e
	}
	check := s.Verify(ctx, password, hash)
	if check != nil {
		return u, check
	}
	if e != nil {
		return u, ErrCredentials
	}
	return u, nil
}
func (s *Service) Issue(ctx context.Context, u store.User) (Session, error) {
	if e := s.Sessions.RenewToken(ctx); e != nil {
		return Session{}, e
	}
	s.Sessions.Put(ctx, "user", u.ID)
	s.Sessions.Put(ctx, "epoch", u.Epoch)
	token, expiry, e := s.Sessions.Commit(ctx)
	return Session{token, expiry, u}, e
}
func (s *Service) Principal(ctx context.Context) (store.User, error) {
	id := s.Sessions.GetString(ctx, "user")
	if id == "" {
		return store.User{}, ErrCredentials
	}
	u, e := s.Store.User(ctx, id)
	if errors.Is(e, store.ErrNotFound) {
		return u, ErrCredentials
	}
	if e != nil {
		return u, e
	}
	if s.Sessions.GetInt64(ctx, "epoch") != u.Epoch {
		return u, ErrCredentials
	}
	return u, nil
}
