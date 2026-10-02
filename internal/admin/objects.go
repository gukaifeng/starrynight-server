package admin

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"github.com/aliyun/alibabacloud-oss-go-sdk-v2/oss"
	"github.com/gin-gonic/gin"
	"github.com/gukaifeng/starrynight-server/internal/assets"
	"io"
	"mime"
	"os"
	"path"
	"path/filepath"
	"strings"
	"time"
)

func safeObject(key string) bool {
	return key != "" && len(key) < 1024 && path.Clean(key) == key && !strings.HasPrefix(key, "/") && !strings.HasPrefix(key, "../") && !strings.ContainsAny(key, "\x00\r\n\\")
}
func (s *Server) objectReferences(ctx context.Context, key string) ([]map[string]any, error) {
	rows, e := s.DB.Pool.Query(ctx, "SELECT character_id,platform,version,distributable FROM character_releases WHERE EXISTS (SELECT 1 FROM jsonb_array_elements(manifest->'files') f WHERE f->>'object_key'=$1)", key)
	if e != nil {
		return nil, e
	}
	defer rows.Close()
	out := []map[string]any{}
	for rows.Next() {
		var char, platform string
		var version int64
		var enabled bool
		if e := rows.Scan(&char, &platform, &version, &enabled); e != nil {
			return nil, e
		}
		out = append(out, map[string]any{"character_id": char, "platform": platform, "version": version, "enabled": enabled})
	}
	return out, rows.Err()
}
func (s *Server) objects(c *gin.Context) {
	if !writable(c, true) {
		return
	}
	signer := s.Config.Signer
	if signer == nil {
		c.JSON(200, gin.H{"configured": false, "items": []any{}, "next": "", "message": "请在运行配置中配置 OSS，或先使用服务器资源库"})
		return
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 15*time.Second)
	defer cancel()
	result, e := signer.Client.ListObjectsV2(ctx, &oss.ListObjectsV2Request{Bucket: oss.Ptr(signer.Bucket), Prefix: oss.Ptr(c.Query("prefix")), ContinuationToken: oss.Ptr(c.Query("after")), MaxKeys: 50})
	if e != nil {
		fail(c, bad("OSS 列表不可用，请检查存储配置与授权"))
		return
	}
	out := []map[string]any{}
	for _, object := range result.Contents {
		key := oss.ToString(object.Key)
		out = append(out, map[string]any{"key": key, "bytes": object.Size, "etag": oss.ToString(object.ETag), "modified": object.LastModified, "storage_class": object.StorageClass})
	}
	var detail any
	if key := c.Query("key"); key != "" && safeObject(key) {
		head, e := signer.Client.HeadObject(ctx, &oss.HeadObjectRequest{Bucket: oss.Ptr(signer.Bucket), Key: oss.Ptr(key)})
		if e == nil {
			references, _ := s.objectReferences(ctx, key)
			detail = gin.H{"key": key, "bytes": head.ContentLength, "etag": oss.ToString(head.ETag), "metadata": head.Metadata, "references": references}
		}
	}
	c.JSON(200, gin.H{"configured": true, "bucket": signer.Bucket, "items": out, "next": oss.ToString(result.NextContinuationToken), "detail": detail})
}
func (s *Server) objectDownload(c *gin.Context) {
	if !writable(c, true) {
		return
	}
	key := c.Query("key")
	if !safeObject(key) || s.Config.Signer == nil {
		fail(c, bad("无效对象或尚未配置 OSS"))
		return
	}
	result, e := s.Config.Signer.Client.GetObject(c.Request.Context(), &oss.GetObjectRequest{Bucket: oss.Ptr(s.Config.Signer.Bucket), Key: oss.Ptr(key), Range: oss.Ptr(c.GetHeader("Range"))})
	if e != nil {
		fail(c, bad("OSS 文件读取失败"))
		return
	}
	defer result.Body.Close()
	ext := strings.ToLower(filepath.Ext(key))
	preview := c.Query("preview") == "true" && contains([]string{".png", ".jpg", ".jpeg", ".webp", ".glb", ".vrm", ".fbx", ".wav", ".mp3", ".ogg", ".json"}, ext)
	disposition := "attachment"
	if preview {
		disposition = "inline"
	}
	kind := mime.TypeByExtension(ext)
	if kind == "" {
		kind = "application/octet-stream"
	}
	c.Header("Content-Type", kind)
	c.Header("Cache-Control", "no-store")
	c.Header("Content-Disposition", mime.FormatMediaType(disposition, map[string]string{"filename": path.Base(key)}))
	if cr := oss.ToString(result.ContentRange); cr != "" {
		c.Header("Content-Range", cr)
		c.Status(206)
	} else {
		c.Status(200)
	}
	_, _ = io.Copy(c.Writer, result.Body)
}
func (s *Server) objectUpload(c *gin.Context) {
	if !writable(c, true) {
		return
	}
	key := c.Query("key")
	if !safeObject(key) || s.Config.Signer == nil {
		fail(c, bad("无效对象或尚未配置 OSS"))
		return
	}
	s.record(c, "upload", "oss", map[string]string{"key": key}, func() (any, error) {
		file, e := os.CreateTemp("", "starry-upload-*")
		if e != nil {
			return nil, e
		}
		defer os.Remove(file.Name())
		defer file.Close()
		hash := sha256.New()
		size, e := io.Copy(io.MultiWriter(file, hash), c.Request.Body)
		if e != nil || size == 0 || size > 512<<20 {
			return nil, bad("文件为空或超过 512 MB")
		}
		_, _ = file.Seek(0, 0)
		digest := hex.EncodeToString(hash.Sum(nil))
		_, e = s.Config.Signer.Client.PutObject(c.Request.Context(), &oss.PutObjectRequest{Bucket: oss.Ptr(s.Config.Signer.Bucket), Key: oss.Ptr(key), Body: file, ContentLength: oss.Ptr(size), ForbidOverwrite: oss.Ptr("true"), Metadata: map[string]string{"sha256": digest}, ContentType: oss.Ptr("application/octet-stream")})
		if e != nil {
			return nil, bad("上传失败；不覆盖已有对象，请使用新版本路径")
		}
		return gin.H{"key": key, "sha256": digest, "bytes": size}, nil
	})
}
func (s *Server) objectDelete(c *gin.Context) {
	if !writable(c, true) {
		return
	}
	var body struct {
		Key       string `json:"key"`
		ETag      string `json:"etag"`
		Confirmed bool   `json:"confirmed"`
	}
	if c.ShouldBindJSON(&body) != nil || !body.Confirmed || !safeObject(body.Key) || s.Config.Signer == nil {
		fail(c, bad("请确认删除未发布的对象"))
		return
	}
	s.record(c, "delete", "oss", map[string]string{"key": body.Key}, func() (any, error) {
		unlock, e := assets.LockPublication(c.Request.Context(), s.DB.Pool)
		if e != nil {
			return nil, e
		}
		defer unlock()
		refs, e := s.objectReferences(c.Request.Context(), body.Key)
		if e != nil {
			return nil, e
		}
		if len(refs) > 0 {
			return nil, bad("对象被不可变发布版本引用，不能删除")
		}
		head, e := s.Config.Signer.Client.HeadObject(c.Request.Context(), &oss.HeadObjectRequest{Bucket: oss.Ptr(s.Config.Signer.Bucket), Key: oss.Ptr(body.Key)})
		if e != nil {
			return nil, bad("对象不存在")
		}
		if oss.ToString(head.ETag) != body.ETag {
			return nil, bad("对象已变化，请刷新")
		}
		_, e = s.Config.Signer.Client.DeleteObject(c.Request.Context(), &oss.DeleteObjectRequest{Bucket: oss.Ptr(s.Config.Signer.Bucket), Key: oss.Ptr(body.Key)})
		return gin.H{"deleted": e == nil}, e
	})
}
func (s *Server) writeLibraryFile(c *gin.Context, target, id string) (any, error) {
	file, e := os.OpenFile(target, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if e != nil {
		return nil, e
	}
	success := false
	defer func() {
		file.Close()
		if !success {
			os.Remove(target)
		}
	}()
	hash := sha256.New()
	size, e := io.Copy(io.MultiWriter(file, hash), c.Request.Body)
	if e != nil || size == 0 || size > 512<<20 {
		return nil, bad("文件为空或超过 512 MB")
	}
	if e = file.Sync(); e != nil {
		return nil, e
	}
	file.Close()
	out, e := s.runtimeCall(c.Request.Context(), "finish-upload", map[string]any{"id": id, "sha256": hex.EncodeToString(hash.Sum(nil)), "bytes": size})
	success = e == nil
	return out, e
}
