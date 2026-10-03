// Package compatibility evaluates a bounded author rule tree. Authors cannot
// submit arbitrary CEL; only registered public, fixed character fields are read.
package compatibility

import (
	"cel.dev/cel-go/cel"
	"encoding/json"
	"fmt"
	"github.com/gukaifeng/starrynight-server/internal/content"
	"reflect"
	"strings"
)

type Result string

const (
	Match    Result = "match"
	Mismatch Result = "mismatch"
	Unknown  Result = "unknown"
)

type Field struct {
	Kind   string   `json:"kind"`
	Unit   string   `json:"unit,omitempty"`
	Values []string `json:"values,omitempty"`
}

var registry = map[string]Field{
	"identity.gender":    {Kind: "string", Values: []string{"female", "male", "nonbinary", "other"}},
	"identity.age":       {Kind: "number", Unit: "years"},
	"identity.height_cm": {Kind: "number", Unit: "cm"},
	"identity.species":   {Kind: "string"}, "identity.profession": {Kind: "string"},
	"identity.relationships": {Kind: "strings"}, "personality.traits": {Kind: "strings"},
	"personality.tone": {Kind: "string"}, "language_style.tags": {Kind: "strings"},
	"capabilities.spoken_languages": {Kind: "strings"}, "capabilities.features": {Kind: "strings"},
	"capabilities.performance_groups": {Kind: "strings"}, "capabilities.voice_styles": {Kind: "strings"},
	"id": {Kind: "string"},
}

func Fields() map[string]Field {
	out := map[string]Field{}
	for k, v := range registry {
		v.Values = append([]string(nil), v.Values...)
		out[k] = v
	}
	return out
}
func Validate(rule *content.Rule) error { n := 0; return validate(rule, 0, &n) }
func validate(r *content.Rule, depth int, n *int) error {
	if r == nil {
		return nil
	}
	*n++
	if depth > 8 || *n > 128 {
		return fmt.Errorf("compatibility rule exceeds depth or node limit")
	}
	branches := 0
	if len(r.All) > 0 {
		branches++
	}
	if len(r.Any) > 0 {
		branches++
	}
	if r.Not != nil {
		branches++
	}
	if r.Field != "" {
		branches++
	}
	if branches != 1 {
		return fmt.Errorf("each rule must contain exactly one condition")
	}
	for _, items := range [][]content.Rule{r.All, r.Any} {
		for _, child := range items {
			if e := validate(&child, depth+1, n); e != nil {
				return e
			}
		}
	}
	if r.Not != nil {
		return validate(r.Not, depth+1, n)
	}
	if r.Field == "" {
		return nil
	}
	f, ok := registry[r.Field]
	if !ok {
		return fmt.Errorf("unregistered fixed field: %s", r.Field)
	}
	if r.Op == "exists" {
		if _, ok := r.Value.(bool); !ok {
			return fmt.Errorf("exists requires a boolean")
		}
		return nil
	}
	if f.Kind == "number" {
		switch r.Op {
		case "eq", "ne", "lt", "lte", "gt", "gte":
		default:
			return fmt.Errorf("invalid numeric operator")
		}
		if _, ok := number(r.Value); !ok {
			return fmt.Errorf("numeric condition requires a number")
		}
	}
	if f.Kind == "string" {
		switch r.Op {
		case "eq", "ne":
			if _, ok := r.Value.(string); !ok {
				return fmt.Errorf("condition requires a string")
			}
		case "in", "not_in":
			if _, ok := stringsValue(r.Value); !ok {
				return fmt.Errorf("condition requires string choices")
			}
		default:
			return fmt.Errorf("invalid string operator")
		}
	}
	if f.Kind == "strings" {
		if r.Op != "contains_all" && r.Op != "contains_any" {
			return fmt.Errorf("invalid collection operator")
		}
		if _, ok := stringsValue(r.Value); !ok {
			return fmt.Errorf("condition requires string choices")
		}
	}
	return nil
}
func number(v any) (float64, bool) {
	switch x := v.(type) {
	case float64:
		return x, true
	case int:
		return float64(x), true
	case int64:
		return float64(x), true
	case json.Number:
		f, e := x.Float64()
		return f, e == nil
	}
	return 0, false
}
func stringsValue(v any) ([]string, bool) {
	if x, ok := v.([]string); ok {
		return x, true
	}
	a, ok := v.([]any)
	if !ok {
		return nil, false
	}
	out := []string{}
	for _, v := range a {
		s, ok := v.(string)
		if !ok {
			return nil, false
		}
		out = append(out, s)
	}
	return out, true
}
func valueAt(fields map[string]any, path string) (any, bool) {
	var v any = fields
	for _, p := range strings.Split(path, ".") {
		m, ok := v.(map[string]any)
		if !ok {
			return nil, false
		}
		v, ok = m[p]
		if !ok || v == nil {
			return nil, false
		}
	}
	return v, true
}

type Explanation struct {
	Field  string `json:"field"`
	Result Result `json:"result"`
	Reason string `json:"reason"`
}
type Evaluation struct {
	Result  Result        `json:"result"`
	Reasons []Explanation `json:"reasons"`
}

func Evaluate(r *content.Rule, fields map[string]any) (Evaluation, error) {
	if e := Validate(r); e != nil {
		return Evaluation{}, e
	}
	out := Evaluation{Reasons: []Explanation{}}
	out.Result = eval(r, fields, &out.Reasons)
	return out, nil
}
func eval(r *content.Rule, fields map[string]any, reasons *[]Explanation) Result {
	if r == nil {
		return Match
	}
	if len(r.All) > 0 {
		out := Match
		for _, c := range r.All {
			x := eval(&c, fields, reasons)
			if x == Mismatch {
				out = Mismatch
			} else if x == Unknown && out == Match {
				out = Unknown
			}
		}
		return out
	}
	if len(r.Any) > 0 {
		out := Mismatch
		for _, c := range r.Any {
			x := eval(&c, fields, reasons)
			if x == Match {
				out = Match
			} else if x == Unknown && out == Mismatch {
				out = Unknown
			}
		}
		return out
	}
	if r.Not != nil {
		x := eval(r.Not, fields, reasons)
		if x == Match {
			return Mismatch
		}
		if x == Mismatch {
			return Match
		}
		return Unknown
	}
	v, known := valueAt(fields, r.Field)
	result := Unknown
	reason := "fixed attribute is unknown"
	if r.Op == "exists" {
		result = Mismatch
		if known == r.Value.(bool) {
			result = Match
		}
		reason = "attribute presence"
	} else if known {
		if f := registry[r.Field]; f.Kind == "number" {
			x, ok := number(v)
			if !ok {
				known = false
			} else {
				v = x
			}
		}
		if known {
			ok, e := leaf(r, v)
			if e == nil {
				result = Mismatch
				if ok {
					result = Match
				}
				reason = "fixed attribute comparison"
			} else {
				reason = "fixed attribute has an incompatible type"
			}
		}
	}
	*reasons = append(*reasons, Explanation{r.Field, result, reason})
	return result
}
func leaf(r *content.Rule, v any) (bool, error) {
	// The only CEL source is server-generated and never includes author text.
	expr := ""
	wanted := r.Value
	if n, ok := number(wanted); ok {
		wanted = n
	}
	if a, ok := stringsValue(wanted); ok {
		wanted = a
	}
	switch r.Op {
	case "eq":
		expr = "actual == wanted"
	case "ne":
		expr = "actual != wanted"
	case "lt":
		expr = "actual < wanted"
	case "lte":
		expr = "actual <= wanted"
	case "gt":
		expr = "actual > wanted"
	case "gte":
		expr = "actual >= wanted"
	case "in":
		expr = "actual in wanted"
	case "not_in":
		expr = "!(actual in wanted)"
	case "contains_all":
		expr = "wanted.all(x, x in actual)"
	case "contains_any":
		expr = "wanted.exists(x, x in actual)"
	default:
		return false, fmt.Errorf("unknown operator")
	}
	env, e := cel.NewEnv(cel.Variable("actual", cel.DynType), cel.Variable("wanted", cel.DynType))
	if e != nil {
		return false, e
	}
	ast, issues := env.Compile(expr)
	if issues.Err() != nil {
		return false, issues.Err()
	}
	prg, e := env.Program(ast, cel.CostLimit(1024))
	if e != nil {
		return false, e
	}
	result, _, e := prg.Eval(map[string]any{"actual": v, "wanted": wanted})
	if e != nil {
		return false, e
	}
	return reflect.DeepEqual(result.Value(), true), nil
}
