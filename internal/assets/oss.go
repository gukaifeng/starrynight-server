package assets

import (
	"context"
	"fmt"
	"github.com/aliyun/alibabacloud-oss-go-sdk-v2/oss"
	"github.com/aliyun/alibabacloud-oss-go-sdk-v2/oss/credentials"
	"strings"
	"time"
)

type Signer struct {
	Client *oss.Client
	Bucket string
}

func NewSigner(region, bucket, endpoint, source string) (*Signer, error) {
	if bucket == "" && region == "" {
		return nil, nil
	}
	if bucket == "" || region == "" {
		return nil, fmt.Errorf("OSS region and bucket must be configured together")
	}
	var provider credentials.CredentialsProvider
	switch source {
	case "ecs":
		provider = credentials.NewEcsRoleCredentialsProvider()
	case "env":
		provider = credentials.NewEnvironmentVariableCredentialsProvider()
	default:
		return nil, fmt.Errorf("invalid OSS credential source")
	}
	cfg := oss.LoadDefaultConfig().WithRegion(region).WithCredentialsProvider(provider)
	if endpoint != "" {
		cfg.WithEndpoint(endpoint)
	}
	return &Signer{oss.NewClient(cfg), bucket}, nil
}
func (s *Signer) Ticket(ctx context.Context, m Manifest) (Manifest, time.Time, error) {
	if err := m.Validate(); err != nil {
		return Manifest{}, time.Time{}, err
	}
	expiry := time.Now().UTC().Add(15 * time.Minute)
	out := m
	out.Files = append([]File(nil), m.Files...)
	for i, f := range m.Files {
		signed, err := s.Client.Presign(ctx, &oss.GetObjectRequest{Bucket: oss.Ptr(s.Bucket), Key: oss.Ptr(f.ObjectKey)}, oss.PresignExpiration(expiry))
		if err != nil {
			return Manifest{}, time.Time{}, err
		}
		out.Files[i].URL = signed.URL
		out.Files[i].Headers = signed.SignedHeaders
		out.Files[i].ObjectKey = ""
	}
	return out, expiry, nil
}

// A preview is also private OSS data; browsing requires no bucket listing rights.
func (s *Signer) Preview(ctx context.Context, key string) (string, error) {
	if !safePath.MatchString(key) || len(key) > 1024 || strings.Contains(key, "..") || strings.HasPrefix(key, "/") {
		return "", fmt.Errorf("invalid preview key")
	}
	result, err := s.Client.Presign(ctx, &oss.GetObjectRequest{Bucket: oss.Ptr(s.Bucket), Key: oss.Ptr(key)}, oss.PresignExpiration(time.Now().UTC().Add(15*time.Minute)))
	if err != nil {
		return "", err
	}
	return result.URL, nil
}
