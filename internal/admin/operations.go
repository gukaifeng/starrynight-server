package admin

import (
	"context"
	"github.com/gin-gonic/gin"
	"os/exec"
	"regexp"
	"strings"
	"time"
)

var units = []string{"starry-api", "starry-ai", "starry-admin", "starry-edge", "starry-postgres", "starry-redis"}

func (s *Server) operations(c *gin.Context) {
	if !writable(c, true) {
		return
	}
	if !s.Config.Operations {
		c.JSON(200, gin.H{"available": false, "units": []any{}})
		return
	}
	out := []map[string]any{}
	for _, unit := range units {
		ctx, cancel := context.WithTimeout(c.Request.Context(), 3*time.Second)
		data, e := exec.CommandContext(ctx, "systemctl", "--user", "show", unit, "--property=ActiveState,SubState,MainPID,MemoryCurrent,ExecMainStartTimestamp", "--no-pager").Output()
		cancel()
		fields := map[string]any{"id": unit}
		for _, line := range strings.Split(string(data), "\n") {
			k, v, ok := strings.Cut(line, "=")
			if ok {
				fields[k] = v
			}
		}
		fields["available"] = e == nil
		out = append(out, fields)
	}
	logs := []string{}
	if unit := c.Query("logs"); contains(units, unit) {
		ctx, cancel := context.WithTimeout(c.Request.Context(), 3*time.Second)
		defer cancel()
		data, _ := exec.CommandContext(ctx, "journalctl", "--user", "-u", unit, "-n", "60", "--no-pager", "--output=short-iso").Output()
		re := regexp.MustCompile(`(?i)(bearer\s+|api[_-]?key[=: ]+|token[=: ]+|password[=: ]+)\S+`)
		for _, line := range strings.Split(string(data), "\n") {
			logs = append(logs, re.ReplaceAllString(line, "$1[已隐藏]"))
		}
	}
	c.JSON(200, gin.H{"available": true, "units": out, "logs": logs})
}
func (s *Server) restart(c *gin.Context) {
	if !writable(c, true) {
		return
	}
	unit := c.Param("unit")
	if !s.Config.Operations || !contains([]string{"starry-api", "starry-ai"}, unit) {
		c.JSON(403, gin.H{"error": "只允许重启账户与推理服务"})
		return
	}
	var body struct {
		Confirmed bool `json:"confirmed"`
	}
	if c.ShouldBindJSON(&body) != nil || !body.Confirmed {
		c.JSON(400, gin.H{"error": "请确认重启；在途请求可能中断"})
		return
	}
	s.record(c, "restart", "service", map[string]string{"unit": unit}, func() (any, error) {
		ctx, cancel := context.WithTimeout(c.Request.Context(), 10*time.Second)
		defer cancel()
		e := exec.CommandContext(ctx, "systemctl", "--user", "restart", unit).Run()
		return true, e
	})
}
