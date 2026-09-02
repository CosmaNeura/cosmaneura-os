import { describe, expect, it } from "vitest";

describe("queue labels", () => {
  it("hides infrastructure jargon from primary copy", () => {
    const copy = "Practice work queue for synthetic Insurance ArtifactChase";
    expect(copy.toLowerCase()).not.toContain("box_id");
    expect(copy.toLowerCase()).not.toContain("operation");
    expect(copy.toLowerCase()).not.toContain("celery");
  });
});
