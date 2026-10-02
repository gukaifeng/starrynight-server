package admin

import (
	"context"
	"fmt"
	"github.com/aliyun/alibabacloud-oss-go-sdk-v2/oss"
	"github.com/aliyun/alibabacloud-oss-go-sdk-v2/oss/credentials"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestOSSOfficialSDKAgainstPrivateFixture(t *testing.T) {
	for _, key := range []string{"../x", "/x", "a/../x", "a//x", "a\\x", "", "a\x00x"} {
		if safeObject(key) {
			t.Fatalf("accepted %q", key)
		}
	}
	if !safeObject("characters/role/v1/model.glb") {
		t.Fatal("valid object refused")
	}
	requests := []string{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests = append(requests, r.Method)
		if r.Header.Get("Authorization") == "" {
			t.Error("request not signed by official SDK")
		}
		switch r.Method {
		case "HEAD":
			w.Header().Set("ETag", `"fixture"`)
			w.Header().Set("Content-Length", "3")
			w.Header().Set("x-oss-meta-sha256", "fixture-sha")
		case "GET":
			if r.URL.Query().Get("list-type") == "2" {
				w.Header().Set("Content-Type", "application/xml")
				fmt.Fprint(w, `<ListBucketResult><Name>fixture</Name><IsTruncated>false</IsTruncated><Contents><Key>models/a.glb</Key><ETag>"fixture"</ETag><Size>3</Size><StorageClass>Standard</StorageClass></Contents></ListBucketResult>`)
			} else {
				fmt.Fprint(w, "glb")
			}
		case "PUT":
			if r.Header.Get("x-oss-forbid-overwrite") != "true" {
				t.Error("immutable upload protection lost")
			}
			w.Header().Set("ETag", `"fixture"`)
		case "DELETE":
			w.WriteHeader(204)
		}
	}))
	defer server.Close()
	cfg := oss.LoadDefaultConfig().WithRegion("cn-beijing").WithEndpoint(server.URL).WithUsePathStyle(true).WithCredentialsProvider(credentials.NewStaticCredentialsProvider("fake-id", "fake-secret"))
	client := oss.NewClient(cfg)
	ctx := context.Background()
	listing, err := client.ListObjectsV2(ctx, &oss.ListObjectsV2Request{Bucket: oss.Ptr("fixture"), MaxKeys: 50})
	if err != nil || len(listing.Contents) != 1 {
		t.Fatalf("list %v", err)
	}
	head, err := client.HeadObject(ctx, &oss.HeadObjectRequest{Bucket: oss.Ptr("fixture"), Key: oss.Ptr("models/a.glb")})
	if err != nil || head.Metadata["sha256"] != "fixture-sha" {
		t.Fatalf("head %v", err)
	}
	_, err = client.PutObject(ctx, &oss.PutObjectRequest{Bucket: oss.Ptr("fixture"), Key: oss.Ptr("models/new.glb"), ForbidOverwrite: oss.Ptr("true")})
	if err != nil {
		t.Fatal(err)
	}
	_, err = client.DeleteObject(ctx, &oss.DeleteObjectRequest{Bucket: oss.Ptr("fixture"), Key: oss.Ptr("models/new.glb")})
	if err != nil {
		t.Fatal(err)
	}
	if len(requests) != 4 {
		t.Fatal("unexpected provider requests")
	}
}
