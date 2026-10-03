package admin

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"math/big"
	"net/url"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/gukaifeng/starrynight-server/internal/billing"
)

type billReport struct {
	Status      string              `json:"status"`
	Month       string              `json:"month"`
	Product     string              `json:"product"`
	View        string              `json:"view"`
	Bucket      string              `json:"bucket,omitempty"`
	Source      string              `json:"credential_source,omitempty"`
	FetchedAt   time.Time           `json:"fetched_at"`
	Cached      bool                `json:"cached"`
	Rows        []map[string]string `json:"rows"`
	Totals      []map[string]string `json:"totals"`
	Next        string              `json:"next"`
	TotalCount  int                 `json:"total_count"`
	Error       *billing.Error      `json:"error,omitempty"`
	Permissions []string            `json:"permissions"`
	Complete    bool                `json:"complete,omitempty"`
	Granularity string              `json:"granularity,omitempty"`
	StartDate   string              `json:"start_date,omitempty"`
	EndDate     string              `json:"end_date,omitempty"`
}

func billingMonth(value string, now time.Time, months int) bool {
	month, err := time.Parse("2006-01", value)
	if err != nil {
		return false
	}
	local := now.In(time.FixedZone("Asia/Shanghai", 8*3600))
	latest := time.Date(local.Year(), local.Month(), 1, 0, 0, 0, 0, time.UTC)
	return !month.After(latest) && !month.Before(latest.AddDate(0, -months+1, 0))
}

// Only documented billing fields can leave the server. Never forward arbitrary
// upstream extensions, account credentials, or signed URLs to the browser.
var billFields = []string{"ProductCode", "PipCode", "ProductName", "ProductDetail", "ProductType", "CommodityCode", "Currency", "Item", "SubscriptionType", "BillingDate", "SplitBillingDate", "Region", "Zone", "Tag", "CostUnit", "ResourceGroup", "InstanceID", "SplitItemID", "SplitItemName", "BillingItem", "BillingItemCode", "Usage", "UsageUnit", "ListPrice", "ListPriceUnit", "PretaxAmount", "PretaxGrossAmount", "AfterDiscountAmount", "InvoiceDiscount", "DeductedByCashCoupons", "DeductedByResourcePackage", "DeductedByPrepaidCard", "PaymentAmount", "OutstandingAmount"}

func billRows(raw json.RawMessage) ([]map[string]string, error) {
	raw = bytes.TrimSpace(raw)
	rows := []map[string]string{}
	if len(raw) == 0 || string(raw) == "null" {
		return rows, nil
	}
	if raw[0] == '{' {
		var wrapper struct {
			Item json.RawMessage `json:"Item"`
		}
		if err := json.Unmarshal(raw, &wrapper); err != nil {
			return nil, err
		}
		raw = bytes.TrimSpace(wrapper.Item)
		if len(raw) == 0 || string(raw) == "null" {
			return rows, nil
		}
	}
	var input []map[string]json.RawMessage
	if err := json.Unmarshal(raw, &input); err != nil {
		return nil, err
	}
	for _, item := range input {
		row := map[string]string{}
		for _, field := range billFields {
			v := item[field]
			if len(v) == 0 || string(v) == "null" {
				continue
			}
			var value string
			if v[0] == '"' {
				if json.Unmarshal(v, &value) != nil {
					continue
				}
			} else {
				var n json.Number
				if json.Unmarshal(v, &n) != nil {
					continue
				}
				value = n.String()
			}
			row[field] = value
		}
		if row["Currency"] == "" {
			row["Currency"] = "未标明"
		}
		rows = append(rows, row)
	}
	return rows, nil
}

// Decimal arithmetic preserves small official amounts and keeps currencies apart.
func billTotals(rows []map[string]string) []map[string]string {
	fields := []string{"PretaxAmount", "PaymentAmount", "OutstandingAmount", "DeductedByCashCoupons"}
	totals := []map[string]string{}
	groups := map[string]map[string]*big.Rat{}
	for _, row := range rows {
		currency := row["Currency"]
		if groups[currency] == nil {
			groups[currency] = map[string]*big.Rat{}
			totals = append(totals, map[string]string{"Currency": currency})
		}
		for _, field := range fields {
			if n, ok := new(big.Rat).SetString(row[field]); ok {
				if groups[currency][field] == nil {
					groups[currency][field] = new(big.Rat)
				}
				groups[currency][field].Add(groups[currency][field], n)
			}
		}
	}
	for _, total := range totals {
		for _, field := range fields {
			if n := groups[total["Currency"]][field]; n != nil {
				v := strings.TrimRight(strings.TrimRight(n.FloatString(18), "0"), ".")
				if v == "-0" {
					v = "0"
				}
				total[field] = v
			}
		}
	}
	return totals
}

func (s *Server) bills(c *gin.Context) {
	if c.MustGet("admin").(Principal).Role != "owner" {
		c.JSON(403, gin.H{"error": "只有主管理员可以查看云服务费用。"})
		return
	}
	month, product, view := c.Query("month"), c.DefaultQuery("product", "bailian"), c.DefaultQuery("view", "overview")
	months := 18
	if view == "bucket" {
		months = 12
	}
	if !billingMonth(month, time.Now(), months) || (product != "bailian" && product != "oss") || (view != "overview" && view != "details" && view != "bucket") || view == "bucket" && product != "oss" {
		c.JSON(400, gin.H{"error": "请选择有效账期、百炼或 OSS。普通账单支持近 18 个月，Bucket 分账支持近 12 个月。"})
		return
	}
	params := url.Values{"BillingCycle": {month}}
	action := "QueryBillOverview"
	code := "sfm"
	if s.Config.Billing != nil {
		code = s.Config.Billing.BailianCode
	}
	if product == "oss" {
		code = "oss"
	}
	params.Set("ProductCode", code)
	if view != "overview" {
		action = "DescribeInstanceBill"
		params.Set("IsBillingItem", "true")
		params.Set("MaxResults", "100")
		params.Set("Granularity", "MONTHLY")
		if cursor := c.Query("cursor"); cursor != "" {
			if len(cursor) > 4096 {
				c.JSON(400, gin.H{"error": "账单分页参数无效。"})
				return
			}
			params.Set("NextToken", cursor)
		}
		if date := c.Query("date"); date != "" {
			d, err := time.Parse("2006-01-02", date)
			if err != nil || d.Format("2006-01") != month {
				c.JSON(400, gin.H{"error": "日期必须属于所选账期。"})
				return
			}
			params.Set("Granularity", "DAILY")
			params.Set("BillingDate", date)
		}
	}
	bucket := ""
	if view == "bucket" {
		action = "DescribeSplitItemBill"
		params.Del("IsBillingItem")
		if s.Config.Signer != nil {
			bucket = s.Config.Signer.Bucket
		}
		if bucket == "" {
			c.JSON(400, gin.H{"error": "尚未配置项目 Bucket，无法查询 Bucket 分账。"})
			return
		}
		params.Set("SplitItemID", bucket)
	}
	r := billReport{Status: "unavailable", Month: month, Product: product, View: view, Bucket: bucket, FetchedAt: time.Now().UTC(), Rows: []map[string]string{}, Totals: []map[string]string{}, Permissions: billing.Permissions}
	if s.Config.Billing != nil {
		r.Source = s.Config.Billing.Source
	}
	digest := sha256.Sum256([]byte(action + "?" + params.Encode()))
	key := s.RedisPrefix + "admin:billing:" + hex.EncodeToString(digest[:])
	if cached, err := s.Cache.Get(c.Request.Context(), key).Bytes(); err == nil && json.Unmarshal(cached, &r) == nil {
		r.Cached = true
		c.JSON(200, r)
		return
	}
	data, err := s.Config.Billing.Query(c.Request.Context(), action, params)
	if err != nil {
		if c.Request.Context().Err() != nil {
			return
		}
		var problem *billing.Error
		if !errors.As(err, &problem) {
			problem = &billing.Error{Code: "QueryFailed", Message: "费用查询暂时不可用，请稍后重试。"}
		}
		r.Error = problem
		c.JSON(200, r)
		return
	}
	r.Rows, err = billRows(data.Items)
	if err != nil {
		r.Error = &billing.Error{Code: "InvalidItems", Message: "阿里云账单明细格式无法识别。"}
		c.JSON(200, r)
		return
	}
	r.Status = "ready"
	r.Next = data.NextToken
	r.TotalCount = data.TotalCount
	if view == "overview" {
		r.Totals = billTotals(r.Rows)
		r.TotalCount = len(r.Rows)
	}
	if encoded, err := json.Marshal(r); err == nil {
		_ = s.Cache.Set(c.Request.Context(), key, encoded, 5*time.Minute).Err()
	}
	c.JSON(200, r)
}
