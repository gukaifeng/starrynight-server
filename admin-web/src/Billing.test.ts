import { describe, expect, it } from "vitest";
import { csv, modelInfo, money, months } from "./Billing";

describe("official bill presentation", () => {
  it("retains small charges and separates unavailable amounts", () => {
    expect(money("0.0000001", "CNY")).toBe("0.0000001 CNY");
    expect(money("-1.2", "USD")).toBe("-1.2 USD");
    expect(money(undefined, "CNY")).toBe("—");
  });
  it("uses the Shanghai billing month at UTC boundaries", () => {
    const list = months(new Date("2026-09-30T17:00:00Z"));
    expect(list[0]).toBe("2026-10"); expect(list.at(-1)).toBe("2025-05");
  });
  it("parses documented inference IDs and preserves other formats", () => {
    expect(modelInfo("123;llm-demo;qwen-max;output_token;app;0")?.model).toBe("qwen-max");
    expect(modelInfo(";llm-demo;qwen-max;input_token;bmp;0")?.key).toBe("");
    expect(modelInfo("ws-demo!cn-beijing!training-job")).toBeNull();
  });
  it("exports official decimals and neutralizes spreadsheet formulas", () => {
    const result = csv([{ ProductName: "=HYPERLINK(\"https://invalid\")", PretaxAmount: "0.000001", Currency: "CNY" }]);
    expect(result).toContain("'="); expect(result).toContain('"0.000001"');
    expect(result.startsWith("\uFEFF")).toBe(true);
  });
});
