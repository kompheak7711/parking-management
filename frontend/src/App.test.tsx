import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { App } from "./App";

afterEach(cleanup);

describe("frontend bootstrap", () => {
  it("TEST-FE-001 renders an accessible non-business application landmark", () => {
    render(<App environment="development" buildId="test-build" />);

    expect(
      screen.getByRole("heading", { name: "Property Rental Management" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveAccessibleName("Application status");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("TEST-FE-002 shows safe support metadata outside production", () => {
    render(<App environment="development" buildId="test-build" />);

    expect(screen.getByText("development")).toBeInTheDocument();
    expect(screen.getByText("Build test-build")).toBeInTheDocument();
  });

  it("TEST-FE-003 does not show the environment indicator in production", () => {
    render(<App environment="production" buildId="release-1" />);

    expect(screen.queryByText("production")).not.toBeInTheDocument();
    expect(screen.getByText("Build release-1")).toBeInTheDocument();
  });
});
