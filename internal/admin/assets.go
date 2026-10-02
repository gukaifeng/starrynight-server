package admin

import (
	"encoding/json"
	"github.com/aliyun/alibabacloud-oss-go-sdk-v2/oss"
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/gukaifeng/starrynight-server/internal/assets"
	"io"
	"strconv"
)

func (s *Server) avatar(c *gin.Context) {
	if _, e := uuid.Parse(c.Param("id")); e != nil {
		c.Status(400)
		return
	}
	v, e := s.DB.Avatar(c.Request.Context(), c.Param("id"))
	if e != nil {
		fail(c, e)
		return
	}
	c.Header("Cache-Control", "private,max-age=60")
	c.Data(200, v.ContentType, v.Image)
}
func (s *Server) replaceAvatar(c *gin.Context) {
	if !writable(c, false) {
		return
	}
	id := c.Param("id")
	if _, e := uuid.Parse(id); e != nil {
		c.JSON(400, gin.H{"error": "无效用户 ID"})
		return
	}
	version, e := strconv.ParseInt(c.Query("expected_version"), 10, 64)
	if e != nil {
		c.JSON(400, gin.H{"error": "需要资料版本"})
		return
	}
	data, e := io.ReadAll(c.Request.Body)
	if e != nil || len(data) > 512<<10 {
		c.JSON(400, gin.H{"error": "头像需要不超过 512 KB 的 JPEG / PNG"})
		return
	}
	s.record(c, "replace_avatar", "users", map[string]string{"id": id}, func() (any, error) { return s.DB.ReplaceAvatar(c.Request.Context(), id, version, data) })
}
func (s *Server) publish(c *gin.Context, v map[string]any) (any, error) {
	if v["confirmed_distribution_rights"] != true {
		return nil, bad("发布需要确认全部资源的再分发权")
	}
	var m assets.Manifest
	b, e := json.Marshal(v["manifest"])
	if e != nil {
		return nil, e
	}
	if e = json.Unmarshal(b, &m); e != nil {
		return nil, bad("无效资源清单")
	}
	if e = m.Validate(); e != nil {
		return nil, bad(e.Error())
	}
	if _, e = uuid.Parse(m.ReleaseID); e != nil {
		return nil, bad("发布 ID 必须为 UUID")
	}
	if s.Config.Signer == nil {
		return nil, bad("尚未配置私有 OSS；请先准备存储与上传资源")
	}
	for _, f := range m.Files {
		head, e := s.Config.Signer.Client.HeadObject(c.Request.Context(), &oss.HeadObjectRequest{Bucket: oss.Ptr(s.Config.Signer.Bucket), Key: oss.Ptr(f.ObjectKey)})
		if e != nil {
			return nil, bad("OSS 文件验证失败: " + f.Path)
		}
		if head.ContentLength != f.Size || head.Metadata["sha256"] != f.SHA256 {
			return nil, bad("OSS 大小或校验信息不匹配: " + f.Path)
		}
	}
	_, e = s.DB.Pool.Exec(c.Request.Context(), "INSERT INTO character_releases(character_id,release_id,platform,version,manifest,distributable) VALUES($1,$2,$3,$4,$5::jsonb,true)", m.CharacterID, m.ReleaseID, m.Platform, m.Version, string(b))
	return gin.H{"release_id": m.ReleaseID}, e
}
