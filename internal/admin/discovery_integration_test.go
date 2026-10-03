package admin

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"sync/atomic"
	"testing"

	"github.com/aliyun/alibabacloud-oss-go-sdk-v2/oss"
	"github.com/aliyun/alibabacloud-oss-go-sdk-v2/oss/credentials"
	"github.com/google/uuid"
	"github.com/gukaifeng/starrynight-server/internal/assets"
)

func testDiscoveryAndBucket(t *testing.T, app *Server, get func(string) (int, []byte)) {
	t.Helper()
	ctx := t.Context()
	base := "discovery-" + uuid.NewString()[:12]
	public, private, archived, creator := base+"-public", base+"-private", base+"-archived", base+"-creator"
	user := uuid.NewString()
	exec := func(query string, args ...any) {
		t.Helper()
		if _, err := app.DB.Pool.Exec(ctx, query, args...); err != nil {
			t.Fatal(err)
		}
	}
	exec("INSERT INTO users(id,guest) VALUES($1,true)", user)
	defer app.DB.Pool.Exec(ctx, "DELETE FROM users WHERE id=$1", user)
	for _, id := range []string{public, private, archived, creator} {
		visibility, deleted := "public", false
		if id == private {
			visibility = "private"
		}
		if id == archived {
			deleted = true
		}
		exec("INSERT INTO characters(id,author_id,visibility,deleted,name,description,data) VALUES($1,'starry-studio',$2,$3,$4,'Fixture story','{}')", id, visibility, deleted, id)
	}
	defer app.DB.Pool.Exec(ctx, "DELETE FROM characters WHERE id=ANY($1::text[])", []string{creator, public, private, archived})
	exec("UPDATE characters SET owner_id=$2,base_id=$3 WHERE id=$1", creator, user, public)
	key := "models/a cover.png"
	definition := map[string]any{"public_profile": map[string]any{"name": public, "story": "Shared App public story", "invitation": "Hello", "traits": []string{"温柔"}}, "descriptor": map[string]any{"display": map[string]any{"name": public}}}
	market := map[string]any{"data": definition, "media": map[string]any{"cover": map[string]any{"object_key": key, "path": "cover.png", "size": 3, "sha256": "fixture", "content_type": "image/png"}}, "delivery": "bundled"}
	raw, _ := json.Marshal(market)
	for _, id := range []string{public, private, archived} {
		exec("INSERT INTO character_market_assets(character_id,data) VALUES($1,$2)", id, string(raw))
	}
	code, body := get("/discovery")
	if code != 200 {
		t.Fatalf("discovery %d", code)
	}
	var report struct {
		Items    []discoveryItem `json:"items"`
		Complete bool            `json:"complete"`
		Curation struct {
			Schema int `json:"schemaVersion"`
		} `json:"curation"`
	}
	if err := json.Unmarshal(body, &report); err != nil {
		t.Fatal(err)
	}
	if !report.Complete || report.Curation.Schema != 1 {
		t.Fatal("catalogue not complete")
	}
	found := map[string]discoveryItem{}
	for _, item := range report.Items {
		found[item.ID] = item
	}
	if _, ok := found[private]; ok {
		t.Fatal("private draft entered discovery")
	}
	if _, ok := found[archived]; ok {
		t.Fatal("archived character entered discovery")
	}
	for _, id := range []string{public, creator} {
		item, ok := found[id]
		if !ok || item.Name != id || item.Media["cover"].ObjectKey != "" || item.Media["cover"].URL != "/admin-api/v1/discovery/"+id+"/media/cover" {
			t.Fatal("published metadata or inherited preview lost")
		}
		data, _ := json.Marshal(item.Data)
		want, _ := json.Marshal(definition)
		if !bytes.Equal(data, want) {
			t.Fatal("App public character data changed in the console")
		}
	}
	if !found[creator].Creator || found[public].Creator {
		t.Fatal("creator shelf classification incorrect")
	}
	if code, _ := get("/discovery?platform=desktop"); code != 400 {
		t.Fatal("unknown platform accepted")
	}
	if code, _ := get("/discovery/" + private + "/media/cover"); code != 404 {
		t.Fatal("private preview exposed")
	}
	previous := app.Config.Signer
	defer func() { app.Config.Signer = previous }()
	if code, _ := get("/objects?folders=true"); code != 200 {
		t.Fatal("unconfigured storage not explicit")
	}
	var calls atomic.Int64
	provider := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		if r.Header.Get("Authorization") == "" {
			t.Error("unsigned OSS access")
		}
		if r.Method == "HEAD" {
			if r.URL.Path == "/fixture/models/" {
				w.Header().Set("Content-Length", "0")
				return
			}
			w.Header().Set("Content-Length", "3")
			w.Header().Set("Content-Type", "image/png")
			w.Header().Set("ETag", `"fixture"`)
			w.Header().Set("x-oss-meta-sha256", "fixture-sha")
			return
		}
		if r.Method != "GET" {
			t.Errorf("unexpected provider write %s", r.Method)
			w.WriteHeader(500)
			return
		}
		if r.URL.Query().Get("list-type") == "2" {
			q := r.URL.Query()
			if q.Get("delimiter") != "/" || q.Get("max-keys") != "50" || q.Get("encoding-type") != "url" {
				t.Error("directory grouping or bounded page lost")
			}
			if token := q.Get("continuation-token"); token != "" && token != "a+b/=" {
				t.Error("cursor changed")
			}
			w.Header().Set("Content-Type", "application/xml")
			fmt.Fprint(w, `<ListBucketResult><Name>fixture</Name><EncodingType>url</EncodingType><IsTruncated>true</IsTruncated><NextContinuationToken>a%2Bb%2F%3D</NextContinuationToken><CommonPrefixes><Prefix>models%2Fcat%2F</Prefix></CommonPrefixes><Contents><Key>models%2Fa%20cover.png</Key><Size>3</Size><StorageClass>Standard</StorageClass></Contents></ListBucketResult>`)
			return
		}
		if r.URL.Path != "/fixture/"+key {
			t.Error("unexpected object requested")
		}
		w.Header().Set("Content-Length", "3")
		fmt.Fprint(w, "png")
	}))
	defer provider.Close()
	cfg := oss.LoadDefaultConfig().WithRegion("cn-beijing").WithEndpoint(provider.URL).WithUsePathStyle(true).WithCredentialsProvider(credentials.NewStaticCredentialsProvider("fixture-id", "fixture-secret"))
	app.Config.Signer = &assets.Signer{Bucket: "fixture", Client: oss.NewClient(cfg)}
	for _, id := range []string{public, creator} {
		if code, body := get("/discovery/" + id + "/media/cover"); code != 200 || string(body) != "png" {
			t.Fatal("immutable public preview not served")
		}
	}
	exec("UPDATE characters SET base_id=$2 WHERE id=$1", creator, private)
	if code, _ := get("/discovery/" + creator + "/media/cover"); code != 404 {
		t.Fatal("private base preview exposed through a public creation")
	}
	exec("UPDATE characters SET base_id=$2 WHERE id=$1", creator, public)
	before := calls.Load()
	if code, _ := get("/discovery/" + public + "/media/unknown"); code != 404 {
		t.Fatal("unknown media kind accepted")
	}
	if calls.Load() != before {
		t.Fatal("unknown media caused provider access")
	}
	code, body = get("/objects?folders=true&prefix=models%2F&after=a%2Bb%2F%3D&key=" + url.QueryEscape(key))
	var listing struct {
		Directories []string `json:"directories"`
		Items       []struct {
			Key string `json:"key"`
		} `json:"items"`
		Next   string         `json:"next"`
		Detail map[string]any `json:"detail"`
	}
	if code != 200 || json.Unmarshal(body, &listing) != nil || len(listing.Directories) != 1 || listing.Directories[0] != "models/cat/" || listing.Items[0].Key != key || listing.Next != "a+b/=" || listing.Detail["content_type"] != "image/png" {
		t.Fatalf("directory, encoded key, cursor or HEAD information lost: status %d: %s", code, body)
	}
	code, body = get("/objects?folders=true&key=models%2F")
	if code != 200 || json.Unmarshal(body, &listing) != nil || listing.Detail["bytes"] != float64(0) {
		t.Fatal("zero-byte directory marker cannot be inspected")
	}
	if code, _ := get("/objects?prefix=" + url.QueryEscape("\n")); code != 400 {
		t.Fatal("invalid prefix accepted")
	}
}
