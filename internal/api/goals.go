package api

import (
	"context"
	"crypto/subtle"
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/gukaifeng/starrynight-server/internal/store"
	"net/http"
)

func (s *Server) goalRoutes() {
	register(s, "GET", "/v1/conversations/{character}/goals", "conversation-goals", true, func(ctx context.Context, in *CharacterPath) (*Output[store.Goals], error) {
		v, e := s.Store.Goals(ctx, principal(ctx).ID, in.Character)
		return output(v, e)
	})
	type Input struct {
		CharacterPath
		Body struct {
			ExpectedVersion int64            `json:"expected_version" minimum:"0"`
			Config          store.GoalConfig `json:"config"`
			Reset           string           `json:"conversation_reset,omitempty"`
		}
	}
	register(s, "PUT", "/v1/conversations/{character}/goals", "set-conversation-goals", true, func(ctx context.Context, in *Input) (*Output[store.Goals], error) {
		v, e := s.Store.SetGoals(ctx, principal(ctx).ID, in.Character, in.Body.ExpectedVersion, in.Body.Config, in.Body.Reset)
		return output(v, e)
	})
	// Separate service credential. Not a public account API, never a client identity header.
	s.Router.POST("/internal/goals/:user/:character/feedback", func(c *gin.Context) {
		if s.Config.AIServiceToken == "" || subtle.ConstantTimeCompare([]byte(c.GetHeader("Authorization")), []byte("Bearer "+s.Config.AIServiceToken)) != 1 {
			c.AbortWithStatus(401)
			return
		}
		if _, e := uuid.Parse(c.Param("user")); e != nil {
			c.AbortWithStatus(400)
			return
		}
		c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, 8192)
		var feedback store.GoalFeedback
		if e := c.ShouldBindJSON(&feedback); e != nil {
			c.AbortWithStatus(422)
			return
		}
		v, e := s.Store.CommitGoalTurn(c.Request.Context(), c.Param("user"), c.Param("character"), feedback)
		if e != nil {
			if e == store.ErrConflict {
				c.AbortWithStatus(409)
			} else {
				c.AbortWithStatus(422)
			}
			return
		}
		c.JSON(200, v)
	})
}
