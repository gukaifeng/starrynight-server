-- +goose Up
-- Directory search does not serialize or scan every user's JSON document.
CREATE INDEX admin_users_directory_search ON users USING gin
    ((coalesce(starry_id,'') || ' ' || coalesce(username,'') || ' ' || coalesce(profile->>'display_name','')) gin_trgm_ops);
CREATE INDEX admin_characters_directory_search ON characters USING gin ((id || ' ' || name) gin_trgm_ops);
CREATE INDEX admin_users_name_prefix ON users (lower(coalesce(profile->>'display_name','')) text_pattern_ops);
CREATE INDEX admin_users_handle_prefix ON users (lower(coalesce(starry_id,'')) text_pattern_ops);
CREATE INDEX admin_users_login_prefix ON users (lower(coalesce(username,'')) text_pattern_ops);
CREATE INDEX admin_characters_name_prefix ON characters (lower(name) text_pattern_ops);
CREATE INDEX admin_characters_id_prefix ON characters (lower(id) text_pattern_ops);
CREATE INDEX admin_conversations_character_user ON conversations(character_id,user_id);
CREATE INDEX admin_preferences_character_user ON preferences(character_id,user_id);
CREATE INDEX admin_goals_character_user ON conversation_goals(character_id,user_id);
CREATE INDEX admin_messages_character_sequence ON messages(character_id,sequence DESC);
CREATE INDEX admin_entries_character_user ON entries(character_id,user_id,kind,id);
CREATE INDEX admin_resets_character_user ON conversation_resets(character_id,user_id,reset_id);
CREATE INDEX admin_goal_turns_character_user ON goal_turns(character_id,user_id,request_id);
CREATE INDEX admin_tickets_user_id ON support_tickets(user_id,id);

-- One row per conversation, never a contended global character counter.
-- Backfill and trigger installation share the migration transaction. Block
-- writes briefly so the initial counts cannot miss an in-flight message.
LOCK TABLE messages IN SHARE ROW EXCLUSIVE MODE;
CREATE TABLE admin_conversation_stats (
    user_id uuid NOT NULL,
    character_id text NOT NULL,
    messages bigint NOT NULL DEFAULT 0 CHECK(messages >= 0),
    user_messages bigint NOT NULL DEFAULT 0 CHECK(user_messages >= 0),
    ai_messages bigint NOT NULL DEFAULT 0 CHECK(ai_messages >= 0),
    PRIMARY KEY(user_id,character_id),
    FOREIGN KEY(user_id,character_id) REFERENCES conversations ON DELETE CASCADE
);
CREATE INDEX admin_stats_character ON admin_conversation_stats(character_id,user_id);
INSERT INTO admin_conversation_stats
SELECT user_id,character_id,count(*),count(*) FILTER(WHERE role='user'),count(*) FILTER(WHERE role='assistant')
FROM messages GROUP BY user_id,character_id;

-- +goose StatementBegin
CREATE FUNCTION admin_message_counts() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        UPDATE admin_conversation_stats SET messages=messages-1,
            user_messages=user_messages-(CASE WHEN OLD.role='user' THEN 1 ELSE 0 END),
            ai_messages=ai_messages-(CASE WHEN OLD.role='assistant' THEN 1 ELSE 0 END)
        WHERE user_id=OLD.user_id AND character_id=OLD.character_id;
    END IF;
    IF TG_OP <> 'DELETE' THEN
        INSERT INTO admin_conversation_stats(user_id,character_id,messages,user_messages,ai_messages)
        VALUES(NEW.user_id,NEW.character_id,1,CASE WHEN NEW.role='user' THEN 1 ELSE 0 END,CASE WHEN NEW.role='assistant' THEN 1 ELSE 0 END)
        ON CONFLICT(user_id,character_id) DO UPDATE SET
            messages=admin_conversation_stats.messages+1,
            user_messages=admin_conversation_stats.user_messages+EXCLUDED.user_messages,
            ai_messages=admin_conversation_stats.ai_messages+EXCLUDED.ai_messages;
    END IF;
    RETURN NULL;
END $$;
-- +goose StatementEnd
CREATE TRIGGER admin_message_counts AFTER INSERT OR DELETE OR UPDATE OF role,user_id,character_id ON messages
FOR EACH ROW EXECUTE FUNCTION admin_message_counts();

-- +goose Down
DROP TRIGGER admin_message_counts ON messages;
DROP FUNCTION admin_message_counts();
DROP TABLE admin_conversation_stats;
DROP INDEX admin_users_directory_search,admin_characters_directory_search,admin_users_name_prefix,
    admin_users_handle_prefix,admin_users_login_prefix,admin_characters_name_prefix,admin_characters_id_prefix,admin_conversations_character_user,
    admin_preferences_character_user,admin_goals_character_user,admin_messages_character_sequence,
    admin_entries_character_user,admin_resets_character_user,admin_goal_turns_character_user,admin_tickets_user_id;
