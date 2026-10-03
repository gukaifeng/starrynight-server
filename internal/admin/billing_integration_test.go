package admin

import (
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/aliyun/alibabacloud-oss-go-sdk-v2/oss/credentials"
	"github.com/gukaifeng/starrynight-server/internal/assets"
	"github.com/gukaifeng/starrynight-server/internal/billing"
)

type billingTransport func(*http.Request) (*http.Response, error)

func (f billingTransport) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

// The enclosing test uses actual PostgreSQL / Redis sessions and caches, but
// the official provider is replaced at the HTTP boundary: no paid API calls.
func testBillingReports(t *testing.T, app *Server, get func(string) (int, []byte)) {
	t.Helper()
	previous, signer := app.Config.Billing, app.Config.Signer
	defer func() { app.Config.Billing = previous; app.Config.Signer = signer }()
	var calls atomic.Int64
	app.Config.Billing = &billing.Client{BailianCode: "sfm", Source: "billing", Provider: credentials.NewStaticCredentialsProvider("fixture-id", "fixture-secret"), HTTP: &http.Client{Transport: billingTransport(func(r *http.Request) (*http.Response, error) {
		calls.Add(1)
		q := r.URL.Query()
		payload := `{"Success":true,"Data":{"Items":{"Item":[{"Currency":"CNY","PretaxAmount":0.1,"PaymentAmount":0,"ProductCode":"sfm"}]}}}`
		if q.Get("Action") == "DescribeInstanceBill" {
			if q.Get("MaxResults") != "100" || q.Get("IsBillingItem") != "true" {
				t.Error("billing page is unbounded or not itemized")
			}
			payload = `{"Success":true,"Data":{"Items":[{"Currency":"CNY","InstanceID":"1;llm-fixture;qwen-max;input_token;app;0","Usage":"123","PretaxAmount":0.000001}],"NextToken":"a+b/=","TotalCount":2}}`
			if q.Get("NextToken") == "a+b/=" {
				payload = `{"Success":true,"Data":{"Items":[{"Currency":"CNY","PretaxAmount":-0.01}],"TotalCount":2}}`
			}
		} else if q.Get("Action") == "DescribeSplitItemBill" {
			if q.Get("SplitItemID") != "fixture-bucket" || q.Get("ProductCode") != "oss" {
				t.Error("project bucket filter missing")
			}
			payload = `{"Success":true,"Data":{"Items":[{"Currency":"CNY","SplitItemID":"fixture-bucket","PretaxAmount":0.01}],"TotalCount":1}}`
		} else if q.Get("ProductCode") == "oss" {
			return &http.Response{StatusCode: 400, Body: io.NopCloser(strings.NewReader(`{"Code":"NotAuthorized","Message":"fixture-secret should never appear"}`))}, nil
		}
		return &http.Response{StatusCode: 200, Body: io.NopCloser(strings.NewReader(payload))}, nil
	})}}
	month := time.Now().In(time.FixedZone("Shanghai", 8*3600)).Format("2006-01")
	read := func(path string) billReport {
		t.Helper()
		code, raw := get(path)
		if code != 200 {
			t.Fatalf("billing status %d: %s", code, raw)
		}
		if strings.Contains(string(raw), "fixture-secret") || strings.Contains(string(raw), "AccessKeyId") {
			t.Fatal("credentials exposed")
		}
		var report billReport
		if err := json.Unmarshal(raw, &report); err != nil {
			t.Fatal(err)
		}
		return report
	}
	base := "/billing?month=" + month
	one := read(base)
	if one.Status != "ready" || one.Totals[0]["PretaxAmount"] != "0.1" || one.Cached {
		t.Fatal("invalid official summary")
	}
	two := read(base)
	if !two.Cached || calls.Load() != 1 {
		t.Fatal("Redis bill cache not used")
	}
	page := read(base + "&view=details")
	if page.Next != "a+b/=" || page.TotalCount != 2 || len(page.Totals) != 0 {
		t.Fatal("page mistaken for full month")
	}
	page = read(base + "&view=details&cursor=a%2Bb%2F%3D")
	if page.Next != "" || page.Rows[0]["PretaxAmount"] != "-0.01" {
		t.Fatal("cursor or refund lost")
	}
	if code, _ := get(base + "&view=details&date=2000-01-01"); code != 400 {
		t.Fatal("wrong date accepted")
	}
	app.Config.Signer = &assets.Signer{Bucket: "fixture-bucket"}
	page = read(base + "&product=oss&view=bucket")
	if page.Bucket != "fixture-bucket" || page.Rows[0]["SplitItemID"] != "fixture-bucket" {
		t.Fatal("bucket scope missing")
	}
	denied := read(base + "&product=oss")
	if denied.Status != "unavailable" || denied.Error.Code != "NotAuthorized" || len(denied.Totals) != 0 {
		t.Fatal("permission denied displayed as zero")
	}
	before := calls.Load()
	read(base + "&product=oss")
	if calls.Load() != before+1 {
		t.Fatal("permission failures must not be cached")
	}
	testBillingAnalysis(t, app, get)
}
