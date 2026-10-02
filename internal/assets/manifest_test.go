package assets

import (
	"context"
	"github.com/aliyun/alibabacloud-oss-go-sdk-v2/oss"
	"github.com/aliyun/alibabacloud-oss-go-sdk-v2/oss/credentials"
	"strings"
	"testing"
	"time"
)

func testManifest() Manifest {
	return Manifest{SchemaVersion: 1, CharacterID: "role", ReleaseID: "release", Version: 1, Platform: "ios", RuntimeVersion: "xcp/1", Files: []File{{Path: "role.bundle", ObjectKey: "characters/role/1/role.bundle", Size: 4096, SHA256: strings.Repeat("a", 64)}}}
}
func TestManifestRejectsUnsafePathsAndMetadata(t *testing.T) {
	for _, name := range []string{"../model", "/model", "a/../model", "a//model", "a\\model", ""} {
		m := testManifest()
		m.Files[0].Path = name
		if m.Validate() == nil {
			t.Fatalf("accepted %q", name)
		}
	}
	m := testManifest()
	m.Files[0].ObjectKey = "../escape"
	if m.Validate() == nil {
		t.Fatal("accepted parent object key")
	}
	m = testManifest()
	m.Files = append(m.Files, m.Files[0])
	if m.Validate() == nil {
		t.Fatal("accepted duplicate destination")
	}
	m = testManifest()
	m.Files[0].SHA256 = "invalid"
	if m.Validate() == nil {
		t.Fatal("accepted missing digest")
	}
}
func TestTicketsUseOfficialOfflineSignerAndDoNotExposeObjectKeys(t *testing.T) {
	// Fake credentials only; presigning does not send any OSS request or charge.
	cfg := oss.LoadDefaultConfig().WithRegion("cn-beijing").WithCredentialsProvider(credentials.NewStaticCredentialsProvider("fixture-id", "fixture-secret"))
	signer := Signer{Client: oss.NewClient(cfg), Bucket: "fixture-private"}
	m := testManifest()
	result, expiry, err := signer.Ticket(context.Background(), m)
	if err != nil {
		t.Fatal(err)
	}
	if result.Files[0].ObjectKey != "" || !strings.HasPrefix(result.Files[0].URL, "https://") || !strings.Contains(result.Files[0].URL, "x-oss-signature=") {
		t.Fatal("invalid signed ticket")
	}
	if time.Until(expiry) > 15*time.Minute || time.Until(expiry) < 14*time.Minute {
		t.Fatal("invalid expiry")
	}
	if m.Files[0].ObjectKey == "" || m.Files[0].URL != "" {
		t.Fatal("signing mutated stored manifest")
	}
}
func TestPreviewRejectsUnsafeStorageKeys(t *testing.T) {
	s := Signer{}
	for _, key := range []string{"", "../escape", "/root", "characters/../../escape", "bad?query"} {
		if _, err := s.Preview(context.Background(), key); err == nil {
			t.Fatalf("accepted key %q", key)
		}
	}
}
