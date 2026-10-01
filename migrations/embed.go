package migrations

import "embed"

// Files is the versioned schema, embedded in the standalone migration binary.
//
//go:embed *.sql
var Files embed.FS
