// Controlled offline authoring tool. Credentials and generated plans are private files.
package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"github.com/aliyun/alibabacloud-oss-go-sdk-v2/oss"
	"github.com/aliyun/alibabacloud-oss-go-sdk-v2/oss/credentials"
	"github.com/gukaifeng/starrynight-server/internal/assets"
	"github.com/gukaifeng/starrynight-server/internal/config"
	"github.com/gukaifeng/starrynight-server/internal/store"
	"io"
	"os"
	"time"
)

type upload struct {
	Local       string `json:"local"`
	Key         string `json:"key"`
	SHA256      string `json:"sha256"`
	Size        int64  `json:"size"`
	ContentType string `json:"content_type"`
}
type plan struct {
	Audience string                `json:"audience"`
	Objects  []upload              `json:"objects"`
	Listings []store.MarketListing `json:"listings"`
	Releases []assets.Manifest     `json:"releases"`
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "asset operation failed:", err)
		os.Exit(1)
	}
}
func run() error {
	account := flag.String("account", "", "private OSS account JSON; omitted on server")
	input := flag.String("plan", "", "private publication plan")
	publish := flag.Bool("publish", false, "verify existing objects and atomically publish metadata")
	probe := flag.Bool("probe", false, "verify bucket region and private ACL only")
	flag.Parse()
	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Minute)
	defer cancel()
	var signer *assets.Signer
	if *account != "" {
		raw, e := os.ReadFile(*account)
		if e != nil {
			return e
		}
		var v map[string]string
		if e = json.Unmarshal(raw, &v); e != nil {
			return e
		}
		cfg := oss.LoadDefaultConfig().WithRegion(v["Region"]).WithEndpoint("https://" + v["Endpoint"]).WithCredentialsProvider(credentials.NewStaticCredentialsProvider(v["AccessKeyId"], v["AccessKeySecret"]))
		signer = &assets.Signer{Client: oss.NewClient(cfg), Bucket: v["BucketName"]}
	} else {
		c, e := config.Load()
		if e != nil {
			return e
		}
		signer, e = assets.NewSigner(c.OSSRegion, c.OSSBucket, c.OSSEndpoint, c.OSSCredentialSource)
		if e != nil {
			return e
		}
	}
	if signer == nil {
		return fmt.Errorf("OSS not configured")
	}
	if *probe {
		acl, e := signer.Client.GetBucketAcl(ctx, &oss.GetBucketAclRequest{Bucket: oss.Ptr(signer.Bucket)})
		if e != nil {
			return fmt.Errorf("bucket ACL check failed")
		}
		if oss.ToString(acl.ACL) != "private" {
			return fmt.Errorf("bucket must be private")
		}
		fmt.Println("Private OSS bucket verified:", signer.Bucket)
		return nil
	}
	raw, e := os.ReadFile(*input)
	if e != nil {
		return e
	}
	var p plan
	if e = json.Unmarshal(raw, &p); e != nil {
		return e
	}
	if p.Audience != "private-development" {
		return fmt.Errorf("this command requires an explicit private-development audience")
	}
	for _, m := range p.Releases {
		if e = m.Validate(); e != nil {
			return e
		}
	}
	for _, f := range p.Objects {
		// Validate storage paths and sizes even when input was produced by our build tool.
		m := assets.Manifest{SchemaVersion: 1, CharacterID: "validation", ReleaseID: "validation", Version: 1, Platform: "ios", RuntimeVersion: "starry-runtime/1", Files: []assets.File{{Path: "asset", ObjectKey: f.Key, Size: f.Size, SHA256: f.SHA256}}}
		if e = m.Validate(); e != nil {
			return e
		}
		head, e := signer.Client.HeadObject(ctx, &oss.HeadObjectRequest{Bucket: oss.Ptr(signer.Bucket), Key: oss.Ptr(f.Key)})
		if e != nil && !*publish {
			file, err := os.Open(f.Local)
			if err != nil {
				return err
			}
			hash := sha256.New()
			n, err := io.Copy(hash, file)
			if err != nil {
				file.Close()
				return err
			}
			if n != f.Size || hex.EncodeToString(hash.Sum(nil)) != f.SHA256 {
				file.Close()
				return fmt.Errorf("local digest mismatch")
			}
			file.Seek(0, 0)
			_, err = signer.Client.PutObject(ctx, &oss.PutObjectRequest{Bucket: oss.Ptr(signer.Bucket), Key: oss.Ptr(f.Key), Body: file, ContentType: oss.Ptr(f.ContentType), ForbidOverwrite: oss.Ptr("true"), Metadata: map[string]string{"sha256": f.SHA256}})
			file.Close()
			if err != nil {
				return fmt.Errorf("upload failed for %s", f.Key)
			}
			head, e = signer.Client.HeadObject(ctx, &oss.HeadObjectRequest{Bucket: oss.Ptr(signer.Bucket), Key: oss.Ptr(f.Key)})
		}
		if e != nil || head.ContentLength != f.Size || head.Metadata["sha256"] != f.SHA256 {
			return fmt.Errorf("object verification failed for %s", f.Key)
		}
		fmt.Println("Verified object:", f.Key, "bytes:", f.Size)
	}
	if !*publish {
		return nil
	}
	c, e := config.Load()
	if e != nil {
		return e
	}
	db, e := store.Open(ctx, c.DatabaseURL, c.PoolSize)
	if e != nil {
		return e
	}
	defer db.Pool.Close()
	unlock, e := assets.LockPublication(ctx, db.Pool)
	if e != nil {
		return e
	}
	defer unlock()
	tx, e := db.Pool.Begin(ctx)
	if e != nil {
		return e
	}
	defer tx.Rollback(ctx)
	for _, m := range p.Releases {
		b, _ := json.Marshal(m)
		// Re-running the same plan is safe; version collisions with changed bytes fail.
		var old []byte
		err := tx.QueryRow(ctx, "SELECT manifest FROM character_releases WHERE character_id=$1 AND platform=$2 AND version=$3", m.CharacterID, m.Platform, m.Version).Scan(&old)
		if err == nil {
			var existing assets.Manifest
			if json.Unmarshal(old, &existing) != nil {
				return fmt.Errorf("invalid existing manifest")
			}
			a, _ := json.Marshal(existing)
			if string(a) != string(b) {
				return fmt.Errorf("immutable version collision")
			}
			continue
		}
		_, e = tx.Exec(ctx, "INSERT INTO character_releases(character_id,release_id,platform,version,manifest,distributable) VALUES($1,$2,$3,$4,$5::jsonb,true)", m.CharacterID, m.ReleaseID, m.Platform, m.Version, string(b))
		if e != nil {
			return e
		}
	}
	for _, listing := range p.Listings {
		b, _ := json.Marshal(listing)
		_, e = tx.Exec(ctx, `INSERT INTO character_market_assets(character_id,data) VALUES($1,$2::jsonb) ON CONFLICT(character_id) DO UPDATE SET data=EXCLUDED.data,updated_at=now()`, listing.ID, string(b))
		if e != nil {
			return e
		}
		_, e = tx.Exec(ctx, `UPDATE characters SET data=data||jsonb_build_object('asset_delivery',$2::text),version=version+1,updated_at=now() WHERE id=$1`, listing.ID, listing.Delivery)
		if e != nil {
			return e
		}
	}
	if e = tx.Commit(ctx); e != nil {
		return e
	}
	fmt.Println("Published marketplace:", len(p.Listings), "roles;", len(p.Releases), "platform releases")
	return nil
}
