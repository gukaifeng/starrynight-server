package admin

// This registry is the only source of identifiers used by the data browser.
// Values supplied by the browser are always SQL parameters.
type Resource struct {
	ID          string   `json:"id"`
	Name        string   `json:"name"`
	Group       string   `json:"group"`
	Description string   `json:"description"`
	Keys        []string `json:"keys"`
	Fields      []string `json:"fields"`
	Edit        []string `json:"edit"`
	Actions     []string `json:"actions"`
}

var Resources = []Resource{
	{"goose_db_version", "数据库版本", "系统", "只读迁移历史；迁移仍通过验证过的发布工具执行", []string{"id"}, []string{"id", "version_id", "is_applied", "tstamp"}, nil, nil},
	{"users", "用户账户", "账户", "公开星夜号、个人资料与账户会话", []string{"id"}, []string{"id", "starry_id", "username", "guest", "profile", "version", "created_at"}, []string{"profile"}, []string{"revoke_sessions", "reset_password"}},
	{"settings", "全局设置", "账户", "主题、语言、默认称呼与聊天字号", []string{"user_id"}, []string{"user_id", "data", "version"}, []string{"data"}, nil},
	{"preferences", "角色偏好", "账户", "每个账户独立的角色称呼与偏好", []string{"user_id", "character_id"}, []string{"user_id", "character_id", "data", "version"}, []string{"data"}, nil},
	{"authors", "作者", "内容", "作者介绍、头像与用户关联", []string{"id"}, []string{"id", "user_id", "data", "version", "updated_at"}, []string{"data"}, nil},
	{"characters", "角色目录", "内容", "名称、设定与发布可见性；资源权利单独确认", []string{"id"}, []string{"id", "owner_id", "author_id", "base_id", "visibility", "name", "description", "data", "version", "deleted", "updated_at"}, []string{"name", "description", "visibility", "data"}, []string{"archive", "restore"}},
	{"subscriptions", "角色订阅", "账户", "账户订阅的角色", []string{"user_id", "character_id"}, []string{"user_id", "character_id", "created_at"}, nil, []string{"remove"}},
	{"follows", "作者关注", "账户", "账户关注的作者", []string{"user_id", "author_id"}, []string{"user_id", "author_id", "created_at"}, nil, []string{"remove"}},
	{"conversations", "会话", "对话", "消息页隐藏状态与置顶；重置同时清除推理记忆", []string{"user_id", "character_id"}, []string{"user_id", "character_id", "hidden", "pinned", "version", "updated_at"}, []string{"hidden", "pinned"}, []string{"reset"}},
	{"messages", "聊天记录", "对话", "编辑账户归档；不改写 AI 已使用的上下文，重置会话可同时清空两者", []string{"user_id", "character_id", "id"}, []string{"user_id", "character_id", "id", "sequence", "role", "text", "data", "version", "created_at"}, []string{"text", "data"}, nil},
	{"entries", "记忆与片段", "对话", "人工记忆和共同片段；删除写入同步墓碑", []string{"user_id", "character_id", "kind", "id"}, []string{"user_id", "character_id", "kind", "id", "data", "version", "deleted"}, []string{"data"}, []string{"remove"}},
	{"conversation_goals", "关系与目标", "对话", "可切换的关系、任务和沙盒目标", []string{"user_id", "character_id"}, []string{"user_id", "character_id", "config", "progress", "version", "progress_version"}, []string{"config"}, nil},
	{"character_releases", "资源发布", "内容", "清单只读；启用下载需已确认再分发权", []string{"character_id", "platform", "version"}, []string{"character_id", "platform", "version", "release_id", "manifest", "distributable", "published_at"}, nil, []string{"disable_release", "enable_release"}},
	{"character_market_assets", "商店预览", "内容", "封面、头像与音色试听的不可变 OSS 引用；通过验证后的发布工具更新", []string{"character_id"}, []string{"character_id", "data", "updated_at"}, nil, nil},
	{"support_tickets", "反馈工单", "运营", "查看反馈并标记处理状态", []string{"id"}, []string{"id", "user_id", "category", "content", "state", "created_at", "version"}, []string{"state"}, nil},
	{"identities", "登录身份", "系统", "身份关联，只读；不显示认证令牌", []string{"provider", "subject"}, []string{"provider", "subject", "user_id", "verified_at"}, nil, nil},
	{"account_handles", "星夜号历史", "系统", "永久保留分配历史与唯一性", []string{"handle"}, []string{"handle", "user_id", "assigned_at", "retired_at"}, nil, nil},
	{"account_avatars", "头像存储", "系统", "预览当前账户头像及格式、版本与校验信息", []string{"user_id"}, []string{"user_id", "content_type", "sha256", "updated_at"}, nil, nil},
	{"account_clocks", "同步时钟", "系统", "每账户已提交的变更位置", []string{"user_id"}, []string{"user_id", "revision"}, nil, nil},
	{"changes", "同步变更", "系统", "只读；直接删除会破坏离线同步", []string{"user_id", "revision"}, []string{"user_id", "revision", "kind", "resource_id", "deleted", "data", "occurred_at"}, nil, nil},
	{"conversation_resets", "重置收据", "系统", "阻止旧设备恢复已删除内容", []string{"user_id", "character_id", "reset_id"}, []string{"user_id", "character_id", "reset_id", "version", "cleared_at"}, nil, nil},
	{"goal_turns", "目标提交记录", "系统", "目标进度的幂等账本", []string{"user_id", "character_id", "request_id"}, []string{"user_id", "character_id", "request_id", "config_version", "created_at"}, nil, nil},
	{"admin_users", "管理员", "管理", "独立权限与会话撤销；至少保留一名启用的 owner", []string{"id"}, []string{"id", "username", "role", "disabled", "session_epoch", "version", "created_at"}, []string{"role", "disabled"}, []string{"reset_password"}},
	{"admin_audit", "操作记录", "管理", "不可修改的操作意图与执行结果", []string{"id"}, []string{"id", "actor_id", "actor_name", "action", "resource", "target", "outcome", "request_id", "occurred_at"}, nil, nil},
	{"admin_conversation_stats", "会话消息统计", "对话", "当前账户归档的消息计数；事务内维护，不与 AI 上下文条数相加", []string{"user_id", "character_id"}, []string{"user_id", "character_id", "messages", "user_messages", "ai_messages"}, nil, nil},
}

func resource(id string) (Resource, bool) {
	for _, r := range Resources {
		if r.ID == id {
			return r, true
		}
	}
	return Resource{}, false
}
