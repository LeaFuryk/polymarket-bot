import { render, screen } from "@testing-library/react";
import { MetricCard } from "../MetricCard";

describe("MetricCard", () => {
  it("renders label and value", () => {
    render(<MetricCard label="Win Rate" value="72%" />);
    expect(screen.getByText("Win Rate")).toBeInTheDocument();
    expect(screen.getByText("72%")).toBeInTheDocument();
  });

  it("renders subText when provided", () => {
    render(<MetricCard label="PnL" value="+$5.00" subText="3 trades" />);
    expect(screen.getByText("3 trades")).toBeInTheDocument();
  });

  it("does not render subText when omitted", () => {
    const { container } = render(<MetricCard label="PnL" value="+$5.00" />);
    expect(container.querySelectorAll(".text-xs")).toHaveLength(0);
  });
});
