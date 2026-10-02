package api_test

import (
	"context"
	"github.com/google/uuid"
	"github.com/gukaifeng/starrynight-server/internal/store"
	"testing"
)

func TestGoalsBranchesOwnershipCASIdempotencyPauseAndReset(t *testing.T) {
	s := setup(t)
	a, b := s.register(), s.register()
	ctx := context.Background()
	role := "anime-ichigo"
	defaults := decode[store.Goals](t, s.call("GET", "/v1/conversations/"+role+"/goals", a.Token, nil, 200))
	if defaults.Config.LongTerm != "romance" || defaults.Version != 0 {
		t.Fatal(defaults)
	}
	s.call("GET", "/v1/conversations/"+role+"/goals", "", nil, 401)
	g := decode[store.Goals](t, s.call("PUT", "/v1/conversations/"+role+"/goals", a.Token, map[string]any{"expected_version": 0, "config": defaults.Config}, 200))
	s.call("PUT", "/v1/conversations/"+role+"/goals", a.Token, map[string]any{"expected_version": 0, "config": defaults.Config}, 409)
	f := store.GoalFeedback{RequestID: uuid.NewString(), Version: g.Version, Trigger: "user_message", Familiarity: .9, Trust: .02, Affection: .03, Milestone: "date_agreed", Evidence: "一起喝茶", UserText: "周末一起喝茶吧"}
	g, e := s.db.CommitGoalTurn(ctx, a.User.ID, role, f)
	if e != nil {
		t.Fatal(e)
	}
	branch := g.Config.Branch()
	if g.Branches[branch].Familiarity != .04 || len(g.Branches[branch].Milestones) != 1 {
		t.Fatal(g)
	}
	again, e := s.db.CommitGoalTurn(ctx, a.User.ID, role, f)
	if e != nil || again.ProgressVersion != g.ProgressVersion {
		t.Fatal("non-idempotent feedback", e)
	}
	other, e := s.db.Goals(ctx, b.User.ID, role)
	if e != nil || len(other.Branches) != 0 {
		t.Fatal("cross-account progress", e)
	}
	g.Config.Mode = "task"
	g.Config.Task = "english"
	g, e = s.db.SetGoals(ctx, a.User.ID, role, g.Version, g.Config, "")
	if e != nil {
		t.Fatal(e)
	}
	if len(g.Branches) != 2 || g.Bond.Affection != .03 {
		t.Fatal("switch erased relation branch")
	}
	if _, e = s.db.CommitGoalTurn(ctx, a.User.ID, role, f); e != store.ErrConflict {
		t.Fatal("stale draft accepted", e)
	}
	f.RequestID = uuid.NewString()
	f.Version = g.Version
	f.Trigger = "idle"
	idle, e := s.db.CommitGoalTurn(ctx, a.User.ID, role, f)
	if e != nil || idle.ProgressVersion != g.ProgressVersion {
		t.Fatal("idle advanced progress", e)
	}
	g.Config.Paused = true
	g, e = s.db.SetGoals(ctx, a.User.ID, role, g.Version, g.Config, "")
	if e != nil {
		t.Fatal(e)
	}
	f.RequestID = uuid.NewString()
	f.Version = g.Version
	f.Trigger = "user_message"
	paused, e := s.db.CommitGoalTurn(ctx, a.User.ID, role, f)
	if e != nil || paused.ProgressVersion != g.ProgressVersion {
		t.Fatal("paused advanced progress", e)
	}
	if _, e = s.db.ResetConversation(ctx, a.User.ID, role, uuid.NewString()); e != nil {
		t.Fatal(e)
	}
	reset, e := s.db.Goals(ctx, a.User.ID, role)
	if e != nil || len(reset.Branches) != 0 || !reset.Config.Paused {
		t.Fatal("reset did not preserve config/erase progress", e)
	}
	child := store.DefaultGoals("anime-kipfel").Config
	child.LongTerm = "romance"
	s.call("PUT", "/v1/conversations/anime-kipfel/goals", a.Token, map[string]any{"expected_version": 0, "config": child}, 422)
	s.call("POST", "/internal/goals/"+a.User.ID+"/"+role+"/feedback", a.Token, f, 401)
}
