package admin

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/url"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/gukaifeng/starrynight-server/internal/billing"
)

const analysisMaxRows = 10000
const analysisMaxQueries = 100

func analysisDates(month, date, grain string, now time.Time) ([]string, bool) {
	first, err := time.Parse("2006-01", month)
	if err != nil || (grain != "monthly" && grain != "daily") {
		return nil, false
	}
	if date != "" {
		d, err := time.Parse("2006-01-02", date)
		if err != nil || d.Format("2006-01") != month || date > now.In(time.FixedZone("Shanghai", 8*3600)).Format("2006-01-02") {
			return nil, false
		}
		return []string{date}, true
	}
	if grain == "monthly" {
		return []string{""}, true
	}
	last := first.AddDate(0, 1, -1).Format("2006-01-02")
	today := now.In(time.FixedZone("Shanghai", 8*3600)).Format("2006-01-02")
	if today < last {
		last = today
	}
	dates := []string{}
	for d := first; d.Format("2006-01-02") <= last; d = d.AddDate(0, 0, 1) {
		dates = append(dates, d.Format("2006-01-02"))
	}
	return dates, len(dates) > 0
}

func analysisProblem(code, message string) error {
	return &billing.Error{Code: code, Message: message}
}

// No partial month can be returned as a complete analysis. Follow every
// cursor, fail closed on limits/repeated cursors/count changes, and discard
// accumulated rows if any page fails. Successful individual days are cached
// so retrying a long daily query can resume without reading them again.
func (s *Server) analysisRows(ctx context.Context, params url.Values, budget *int) (billReport, error) {
	digest := sha256.Sum256([]byte(params.Encode()))
	key := s.RedisPrefix + "admin:billing:analysis:v1:" + hex.EncodeToString(digest[:])
	var result billReport
	if raw, err := s.Cache.Get(ctx, key).Bytes(); err == nil && json.Unmarshal(raw, &result) == nil && result.Complete {
		result.Cached = true
		return result, nil
	}
	result = billReport{Rows: []map[string]string{}, FetchedAt: time.Now().UTC()}
	seen := map[string]bool{}
	count := -1
	for {
		if *budget <= 0 {
			return billReport{}, analysisProblem("AnalysisLimit", "账单明细较多，已达到单次统计的查询上限。请选择具体日期后重试。")
		}
		*budget -= 1
		data, err := s.Config.Billing.Query(ctx, "DescribeInstanceBill", params)
		if err != nil {
			return billReport{}, err
		}
		rows, err := billRows(data.Items)
		if err != nil {
			return billReport{}, analysisProblem("InvalidItems", "阿里云账单明细格式无法识别，统计未完成。")
		}
		if len(result.Rows)+len(rows) > analysisMaxRows || data.TotalCount > analysisMaxRows {
			return billReport{}, analysisProblem("AnalysisLimit", "账单超过单次统计的 10,000 条上限。请选择具体日期后重试。")
		}
		if count >= 0 && data.TotalCount != count {
			return billReport{}, analysisProblem("BillChanged", "读取期间账单条数发生变化，统计未完成，请刷新重试。")
		}
		count = data.TotalCount
		for _, row := range rows {
			if date := params.Get("BillingDate"); date != "" {
				row["BillingDate"] = date
			}
		}
		result.Rows = append(result.Rows, rows...)
		if data.NextToken == "" {
			if count > 0 && count != len(result.Rows) {
				return billReport{}, analysisProblem("IncompleteBill", "阿里云返回的明细条数与总数不一致，统计未完成，请刷新重试。")
			}
			break
		}
		if len(rows) == 0 || seen[data.NextToken] {
			return billReport{}, analysisProblem("InvalidCursor", "阿里云账单分页未能继续，统计未完成，请刷新重试。")
		}
		seen[data.NextToken] = true
		params.Set("NextToken", data.NextToken)
	}
	result.Complete = true
	result.TotalCount = len(result.Rows)
	result.FetchedAt = time.Now().UTC()
	if raw, err := json.Marshal(result); err == nil {
		_ = s.Cache.Set(ctx, key, raw, 5*time.Minute).Err()
	}
	return result, nil
}

func (s *Server) billAnalysis(c *gin.Context) {
	if c.MustGet("admin").(Principal).Role != "owner" {
		c.JSON(403, gin.H{"error": "只有主管理员可以查看云服务费用。"})
		return
	}
	month, date, grain := c.Query("month"), c.Query("date"), c.DefaultQuery("granularity", "monthly")
	if date != "" {
		grain = "daily"
	}
	dates, valid := analysisDates(month, date, grain, time.Now())
	if !valid || !billingMonth(month, time.Now(), 18) || c.Query("cursor") != "" {
		c.JSON(400, gin.H{"error": "请选择近 18 个月的账期及有效日期，统计不接受分页参数。"})
		return
	}
	code := "sfm"
	if s.Config.Billing != nil {
		code = s.Config.Billing.BailianCode
	}
	r := billReport{Status: "unavailable", Month: month, Product: "bailian", View: "analysis", Granularity: grain, FetchedAt: time.Now().UTC(), Rows: []map[string]string{}, Totals: []map[string]string{}, Permissions: billing.Permissions, Cached: true}
	if s.Config.Billing != nil {
		r.Source = s.Config.Billing.Source
	}
	if grain == "daily" {
		r.StartDate, r.EndDate = dates[0], dates[len(dates)-1]
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 60*time.Second)
	defer cancel()
	budget := analysisMaxQueries
	for _, day := range dates {
		params := url.Values{"BillingCycle": {month}, "ProductCode": {code}, "MaxResults": {"100"}, "IsBillingItem": {"true"}, "Granularity": {"MONTHLY"}}
		if day != "" {
			params.Set("Granularity", "DAILY")
			params.Set("BillingDate", day)
		}
		part, err := s.analysisRows(ctx, params, &budget)
		if err == nil && len(r.Rows)+len(part.Rows) > analysisMaxRows {
			err = analysisProblem("AnalysisLimit", "所选范围超过 10,000 条明细。请选择具体日期后重试。")
		}
		if err != nil {
			if c.Request.Context().Err() != nil {
				return
			}
			var problem *billing.Error
			if !errors.As(err, &problem) {
				problem = &billing.Error{Code: "AnalysisTimeout", Message: "完整账单统计未能在 60 秒内完成。请选择具体日期，或稍后刷新重试。"}
			}
			r.Rows, r.Cached, r.Error = []map[string]string{}, false, problem
			c.JSON(200, r)
			return
		}
		r.Rows = append(r.Rows, part.Rows...)
		r.Cached = r.Cached && part.Cached
		if part.FetchedAt.Before(r.FetchedAt) {
			r.FetchedAt = part.FetchedAt
		}
	}
	r.Status, r.Complete = "ready", true
	r.TotalCount = len(r.Rows)
	r.Totals = billTotals(r.Rows)
	c.JSON(200, r)
}
