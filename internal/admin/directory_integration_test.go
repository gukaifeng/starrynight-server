package admin

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net/url"
	"strings"
	"testing"

	"github.com/google/uuid"
	"github.com/gukaifeng/starrynight-server/internal/store"
)

func testEntityDirectories(t *testing.T, db *store.Store, user string, get func(string) (int, []byte)) {
	t.Helper()
	ctx := context.Background()
	prefix := "directory_" + strings.ReplaceAll(uuid.NewString(), "-", "")[:10]
	ids := []string{}
	for i := 0; i < 27; i++ {
		id := uuid.NewString()
		ids = append(ids, id)
		if _, e := db.Pool.Exec(ctx, `INSERT INTO users(id,guest,profile) VALUES($1,true,jsonb_build_object('display_name',$2::text))`, id, fmt.Sprintf("%s %02d", prefix, i)); e != nil {
			t.Fatal(e)
		}
	}
	defer func() {
		for _, id := range ids {
			db.DeleteUser(ctx, id)
		}
	}()
	read := func(path string) map[string]any {
		t.Helper()
		code, data := get(path)
		if code != 200 {
			t.Fatalf("%s returned %d: %s", path, code, data)
		}
		var row map[string]any
		if e := json.Unmarshal(data, &row); e != nil {
			t.Fatal(e)
		}
		return row
	}
	page := func(path string) Page {
		t.Helper()
		code, data := get(path)
		if code != 200 {
			t.Fatalf("%s returned %d: %s", path, code, data)
		}
		var out Page
		if e := json.Unmarshal(data, &out); e != nil {
			t.Fatal(e)
		}
		return out
	}
	seen := map[string]bool{}
	cursor := ""
	for {
		p := page("/directory/users?q=" + url.QueryEscape(prefix) + "&limit=10&after=" + url.QueryEscape(cursor))
		if len(p.Items) > 10 {
			t.Fatal("unbounded directory")
		}
		for _, r := range p.Items {
			id := r["id"].(string)
			if seen[id] {
				t.Fatal("duplicate cursor row")
			}
			seen[id] = true
			if strings.Contains(fmt.Sprint(r), "password_hash") {
				t.Fatal("credentials leaked")
			}
		}
		if p.Next == "" {
			break
		}
		cursor = p.Next
	}
	if len(seen) != 27 {
		t.Fatalf("missing users %d", len(seen))
	}
	if p := page("/directory/users?q=" + user); len(p.Items) != 1 || p.Items[0]["id"] != user {
		t.Fatal("exact UUID lookup failed")
	}
	if p := page("/directory/users?q=%25%27%20OR%201%3D1--"); len(p.Items) != 0 {
		t.Fatal("search was not literal")
	}
	if code, _ := get("/directory/users?limit=51"); code != 400 {
		t.Fatal("page cap not enforced")
	}
	if code, _ := get("/directory/users?q=another&after=" + cursor); code != 400 {
		t.Fatal("cursor scope not checked")
	}

	characters := []string{prefix + "-a", prefix + "-b", prefix + "-c"}
	defer func() {
		for _, id := range characters {
			db.Pool.Exec(ctx, "DELETE FROM characters WHERE id=$1", id)
		}
	}()
	for _, id := range characters {
		if _, e := db.Pool.Exec(ctx, `INSERT INTO characters(id,owner_id,author_id,visibility,name) VALUES($1,$2,'starry-studio','private',$3)`, id, user, "验证角色"+id); e != nil {
			t.Fatal(e)
		}
	}
	other := ids[0]
	exec := func(q string, args ...any) {
		t.Helper()
		if _, e := db.Pool.Exec(ctx, q, args...); e != nil {
			t.Fatal(e)
		}
	}
	// CreateUser assigns a default subscription. This test owns its isolated
	// account and replaces that association with the explicit fixture below.
	exec("DELETE FROM subscriptions WHERE user_id=$1", user)
	for _, pair := range [][2]string{{user, characters[0]}, {user, characters[1]}, {other, characters[0]}} {
		exec("INSERT INTO conversations(user_id,character_id) VALUES($1,$2)", pair[0], pair[1])
	}
	for _, pair := range [][2]string{{user, characters[0]}, {user, characters[2]}, {other, characters[0]}} {
		exec("INSERT INTO subscriptions(user_id,character_id) VALUES($1,$2)", pair[0], pair[1])
	}
	exec("INSERT INTO preferences(user_id,character_id,data) VALUES($1,$2,'{\"nickname\":\"测试称呼\"}')", user, characters[2])
	exec("INSERT INTO conversation_goals(user_id,character_id,config) VALUES($1,$2,'{}')", user, characters[1])
	exec(`INSERT INTO messages(user_id,character_id,id,role,text,created_at)
SELECT $1::text::uuid,$2::text,gen_random_uuid(),CASE WHEN i%2=0 THEN 'assistant' ELSE 'user' END,'scope fixture',now() FROM generate_series(1,30) i`, user, characters[0])
	exec("INSERT INTO messages(user_id,character_id,id,role,text,created_at) VALUES($1,$2,$3,'assistant','other character',now())", user, characters[1], uuid.NewString())
	exec(`INSERT INTO messages(user_id,character_id,id,role,text,created_at) SELECT $1::text::uuid,$2::text,gen_random_uuid(),'assistant','other user',now() FROM generate_series(1,7)`, other, characters[0])
	stat := read("/directory/users/" + user)["stats"].(map[string]any)
	if stat["messages"] != float64(31) || stat["subscriptions"] != float64(2) {
		t.Fatalf("incorrect user totals: %v", stat)
	}
	stat = read("/directory/characters/" + characters[0])["stats"].(map[string]any)
	if stat["messages"] != float64(37) || stat["chatters"] != float64(2) {
		t.Fatalf("incorrect role totals: %v", stat)
	}
	if p := page("/directory/characters?q=" + prefix); len(p.Items) != 3 {
		t.Fatal("private roles missing")
	}
	if p := page("/directory/relationships?user_id=" + user); len(p.Items) != 3 {
		t.Fatalf("union of relations incomplete: %v", p)
	}
	if p := page("/directory/relationships?character_id=" + characters[0] + "&kind=subscribers"); len(p.Items) != 2 {
		t.Fatal("subscribers missing")
	}
	if p := page("/directory/relationships?user_id=" + user + "&character_id=" + characters[2]); len(p.Items) != 1 || p.Items[0]["subscribed"] != true {
		t.Fatal("intersection scope failed")
	}

	seen = map[string]bool{}
	cursor = ""
	previous := float64(1e15)
	for {
		p := page("/directory/records/messages?user_id=" + user + "&character_id=" + characters[0] + "&limit=10&after=" + url.QueryEscape(cursor))
		for _, row := range p.Items {
			if row["user_id"] != user || row["character_id"] != characters[0] {
				t.Fatal("cross-scope record leak")
			}
			id := row["id"].(string)
			if seen[id] {
				t.Fatal("duplicate scoped message")
			}
			seen[id] = true
			seq := row["sequence"].(float64)
			if seq >= previous {
				t.Fatal("messages must be newest first")
			}
			previous = seq
		}
		if p.Next == "" {
			break
		}
		cursor = p.Next
	}
	if len(seen) != 30 {
		t.Fatal("message page lost rows")
	}
	for _, r := range Resources {
		uc, cc := scopedColumns(r)
		if uc != "" {
			page("/directory/records/" + r.ID + "?user_id=" + user)
		}
		if cc != "" {
			page("/directory/records/" + r.ID + "?character_id=" + characters[0])
		}
	}
	if code, _ := get("/directory/records/users?character_id=" + characters[0]); code != 400 {
		t.Fatal("unsupported scope accepted")
	}
	if code, _ := get("/directory/relationships"); code != 400 {
		t.Fatal("unbounded relations accepted")
	}
	if code, _ := get("/directory/users/not-an-id"); code != 400 {
		t.Fatal("invalid user accepted")
	}
	if code, _ := get("/directory/users/" + uuid.NewString()); code != 404 {
		t.Fatal("missing user accepted")
	}
	if code, _ := get("/directory/characters/missing"); code != 404 {
		t.Fatal("missing character accepted")
	}
	for _, r := range []string{"messages", "changes"} {
		badCursor, _ := json.Marshal(directoryCursor{Scope: r + ":" + user + "::", Keys: []string{"invalid"}})
		if code, _ := get("/directory/records/" + r + "?user_id=" + user + "&after=" + base64.RawURLEncoding.EncodeToString(badCursor)); code != 400 {
			t.Fatal("invalid typed cursor accepted")
		}
	}
	// Repeated upserts / text edits must not increase message totals. Changing
	// a role changes its split, deleting/resetting removes counts transactionally.
	exec("UPDATE messages SET text='edited' WHERE user_id=$1 AND character_id=$2", user, characters[0])
	stat = read("/directory/users/" + user)["stats"].(map[string]any)
	if stat["messages"] != float64(31) {
		t.Fatal("text edits counted again")
	}
	exec("UPDATE messages SET role='assistant' WHERE user_id=$1 AND character_id=$2", user, characters[0])
	stat = read("/directory/users/" + user)["stats"].(map[string]any)
	if stat["ai_messages"] != float64(31) || stat["user_messages"] != float64(0) {
		t.Fatal("role change counts incorrect")
	}
	exec("DELETE FROM messages WHERE user_id=$1 AND character_id=$2", user, characters[0])
	stat = read("/directory/users/" + user)["stats"].(map[string]any)
	if stat["messages"] != float64(1) {
		t.Fatal("deletion counts stale")
	}
	exec("DELETE FROM conversations WHERE user_id=$1 AND character_id=$2", user, characters[1])
	stat = read("/directory/users/" + user)["stats"].(map[string]any)
	if stat["messages"] != float64(0) {
		t.Fatal("cascade reset counts stale")
	}
	errors := make(chan error, 12)
	for i := 0; i < 12; i++ {
		go func() {
			_, err := db.Pool.Exec(ctx, "INSERT INTO messages(user_id,character_id,id,role,text,created_at) VALUES($1,$2,$3,'assistant','concurrent fixture',now())", user, characters[0], uuid.NewString())
			errors <- err
		}()
	}
	for i := 0; i < 12; i++ {
		if err := <-errors; err != nil {
			t.Fatal(err)
		}
	}
	stat = read("/directory/users/" + user)["stats"].(map[string]any)
	if stat["messages"] != float64(12) {
		t.Fatal("concurrent inserts lost counts")
	}
	var existing string
	if err := db.Pool.QueryRow(ctx, "SELECT id::text FROM messages WHERE user_id=$1 AND character_id=$2 LIMIT 1", user, characters[0]).Scan(&existing); err != nil {
		t.Fatal(err)
	}
	exec("INSERT INTO messages(user_id,character_id,id,role,text,created_at) VALUES($1,$2,$3,'assistant','same outbox item',now()) ON CONFLICT(user_id,character_id,id) DO UPDATE SET text=EXCLUDED.text,role=EXCLUDED.role", user, characters[0], existing)
	stat = read("/directory/users/" + user)["stats"].(map[string]any)
	if stat["messages"] != float64(12) {
		t.Fatal("idempotent sync counted twice")
	}
	tx, err := db.Pool.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = tx.Exec(ctx, "DELETE FROM messages WHERE user_id=$1 AND character_id=$2", user, characters[0]); err != nil {
		tx.Rollback(ctx)
		t.Fatal(err)
	}
	if err = tx.Rollback(ctx); err != nil {
		t.Fatal(err)
	}
	stat = read("/directory/users/" + user)["stats"].(map[string]any)
	if stat["messages"] != float64(12) {
		t.Fatal("rolled back deletion changed counts")
	}
}
