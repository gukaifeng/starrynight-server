package identity

import (
	"context"
	"errors"
	"github.com/redis/go-redis/v9"
	"strings"
	"testing"
	"time"
)

func TestPasswordHashAndBoundedWork(t *testing.T) {
	redisClient := redis.NewClient(&redis.Options{Addr: "127.0.0.1:0"})
	defer redisClient.Close()
	service, err := New(nil, redisClient, "fixture:", time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	hash, err := service.Hash(ctx, "this-is-a-fixture-password")
	if err != nil || !strings.HasPrefix(hash, "$argon2id$") {
		t.Fatal("missing Argon2id")
	}
	if err = service.Verify(ctx, "this-is-a-fixture-password", hash); err != nil {
		t.Fatal(err)
	}
	if err = service.Verify(ctx, "wrong-fixture-password", hash); !errors.Is(err, ErrCredentials) {
		t.Fatal("wrong password accepted")
	}
	service.slots <- struct{}{}
	service.slots <- struct{}{}
	if _, err = service.Hash(ctx, "excess-request"); !errors.Is(err, ErrCapacity) {
		t.Fatal("unbounded password work")
	}
	<-service.slots
	<-service.slots
}
