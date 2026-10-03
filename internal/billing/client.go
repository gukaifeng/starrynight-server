// Package billing reads official Alibaba Cloud BSS bills, without model calls,
// price estimates, account mutations, or undocumented console APIs.
package billing

import (
	"context"
	"crypto/hmac"
	"crypto/sha1"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/aliyun/alibabacloud-oss-go-sdk-v2/oss/credentials"
	"github.com/google/uuid"
)

const Endpoint = "https://business.aliyuncs.com/"

var Permissions = []string{"bss:DescribeBillList", "bssapi:DescribeInstanceBill", "bssapi:DescribeSplitItemBill"}

type Client struct {
	Provider    credentials.CredentialsProvider
	HTTP        *http.Client
	Source      string
	BailianCode string
	paceMu      sync.Mutex
	nextRequest time.Time
}
type Error struct {
	Code      string `json:"code"`
	RequestID string `json:"request_id,omitempty"`
	Message   string `json:"message"`
}

func (e *Error) Error() string { return e.Code } // Never log signed URLs or credentials.

func FromEnvironment() (*Client, error) {
	c := &Client{HTTP: &http.Client{Timeout: 15 * time.Second}, BailianCode: "sfm"}
	if code := os.Getenv("BILLING_BAILIAN_PRODUCT_CODE"); code != "" {
		c.BailianCode = code
	}
	id, secret, token := os.Getenv("BILLING_ACCESS_KEY_ID"), os.Getenv("BILLING_ACCESS_KEY_SECRET"), os.Getenv("BILLING_SECURITY_TOKEN")
	if id != "" || secret != "" {
		if id == "" || secret == "" {
			return nil, errors.New("billing AccessKey ID and secret must be configured together")
		}
		c.Provider = credentials.NewStaticCredentialsProvider(id, secret, token)
		c.Source = "billing"
	} else if os.Getenv("BILLING_CREDENTIAL_SOURCE") == "ecs" || os.Getenv("OSS_REGION") != "" && (os.Getenv("OSS_CREDENTIAL_SOURCE") == "ecs" || os.Getenv("OSS_CREDENTIAL_SOURCE") == "") {
		c.Provider = credentials.NewEcsRoleCredentialsProvider()
		c.Source = "ecs"
	} else if os.Getenv("OSS_ACCESS_KEY_ID") != "" && os.Getenv("OSS_ACCESS_KEY_SECRET") != "" {
		c.Provider = credentials.NewEnvironmentVariableCredentialsProvider()
		c.Source = "oss"
	}
	return c, nil
}

// BSS 2017-12-14 uses the documented RPC HMAC-SHA1 signature. The official
// OSS SDK provider refreshes temporary credentials for STS / ECS roles.
func signature(q url.Values, secret string) string {
	encode := func(s string) string { return strings.ReplaceAll(url.QueryEscape(s), "+", "%20") }
	canonical := strings.ReplaceAll(q.Encode(), "+", "%20")
	h := hmac.New(sha1.New, []byte(secret+"&"))
	h.Write([]byte("GET&%2F&" + encode(canonical)))
	return base64.StdEncoding.EncodeToString(h.Sum(nil))
}

type Data struct {
	Items      json.RawMessage `json:"Items"`
	NextToken  string          `json:"NextToken"`
	TotalCount int             `json:"TotalCount"`
}

func (c *Client) Query(ctx context.Context, action string, params url.Values) (Data, error) {
	if c == nil || c.Provider == nil {
		return Data{}, &Error{Code: "NotConfigured", Message: "尚未配置具有账单读取权限的阿里云凭据。"}
	}
	if action != "QueryBillOverview" && action != "DescribeInstanceBill" && action != "DescribeSplitItemBill" {
		return Data{}, &Error{Code: "InvalidAction", Message: "仅允许读取费用账单。"}
	}
	// DescribeInstanceBill has an account limit of 10 requests/second. Keep
	// this process below it, including concurrent summaries and analytics.
	c.paceMu.Lock()
	now := time.Now()
	start := c.nextRequest
	if start.Before(now) {
		start = now
	}
	c.nextRequest = start.Add(150 * time.Millisecond)
	c.paceMu.Unlock()
	if delay := time.Until(start); delay > 0 {
		timer := time.NewTimer(delay)
		defer timer.Stop()
		select {
		case <-timer.C:
		case <-ctx.Done():
			return Data{}, ctx.Err()
		}
	}
	cred, err := c.Provider.GetCredentials(ctx)
	if err != nil || !cred.HasKeys() || cred.Expired() {
		return Data{}, &Error{Code: "CredentialsUnavailable", Message: "账单查询凭据不可用或已过期。"}
	}
	q := url.Values{}
	for k, v := range params {
		q[k] = append([]string(nil), v...)
	}
	q.Set("Action", action)
	q.Set("Version", "2017-12-14")
	q.Set("Format", "JSON")
	q.Set("AccessKeyId", cred.AccessKeyID)
	q.Set("SignatureMethod", "HMAC-SHA1")
	q.Set("SignatureVersion", "1.0")
	q.Set("SignatureNonce", uuid.NewString())
	q.Set("Timestamp", time.Now().UTC().Format("2006-01-02T15:04:05Z"))
	if cred.SecurityToken != "" {
		q.Set("SecurityToken", cred.SecurityToken)
	}
	q.Set("Signature", signature(q, cred.AccessKeySecret))
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, Endpoint+"?"+q.Encode(), nil)
	if err != nil {
		return Data{}, &Error{Code: "InvalidRequest", Message: "无法构造账单查询请求。"}
	}
	// Do not redirect an AccessKey ID / STS token to a different host.
	httpClient := *c.HTTP
	httpClient.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	resp, err := httpClient.Do(req)
	if err != nil {
		if ctx.Err() != nil {
			return Data{}, ctx.Err()
		}
		return Data{}, &Error{Code: "TransportError", Message: "阿里云账单服务暂时无法连接，请稍后重试。"}
	}
	defer resp.Body.Close()
	var envelope struct {
		Success   bool   `json:"Success"`
		Code      string `json:"Code"`
		RequestID string `json:"RequestId"`
		Data      Data   `json:"Data"`
	}
	if err := json.NewDecoder(io.LimitReader(resp.Body, 8<<20)).Decode(&envelope); err != nil {
		return Data{}, &Error{Code: "InvalidResponse", Message: "阿里云返回了无法识别的账单结果，请稍后重试。"}
	}
	if resp.StatusCode != 200 || !envelope.Success {
		code := envelope.Code
		if code == "" {
			code = "UpstreamError"
		}
		message := "阿里云未能返回账单，请核对账单服务状态后重试。"
		if strings.Contains(strings.ToLower(code), "authoriz") || strings.Contains(strings.ToLower(code), "forbidden") || strings.Contains(strings.ToLower(code), "permission") {
			message = "当前阿里云凭据没有账单读取权限，请为所属 RAM 用户或角色附加账单只读策略。"
		}
		return Data{}, &Error{Code: code, RequestID: envelope.RequestID, Message: message}
	}
	return envelope.Data, nil
}
