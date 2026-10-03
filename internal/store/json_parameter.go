package store

import "encoding/json"

// jsonParam is for values already checked by the content contract. Passing
// RawMessage gives pgx's exec mode a known JSON OID rather than an unknown Go
// struct; this also works with PgBouncer's transaction pooling.
func jsonParam(v any) json.RawMessage {
	b, e := json.Marshal(v)
	if e != nil {
		panic("validated content cannot be encoded")
	}
	return json.RawMessage(b)
}
