package content

import (
	"encoding/json"
	"os"
	"strings"
	"testing"
)

func fixture(t *testing.T) SettingDocument {
	t.Helper()
	b, e := os.ReadFile("../../api/contracts/fixtures/setting-v1.json")
	if e != nil {
		t.Fatal(e)
	}
	var d SettingDocument
	if e = json.Unmarshal(b, &d); e != nil {
		t.Fatal(e)
	}
	return d
}
func TestStructuredSourceAndVariables(t *testing.T) {
	d := fixture(t)
	if r := Validate(d); !r.Valid {
		t.Fatal(r)
	}
	d.Runtime.Blocks["teaching-rule"] = SettingBlock{Kind: "instruction", Purpose: "teaching", Text: "{{platform.api_key}}"}
	if r := Validate(d); r.Valid {
		t.Fatal("unregistered interpolation accepted")
	}
	d = fixture(t)
	d.Runtime.Blocks["secret"] = SettingBlock{Kind: "secret", Text: "hidden reveal"}
	d.Runtime.BlockOrder = append(d.Runtime.BlockOrder, "secret")
	if r := Validate(d); r.Valid {
		t.Fatal("secret without disclosure accepted")
	}
	d = fixture(t)
	d.Runtime.BlockOrder = append(d.Runtime.BlockOrder, "teaching-rule")
	if r := Validate(d); r.Valid {
		t.Fatal("duplicate ordering accepted")
	}
}
func TestDraftKeepsIncompleteTextAndExtensions(t *testing.T) {
	b := DraftBody{RawFields: map[string]json.RawMessage{"height": json.RawMessage(`"-"`), "composition": json.RawMessage(`"未提交的输入"`)}, Document: SettingDocument{Extensions: map[string]json.RawMessage{"future.example": json.RawMessage(`{"option":true}`)}}}
	if e := ValidateDraft(b); e != nil {
		t.Fatal(e)
	}
	if r := Validate(b.Document); r.Valid {
		t.Fatal("incomplete draft may not be activated")
	}
	d := fixture(t)
	d.Extensions["future.plugin"] = json.RawMessage(`{"nested":{"unused":true}}`)
	if r := Validate(d); !r.Valid {
		t.Fatal(r)
	}
	b.RawFields["long"] = json.RawMessage(`"` + strings.Repeat("x", MaxDraftBytes) + `"`)
	if ValidateDraft(b) == nil {
		t.Fatal("unbounded draft accepted")
	}
}
func TestParameterNormalizationAndUnknownKeys(t *testing.T) {
	d := fixture(t)
	p, e := ResolveParameters(d.ParameterSchema, nil)
	if e != nil || p["level"] != "B1" {
		t.Fatal(p, e)
	}
	if _, e = ResolveParameters(d.ParameterSchema, map[string]any{"unknown": "injection"}); e == nil {
		t.Fatal("unknown parameter accepted")
	}
	if _, e = ResolveParameters(d.ParameterSchema, map[string]any{"level": "C9"}); e == nil {
		t.Fatal("invalid parameter accepted")
	}
}
