package admin

import (
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func testBillingAnalysis(t *testing.T, app *Server, get func(string) (int, []byte)) {
	t.Helper()
	var calls atomic.Int64
	mode := "ready"
	app.Config.Billing.HTTP = &http.Client{Transport: billingTransport(func(r *http.Request) (*http.Response, error) {
		calls.Add(1)
		q := r.URL.Query()
		if q.Get("Granularity") == "DAILY" && q.Get("BillingDate") == "" {
			t.Error("daily analysis requires explicit date")
		}
		payload := `{"Success":true,"Data":{"Items":[{"Currency":"CNY","InstanceID":"1;ws;model;input_token;app;0","PretaxAmount":0.1,"Tag":"key:project value:fixture"}],"NextToken":"second-page","TotalCount":2}}`
		if q.Get("NextToken") != "" {
			payload = `{"Success":true,"Data":{"Items":[{"Currency":"CNY","PretaxAmount":0.2}],"TotalCount":2}}`
		}
		switch mode {
		case "denied":
			if q.Get("NextToken") != "" {
				payload = `{"Success":false,"Code":"NotAuthorized","Message":"fixture-secret"}`
			}
		case "loop":
			payload = `{"Success":true,"Data":{"Items":[{"Currency":"CNY","PretaxAmount":0.1}],"NextToken":"second-page","TotalCount":2}}`
		case "limit":
			payload = `{"Success":true,"Data":{"Items":[],"TotalCount":10001}}`
		case "count-changed":
			if q.Get("NextToken") != "" {
				payload = `{"Success":true,"Data":{"Items":[{"Currency":"CNY","PretaxAmount":0.2}],"TotalCount":3}}`
			}
		}
		return &http.Response{StatusCode: 200, Body: io.NopCloser(strings.NewReader(payload))}, nil
	})}
	month := time.Now().In(time.FixedZone("Shanghai", 8*3600)).Format("2006-01")
	base := "/billing/analysis?month=" + month
	read := func(path string) billReport {
		t.Helper()
		code, raw := get(path)
		if code != 200 || strings.Contains(string(raw), "fixture-secret") {
			t.Fatalf("bad analysis status: %d", code)
		}
		var report billReport
		if err := json.Unmarshal(raw, &report); err != nil {
			t.Fatal(err)
		}
		return report
	}
	t.Run("complete_all_pages_and_Redis_cache", func(t *testing.T) {
		app.Config.Billing.BailianCode = "analysis-fixture-complete"
		one := read(base)
		if !one.Complete || one.Status != "ready" || one.TotalCount != 2 || one.Totals[0]["PretaxAmount"] != "0.3" || one.Rows[0]["Tag"] == "" || calls.Load() != 2 {
			t.Fatal("full month must cover every page and exact amounts")
		}
		two := read(base)
		if !two.Cached || calls.Load() != 2 {
			t.Fatal("complete report must be cached in Redis")
		}
	})
	t.Run("daily_range_and_dates", func(t *testing.T) {
		one := read(base + "&date=" + month + "-01")
		if !one.Complete || one.Granularity != "daily" || one.Rows[0]["BillingDate"] != month+"-01" || one.EndDate != month+"-01" {
			t.Fatal("daily statistics scope missing")
		}
	})
	for _, failure := range []struct{ mode, code string }{{"denied", "NotAuthorized"}, {"loop", "InvalidCursor"}, {"limit", "AnalysisLimit"}, {"count-changed", "BillChanged"}} {
		t.Run(failure.mode+"_must_not_publish_partial_totals", func(t *testing.T) {
			mode = failure.mode
			app.Config.Billing.BailianCode = "analysis-fixture-" + mode
			one := read(base)
			if one.Status != "unavailable" || one.Complete || len(one.Rows) != 0 || len(one.Totals) != 0 || one.Error == nil || one.Error.Code != failure.code {
				t.Fatal("partial analysis must never look complete")
			}
			before := calls.Load()
			mode = "ready"
			two := read(base)
			if !two.Complete || calls.Load() <= before {
				t.Fatal("failed statistics must not be cached")
			}
		})
	}
	for _, suffix := range []string{"&granularity=weekly", "&date=2000-01-01", "&cursor=untrusted"} {
		if code, _ := get(base + suffix); code != 400 {
			t.Fatal("invalid analytics scope accepted")
		}
	}
}
