import { describe, expect, it } from "vitest";

import { isForbiddenCaptureUploadHost } from "./forbidden-upload-hosts";
import { HttpCiphertextUploadTarget } from "./upload-target";

describe("forbidden capture upload hosts", () => {
  it.each([
    "api.assemblyai.com",
    "streaming.assemblyai.com",
    "assemblyai.com",
    "api.recall.ai",
    "us-east-1.recall.ai",
    "recall.ai",
  ])("blocks %s", (hostname) => {
    expect(isForbiddenCaptureUploadHost(hostname)).toBe(true);
  });

  it.each([
    "uploads.example.invalid",
    "synthetic.blob.core.windows.net",
    "localhost",
  ])("allows %s", (hostname) => {
    expect(isForbiddenCaptureUploadHost(hostname)).toBe(false);
  });

  it.each([
    "https://api.assemblyai.com",
    "https://streaming.assemblyai.com",
    "https://api.recall.ai",
    "https://us-east-1.recall.ai",
  ])("refuses allowlisting %s", (origin) => {
    expect(() => new HttpCiphertextUploadTarget([origin])).toThrow(
      /forbidden|origin/i,
    );
  });

  it("accepts a synthetic Azure blob upload origin", () => {
    expect(
      () => new HttpCiphertextUploadTarget(["https://synthetic.blob.core.windows.net"]),
    ).not.toThrow();
  });
});
