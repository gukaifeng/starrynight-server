package admin

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"github.com/gin-gonic/gin"
	"io"
	"mime"
	"net/http"
	"net/url"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

func (s *Server) managementRoutes(r *gin.RouterGroup) {
	r.GET("/cache", s.caches)
	r.GET("/cache/detail", s.cacheDetail)
	r.POST("/cache/clear", s.clearCache)
	r.GET("/runtime/:section", s.runtimeRead)
	r.POST("/runtime/:section", s.runtimeWrite)
	r.GET("/runtime-download", s.runtimeDownload)
	r.GET("/files/ai", s.workerFiles)
	r.GET("/files/ai/download", s.workerDownload)
	r.POST("/files/ai/delete", s.workerDelete)
	r.POST("/library/upload", s.libraryUpload)
	r.GET("/objects", s.objects)
	r.GET("/objects/detail", s.objectDetail)
	r.GET("/objects/download", s.objectDownload)
	r.POST("/objects/upload", s.objectUpload)
	r.POST("/objects/delete", s.objectDelete)
}
func (s *Server) runtimeCall(ctx context.Context, action string, body any) (any, error) {
	if s.Config.RuntimeRoot == "" || s.Config.ReleaseRoot == "" {
		return nil, bad("此环境未配置服务器文件管理")
	}
	data, e := json.Marshal(body)
	if e != nil {
		return nil, e
	}
	script := filepath.Join(s.Config.ReleaseRoot, "scripts/deploy/admin_ops.py")
	command := exec.CommandContext(ctx, "python3", script, "--root", s.Config.RuntimeRoot, "--release", s.Config.ReleaseRoot, "--action", action)
	command.Stdin = bytes.NewReader(data)
	var stdout bytes.Buffer
	command.Stdout = &stdout
	// Subprocess errors are not exposed: private config URLs can contain passwords.
	if e = command.Run(); e != nil {
		return nil, fmt.Errorf("服务器管理操作失败，请查看任务结果")
	}
	var out map[string]any
	if e = json.Unmarshal(stdout.Bytes(), &out); e != nil {
		return nil, e
	}
	if message, ok := out["error"].(string); ok {
		return nil, bad(message)
	}
	return out, nil
}

var runtimeSections = []string{"config", "backups", "jobs", "releases", "certificates", "library", "files", "connections"}

func (s *Server) runtimeRead(c *gin.Context) {
	if !writable(c, true) {
		return
	}
	section := c.Param("section")
	if !contains(runtimeSections, section) {
		c.Status(404)
		return
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 15*time.Second)
	defer cancel()
	out, e := s.runtimeCall(ctx, "read-"+section, map[string]string{"q": c.Query("q"), "after": c.Query("after"), "id": c.Query("id"), "folder": c.Query("folder")})
	if e != nil {
		fail(c, e)
		return
	}
	c.JSON(200, out)
}
func (s *Server) runtimeWrite(c *gin.Context) {
	if !writable(c, true) {
		return
	}
	section := c.Param("section")
	if !contains([]string{"config", "backups", "releases", "library", "certificates", "services"}, section) {
		c.Status(404)
		return
	}
	var body map[string]any
	if c.ShouldBindJSON(&body) != nil || body["confirmed"] != true {
		fail(c, bad("请确认操作影响"))
		return
	}
	target := map[string]string{"section": section}
	if id, ok := body["id"].(string); ok {
		target["id"] = id
	}
	s.record(c, "runtime", "server", target, func() (any, error) {
		ctx, cancel := context.WithTimeout(c.Request.Context(), 25*time.Second)
		defer cancel()
		return s.runtimeCall(ctx, "write-"+section, body)
	})
}
func (s *Server) runtimeDownload(c *gin.Context) {
	if !writable(c, true) {
		return
	}
	out, e := s.runtimeCall(c.Request.Context(), "resolve-download", map[string]string{"kind": c.Query("kind"), "id": c.Query("id"), "file": c.Query("file"), "folder": c.Query("folder")})
	if e != nil {
		fail(c, e)
		return
	}
	data := out.(map[string]any)
	path, _ := data["path"].(string)
	name, _ := data["name"].(string)
	preview := c.Query("preview") == "true"
	if path == "" {
		c.Status(404)
		return
	}
	s.servePrivateFile(c, path, name, preview)
}
func (s *Server) servePrivateFile(c *gin.Context, path, name string, preview bool) {
	ext := strings.ToLower(filepath.Ext(name))
	kind := mime.TypeByExtension(ext)
	if kind == "" {
		kind = "application/octet-stream"
	}
	if !contains([]string{".png", ".jpg", ".jpeg", ".webp", ".gif", ".wav", ".mp3", ".ogg", ".m4a", ".glb", ".vrm", ".fbx", ".json"}, ext) {
		preview = false
	}
	disposition := "attachment"
	if preview {
		disposition = "inline"
	}
	c.Header("Content-Disposition", mime.FormatMediaType(disposition, map[string]string{"filename": name}))
	c.Header("Content-Type", kind)
	c.Header("Cache-Control", "no-store")
	c.File(path)
}
func (s *Server) workerRequest(c *gin.Context, method, path string, body io.Reader) (*http.Response, error) {
	if s.Config.AIToken == "" {
		return nil, bad("未配置推理管理凭证")
	}
	req, e := http.NewRequestWithContext(c.Request.Context(), method, s.Config.AIURL+"/v1/admin/console/"+path, body)
	if e != nil {
		return nil, e
	}
	req.Header.Set("Authorization", "Bearer "+s.Config.AIToken)
	req.Header.Set("Content-Type", "application/json")
	if value := c.GetHeader("Range"); value != "" {
		req.Header.Set("Range", value)
	}
	return s.Client.Do(req)
}
func (s *Server) workerFiles(c *gin.Context) {
	if !writable(c, true) {
		return
	}
	response, e := s.workerRequest(c, "GET", "files?"+c.Request.URL.RawQuery, nil)
	if e != nil {
		fail(c, e)
		return
	}
	defer response.Body.Close()
	var out any
	if e = json.NewDecoder(io.LimitReader(response.Body, 4<<20)).Decode(&out); e != nil {
		fail(c, e)
		return
	}
	c.JSON(response.StatusCode, out)
}
func (s *Server) workerDownload(c *gin.Context) {
	if !writable(c, true) {
		return
	}
	response, e := s.workerRequest(c, "GET", "files/download?"+c.Request.URL.RawQuery, nil)
	if e != nil {
		fail(c, e)
		return
	}
	defer response.Body.Close()
	for _, key := range []string{"Content-Type", "Content-Length", "Content-Range", "Accept-Ranges", "Content-Disposition"} {
		if value := response.Header.Get(key); value != "" {
			c.Header(key, value)
		}
	}
	c.Header("Cache-Control", "no-store")
	c.Status(response.StatusCode)
	_, _ = io.Copy(c.Writer, response.Body)
}
func (s *Server) workerDelete(c *gin.Context) {
	if !writable(c, true) {
		return
	}
	var body map[string]any
	if c.ShouldBindJSON(&body) != nil || body["confirmed"] != true {
		fail(c, bad("请确认删除及重播影响"))
		return
	}
	encoded, _ := json.Marshal(body)
	s.record(c, "delete_file", "ai-files", map[string]string{"id": fmt.Sprint(body["id"])}, func() (any, error) {
		response, e := s.workerRequest(c, "POST", "files/delete", bytes.NewReader(encoded))
		if e != nil {
			return nil, e
		}
		defer response.Body.Close()
		var out any
		e = json.NewDecoder(io.LimitReader(response.Body, 1<<20)).Decode(&out)
		if response.StatusCode >= 400 {
			return nil, upstreamError{response.StatusCode, "文件已变化、被使用或不能删除，请刷新检查"}
		}
		return out, e
	})
}
func (s *Server) libraryUpload(c *gin.Context) {
	if !writable(c, true) {
		return
	}
	out, e := s.runtimeCall(c.Request.Context(), "prepare-upload", map[string]string{"name": c.Query("name"), "character_id": c.Query("character_id")})
	if e != nil {
		fail(c, e)
		return
	}
	data := out.(map[string]any)
	path, _ := data["path"].(string)
	id, _ := data["id"].(string)
	// The larger body allowance is granted only after authentication.
	c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, 512<<20)
	s.record(c, "upload", "library", map[string]string{"id": id}, func() (any, error) { return s.writeLibraryFile(c, path, id) })
}
func quoted(value string) string { return url.QueryEscape(value) }
