package content

import "encoding/json"

const Contract = "starry.setting/1"
const MaxDraftBytes = 512 << 10

type SettingPublicProfile struct {
	PrimaryLocale string `json:"primary_locale"`
	Title         string `json:"title"`
	Synopsis      string `json:"synopsis"`
	Experience    string `json:"experience"`
	CoverAssetID  string `json:"cover_asset_id,omitempty"`
}
type SettingScene struct {
	Location        string `json:"location"`
	Time            string `json:"time,omitempty"`
	Event           string `json:"event"`
	UserIdentity    string `json:"user_identity,omitempty"`
	InitialRelation string `json:"initial_relation"`
}
type SettingGoals struct {
	Primary     string   `json:"primary"`
	Secondary   []string `json:"secondary"`
	LongTerm    string   `json:"long_term"`
	ShortTerm   string   `json:"short_term"`
	AllowSwitch bool     `json:"allow_switch"`
}
type SettingLanguagePolicy struct {
	Default         string   `json:"default"`
	Allowed         []string `json:"allowed"`
	ThoughtLanguage string   `json:"thought_language"`
	AllowMixing     bool     `json:"allow_mixing"`
}
type SettingBlock struct {
	Kind       string `json:"kind"`
	Purpose    string `json:"purpose"`
	Text       string `json:"text"`
	Disclosure *Rule  `json:"disclosure,omitempty"`
}
type SettingRuntime struct {
	Scene                  SettingScene            `json:"scene"`
	Goals                  SettingGoals            `json:"goals"`
	LanguagePolicy         SettingLanguagePolicy   `json:"language_policy"`
	Learning               map[string]any          `json:"learning,omitempty"`
	Blocks                 map[string]SettingBlock `json:"blocks"`
	BlockOrder             []string                `json:"block_order"`
	PerformancePreferences map[string]any          `json:"performance_preferences,omitempty"`
}
type Rule struct {
	All   []Rule `json:"all,omitempty"`
	Any   []Rule `json:"any,omitempty"`
	Not   *Rule  `json:"not,omitempty"`
	Field string `json:"field,omitempty"`
	Op    string `json:"op,omitempty"`
	Value any    `json:"value,omitempty"`
}
type Compatibility struct {
	Required  *Rule  `json:"required,omitempty"`
	Preferred []Rule `json:"preferred"`
}
type SettingParameter struct {
	Type         string   `json:"type"`
	Label        string   `json:"label"`
	Values       []string `json:"values,omitempty"`
	Default      any      `json:"default"`
	Min          *float64 `json:"min,omitempty"`
	Max          *float64 `json:"max,omitempty"`
	MaxLength    int      `json:"max_length,omitempty"`
	ChangePolicy string   `json:"change_policy"`
}
type SettingOpening struct {
	ID           string `json:"id"`
	Text         string `json:"text"`
	Thought      string `json:"thought"`
	Emotion      string `json:"emotion"`
	Style        string `json:"style,omitempty"`
	AudioAssetID string `json:"audio_asset_id,omitempty"`
}
type OpeningPolicy struct {
	Mode           string           `json:"mode"`
	Candidates     []SettingOpening `json:"candidates"`
	ReturnGuidance string           `json:"return_guidance,omitempty"`
	IdleGuidance   string           `json:"idle_guidance,omitempty"`
}
type SettingDocument struct {
	SchemaVersion    int                         `json:"schema_version"`
	PublicProfile    SettingPublicProfile        `json:"public_profile"`
	Runtime          SettingRuntime              `json:"runtime"`
	Compatibility    Compatibility               `json:"compatibility"`
	ParameterSchema  map[string]SettingParameter `json:"parameter_schema"`
	OpeningPolicy    OpeningPolicy               `json:"opening_policy"`
	MediaRefs        map[string]string           `json:"media_refs"`
	RequiredFeatures []string                    `json:"required_features,omitempty"`
	Extensions       map[string]json.RawMessage  `json:"extensions"`
}

// DraftBody retains raw, temporarily invalid fields without interpreting them.
type DraftBody struct {
	RawFields   map[string]json.RawMessage `json:"raw_fields"`
	Document    SettingDocument            `json:"normalized_document"`
	FieldErrors map[string]string          `json:"field_errors"`
	EditorState map[string]json.RawMessage `json:"editor_state"`
}
type CharacterCore struct {
	ID            string         `json:"id"`
	Revision      int64          `json:"revision"`
	Name          string         `json:"name"`
	Identity      map[string]any `json:"identity"`
	Personality   map[string]any `json:"personality"`
	LanguageStyle map[string]any `json:"language_style"`
	Capabilities  map[string]any `json:"capabilities"`
	VoiceRevision string         `json:"voice_revision"`
	AssetRelease  string         `json:"asset_release"`
}
