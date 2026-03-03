import {
  formatCurrency,
  formatUsd,
  formatPercent,
  formatPnlPercent,
  formatCountdown,
  formatRelativeTime,
  pnlColor,
  pnlBgColor,
} from "../format";

describe("formatCurrency", () => {
  it("prefixes positive values with +$", () => {
    expect(formatCurrency(12.5)).toBe("+$12.50");
  });

  it("prefixes negative values with -$", () => {
    expect(formatCurrency(-3.1)).toBe("-$3.10");
  });

  it("shows zero without sign", () => {
    expect(formatCurrency(0)).toBe("$0.00");
  });

  it("respects custom decimals", () => {
    expect(formatCurrency(1.2345, 3)).toBe("+$1.234");
  });
});

describe("formatUsd", () => {
  it("formats without sign prefix", () => {
    expect(formatUsd(100)).toBe("$100.00");
    expect(formatUsd(0.5, 4)).toBe("$0.5000");
  });
});

describe("formatPercent", () => {
  it("adds + sign for positive", () => {
    expect(formatPercent(5.67)).toBe("+5.7%");
  });

  it("keeps - sign for negative", () => {
    expect(formatPercent(-2.34)).toBe("-2.3%");
  });
});

describe("formatPnlPercent", () => {
  it("converts decimal to percentage", () => {
    expect(formatPnlPercent(0.123)).toBe("+12.3%");
    expect(formatPnlPercent(-0.05)).toBe("-5.0%");
  });
});

describe("formatCountdown", () => {
  it("formats minutes and seconds", () => {
    expect(formatCountdown(125)).toBe("2:05");
    expect(formatCountdown(60)).toBe("1:00");
    expect(formatCountdown(9)).toBe("0:09");
  });

  it("returns 0:00 for zero or negative", () => {
    expect(formatCountdown(0)).toBe("0:00");
    expect(formatCountdown(-5)).toBe("0:00");
  });
});

describe("formatRelativeTime", () => {
  it("shows seconds for < 60s", () => {
    expect(formatRelativeTime(30)).toBe("30s ago");
  });

  it("shows minutes for < 3600s", () => {
    expect(formatRelativeTime(120)).toBe("2m ago");
  });

  it("shows hours for >= 3600s", () => {
    expect(formatRelativeTime(7200)).toBe("2h ago");
  });
});

describe("pnlColor", () => {
  it("returns green for positive", () => {
    expect(pnlColor(1)).toBe("text-green-400");
  });

  it("returns red for negative", () => {
    expect(pnlColor(-1)).toBe("text-red-400");
  });

  it("returns zinc for near-zero", () => {
    expect(pnlColor(0)).toBe("text-zinc-400");
    expect(pnlColor(0.0001)).toBe("text-zinc-400");
  });
});

describe("pnlBgColor", () => {
  it("returns green bg for positive", () => {
    expect(pnlBgColor(1)).toBe("bg-green-500/10");
  });

  it("returns red bg for negative", () => {
    expect(pnlBgColor(-1)).toBe("bg-red-500/10");
  });

  it("returns zinc bg for near-zero", () => {
    expect(pnlBgColor(0)).toBe("bg-zinc-500/10");
  });
});
