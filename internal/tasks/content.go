// Package tasks delivers durable PG jobs through Asynq. Redis is the execution
// transport, not the only record of accepted publication work.
package tasks

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/gukaifeng/starrynight-server/internal/privatecontent"
	"github.com/gukaifeng/starrynight-server/internal/store"
	"github.com/hibiken/asynq"
	"github.com/jackc/pgx/v5"
	"github.com/redis/go-redis/v9"
	"log/slog"
	"time"
)

const taskType = "starry:content:v2"

type ContentWorker struct {
	DB     *store.Store
	Keys   *privatecontent.Keyring
	Client *asynq.Client
	Server *asynq.Server
	Queue  string
}

func New(db *store.Store, k *privatecontent.Keyring, ro *redis.Options, prefix string) *ContentWorker {
	opt := asynq.RedisClientOpt{Addr: ro.Addr, Username: ro.Username, Password: ro.Password, DB: ro.DB, TLSConfig: ro.TLSConfig, DialTimeout: 3 * time.Second, ReadTimeout: 3 * time.Second, WriteTimeout: 3 * time.Second}
	q := prefix + "content-v2"
	return &ContentWorker{db, k, asynq.NewClient(opt), asynq.NewServer(opt, asynq.Config{Concurrency: 2, Queues: map[string]int{q: 1}, ShutdownTimeout: 20 * time.Second, HealthCheckInterval: 10 * time.Second}), q}
}
func (w *ContentWorker) Run(ctx context.Context) error {
	mux := asynq.NewServeMux()
	mux.HandleFunc(taskType, w.handle)
	if e := w.Server.Start(mux); e != nil {
		return e
	}
	defer w.Server.Shutdown()
	defer w.Client.Close()
	tick := time.NewTicker(time.Second)
	defer tick.Stop()
	for {
		if e := w.Dispatch(ctx); e != nil && !errors.Is(e, context.Canceled) {
			slog.Warn("content outbox delivery deferred", "error_type", fmt.Sprintf("%T", e))
		}
		select {
		case <-ctx.Done():
			return nil
		case <-tick.C:
		}
	}
}
func (w *ContentWorker) Dispatch(ctx context.Context) error {
	// Reclaim execution leases after node death, including complete Redis loss.
	_, e := w.DB.Pool.Exec(ctx, `UPDATE content_jobs SET status='retry',retry_at=now(),lease_until=NULL,updated_at=now() WHERE status='running' AND lease_until<now()`)
	if e != nil {
		return e
	}
	rows, e := w.DB.Pool.Query(ctx, `WITH chosen AS (SELECT o.job_id FROM content_outbox o JOIN content_jobs j ON j.id=o.job_id WHERE j.status IN ('pending','retry') AND j.retry_at<=now() AND o.next_attempt_at<=now() ORDER BY j.retry_at,o.job_id FOR UPDATE OF o SKIP LOCKED LIMIT 20) UPDATE content_outbox o SET attempts=attempts+1,next_attempt_at=now()+interval '30 seconds' FROM chosen c WHERE o.job_id=c.job_id RETURNING o.job_id::text,o.attempts`)
	if e != nil {
		return e
	}
	type delivery struct {
		id      string
		attempt int
	}
	ids := []delivery{}
	for rows.Next() {
		var item delivery
		if e = rows.Scan(&item.id, &item.attempt); e != nil {
			rows.Close()
			return e
		}
		ids = append(ids, item)
	}
	e = rows.Err()
	rows.Close()
	if e != nil {
		return e
	}
	for _, item := range ids {
		id := item.id
		payload, _ := json.Marshal(map[string]string{"job_id": id})
		// Stable job identity lives in PG; delivery attempt has its own ID. A
		// retained Redis success cannot suppress recovery of a still-pending job.
		_, e = w.Client.EnqueueContext(ctx, asynq.NewTask(taskType, payload), asynq.Queue(w.Queue), asynq.TaskID(fmt.Sprintf("%s:%d", id, item.attempt)), asynq.MaxRetry(8), asynq.Timeout(45*time.Second), asynq.Retention(15*time.Minute))
		if e != nil && !errors.Is(e, asynq.ErrTaskIDConflict) {
			return e
		}
		if _, e = w.DB.Pool.Exec(ctx, `UPDATE content_outbox SET delivered_at=now() WHERE job_id=$1`, id); e != nil {
			return e
		}
	}
	return nil
}
func (w *ContentWorker) handle(ctx context.Context, t *asynq.Task) error {
	var payload struct {
		ID string `json:"job_id"`
	}
	if json.Unmarshal(t.Payload(), &payload) != nil {
		return asynq.SkipRetry
	}
	var kind, resource string
	var fence int64
	e := w.DB.Pool.QueryRow(ctx, `UPDATE content_jobs SET status='running',fence=fence+1,attempts=attempts+1,lease_until=now()+interval '90 seconds',updated_at=now() WHERE id=$1 AND status IN ('pending','retry') AND retry_at<=now() RETURNING kind,resource_id,fence`, payload.ID).Scan(&kind, &resource, &fence)
	if errors.Is(e, pgx.ErrNoRows) {
		return nil
	}
	if e != nil {
		return e
	}
	switch kind {
	case "validate_setting":
		e = w.DB.ValidateSubmission(ctx, w.Keys, resource)
	default:
		e = errors.New("unsupported content job")
	}
	status := "complete"
	code := ""
	if e != nil {
		status = "retry"
		code = "validation_temporarily_unavailable"
	}
	// A lease owned by another worker cannot be completed by this stale one.
	finish, cancel := context.WithTimeout(context.WithoutCancel(ctx), 3*time.Second)
	defer cancel()
	_, save := w.DB.Pool.Exec(finish, `UPDATE content_jobs SET status=$3,lease_until=NULL,last_error=$4,retry_at=now()+interval '10 seconds',updated_at=now() WHERE id=$1 AND fence=$2 AND status='running'`, payload.ID, fence, status, code)
	if e != nil {
		return e
	}
	return save
}
