import {describe, expect, it} from "vitest";
import {permittedSignedWorkspaceApi, permittedWorkspaceApi} from "./workspace-origin";

describe("synthetic workspace origin", () => {
  it("keeps browser access on loopback and enables the exact desktop bridge only in its own build and origin", () => {
    expect(permittedWorkspaceApi("http://127.0.0.1:8018", false, "http://127.0.0.1:5188")).toBe(true);
    expect(permittedWorkspaceApi("app://cosmas/api", true, "app://cosmas/index.html")).toBe(true);
    expect(permittedWorkspaceApi("app://cosmas/api", false, "app://cosmas/index.html")).toBe(false);
    expect(permittedWorkspaceApi("app://cosmas/api", true, "https://outside.invalid")).toBe(false);
  });
  it.each(["app://other/api", "app://cosmas/api/", "app://cosmas:123/api", "app://cosmas/api?url=outside",
    "https://outside.invalid", "http://user@127.0.0.1", "http://127.0.0.1/private"])("rejects %s", base => {
    expect(permittedWorkspaceApi(base, true, "app://cosmas/index.html")).toBe(false);
  });
});

describe("signed Apple local transport", () => {
  const api = "http://127.0.0.1:8035";
  it("requires an explicit flag for the exact Apple shell and retains browser access", () => {
    expect(permittedSignedWorkspaceApi(api, "capacitor://localhost/index.html")).toBe(false);
    expect(permittedSignedWorkspaceApi(api, "capacitor://localhost/index.html", true)).toBe(true);
    expect(permittedSignedWorkspaceApi(api, "http://localhost:5173", false)).toBe(true);
  });
  it.each(["capacitor://other", "capacitor://localhost:123", "capacitor://user@localhost",
    "capacitor://localhost.evil", "app://cosmas/index.html", "file:///index.html", "null",
    "https://outside.invalid", "http://user@localhost:5173"])("rejects page %s before sending a token", page => {
    expect(permittedSignedWorkspaceApi(api, page, true)).toBe(false);
  });
  it.each(["app://cosmas/api", "https://outside.invalid", "http://192.168.1.2:8035",
    "http://user@localhost", "http://127.0.0.1/private", "http://127.0.0.1?token=secret"])(
    "never forwards tokens to %s", base => {
      expect(permittedSignedWorkspaceApi(base, "capacitor://localhost", true)).toBe(false);
    });
});
