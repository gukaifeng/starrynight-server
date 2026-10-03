import { describe, expect, it } from "vitest";
import {
  addDecimal,
  aggregate,
  compareDecimal,
  dimensionValue,
  filterRows,
  groupedCSV,
  modelInfo,
  percent,
  type BillRow,
} from "./BillingAnalysis";

const rows: BillRow[] = [
  {
    Currency: "CNY",
    InstanceID: "1;ws-a;model-a;input_token;app;0",
    PretaxAmount: "0.1",
    Usage: "1000",
    UsageUnit: "Token",
  },
  {
    Currency: "CNY",
    InstanceID: "1;ws-a;model-a;output_token;app;0",
    PretaxAmount: "0.2",
    Usage: "2",
    UsageUnit: "秒",
  },
  {
    Currency: "CNY",
    InstanceID: "2;ws-b;model-b;input_token;bmp;1",
    PretaxAmount: "-0.05",
    Item: "Refund",
    Usage: "10",
    UsageUnit: "Token",
  },
  {
    Currency: "USD",
    InstanceID: "1;ws-a;model-a;input_token;app;0",
    PretaxAmount: "0.0000001",
    Usage: "7",
    UsageUnit: "Token",
  },
];
describe("complete bill analytics", () => {
  it("keeps exact decimals, exponents, tiny charges, and large numbers", () => {
    expect(addDecimal("0.1", "0.2")).toBe("0.3");
    expect(addDecimal("1e-7", "-0.00000009")).toBe("0.00000001");
    expect(addDecimal("9007199254740993.123456789", "0.000000001")).toBe(
      "9007199254740993.12345679",
    );
    expect(compareDecimal("1e-8", "0.000000001")).toBe(1);
    expect(percent("0.1", "0.3")).toBe(33.33);
    expect(percent("0", "0")).toBe(0);
  });
  it("separates currencies and usage units, and preserves refunds", () => {
    const totals = aggregate(rows);
    expect(totals).toHaveLength(2);
    expect(totals[0].amounts.PretaxAmount).toBe("0.25");
    expect(totals[0].positive).toBe("0.3");
    expect(totals[0].refund).toBe("-0.05");
    expect(totals[0].usage).toEqual({ Token: "1010", 秒: "2" });
    expect(totals[1].amounts.PretaxAmount).toBe("0.0000001");
  });
  it("combines filters and two dimensions without losing currency", () => {
    const filtered = filterRows(rows, { key: "1", currency: "CNY" }, "MODEL-A");
    expect(filtered).toHaveLength(2);
    const groups = aggregate(filtered, ["model", "kind"]);
    expect(groups).toHaveLength(2);
    expect(groups[0].values).toEqual(["model-a", "input_token"]);
    expect(groupedCSV(groups, ["model", "kind"])).toContain('"0.1"');
  });
  it("retains unknown schemas and never invents model names or amounts", () => {
    expect(
      dimensionValue({ InstanceID: "ws!cn-beijing!training-job" }, "workspace"),
    ).toBe("ws");
    expect(
      dimensionValue({ InstanceID: "ws!cn-beijing!training-job" }, "model"),
    ).toBe("未提供");
    expect(
      dimensionValue({ InstanceID: ";ws;qwen;input_token;app;0" }, "key"),
    ).toBe("未提供 API Key ID");
    const total = aggregate([{ Currency: "CNY", Usage: "10" }])[0];
    expect(total.amounts.PretaxAmount).toBeUndefined();
    expect(total.missingAmount).toBe(1);
    expect(total.usage).toEqual({});
  });
  it("uses refund-safe shares and escapes group CSV formulas", () => {
    const groups = aggregate(
      [{ Currency: "CNY", ProductDetail: "=danger", PretaxAmount: "-0.1" }],
      ["product"],
    );
    expect(percent(groups[0].positive, groups[0].positive)).toBe(0);
    expect(groupedCSV(groups, ["product"])).toContain("'=danger");
    expect(groupedCSV(groups, ["product"])).toContain("'-0.1");
  });
  it("supports observed five-part inference IDs without guessing the channel", () => {
    const row = {
      InstanceID: "123;llm-fixture;qwen-audio-tts;tts_output_token;0",
    };
    expect(dimensionValue(row, "model")).toBe("qwen-audio-tts");
    expect(dimensionValue(row, "channel")).toBe("未提供");
    expect(dimensionValue(row, "quota")).toBe("0");
    expect(modelInfo("123;unknown-resource;model;meter;0")).toBeNull();
    expect(modelInfo("123;llm-fixture;model;meter;unexpected")).toBeNull();
  });
});
