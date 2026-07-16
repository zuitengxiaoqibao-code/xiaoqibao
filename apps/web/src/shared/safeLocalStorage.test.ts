import { describe, expect, it, vi } from "vitest";
import { safeStorageGet, safeStorageSet } from "./safeLocalStorage";

describe("safeLocalStorage", () => {
  it("falls back when browser storage throws", () => {
    const get = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new DOMException("blocked", "SecurityError"); });
    expect(safeStorageGet("key", "fallback")).toBe("fallback");
    get.mockRestore();
    const set = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("blocked", "SecurityError"); });
    expect(() => safeStorageSet("key", "value")).not.toThrow();
    set.mockRestore();
  });
});
