package content

import (
	"bytes"
	"crypto/sha256"
	"embed"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"github.com/santhosh-tekuri/jsonschema/v6"
	"regexp"
	"strings"
	"sync"
	"unicode/utf8"
)

//go:embed setting.schema.json
var schemas embed.FS
var compiled *jsonschema.Schema
var compileOnce sync.Once
var compileError error

type SettingIssue struct {
	Path    string `json:"path"`
	Code    string `json:"code"`
	Message string `json:"message"`
}
type SettingReport struct {
	Valid      bool           `json:"valid"`
	Issues     []SettingIssue `json:"issues"`
	Contract   string         `json:"contract"`
	SourceHash string         `json:"source_hash"`
}

func Hash(v any) string {
	b, _ := json.Marshal(v)
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:])
}
func ValidateDraft(b DraftBody) error {
	raw, e := json.Marshal(b)
	if e != nil || len(raw) > MaxDraftBytes {
		return fmt.Errorf("draft exceeds 512 KiB")
	}
	if len(b.RawFields) > 512 || len(b.EditorState) > 32 || len(b.FieldErrors) > 512 {
		return fmt.Errorf("draft field limit exceeded")
	}
	return nil
}
func Validate(d SettingDocument) SettingReport {
	r := SettingReport{Valid: true, Issues: []SettingIssue{}, Contract: Contract, SourceHash: Hash(d)}
	add := func(path, code, message string) {
		r.Valid = false
		r.Issues = append(r.Issues, SettingIssue{path, code, message})
	}
	compileOnce.Do(func() {
		raw, _ := schemas.ReadFile("setting.schema.json")
		var v any
		compileError = json.Unmarshal(raw, &v)
		if compileError != nil {
			return
		}
		c := jsonschema.NewCompiler()
		compileError = c.AddResource("urn:starry:setting:1", v)
		if compileError == nil {
			compiled, compileError = c.Compile("urn:starry:setting:1")
		}
	})
	if compileError != nil {
		add("/", "contract_unavailable", "setting contract is unavailable")
		return r
	}
	b, _ := json.Marshal(d)
	if len(b) > MaxDraftBytes {
		add("/", "too_large", "setting exceeds 512 KiB")
	}
	var v any
	_ = json.Unmarshal(b, &v)
	if e := compiled.Validate(v); e != nil { // Validation errors include user text; return paths/codes only.
		var walk func(*jsonschema.ValidationError)
		walk = func(e *jsonschema.ValidationError) {
			if len(e.Causes) == 0 {
				add("/"+strings.Join(e.InstanceLocation, "/"), "schema", "field does not satisfy the setting contract")
			}
			for _, c := range e.Causes {
				walk(c)
			}
		}
		if e, ok := e.(*jsonschema.ValidationError); ok {
			walk(e)
		} else {
			add("/", "schema", "invalid setting document")
		}
	}
	if len(d.RequiredFeatures) > 0 {
		add("/required_features", "unsupported_feature", "required features are not supported by this compiler")
	}
	seen := map[string]bool{}
	for _, id := range d.Runtime.BlockOrder {
		if seen[id] {
			add("/runtime/block_order", "duplicate", "block is listed more than once")
		}
		seen[id] = true
		if _, ok := d.Runtime.Blocks[id]; !ok {
			add("/runtime/block_order", "missing_block", "ordered block does not exist")
		}
	}
	if len(d.Runtime.Blocks) > 128 {
		add("/runtime/blocks", "too_many", "at most 128 blocks are supported")
	}
	for id, block := range d.Runtime.Blocks {
		if !safeID.MatchString(id) {
			add("/runtime/blocks", "invalid_id", "use stable alphanumeric block IDs")
		}
		if !seen[id] {
			add("/runtime/blocks/"+id, "unordered", "every block must appear in block order")
		}
		if len(block.Text) > 64<<10 {
			add("/runtime/blocks/"+id, "too_large", "block exceeds 64 KiB")
		}
		if block.Kind == "secret" && block.Disclosure == nil {
			add("/runtime/blocks/"+id, "missing_disclosure", "secret blocks require a disclosure condition")
		}
		if block.Kind != "secret" && block.Disclosure != nil {
			add("/runtime/blocks/"+id, "invalid_disclosure", "disclosure is only supported for secret blocks")
		}
		for _, variable := range variables.FindAllStringSubmatch(block.Text, -1) {
			if !allowedVariables[variable[1]] {
				add("/runtime/blocks/"+id, "unknown_variable", "unregistered variable")
			}
		}
	}
	for key, p := range d.ParameterSchema {
		if !safeID.MatchString(key) {
			add("/parameter_schema", "invalid_id", "invalid parameter ID")
		}
		if _, e := resolveParameter(p, p.Default); e != nil {
			add("/parameter_schema/"+key, "invalid_default", e.Error())
		}
	}
	if !contains(d.Runtime.LanguagePolicy.Allowed, d.Runtime.LanguagePolicy.Default) {
		add("/runtime/language_policy/default", "unsupported_language", "default language must be allowed")
	}
	openingIDs := map[string]bool{}
	for _, o := range d.OpeningPolicy.Candidates {
		if !safeID.MatchString(o.ID) || openingIDs[o.ID] {
			add("/opening_policy/candidates", "invalid_id", "opening IDs must be unique")
		}
		openingIDs[o.ID] = true
		if !emotions[o.Emotion] {
			add("/opening_policy/candidates", "unknown_emotion", "unknown emotion")
		}
	}
	for key := range d.Extensions {
		if !strings.Contains(key, ".") {
			add("/extensions", "namespace", "extension keys require a namespace")
		}
	}
	return r
}

var safeID = regexp.MustCompile(`^[a-zA-Z0-9_-]{1,80}$`)
var variables = regexp.MustCompile(`\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}`)
var allowedVariables = map[string]bool{"user.nickname": true, "character.name": true, "scene.location": true, "conversation.language": true}
var emotions = func() map[string]bool {
	out := map[string]bool{}
	for _, v := range strings.Fields("neutral calm happy excited sad crying angry worried fearful panicked surprised curious thoughtful serious empathetic affectionate shy playful sarcastic scornful reluctant bored tired confident grateful jealous relieved hopeful") {
		out[v] = true
	}
	return out
}()

func contains(a []string, v string) bool {
	for _, x := range a {
		if x == v {
			return true
		}
	}
	return false
}
func ResolveParameters(schema map[string]SettingParameter, input map[string]any) (map[string]any, error) {
	out := map[string]any{}
	for key := range input {
		if _, ok := schema[key]; !ok {
			return nil, fmt.Errorf("unknown parameter: %s", key)
		}
	}
	for key, p := range schema {
		v, ok := input[key]
		if !ok {
			v = p.Default
		}
		n, e := resolveParameter(p, v)
		if e != nil {
			return nil, fmt.Errorf("parameter %s: %w", key, e)
		}
		out[key] = n
	}
	return out, nil
}
func resolveParameter(p SettingParameter, v any) (any, error) {
	if p.ChangePolicy != "in_place" && p.ChangePolicy != "new_instance" {
		return nil, fmt.Errorf("invalid change policy")
	}
	switch p.Type {
	case "enum":
		s, ok := v.(string)
		if !ok || !contains(p.Values, s) || len(p.Values) > 100 {
			return nil, fmt.Errorf("choose a permitted value")
		}
		return s, nil
	case "text":
		s, ok := v.(string)
		limit := p.MaxLength
		if limit == 0 {
			limit = 2000
		}
		if !ok || limit > 64000 || utf8.RuneCountInString(s) > limit {
			return nil, fmt.Errorf("text exceeds its limit")
		}
		return s, nil
	case "number":
		raw, _ := json.Marshal(v)
		decoder := json.NewDecoder(bytes.NewReader(raw))
		decoder.UseNumber()
		var n json.Number
		if decoder.Decode(&n) != nil {
			return nil, fmt.Errorf("enter a number")
		}
		f, e := n.Float64()
		if e != nil || (p.Min != nil && f < *p.Min) || (p.Max != nil && f > *p.Max) || (p.Min != nil && p.Max != nil && *p.Min > *p.Max) {
			return nil, fmt.Errorf("number is outside the permitted range")
		}
		return f, nil
	default:
		return nil, fmt.Errorf("unknown parameter type")
	}
}
