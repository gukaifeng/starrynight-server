package billing

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/url"
	"strings"
	"testing"

	"github.com/aliyun/alibabacloud-oss-go-sdk-v2/oss/credentials"
)

type transportFunc func(*http.Request) (*http.Response, error)

func (f transportFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func TestRPCOfficialSignatureExample(t *testing.T) {
	// Published testid/testsecret vector from Alibaba Cloud's signature guide.
	q := url.Values{"Timestamp": {"2016-02-23T12:46:24Z"}, "Format": {"XML"}, "AccessKeyId": {"testid"}, "Action": {"DescribeRegions"}, "SignatureMethod": {"HMAC-SHA1"}, "SignatureNonce": {"3ee8c1b8-83d3-44af-a94f-4e0ad82fd6cf"}, "Version": {"2014-05-26"}, "SignatureVersion": {"1.0"}}
	if got := signature(q, "testsecret"); got != "OLeaidS1JvxuMvnyHOwuJ+uX5qY=" {
		t.Fatalf("official RPC vector mismatch: %s", got)
	}
}

func TestQuerySignsTemporaryCredentialsAndPreservesAmounts(t *testing.T) {
	params := url.Values{"BillingCycle": {"2026-10"}, "NextToken": {"a+b/=中"}}
	c := &Client{Provider: credentials.NewStaticCredentialsProvider("fixture-id", "fixture-secret", "fixture-token"), HTTP: &http.Client{Transport: transportFunc(func(r *http.Request) (*http.Response, error) {
		q := r.URL.Query()
		if r.URL.Host != "business.aliyuncs.com" || r.Method != "GET" || q.Get("Action") != "DescribeInstanceBill" || q.Get("SecurityToken") != "fixture-token" || q.Get("NextToken") != "a+b/=中" {
			t.Fatal("wrong endpoint or signed parameters")
		}
		sig := q.Get("Signature")
		q.Del("Signature")
		if signature(q, "fixture-secret") != sig || q.Get("SignatureNonce") == "" {
			t.Fatal("invalid signature")
		}
		return &http.Response{StatusCode: 200, Body: io.NopCloser(strings.NewReader(`{"Success":true,"Data":{"Items":[{"PretaxAmount":0.000000123}],"NextToken":"next","TotalCount":2}}`))}, nil
	})}}
	result, err := c.Query(context.Background(), "DescribeInstanceBill", params)
	if err != nil || result.NextToken != "next" || !strings.Contains(string(result.Items), "0.000000123") {
		t.Fatalf("lost provider data: %v", err)
	}
	if params.Get("Signature") != "" || params.Get("AccessKeyId") != "" {
		t.Fatal("mutated caller parameters")
	}
}

func TestErrorsDoNotExposeCredentialsAndNoWrites(t *testing.T) {
	c := &Client{Provider: credentials.NewStaticCredentialsProvider("fixture-id", "fixture-secret"), HTTP: &http.Client{Transport: transportFunc(func(r *http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: 400, Body: io.NopCloser(strings.NewReader(`{"Code":"NotAuthorized","Message":"fixture-secret must not escape","RequestId":"fixture-request"}`))}, nil
	})}}
	_, err := c.Query(context.Background(), "QueryBillOverview", url.Values{})
	var problem *Error
	if !errors.As(err, &problem) || problem.Code != "NotAuthorized" || problem.RequestID != "fixture-request" || strings.Contains(problem.Message, "fixture-secret") {
		t.Fatal("unsafe permission error")
	}
	_, err = c.Query(context.Background(), "CreateInstance", url.Values{})
	if !errors.As(err, &problem) || problem.Code != "InvalidAction" {
		t.Fatal("billing writes not rejected")
	}
	var absent *Client
	_, err = absent.Query(context.Background(), "QueryBillOverview", url.Values{})
	if !errors.As(err, &problem) || problem.Code != "NotConfigured" {
		t.Fatal("missing configuration not reported")
	}
	c.HTTP.Transport = transportFunc(func(r *http.Request) (*http.Response, error) { return nil, errors.New(r.URL.String()) })
	_, err = c.Query(context.Background(), "QueryBillOverview", url.Values{})
	if !errors.As(err, &problem) || strings.Contains(problem.Error()+problem.Message, "fixture-id") || strings.Contains(problem.Message, "Signature") {
		t.Fatal("transport leaked URL")
	}
}

func TestCredentialSelection(t *testing.T) {
	for _, name := range []string{"BILLING_ACCESS_KEY_ID", "BILLING_ACCESS_KEY_SECRET", "BILLING_SECURITY_TOKEN", "BILLING_CREDENTIAL_SOURCE", "OSS_REGION", "OSS_CREDENTIAL_SOURCE", "OSS_ACCESS_KEY_ID", "OSS_ACCESS_KEY_SECRET", "OSS_SESSION_TOKEN"} {
		t.Setenv(name, "")
	}
	c, err := FromEnvironment()
	if err != nil || c.Provider != nil {
		t.Fatal("missing credentials should not disable admin")
	}
	t.Setenv("OSS_ACCESS_KEY_ID", "oss-fixture")
	t.Setenv("OSS_ACCESS_KEY_SECRET", "oss-fixture-secret")
	c, err = FromEnvironment()
	if err != nil || c.Source != "oss" {
		t.Fatal("OSS fallback unavailable")
	}
	t.Setenv("BILLING_ACCESS_KEY_ID", "billing-fixture")
	if _, err = FromEnvironment(); err == nil {
		t.Fatal("partial credentials accepted")
	}
	t.Setenv("BILLING_ACCESS_KEY_SECRET", "billing-fixture-secret")
	t.Setenv("BILLING_SECURITY_TOKEN", "temporary-token")
	c, err = FromEnvironment()
	if err != nil || c.Source != "billing" {
		t.Fatal("dedicated credentials not preferred")
	}
	cred, err := c.Provider.GetCredentials(context.Background())
	if err != nil || cred.SecurityToken != "temporary-token" {
		t.Fatal("temporary token lost")
	}
}
