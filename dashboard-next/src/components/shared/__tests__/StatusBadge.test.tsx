import { render, screen } from "@testing-library/react";
import { StatusBadge } from "../StatusBadge";

describe("StatusBadge", () => {
  it("renders the label text", () => {
    render(<StatusBadge label="LIVE" variant="blue" />);
    expect(screen.getByText("LIVE")).toBeInTheDocument();
  });

  it("applies variant classes", () => {
    render(<StatusBadge label="PAPER" variant="green" />);
    const badge = screen.getByText("PAPER");
    expect(badge.className).toContain("bg-green-500/15");
    expect(badge.className).toContain("text-green-400");
  });

  it("defaults to zinc variant", () => {
    render(<StatusBadge label="UNKNOWN" />);
    const badge = screen.getByText("UNKNOWN");
    expect(badge.className).toContain("bg-zinc-500/15");
  });
});
