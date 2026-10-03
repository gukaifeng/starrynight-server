package admin

import (
	"testing"
	"time"
)

func TestAnalysisDates(t *testing.T) {
	now := time.Date(2026, 9, 30, 17, 0, 0, 0, time.UTC) // Oct 1 in Shanghai
	days, ok := analysisDates("2026-10", "", "daily", now)
	if !ok || len(days) != 1 || days[0] != "2026-10-01" {
		t.Fatal("daily range must stop at Beijing today")
	}
	days, ok = analysisDates("2024-02", "", "daily", now)
	if !ok || len(days) != 29 || days[28] != "2024-02-29" {
		t.Fatal("leap month lost")
	}
	for _, test := range [][3]string{{"2026-10", "2026-09-01", "daily"}, {"2026-10", "2026-10-02", "daily"}, {"2026-10", "2026-10-32", "daily"}, {"2026-10", "", "weekly"}} {
		if _, ok := analysisDates(test[0], test[1], test[2], now); ok {
			t.Fatalf("invalid range accepted: %v", test)
		}
	}
}
