package store

import (
	"context"
	"encoding/json"
	"errors"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"math"
	"strings"
	"unicode/utf8"
)

// Configuration is user-owned. AI feedback can only advance the active branch.
type GoalConfig struct {
	Mode            string         `json:"mode" enum:"relationship,task,sandbox"`
	InitialRelation string         `json:"initial_relation"`
	LongTerm        string         `json:"long_term"`
	ShortTerm       string         `json:"short_term" maxLength:"160"`
	Task            string         `json:"task"`
	Paused          bool           `json:"paused"`
	ConfirmedCouple bool           `json:"confirmed_couple"`
	Extensions      map[string]any `json:"extensions,omitempty"`
}
type GoalBranch struct {
	Familiarity  float64  `json:"familiarity"`
	Trust        float64  `json:"trust"`
	Affection    float64  `json:"affection"`
	TaskProgress float64  `json:"task_progress"`
	Milestones   []string `json:"milestones"`
}
type Goals struct {
	SchemaVersion   int                   `json:"schema_version"`
	Version         int64                 `json:"version"`
	ProgressVersion int64                 `json:"progress_version"`
	RomanceAllowed  bool                  `json:"romance_allowed"`
	Config          GoalConfig            `json:"config"`
	Branches        map[string]GoalBranch `json:"branches"`
	Bond            GoalBranch            `json:"bond"`
}

// Eligibility is authored, never inferred from an avatar's body or an AI reply.
func RomanceAllowed(character string) bool {
	return character == "anime-mafuyu" || character == "anime-ichigo"
}
func DefaultGoals(character string) Goals {
	long := "friendship"
	if RomanceAllowed(character) {
		long = "romance"
	}
	result := Goals{SchemaVersion: 1, RomanceAllowed: RomanceAllowed(character), Config: GoalConfig{Mode: "relationship", InitialRelation: "friends", LongTerm: long, Task: "study", ShortTerm: ""}, Branches: map[string]GoalBranch{}}
	if character == "anime-lime" || character == "anime-nozomi" {
		result.Config.Mode = "task"
		result.Config.Task = "english"
	}
	return result
}
func (c GoalConfig) Branch() string {
	if c.Mode == "task" {
		return "task:" + c.Task
	}
	if c.Mode == "sandbox" {
		return "sandbox"
	}
	return "relationship:" + c.InitialRelation + ":" + c.LongTerm
}
func oneOf(value string, choices ...string) bool {
	for _, v := range choices {
		if value == v {
			return true
		}
	}
	return false
}
func ValidateGoals(c GoalConfig, character string) error {
	if !oneOf(c.Mode, "relationship", "task", "sandbox") || !oneOf(c.InitialRelation, "strangers", "pursuit", "flirting", "lovers", "friends", "mentor", "rivals", "childhood") || !oneOf(c.LongTerm, "romance", "friendship", "understanding") || !oneOf(c.Task, "study", "english", "listening", "planning") {
		return invalid("unsupported goal configuration")
	}
	if utf8.RuneCountInString(c.ShortTerm) > 160 || strings.TrimSpace(c.ShortTerm) != c.ShortTerm {
		return invalid("invalid short_term")
	}
	if !RomanceAllowed(character) && (c.LongTerm == "romance" || oneOf(c.InitialRelation, "pursuit", "flirting", "lovers") || c.ConfirmedCouple) {
		return invalid("this authored persona supports non-romantic companionship")
	}
	if c.ConfirmedCouple && c.LongTerm != "romance" {
		return invalid("couple confirmation requires romance direction")
	}
	if c.Extensions != nil {
		if _, err := merge(map[string]any{}, c.Extensions); err != nil {
			return err
		}
	}
	encoded, e := json.Marshal(c)
	if e != nil || len(encoded) > 4096 {
		return invalid("goal configuration exceeds 4 KiB")
	}
	return nil
}
func readGoals(ctx context.Context, q interface {
	QueryRow(context.Context, string, ...any) pgx.Row
}, user, char string) (Goals, error) {
	out := DefaultGoals(char)
	err := q.QueryRow(ctx, `SELECT config,progress,version,progress_version FROM conversation_goals WHERE user_id=$1 AND character_id=$2`, user, char).Scan(&out.Config, &out.Branches, &out.Version, &out.ProgressVersion)
	out.Bond = out.Branches["bond"]
	if errors.Is(err, pgx.ErrNoRows) {
		return out, nil
	}
	return out, err
}
func (s *Store) Goals(ctx context.Context, user, char string) (Goals, error) {
	if _, err := s.Character(ctx, user, char); err != nil {
		return Goals{}, err
	}
	return readGoals(ctx, s.Pool, user, char)
}
func (s *Store) EnsureGoals(ctx context.Context, user, char string) (Goals, error) {
	var out Goals
	err := s.write(ctx, user, func(tx pgx.Tx) error {
		if e := accessible(ctx, tx, user, char); e != nil {
			return e
		}
		var e error
		out, e = readGoals(ctx, tx, user, char)
		if e != nil {
			return e
		}
		if out.Version > 0 {
			return nil
		}
		out.Version = 1
		encoded, e := json.Marshal(out.Config)
		if e != nil {
			return e
		}
		_, e = tx.Exec(ctx, `INSERT INTO conversation_goals(user_id,character_id,config,progress,version) VALUES($1,$2,$3::jsonb,'{}',1)`, user, char, string(encoded))
		if e != nil {
			return e
		}
		return event(ctx, tx, user, "goal", char, false, out)
	})
	return out, err
}
func (s *Store) SetGoals(ctx context.Context, user, char string, expected int64, config GoalConfig, reset string) (Goals, error) {
	var out Goals
	if err := ValidateGoals(config, char); err != nil {
		return out, err
	}
	err := s.write(ctx, user, func(tx pgx.Tx) error {
		if e := accessible(ctx, tx, user, char); e != nil {
			return e
		}
		if e := checkConversationReset(ctx, tx, user, char, []string{reset}); e != nil {
			return e
		}
		var e error
		out, e = readGoals(ctx, tx, user, char)
		if e != nil {
			return e
		}
		if out.Version != expected {
			return ErrConflict
		}
		out.Config = config
		out.Version++
		encoded, e := json.Marshal(config)
		if e != nil {
			return e
		}
		progress, e := json.Marshal(out.Branches)
		if e != nil {
			return e
		}
		_, e = tx.Exec(ctx, `INSERT INTO conversation_goals(user_id,character_id,config,progress,version) VALUES($1,$2,$3::jsonb,$4::jsonb,$5) ON CONFLICT(user_id,character_id) DO UPDATE SET config=$3::jsonb,version=$5`, user, char, string(encoded), string(progress), out.Version)
		if e != nil {
			return e
		}
		return event(ctx, tx, user, "goal", char, false, out)
	})
	return out, err
}

type GoalFeedback struct {
	RequestID    string  `json:"request_id"`
	Version      int64   `json:"version"`
	Reset        string  `json:"conversation_reset"`
	Trigger      string  `json:"trigger"`
	Familiarity  float64 `json:"familiarity"`
	Trust        float64 `json:"trust"`
	Affection    float64 `json:"affection"`
	TaskProgress float64 `json:"task_progress"`
	Milestone    string  `json:"milestone"`
	Evidence     string  `json:"evidence"`
	UserText     string  `json:"user_text"`
}

func boundedDelta(v float64) float64 {
	if math.IsNaN(v) || math.IsInf(v, 0) {
		return 0
	}
	return max(-.04, min(.04, v))
}
func advance(v, delta float64) float64 { return max(0, min(1, v+boundedDelta(delta))) }
func (s *Store) CommitGoalTurn(ctx context.Context, user, char string, f GoalFeedback) (Goals, error) {
	var out Goals
	if _, e := uuid.Parse(f.RequestID); e != nil {
		return out, invalid("invalid request_id")
	}
	err := s.write(ctx, user, func(tx pgx.Tx) error {
		if e := accessible(ctx, tx, user, char); e != nil {
			return e
		}
		if e := checkConversationReset(ctx, tx, user, char, []string{f.Reset}); e != nil {
			return e
		}
		var e error
		out, e = readGoals(ctx, tx, user, char)
		if e != nil {
			return e
		}
		if out.Version != f.Version {
			return ErrConflict
		}
		// Defaults are persisted before feedback; drafts, idle and return cannot farm progress.
		if out.Version == 0 || out.Config.Paused || !oneOf(f.Trigger, "user_message", "story") || strings.TrimSpace(f.UserText) == "" {
			return nil
		}
		result, e := tx.Exec(ctx, `INSERT INTO goal_turns(user_id,character_id,request_id,config_version) VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING`, user, char, f.RequestID, f.Version)
		if e != nil {
			return e
		}
		if result.RowsAffected() == 0 {
			return nil
		}
		key := out.Config.Branch()
		b := out.Branches[key]
		if len(f.Evidence) < 2 || !strings.Contains(f.UserText, f.Evidence) {
			return nil
		}
		b.Familiarity = advance(b.Familiarity, f.Familiarity)
		b.Trust = advance(b.Trust, f.Trust)
		affection := f.Affection
		if out.Config.Mode != "relationship" {
			affection *= .25
		}
		if out.RomanceAllowed && out.Config.LongTerm == "romance" {
			b.Affection = advance(b.Affection, affection)
		}
		if out.Config.Mode == "task" {
			b.TaskProgress = advance(b.TaskProgress, f.TaskProgress)
		}
		// A milestone must cite an actual user phrase; no invented fact or automatic coupling.
		if len(f.Evidence) >= 2 && strings.Contains(f.UserText, f.Evidence) && oneOf(f.Milestone, "shared_interest", "trust_opened", "date_agreed", "repair", "learning_step", "preference_understood") {
			if !oneOf(f.Milestone, b.Milestones...) {
				b.Milestones = append(b.Milestones, f.Milestone)
			}
		}
		out.Branches[key] = b
		bond := out.Bond
		bond.Familiarity = advance(bond.Familiarity, f.Familiarity)
		bond.Trust = advance(bond.Trust, f.Trust)
		if out.RomanceAllowed && out.Config.LongTerm == "romance" {
			bond.Affection = advance(bond.Affection, affection)
		}
		for _, milestone := range b.Milestones {
			if milestone != "learning_step" && !oneOf(milestone, bond.Milestones...) {
				bond.Milestones = append(bond.Milestones, milestone)
			}
		}
		out.Bond = bond
		out.Branches["bond"] = bond
		out.ProgressVersion++
		encoded, e := json.Marshal(out.Branches)
		if e != nil {
			return e
		}
		_, e = tx.Exec(ctx, `UPDATE conversation_goals SET progress=$3::jsonb,progress_version=$4 WHERE user_id=$1 AND character_id=$2`, user, char, string(encoded), out.ProgressVersion)
		if e != nil {
			return e
		}
		return event(ctx, tx, user, "goal", char, false, out)
	})
	return out, err
}
