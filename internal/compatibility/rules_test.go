package compatibility

import (
	"github.com/gukaifeng/starrynight-server/internal/content"
	"testing"
)

func TestUnknownCannotPassNegation(t *testing.T) {
	height := content.Rule{Field: "identity.height_cm", Op: "gte", Value: 160.0}
	rules := []struct {
		rule content.Rule
		want Result
	}{
		{height, Unknown}, {content.Rule{Not: &height}, Unknown},
		{content.Rule{Any: []content.Rule{height, {Field: "identity.gender", Op: "eq", Value: "female"}}}, Match},
		{content.Rule{All: []content.Rule{height, {Field: "identity.gender", Op: "eq", Value: "male"}}}, Mismatch},
	}
	fields := map[string]any{"identity": map[string]any{"gender": "female"}}
	for _, c := range rules {
		v, e := Evaluate(&c.rule, fields)
		if e != nil || v.Result != c.want {
			t.Fatalf("%+v: %v %v", c.rule, v, e)
		}
	}
	fields["identity"].(map[string]any)["height_cm"] = 160.0
	v, e := Evaluate(&height, fields)
	if e != nil || v.Result != Match {
		t.Fatal("inclusive numeric boundary", v, e)
	}
}
func TestRulesRejectExecutableOrPrivateFields(t *testing.T) {
	for _, r := range []content.Rule{{Field: "private.prompt", Op: "eq", Value: "secret"}, {Field: "id", Op: "raw_cel", Value: "true"}, {Field: "identity.age", Op: "gte", Value: "18"}, {All: []content.Rule{{Field: "id", Op: "eq", Value: "x"}}, Field: "id", Op: "eq", Value: "y"}} {
		if Validate(&r) == nil {
			t.Fatalf("invalid rule accepted: %+v", r)
		}
	}
	r := content.Rule{Field: "id", Op: "eq", Value: "character"}
	for range 10 {
		r = content.Rule{Not: &r}
	}
	if Validate(&r) == nil {
		t.Fatal("unbounded rule accepted")
	}
}
func TestCollectionCapabilities(t *testing.T) {
	r := content.Rule{Field: "capabilities.spoken_languages", Op: "contains_all", Value: []any{"en", "zh"}}
	v, e := Evaluate(&r, map[string]any{"capabilities": map[string]any{"spoken_languages": []any{"zh", "en"}}})
	if e != nil || v.Result != Match {
		t.Fatal(v, e)
	}
}
