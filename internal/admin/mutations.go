package admin

import (
	"encoding/json"
	"errors"
	"fmt"
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/gukaifeng/starrynight-server/internal/store"
	"net/http"
	"net/url"
	"regexp"
	"strings"
)

type Mutation struct {
	Keys     map[string]string `json:"keys"`
	Values   map[string]any    `json:"values"`
	Expected int64             `json:"expected_version"`
	Action   string            `json:"action"`
	Confirm  bool              `json:"confirmed"`
	ResetID  string            `json:"reset_id"`
}

func bad(msg string) error { return store.ValidationError{Message: msg} }
func contains(xs []string, k string) bool {
	for _, x := range xs {
		if x == k {
			return true
		}
	}
	return false
}
func (s *Server) current(c *gin.Context, r Resource, keys map[string]string) (map[string]any, error) {
	if len(keys) != len(r.Keys) {
		return nil, bad("主键不完整")
	}
	parts := []string{}
	args := []any{}
	for _, k := range r.Keys {
		v, ok := keys[k]
		if !ok || len(v) > 200 {
			return nil, bad("无效主键")
		}
		args = append(args, v)
		parts = append(parts, fmt.Sprintf("%s::text=$%d", k, len(args)))
	}
	var row map[string]any
	e := s.DB.Pool.QueryRow(c.Request.Context(), "SELECT to_jsonb(t) FROM (SELECT "+columns(r)+" FROM "+r.ID+" WHERE "+strings.Join(parts, " AND ")+") t", args...).Scan(&row)
	return row, e
}
func object(v any) (map[string]any, error) {
	m, ok := v.(map[string]any)
	if !ok {
		return nil, bad("内容必须是 JSON 对象")
	}
	return m, nil
}
func (s *Server) mutate(c *gin.Context) {
	r, ok := resource(c.Param("resource"))
	if !ok {
		c.JSON(404, gin.H{"error": "未知分类"})
		return
	}
	if !writable(c, r.ID == "admin_users" || r.ID == "character_releases") {
		return
	}
	var m Mutation
	if c.ShouldBindJSON(&m) != nil {
		c.JSON(400, gin.H{"error": "无效请求"})
		return
	}
	if m.Action == "" {
		m.Action = "edit"
	}
	if m.Action != "edit" && !contains(r.Actions, m.Action) {
		c.JSON(400, gin.H{"error": "不支持此操作"})
		return
	}
	for k := range m.Values {
		if m.Action == "edit" && !contains(r.Edit, k) {
			c.JSON(400, gin.H{"error": "此字段不允许修改: " + k})
			return
		}
	}
	if m.Action != "edit" && !m.Confirm {
		c.JSON(400, gin.H{"error": "请确认此操作"})
		return
	}
	if m.Action == "reset_password" && !writable(c, true) {
		return
	}
	s.record(c, m.Action, r.ID, m.Keys, func() (any, error) {
		row, e := s.current(c, r, m.Keys)
		if e != nil {
			return nil, e
		}
		resumingReset := false
		if m.Action == "reset" && r.ID == "conversations" {
			if _, err := uuid.Parse(m.ResetID); err == nil {
				_ = s.DB.Pool.QueryRow(c.Request.Context(), "SELECT EXISTS(SELECT 1 FROM conversation_resets WHERE user_id=$1 AND character_id=$2 AND reset_id=$3)", m.Keys["user_id"], m.Keys["character_id"], m.ResetID).Scan(&resumingReset)
			}
		}
		if v, ok := row["version"].(float64); ok && int64(v) != m.Expected && !resumingReset {
			return nil, store.ErrConflict
		}
		return s.execute(c, r, m, row)
	})
}
func (s *Server) execute(c *gin.Context, r Resource, m Mutation, row map[string]any) (any, error) {
	ctx := c.Request.Context()
	user, char, id := m.Keys["user_id"], m.Keys["character_id"], m.Keys["id"]
	switch r.ID {
	case "users":
		if m.Action == "edit" {
			v, e := object(m.Values["profile"])
			if e != nil {
				return nil, e
			}
			return s.DB.Profile(ctx, id, m.Expected, v)
		}
		if m.Action == "revoke_sessions" {
			_, e := s.DB.Pool.Exec(ctx, "UPDATE users SET session_epoch=session_epoch+1 WHERE id=$1", id)
			return true, e
		}
		if m.Action == "reset_password" {
			p, _ := m.Values["password"].(string)
			if len(p) < 12 || len(p) > 128 {
				return nil, bad("密码需要 12–128 字符")
			}
			hash, e := s.Auth.Hash(ctx, p)
			if e != nil {
				return nil, e
			}
			var old string
			if e = s.DB.Pool.QueryRow(ctx, "SELECT COALESCE(password_hash,'') FROM users WHERE id=$1", id).Scan(&old); e != nil {
				return nil, e
			}
			return true, s.DB.ChangePassword(ctx, id, old, hash)
		}
	case "settings", "preferences":
		v, e := object(m.Values["data"])
		if e != nil {
			return nil, e
		}
		kind := "settings"
		if r.ID == "preferences" {
			kind = "preference"
		}
		return s.DB.PatchDocument(ctx, user, kind, char, m.Expected, v, s.resetToken(c, user, char))
	case "characters":
		var archived *bool
		if m.Action != "edit" {
			v := m.Action == "archive"
			archived = &v
		}
		return s.DB.AdminCatalog(ctx, id, m.Expected, m.Values, archived)
	case "authors":
		v, e := object(m.Values["data"])
		if e != nil {
			return nil, e
		}
		return s.DB.AdminAuthor(ctx, id, m.Expected, v)
	case "subscriptions", "follows":
		kind := "subscription"
		target := char
		if r.ID == "follows" {
			kind = "follow"
			target = m.Keys["author_id"]
		}
		return true, s.DB.SetRelation(ctx, user, kind, target, false)
	case "conversations":
		if m.Action == "reset" {
			if _, e := uuid.Parse(m.ResetID); e != nil {
				return nil, bad("重置请求需要固定 UUID")
			}
			receipt, e := s.DB.ResetConversation(ctx, user, char, m.ResetID)
			if e != nil {
				return nil, e
			}
			req, _ := http.NewRequestWithContext(ctx, "DELETE", s.Config.AIURL+"/v1/conversations/"+url.PathEscape(char)+"?reset_id="+m.ResetID+"&reset_version="+fmt.Sprint(receipt.Version), nil)
			req.Header.Set("Authorization", "Bearer "+s.Config.AIClientToken)
			req.Header.Set("X-Starry-Installation", user)
			req.Header.Set("X-Starry-Account", user)
			resp, e := s.Client.Do(req)
			if e != nil {
				return nil, bad("账户记录已重置，推理服务未确认；请用本次请求重试")
			}
			defer resp.Body.Close()
			if resp.StatusCode != 200 && resp.StatusCode != 404 {
				return nil, bad("账户记录已重置，推理服务未确认；请用本次请求重试")
			}
			return receipt, nil
		}
		hidden, _ := row["hidden"].(bool)
		pinned, _ := row["pinned"].(bool)
		if v, ok := m.Values["hidden"].(bool); ok {
			hidden = v
		}
		if v, ok := m.Values["pinned"].(bool); ok {
			pinned = v
		}
		return s.DB.SetConversation(ctx, user, char, m.Expected, hidden, pinned)
	case "messages":
		var message store.Message
		b, _ := json.Marshal(row)
		if e := json.Unmarshal(b, &message); e != nil {
			return nil, e
		}
		if v, ok := m.Values["text"].(string); ok {
			if len(v) > 32000 {
				return nil, bad("消息过长")
			}
			message.Text = v
		}
		if v, ok := m.Values["data"]; ok {
			data, e := object(v)
			if e != nil {
				return nil, e
			}
			message.Data = data
		}
		return s.DB.PutMessage(ctx, user, message, m.Expected, s.resetToken(c, user, char))
	case "entries":
		if m.Action == "remove" {
			return true, s.DB.DeleteEntry(ctx, user, char, m.Keys["kind"], id, m.Expected)
		}
		data, e := object(m.Values["data"])
		if e != nil {
			return nil, e
		}
		return s.DB.PutEntry(ctx, user, store.Entry{ID: id, CharacterID: char, Kind: m.Keys["kind"], Data: data}, m.Expected, s.resetToken(c, user, char))
	case "conversation_goals":
		raw, _ := json.Marshal(m.Values["config"])
		var cfg store.GoalConfig
		if e := json.Unmarshal(raw, &cfg); e != nil {
			return nil, e
		}
		return s.DB.SetGoals(ctx, user, char, m.Expected, cfg, s.resetToken(c, user, char))
	case "support_tickets":
		state, _ := m.Values["state"].(string)
		if !contains([]string{"open", "in_progress", "resolved", "closed"}, state) {
			return nil, bad("状态需要 open / in_progress / resolved / closed")
		}
		tag, e := s.DB.Pool.Exec(ctx, "UPDATE support_tickets SET state=$2,version=version+1 WHERE id=$1 AND version=$3", id, state, m.Expected)
		if e == nil && tag.RowsAffected() != 1 {
			e = store.ErrConflict
		}
		return true, e
	case "character_releases":
		on := m.Action == "enable_release"
		tag, e := s.DB.Pool.Exec(ctx, "UPDATE character_releases SET distributable=$4 WHERE character_id=$1 AND platform=$2 AND version=$3", char, m.Keys["platform"], m.Keys["version"], on)
		if e == nil && tag.RowsAffected() != 1 {
			e = store.ErrNotFound
		}
		return true, e
	case "admin_users":
		tx, e := s.DB.Pool.Begin(ctx)
		if e != nil {
			return nil, e
		}
		defer tx.Rollback(ctx)
		if _, e = tx.Exec(ctx, "SELECT pg_advisory_xact_lock(74831920)"); e != nil {
			return nil, e
		}
		var role string
		var disabled bool
		var version int64
		if e = tx.QueryRow(ctx, "SELECT role,disabled,version FROM admin_users WHERE id=$1 FOR UPDATE", id).Scan(&role, &disabled, &version); e != nil {
			return nil, e
		}
		if version != m.Expected {
			return nil, store.ErrConflict
		}
		if m.Action == "reset_password" {
			p, _ := m.Values["password"].(string)
			if len(p) < 12 || len(p) > 128 {
				return nil, bad("密码需要 12–128 字符")
			}
			hash, e := s.Auth.Hash(ctx, p)
			if e != nil {
				return nil, e
			}
			_, e = tx.Exec(ctx, "UPDATE admin_users SET password_hash=$2,session_epoch=session_epoch+1,version=version+1 WHERE id=$1", id, hash)
			if e != nil {
				return nil, e
			}
		} else {
			if v, ok := m.Values["role"].(string); ok {
				role = v
			}
			if v, ok := m.Values["disabled"].(bool); ok {
				disabled = v
			}
			if !contains([]string{"owner", "editor", "viewer"}, role) {
				return nil, bad("无效权限")
			}
			if _, e = tx.Exec(ctx, "UPDATE admin_users SET role=$2,disabled=$3,session_epoch=session_epoch+1,version=version+1 WHERE id=$1", id, role, disabled); e != nil {
				return nil, e
			}
			var n int
			if e = tx.QueryRow(ctx, "SELECT count(*) FROM admin_users WHERE role='owner' AND NOT disabled").Scan(&n); e != nil {
				return nil, e
			}
			if n == 0 {
				return nil, bad("至少保留一名启用的 owner")
			}
		}
		return true, tx.Commit(ctx)
	}
	return nil, store.ErrForbidden
}
func (s *Server) resetToken(c *gin.Context, user, char string) string {
	var token string
	_ = s.DB.Pool.QueryRow(c.Request.Context(), "SELECT reset_id::text FROM conversation_resets WHERE user_id=$1 AND character_id=$2 ORDER BY version DESC LIMIT 1", user, char).Scan(&token)
	return token
}
func (s *Server) create(c *gin.Context) {
	res := c.Param("resource")
	if !writable(c, true) {
		return
	}
	var v map[string]any
	if c.ShouldBindJSON(&v) != nil {
		c.JSON(400, gin.H{"error": "无效请求"})
		return
	}
	s.record(c, "create", res, map[string]string{}, func() (any, error) {
		ctx := c.Request.Context()
		switch res {
		case "character_releases":
			return s.publish(c, v)
		case "admin_users", "users":
			name, _ := v["username"].(string)
			p, _ := v["password"].(string)
			if !regexp.MustCompile(`^[a-z0-9_]{3,32}$`).MatchString(name) || len(p) < 12 || len(p) > 128 {
				return nil, bad("账号使用 3–32 个小写字母数字或下划线，密码至少 12 字符")
			}
			hash, e := s.Auth.Hash(ctx, p)
			if e != nil {
				return nil, e
			}
			if res == "users" {
				display, _ := v["display_name"].(string)
				if display == "" {
					display = name
				}
				return s.DB.CreateUser(ctx, name, hash, display, false)
			}
			role, _ := v["role"].(string)
			if !contains([]string{"owner", "editor", "viewer"}, role) {
				return nil, bad("请选择管理权限")
			}
			id := uuid.NewString()
			_, e = s.DB.Pool.Exec(ctx, "INSERT INTO admin_users(id,username,password_hash,role) VALUES($1,$2,$3,$4)", id, name, hash, role)
			return gin.H{"id": id}, e
		case "subscriptions", "follows":
			user, _ := v["user_id"].(string)
			target, _ := v["character_id"].(string)
			kind := "subscription"
			if res == "follows" {
				kind = "follow"
				target, _ = v["author_id"].(string)
			}
			if _, e := uuid.Parse(user); e != nil {
				return nil, bad("需要用户 UUID")
			}
			return true, s.DB.SetRelation(ctx, user, kind, target, true)
		case "authors":
			id, _ := v["id"].(string)
			data, e := object(v["data"])
			if e != nil {
				return nil, e
			}
			if !regexp.MustCompile(`^[a-zA-Z0-9_-]{1,100}$`).MatchString(id) {
				return nil, bad("无效作者 ID")
			}
			name, ok := data["name"].(string)
			if !ok || len(name) > 144 || name == "" {
				return nil, bad("需要作者名称")
			}
			_, e = s.DB.Pool.Exec(ctx, "INSERT INTO authors(id,data) VALUES($1,$2)", id, data)
			return gin.H{"id": id}, e
		case "characters":
			var character store.Character
			b, _ := json.Marshal(v)
			if e := json.Unmarshal(b, &character); e != nil {
				return nil, e
			}
			if !regexp.MustCompile(`^[a-zA-Z0-9_-]{1,100}$`).MatchString(character.ID) || character.Name == "" || len(character.Name) > 144 || len(character.Description) > 6000 || !contains([]string{"private", "public", "unlisted"}, character.Visibility) {
				return nil, bad("请填写有效角色 ID、名称与可见性")
			}
			if character.Data == nil {
				character.Data = map[string]any{}
			}
			_, e := s.DB.Pool.Exec(ctx, "INSERT INTO characters(id,author_id,visibility,name,description,data) VALUES($1,$2,$3,$4,$5,$6)", character.ID, character.AuthorID, character.Visibility, character.Name, character.Description, character.Data)
			return gin.H{"id": character.ID}, e
		}
		return nil, errors.New("unsupported create")
	})
}
