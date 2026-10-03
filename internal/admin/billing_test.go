package admin

import (
	"encoding/json"
	"testing"
	"time"
)

func TestBillAmountsCurrenciesAndProviderFields(t *testing.T) {
	rows, err := billRows(json.RawMessage(`{"Item":[{"Currency":"CNY","PretaxAmount":0.1,"PaymentAmount":"0.0000001","AccessKeySecret":"never-export"},{"Currency":"CNY","PretaxAmount":"0.2"},{"Currency":"CNY","PretaxAmount":"-0.05","PaymentAmount":0},{"Currency":"USD","PretaxAmount":9}]}`))
	if err != nil || len(rows) != 4 || rows[0]["AccessKeySecret"] != "" || rows[0]["PaymentAmount"] != "0.0000001" {
		t.Fatal("lost precision or field allowlist")
	}
	totals := billTotals(rows)
	if len(totals) != 2 || totals[0]["PretaxAmount"] != "0.25" || totals[0]["PaymentAmount"] != "0.0000001" || totals[1]["PretaxAmount"] != "9" {
		t.Fatalf("incorrect money totals: %v", totals)
	}
	if _, present := totals[1]["PaymentAmount"]; present {
		t.Fatal("unknown amount turned into zero")
	}
	if rows, err = billRows(json.RawMessage(`[]`)); err != nil || len(rows) != 0 {
		t.Fatal("empty bill not preserved")
	}
	if _, err = billRows(json.RawMessage(`{"Item":"invalid"}`)); err == nil {
		t.Fatal("invalid bill appeared successful")
	}
}

func TestBillingMonthsUseShanghaiAndProviderWindows(t *testing.T) {
	now := time.Date(2026, 9, 30, 17, 0, 0, 0, time.UTC)
	for _, test := range []struct {
		month  string
		window int
		valid  bool
	}{{"2026-10", 18, true}, {"2025-05", 18, true}, {"2025-04", 18, false}, {"2026-11", 18, false}, {"2026-00", 18, false}, {"2025-10", 12, false}, {"2025-11", 12, true}} {
		if billingMonth(test.month, now, test.window) != test.valid {
			t.Fatalf("wrong period %s/%d", test.month, test.window)
		}
	}
}
