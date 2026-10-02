package admin

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"github.com/alexedwards/scs/v2"
	"github.com/gin-gonic/gin"
	"github.com/redis/go-redis/v9"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// Opaque handles keep bearer session IDs out of browser tables and logs.
// The existing private administrator credential keys authenticated encryption.
func (s *Server) keyCipher() cipher.AEAD {
	key := sha256.Sum256([]byte(s.Config.AIToken + "\x00" + s.Config.Origin + "\x00redis-inspector"))
	block, _ := aes.NewCipher(key[:])
	gcm, _ := cipher.NewGCM(block)
	return gcm
}
func (s *Server) sealKey(key string) string {
	gcm := s.keyCipher()
	nonce := make([]byte, gcm.NonceSize())
	if _, e := rand.Read(nonce); e != nil {
		panic(e)
	}
	return base64.RawURLEncoding.EncodeToString(gcm.Seal(nonce, nonce, []byte(key), nil))
}
func (s *Server) openKey(id string) (string, error) {
	if s.Config.AIToken == "" {
		return "", errors.New("private admin credential required for cache inspection")
	}
	b, e := base64.RawURLEncoding.DecodeString(id)
	gcm := s.keyCipher()
	if e != nil || len(b) < gcm.NonceSize() {
		return "", bad("无效缓存标识")
	}
	data, e := gcm.Open(nil, b[:gcm.NonceSize()], b[gcm.NonceSize():], nil)
	key := string(data)
	if e != nil || !s.ownedCacheKey(key) {
		return "", bad("无效缓存标识")
	}
	return key, nil
}
func (s *Server) ownedCacheKey(key string) bool {
	// redis_rate prefixes its own keys; no other application's keys are exposed.
	stripped := strings.TrimPrefix(key, "rate:")
	return strings.HasPrefix(stripped, s.RedisPrefix) || strings.HasPrefix(stripped, "admin-login:")
}
func displayCacheKey(key string) string {
	if i := strings.Index(key, "session:"); i >= 0 {
		hash := sha256.Sum256([]byte(key))
		return key[:i+8] + "[" + hex.EncodeToString(hash[:4]) + "]"
	}
	return key
}
func (s *Server) caches(c *gin.Context) {
	if !writable(c, true) {
		return
	}
	if s.Config.AIToken == "" {
		c.JSON(503, gin.H{"error": "缓存检查需要私有管理凭证"})
		return
	}
	cursor, e := strconv.ParseUint(c.DefaultQuery("cursor", "0"), 10, 64)
	if e != nil {
		fail(c, bad("无效分页位置"))
		return
	}
	q := c.Query("q")
	if len(q) > 200 {
		fail(c, bad("搜索过长"))
		return
	}
	out := []map[string]any{}
	seen := map[string]bool{}
	// SCAN is bounded, can return empty pages, and is not a snapshot. Never KEYS.
	for round := 0; round < 5; round++ {
		keys, next, e := s.Cache.Scan(c.Request.Context(), cursor, "*", 50).Result()
		if e != nil {
			fail(c, e)
			return
		}
		cursor = next
		for _, key := range keys {
			if seen[key] || !s.ownedCacheKey(key) || q != "" && !strings.Contains(displayCacheKey(key), q) {
				continue
			}
			seen[key] = true
			kind, e := s.Cache.Type(c.Request.Context(), key).Result()
			if e != nil || kind == "none" {
				continue
			}
			ttl, _ := s.Cache.TTL(c.Request.Context(), key).Result()
			size, _ := s.Cache.MemoryUsage(c.Request.Context(), key).Result()
			row := map[string]any{"id": s.sealKey(key), "key": displayCacheKey(key), "type": kind, "ttl_seconds": ttlSeconds(ttl), "bytes": size, "session": strings.Contains(key, "session:")}
			if kind == "string" && size < 1<<20 && strings.Contains(key, "session:") {
				b, e := s.Cache.Get(c.Request.Context(), key).Bytes()
				if e == nil && len(b) < 1<<20 {
					expiry, values, e := (scs.GobCodec{}).Decode(b)
					if e == nil {
						row["expires_at"] = expiry
						clean := map[string]any{}
						for _, field := range []string{"user_id", "admin_id", "epoch"} {
							if v, ok := values[field]; ok {
								clean[field] = v
							}
						}
						row["principal"] = clean
					}
				}
			}
			out = append(out, row)
		}
		if cursor == 0 || len(out) > 0 {
			break
		}
	}
	c.JSON(200, gin.H{"items": out, "cursor": strconv.FormatUint(cursor, 10), "complete": cursor == 0})
}
func (s *Server) cacheDetail(c *gin.Context) {
	if !writable(c, true) {
		return
	}
	key, e := s.openKey(c.Query("id"))
	if e != nil {
		fail(c, e)
		return
	}
	if size, _ := s.Cache.MemoryUsage(c.Request.Context(), key).Result(); size > 2<<20 {
		fail(c, bad("缓存过大，仅显示列表信息"))
		return
	}
	data, e := s.Cache.Dump(c.Request.Context(), key).Result()
	if e != nil {
		fail(c, e)
		return
	}
	hash := sha256.Sum256([]byte(data))
	kind, _ := s.Cache.Type(c.Request.Context(), key).Result()
	out := map[string]any{"key": displayCacheKey(key), "type": kind, "version": hex.EncodeToString(hash[:]), "content": "登录会话正文不展示，避免泄露 CSRF 与凭据"}
	if !strings.Contains(key, "session:") {
		switch kind {
		case "string":
			out["content"], _ = s.Cache.GetRange(c.Request.Context(), key, 0, 4095).Result()
		case "list":
			out["content"], _ = s.Cache.LRange(c.Request.Context(), key, 0, 49).Result()
		case "set":
			out["content"], _, _ = s.Cache.SScan(c.Request.Context(), key, 0, "", 50).Result()
		case "hash":
			entries, _, _ := s.Cache.HScan(c.Request.Context(), key, 0, "", 50).Result()
			fields := map[string]any{}
			for i := 0; i+1 < len(entries); i += 2 {
				fields[entries[i]] = entries[i+1]
			}
			out["content"] = fields
		case "zset":
			out["content"], _ = s.Cache.ZRangeWithScores(c.Request.Context(), key, 0, 49).Result()
		default:
			out["content"] = "仅显示类型与占用"
		}
	}
	// Limiters contain numbers/IPs; application cache objects are recursively redacted.
	clean, _ := json.Marshal(out)
	var value any
	_ = json.Unmarshal(clean, &value)
	c.JSON(200, redact(value))
}
func redact(v any) any {
	switch x := v.(type) {
	case map[string]any:
		for key, value := range x {
			lower := strings.ToLower(key)
			if strings.Contains(lower, "password") || strings.Contains(lower, "token") || strings.Contains(lower, "api_key") || strings.Contains(lower, "voice_id") || strings.Contains(lower, "secret") || strings.Contains(lower, "authorization") || strings.Contains(lower, "cookie") || strings.Contains(lower, "access_key") {
				x[key] = "[已隐藏]"
			} else {
				x[key] = redact(value)
			}
		}
	case string:
		var decoded any
		if json.Valid([]byte(x)) && json.Unmarshal([]byte(x), &decoded) == nil {
			return redact(decoded)
		}
		if secretText.MatchString(x) {
			return "[包含凭据，已隐藏]"
		}
		if len(x) > 4096 {
			return x[:4096] + "…"
		}
	case []any:
		for i, value := range x {
			x[i] = redact(value)
		}
	}
	return v
}
func (s *Server) clearCache(c *gin.Context) {
	if !writable(c, true) {
		return
	}
	var body struct {
		ID        string `json:"id"`
		Version   string `json:"version"`
		Confirmed bool   `json:"confirmed"`
	}
	if c.ShouldBindJSON(&body) != nil || !body.Confirmed {
		fail(c, bad("请确认清理该缓存或撤销该会话"))
		return
	}
	key, e := s.openKey(body.ID)
	if e != nil {
		fail(c, e)
		return
	}
	s.record(c, "unlink", "redis", map[string]string{"key": displayCacheKey(key)}, func() (any, error) {
		e := s.Cache.Watch(c.Request.Context(), func(tx *redis.Tx) error {
			if size, _ := tx.MemoryUsage(c.Request.Context(), key).Result(); size > 2<<20 {
				return bad("缓存过大，不支持逐项清理")
			}
			data, e := tx.Dump(c.Request.Context(), key).Result()
			if e != nil {
				return e
			}
			hash := sha256.Sum256([]byte(data))
			if hex.EncodeToString(hash[:]) != body.Version {
				return bad("缓存已变化，请刷新再清理")
			}
			_, e = tx.TxPipelined(c.Request.Context(), func(p redis.Pipeliner) error { p.Unlink(c.Request.Context(), key); return nil })
			return e
		}, key)
		return gin.H{"cleared": e == nil}, e
	})
}

func ttlSeconds(ttl time.Duration) int64 {
	if ttl < 0 {
		return int64(ttl)
	}
	return int64(ttl / time.Second)
}

var secretText = regexp.MustCompile(`(?i)(password|token|api[_-]?key|authorization|bearer |access[_-]?key|secret|voice_id)`)
