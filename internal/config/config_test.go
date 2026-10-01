package config

import "testing"

func TestProductionCannotEnableTestAccess(t *testing.T) {
	c := Config{Environment: "production", DatabaseURL: "postgres://db/platform?sslmode=verify-full", RedisURL: "rediss://cache", AllowGuest: true}
	if c.Validate() == nil {
		t.Fatal("production guest bypass was accepted")
	}
	c.AllowGuest = false
	if e := c.Validate(); e != nil {
		t.Fatal(e)
	}
	c.RedisURL = "redis://cache"
	if c.Validate() == nil {
		t.Fatal("production cleartext Redis was accepted")
	}
	c.RedisURL = "rediss://cache"
	c.DatabaseURL = "postgres://db/platform?sslmode=disable"
	if c.Validate() == nil {
		t.Fatal("production cleartext database was accepted")
	}
	c.DatabaseURL = "postgres://db/platform?sslmode=verify-full&sslmode=disable"
	if c.Validate() == nil {
		t.Fatal("conflicting TLS options accepted")
	}
}

func TestPrivateWorkerConfiguration(t *testing.T) {
	c := Config{Environment: "development", DatabaseURL: "postgres://db/platform", RedisURL: "redis://cache", AIUpstream: "http://worker:8091"}
	if c.Validate() == nil {
		t.Fatal("worker without credential accepted")
	}
	c.AIServiceToken = "fixture-service-token"
	if c.Validate() != nil {
		t.Fatal("private worker origin rejected")
	}
	for _, bad := range []string{"file:///private/secret", "http://user:secret@worker", "http://worker/v1", "http://worker?redirect=other"} {
		c.AIUpstream = bad
		if c.Validate() == nil {
			t.Fatalf("invalid worker origin accepted: %s", bad)
		}
	}
}
