// Publishes an already uploaded, immutable release. There is no public admin API.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"github.com/aliyun/alibabacloud-oss-go-sdk-v2/oss"
	"github.com/gukaifeng/starrynight-server/internal/assets"
	"github.com/gukaifeng/starrynight-server/internal/config"
	"github.com/gukaifeng/starrynight-server/internal/store"
	"os"
	"time"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "release publication failed:", err)
		os.Exit(1)
	}
}
func run() error {
	file := flag.String("manifest", "", "private manifest JSON")
	rights := flag.Bool("confirm-distribution-rights", false, "confirm redistribution rights for every included asset")
	flag.Parse()
	if *file == "" || !*rights {
		return fmt.Errorf("explicit manifest and distribution-rights confirmation are required")
	}
	bytes, err := os.ReadFile(*file)
	if err != nil {
		return err
	}
	var m assets.Manifest
	if err = json.Unmarshal(bytes, &m); err != nil {
		return err
	}
	if err = m.Validate(); err != nil {
		return err
	}
	c, err := config.Load()
	if err != nil {
		return err
	}
	signer, err := assets.NewSigner(c.OSSRegion, c.OSSBucket, c.OSSEndpoint, c.OSSCredentialSource)
	if err != nil {
		return err
	}
	if signer == nil {
		return fmt.Errorf("private OSS storage is not configured")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()
	db, err := store.Open(ctx, c.DatabaseURL, c.PoolSize)
	if err != nil {
		return err
	}
	defer db.Pool.Close()
	unlock, err := assets.LockPublication(ctx, db.Pool)
	if err != nil {
		return err
	}
	defer unlock()
	for _, f := range m.Files {
		head, err := signer.Client.HeadObject(ctx, &oss.HeadObjectRequest{Bucket: oss.Ptr(signer.Bucket), Key: oss.Ptr(f.ObjectKey)})
		if err != nil {
			return fmt.Errorf("object validation failed for %s", f.Path)
		}
		if head.ContentLength != f.Size || head.Metadata["sha256"] != f.SHA256 {
			return fmt.Errorf("size/hash metadata mismatch for %s", f.Path)
		}
	}
	// No UPDATE/UPSERT: replacing bytes or metadata under an old version is forbidden.
	manifestJSON, err := json.Marshal(m)
	if err != nil {
		return err
	}
	_, err = db.Pool.Exec(ctx, `INSERT INTO character_releases(character_id,release_id,platform,version,manifest,distributable) VALUES($1,$2,$3,$4,$5::jsonb,true)`, m.CharacterID, m.ReleaseID, m.Platform, m.Version, string(manifestJSON))
	if err != nil {
		return fmt.Errorf("release insertion failed; character/version/release ID must be valid and unique")
	}
	fmt.Println("Published immutable character release", m.CharacterID, m.Version, m.Platform)
	return nil
}
