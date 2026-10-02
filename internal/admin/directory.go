package admin

// The directory is an administrator view, not a public account API. Every
// route inherits the same revocable session and read/write role middleware.
import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

func (s *Server) directoryRoutes(r *gin.RouterGroup) {
	r.GET("/directory/users", s.directoryUsers)
	r.GET("/directory/users/:id", s.directoryUser)
	r.GET("/directory/characters", s.directoryCharacters)
	r.GET("/directory/characters/:id", s.directoryCharacter)
	r.GET("/directory/relationships", s.directoryRelationships)
	r.GET("/directory/ai-relationships", s.directoryAIRelationships)
	r.GET("/directory/records/:resource", s.directoryRecords)
}

// Worker-only and legacy owners remain visible. A UUID-shaped worker owner is
// linked to an account only after an exact PostgreSQL lookup, not by guessing.
func (s *Server) directoryAIRelationships(c *gin.Context) {
	user, char, ok := directoryScope(c)
	if !ok {
		return
	}
	q := url.Values{"owner": {user}, "character": {char}, "after": {c.Query("after")}}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 5*time.Second)
	defer cancel()
	originalRequest := c.Request
	c.Request = c.Request.WithContext(ctx)
	response, e := s.workerRequest(c, http.MethodGet, "relationships?"+q.Encode(), nil)
	c.Request = originalRequest
	if e != nil {
		fail(c, e)
		return
	}
	defer response.Body.Close()
	if response.StatusCode != 200 {
		c.JSON(response.StatusCode, gin.H{"error": "AI 关系列表暂不可用，请返回第一页后重试"})
		return
	}
	var page Page
	if e = json.NewDecoder(io.LimitReader(response.Body, 2<<20)).Decode(&page); e != nil {
		fail(c, e)
		return
	}
	if len(page.Items) > 25 {
		fail(c, fmt.Errorf("上游分页超过约定范围"))
		return
	}
	ids := []string{}
	chars := []string{}
	for _, row := range page.Items {
		row["account_exists"] = false
		if owner, ok := row["owner"].(string); ok {
			if id, e := uuid.Parse(owner); e == nil {
				ids = append(ids, id.String())
			}
		}
		if id, ok := row["character"].(string); ok {
			chars = append(chars, id)
		}
	}
	accounts := map[string]map[string]any{}
	rows, e := s.DB.Pool.Query(ctx, "SELECT id::text,jsonb_build_object('starry_id',starry_id,'username',username,'profile',profile) FROM users WHERE id=ANY($1::uuid[])", ids)
	if e != nil {
		fail(c, e)
		return
	}
	for rows.Next() {
		var id string
		var data []byte
		if e = rows.Scan(&id, &data); e != nil {
			rows.Close()
			fail(c, e)
			return
		}
		var account map[string]any
		_ = json.Unmarshal(data, &account)
		accounts[id] = account
	}
	e = rows.Err()
	rows.Close()
	if e != nil {
		fail(c, e)
		return
	}
	names := map[string]string{}
	rows, e = s.DB.Pool.Query(ctx, "SELECT id,name FROM characters WHERE id=ANY($1::text[])", chars)
	if e != nil {
		fail(c, e)
		return
	}
	for rows.Next() {
		var id, name string
		if e = rows.Scan(&id, &name); e != nil {
			rows.Close()
			fail(c, e)
			return
		}
		names[id] = name
	}
	e = rows.Err()
	rows.Close()
	if e != nil {
		fail(c, e)
		return
	}
	for _, row := range page.Items {
		owner, _ := row["owner"].(string)
		char, _ := row["character"].(string)
		if id, e := uuid.Parse(owner); e == nil {
			if account, exists := accounts[id.String()]; exists {
				for k, v := range account {
					row[k] = v
				}
				row["user_id"] = id.String()
				row["account_exists"] = true
			}
		}
		row["character_id"] = char
		row["character_name"] = names[char]
	}
	pairs := []map[string]string{}
	for _, row := range page.Items {
		if row["account_exists"] == true {
			pairs = append(pairs, map[string]string{"user_id": row["user_id"].(string), "character_id": row["character_id"].(string)})
		}
	}
	if len(pairs) > 0 {
		encoded, _ := json.Marshal(pairs)
		rows, e = s.DB.Pool.Query(ctx, `SELECT r.user_id::text,r.character_id,jsonb_build_object(
'subscribed',s.user_id IS NOT NULL,'subscribed_at',s.created_at,'conversation',to_jsonb(v),
'preference',p.data,'goal_config',g.config,'goal_progress',g.progress,'archive_messages',coalesce(m.messages,0))
FROM jsonb_to_recordset($1::jsonb) AS r(user_id uuid,character_id text)
LEFT JOIN subscriptions s USING(user_id,character_id) LEFT JOIN conversations v USING(user_id,character_id)
LEFT JOIN preferences p USING(user_id,character_id) LEFT JOIN conversation_goals g USING(user_id,character_id)
LEFT JOIN admin_conversation_stats m USING(user_id,character_id)`, string(encoded))
		if e != nil {
			fail(c, e)
			return
		}
		relations := map[string]map[string]any{}
		for rows.Next() {
			var user, char string
			var data []byte
			if e = rows.Scan(&user, &char, &data); e != nil {
				rows.Close()
				fail(c, e)
				return
			}
			var relation map[string]any
			_ = json.Unmarshal(data, &relation)
			relations[user+":"+char] = relation
		}
		e = rows.Err()
		rows.Close()
		if e != nil {
			fail(c, e)
			return
		}
		for _, row := range page.Items {
			if row["account_exists"] == true {
				key := row["user_id"].(string) + ":" + row["character_id"].(string)
				for k, v := range relations[key] {
					row[k] = v
				}
			}
		}
	}
	c.JSON(200, page)
}

type directoryCursor struct {
	Scope string   `json:"scope"`
	Keys  []string `json:"keys"`
}

func directoryInput(c *gin.Context, scope string, nkeys int) (int, []string, bool) {
	limit := 25
	if value := c.Query("limit"); value != "" {
		n, e := strconv.Atoi(value)
		if e != nil || n < 1 || n > 50 {
			fail(c, bad("每页记录数必须为 1–50"))
			return 0, nil, false
		}
		limit = n
	}
	if len(c.Query("q")) > 200 {
		fail(c, bad("搜索文字过长"))
		return 0, nil, false
	}
	value := c.Query("after")
	if value == "" {
		return limit, nil, true
	}
	var cursor directoryCursor
	data, e := base64.RawURLEncoding.DecodeString(value)
	if len(value) > 4096 || e != nil || json.Unmarshal(data, &cursor) != nil || cursor.Scope != scope || len(cursor.Keys) != nkeys {
		fail(c, bad("无效分页位置；请返回第一页"))
		return 0, nil, false
	}
	for _, key := range cursor.Keys {
		if key == "" || len(key) > 512 {
			fail(c, bad("无效分页位置"))
			return 0, nil, false
		}
	}
	return limit, cursor.Keys, true
}

func directoryScope(c *gin.Context) (string, string, bool) {
	user, character := c.Query("user_id"), c.Query("character_id")
	if user != "" {
		id, e := uuid.Parse(user)
		if e != nil {
			fail(c, bad("无效用户 UUID"))
			return "", "", false
		}
		user = id.String()
	}
	if len(character) > 160 || strings.ContainsAny(character, "\x00\r\n") {
		fail(c, bad("无效角色 ID"))
		return "", "", false
	}
	if user == "" && character == "" {
		fail(c, bad("请指定用户或角色"))
		return "", "", false
	}
	return user, character, true
}

func literalPattern(q string) string {
	return "%" + strings.NewReplacer("\\", "\\\\", "%", "\\%", "_", "\\_").Replace(strings.TrimSpace(q)) + "%"
}

// Both query duration and result size are bounded. A cursor uses the native
// index key, never OFFSET or a JSON representation of the entire record.
func (s *Server) directoryPage(c *gin.Context, query string, args []any, scope string, limit int) {
	ctx, cancel := context.WithTimeout(c.Request.Context(), 5*time.Second)
	defer cancel()
	rows, e := s.DB.Pool.Query(ctx, query, args...)
	if e != nil {
		fail(c, e)
		return
	}
	defer rows.Close()
	page := Page{Items: []map[string]any{}}
	var last []string
	for rows.Next() {
		var data, key []byte
		if e = rows.Scan(&data, &key); e != nil {
			fail(c, e)
			return
		}
		if len(page.Items) == limit {
			data, _ := json.Marshal(directoryCursor{Scope: scope, Keys: last})
			page.Next = base64.RawURLEncoding.EncodeToString(data)
			continue
		}
		var item map[string]any
		if json.Unmarshal(data, &item) != nil || json.Unmarshal(key, &last) != nil {
			fail(c, fmt.Errorf("目录记录格式错误"))
			return
		}
		page.Items = append(page.Items, item)
	}
	if e = rows.Err(); e != nil {
		fail(c, e)
		return
	}
	c.JSON(200, page)
}

func (s *Server) directoryJSON(c *gin.Context, query string, args ...any) {
	ctx, cancel := context.WithTimeout(c.Request.Context(), 5*time.Second)
	defer cancel()
	var out []byte
	if e := s.DB.Pool.QueryRow(ctx, query, args...).Scan(&out); e != nil {
		if e == pgx.ErrNoRows {
			c.Status(404)
		} else {
			fail(c, e)
		}
		return
	}
	c.Data(200, "application/json", out)
}

func (s *Server) directoryUsers(c *gin.Context) {
	q, kind := strings.TrimSpace(c.Query("q")), c.Query("kind")
	if kind != "" && kind != "guest" && kind != "registered" {
		fail(c, bad("无效账户类型"))
		return
	}
	scope := "users:" + q + ":" + kind
	limit, after, ok := directoryInput(c, scope, 1)
	if !ok {
		return
	}
	where := "TRUE"
	args := []any{}
	if len(after) > 0 {
		id, e := uuid.Parse(after[0])
		if e != nil {
			fail(c, bad("无效分页位置"))
			return
		}
		args = append(args, id.String())
		where += " AND id > $1::text::uuid"
	}
	if q != "" {
		args = append(args, literalPattern(q))
		if utf8.RuneCountInString(q) < 3 {
			args[len(args)-1] = strings.TrimPrefix(literalPattern(strings.ToLower(q)), "%")
			n := len(args)
			where += fmt.Sprintf(" AND (lower(coalesce(starry_id,'')) LIKE $%d ESCAPE '\\' OR lower(coalesce(username,'')) LIKE $%d ESCAPE '\\' OR lower(coalesce(profile->>'display_name','')) LIKE $%d ESCAPE '\\')", n, n, n)
		} else {
			where += fmt.Sprintf(" AND (coalesce(starry_id,'') || ' ' || coalesce(username,'') || ' ' || coalesce(profile->>'display_name','')) ILIKE $%d ESCAPE '\\'", len(args))
		}
		// UUID lookup must be exact and should not cast every row to text.
		if id, e := uuid.Parse(q); e == nil {
			args[len(args)-1] = id.String()
			where = strings.Split(where, " AND (")[0] + fmt.Sprintf(" AND id=$%d::text::uuid", len(args))
		}
	}
	if kind == "guest" {
		where += " AND guest"
	} else if kind == "registered" {
		where += " AND NOT guest"
	}
	args = append(args, limit+1)
	r, _ := resource("users")
	s.directoryPage(c, fmt.Sprintf("SELECT to_jsonb(t),jsonb_build_array(id::text) FROM (SELECT %s FROM users WHERE %s ORDER BY id LIMIT $%d) t", columns(r), where, len(args)), args, scope, limit)
}

func (s *Server) directoryCharacters(c *gin.Context) {
	q := strings.TrimSpace(c.Query("q"))
	scope := "characters:" + q
	limit, after, ok := directoryInput(c, scope, 1)
	if !ok {
		return
	}
	where := "TRUE"
	args := []any{}
	if len(after) > 0 {
		args = append(args, after[0])
		where += " AND c.id > $1"
	}
	if q != "" {
		args = append(args, literalPattern(q))
		if utf8.RuneCountInString(q) < 3 {
			args[len(args)-1] = strings.TrimPrefix(literalPattern(strings.ToLower(q)), "%")
			where += fmt.Sprintf(" AND (lower(c.id) LIKE $%d ESCAPE '\\' OR lower(c.name) LIKE $%d ESCAPE '\\')", len(args), len(args))
		} else {
			where += fmt.Sprintf(" AND (c.id || ' ' || c.name) ILIKE $%d ESCAPE '\\'", len(args))
		}
	}
	args = append(args, limit+1)
	s.directoryPage(c, fmt.Sprintf(`SELECT to_jsonb(t),jsonb_build_array(id) FROM (
SELECT c.id,c.name,c.description,c.visibility,c.deleted,c.version,c.updated_at,c.author_id,c.owner_id,
a.data->>'name' AS author_name FROM characters c LEFT JOIN authors a ON a.id=c.author_id
WHERE %s ORDER BY c.id LIMIT $%d) t`, where, len(args)), args, scope, limit)
}

func (s *Server) directoryUser(c *gin.Context) {
	id, e := uuid.Parse(c.Param("id"))
	if e != nil {
		fail(c, bad("无效用户 UUID"))
		return
	}
	s.directoryJSON(c, `SELECT jsonb_build_object('entity',to_jsonb(u),'settings',
(SELECT jsonb_build_object('data',data,'version',version) FROM settings WHERE user_id=u.id),
'author',(SELECT to_jsonb(a) FROM authors a WHERE user_id=u.id),'stats',jsonb_build_object(
'subscriptions',(SELECT count(*) FROM subscriptions WHERE user_id=u.id),
'follows',(SELECT count(*) FROM follows WHERE user_id=u.id),
'created_characters',(SELECT count(*) FROM characters WHERE owner_id=u.id AND NOT deleted),
'conversations',(SELECT count(*) FROM conversations WHERE user_id=u.id),
'messages',(SELECT coalesce(sum(messages),0) FROM admin_conversation_stats WHERE user_id=u.id),
'user_messages',(SELECT coalesce(sum(user_messages),0) FROM admin_conversation_stats WHERE user_id=u.id),
'ai_messages',(SELECT coalesce(sum(ai_messages),0) FROM admin_conversation_stats WHERE user_id=u.id)))
FROM (SELECT id,starry_id,username,guest,profile,version,created_at FROM users WHERE id=$1::text::uuid) u`, id.String())
}

func (s *Server) directoryCharacter(c *gin.Context) {
	id := c.Param("id")
	if id == "" || len(id) > 160 {
		fail(c, bad("无效角色 ID"))
		return
	}
	s.directoryJSON(c, `SELECT jsonb_build_object('entity',to_jsonb(c),'author',to_jsonb(a),
'owner',(SELECT jsonb_build_object('id',id,'starry_id',starry_id,'profile',profile) FROM users WHERE id=c.owner_id),
'stats',jsonb_build_object(
'subscriptions',(SELECT count(*) FROM subscriptions WHERE character_id=c.id),
'conversations',(SELECT count(*) FROM conversations WHERE character_id=c.id),
'chatters',(SELECT count(*) FROM admin_conversation_stats WHERE character_id=c.id AND messages>0),
'messages',(SELECT coalesce(sum(messages),0) FROM admin_conversation_stats WHERE character_id=c.id),
'user_messages',(SELECT coalesce(sum(user_messages),0) FROM admin_conversation_stats WHERE character_id=c.id),
'ai_messages',(SELECT coalesce(sum(ai_messages),0) FROM admin_conversation_stats WHERE character_id=c.id)))
FROM characters c LEFT JOIN authors a ON a.id=c.author_id WHERE c.id=$1`, id)
}

func (s *Server) directoryRelationships(c *gin.Context) {
	user, char, ok := directoryScope(c)
	if !ok {
		return
	}
	kind := c.Query("kind")
	if kind != "" && kind != "subscribers" && kind != "conversations" {
		fail(c, bad("无效关系分类"))
		return
	}
	scope := "relationships:" + user + ":" + char + ":" + kind
	limit, after, ok := directoryInput(c, scope, 2)
	if !ok {
		return
	}
	args := []any{}
	predicates := []string{}
	if user != "" {
		args = append(args, user)
		predicates = append(predicates, fmt.Sprintf("user_id=$%d::text::uuid", len(args)))
	}
	if char != "" {
		args = append(args, char)
		predicates = append(predicates, fmt.Sprintf("character_id=$%d", len(args)))
	}
	filter := strings.Join(predicates, " AND ")
	// Each UNION arm is restricted before deduplication; no global relation scan.
	tables := []string{"subscriptions", "conversations", "preferences", "conversation_goals"}
	if kind == "subscribers" {
		tables = []string{"subscriptions"}
	} else if kind == "conversations" {
		tables = []string{"conversations"}
	}
	arms := []string{}
	for _, table := range tables {
		arms = append(arms, "SELECT user_id,character_id FROM "+table+" WHERE "+filter)
	}
	where := "TRUE"
	if len(after) > 0 {
		if _, e := uuid.Parse(after[0]); e != nil {
			fail(c, bad("无效分页位置"))
			return
		}
		args = append(args, after[0], after[1])
		where = fmt.Sprintf("(r.user_id,r.character_id)>($%d::text::uuid,$%d)", len(args)-1, len(args))
	}
	args = append(args, limit+1)
	s.directoryPage(c, fmt.Sprintf(`WITH relations AS (%s), selected AS (
SELECT r.* FROM relations r WHERE %s ORDER BY r.user_id,r.character_id LIMIT $%d)
SELECT jsonb_build_object('user_id',r.user_id,'character_id',r.character_id,
'starry_id',u.starry_id,'username',u.username,'profile',u.profile,'character_name',c.name,
'subscribed',s.user_id IS NOT NULL,'subscribed_at',s.created_at,'conversation',to_jsonb(v),
'preference',p.data,'goal_config',g.config,'goal_progress',g.progress,
'messages',coalesce(m.messages,0),'user_messages',coalesce(m.user_messages,0),'ai_messages',coalesce(m.ai_messages,0)),
jsonb_build_array(r.user_id::text,r.character_id)
FROM selected r JOIN users u ON u.id=r.user_id JOIN characters c ON c.id=r.character_id
LEFT JOIN subscriptions s USING(user_id,character_id)
LEFT JOIN conversations v USING(user_id,character_id)
LEFT JOIN preferences p USING(user_id,character_id)
LEFT JOIN conversation_goals g USING(user_id,character_id)
LEFT JOIN admin_conversation_stats m USING(user_id,character_id)
ORDER BY r.user_id,r.character_id`, strings.Join(arms, " UNION "), where, len(args)), args, scope, limit)
}

func scopedColumns(r Resource) (string, string) {
	user, char := "", ""
	for _, f := range r.Fields {
		if f == "user_id" {
			user = f
		}
		if f == "character_id" {
			char = f
		}
	}
	if r.ID == "users" {
		user = "id"
	}
	if r.ID == "characters" {
		user = "owner_id"
		char = "id"
	}
	return user, char
}
func keyType(r Resource, k string) string {
	if k == "user_id" || k == "owner_id" || k == "reset_id" || k == "request_id" || k == "id" && contains([]string{"users", "messages", "entries", "support_tickets"}, r.ID) {
		return "uuid"
	}
	if k == "sequence" || k == "revision" || k == "version" {
		return "bigint"
	}
	return "text"
}

func (s *Server) directoryRecords(c *gin.Context) {
	r, ok := resource(c.Param("resource"))
	if !ok {
		c.Status(404)
		return
	}
	user, char, ok := directoryScope(c)
	if !ok {
		return
	}
	uc, cc := scopedColumns(r)
	if user != "" && uc == "" || char != "" && cc == "" {
		fail(c, bad("此数据不属于所选用户或角色"))
		return
	}
	keys := r.Keys
	direction, comparison := "ASC", ">"
	if r.ID == "messages" {
		keys = []string{"sequence"}
		direction, comparison = "DESC", "<"
	}
	scope := r.ID + ":" + user + ":" + char + ":" + c.Query("q")
	limit, after, ok := directoryInput(c, scope, len(keys))
	if !ok {
		return
	}
	args := []any{}
	where := []string{}
	if user != "" {
		args = append(args, user)
		where = append(where, fmt.Sprintf("%s=$%d::text::uuid", uc, len(args)))
	}
	if char != "" {
		args = append(args, char)
		where = append(where, fmt.Sprintf("%s=$%d", cc, len(args)))
	}
	if len(after) > 0 {
		params := []string{}
		for i, k := range keys {
			typ := keyType(r, k)
			if typ == "uuid" {
				if _, e := uuid.Parse(after[i]); e != nil {
					fail(c, bad("无效分页位置"))
					return
				}
			}
			if typ == "bigint" {
				if _, e := strconv.ParseInt(after[i], 10, 64); e != nil {
					fail(c, bad("无效分页位置"))
					return
				}
			}
			args = append(args, after[i])
			params = append(params, fmt.Sprintf("$%d::text::%s", len(args), typ))
		}
		where = append(where, "("+strings.Join(keys, ",")+")"+comparison+"("+strings.Join(params, ",")+")")
	}
	if q := c.Query("q"); q != "" {
		args = append(args, literalPattern(q))
		where = append(where, fmt.Sprintf("to_jsonb(t)::text ILIKE $%d ESCAPE '\\'", len(args)))
	}
	jsonKeys, order := []string{}, []string{}
	for _, k := range keys {
		jsonKeys = append(jsonKeys, k+"::text")
		order = append(order, k+" "+direction)
	}
	args = append(args, limit+1)
	s.directoryPage(c, fmt.Sprintf("SELECT to_jsonb(t),jsonb_build_array(%s) FROM (SELECT %s FROM %s) t WHERE %s ORDER BY %s LIMIT $%d", strings.Join(jsonKeys, ","), columns(r), r.ID, strings.Join(where, " AND "), strings.Join(order, ","), len(args)), args, scope, limit)
}
