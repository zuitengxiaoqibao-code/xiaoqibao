import { afterEach, describe, expect, it, vi } from "vitest";

import { complianceAction, loadCompliance } from "./api";

afterEach(() => vi.unstubAllGlobals());

describe("convertible-bond compliance API", () => {
  it("scopes status and actions to the convertible-bond asset", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ policy_state: "current", sources: [], features: [] }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await loadCompliance("convertible_bond");
    await complianceAction("eastmoney", "authorize", "contract:test", "convertible_bond");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/v1/libu/status?asset=convertible_bond",
    );
    expect(fetchMock.mock.calls[1][0]).toBe(
      "/api/v1/libu/sources/eastmoney/authorize?asset=convertible_bond",
    );
  });
});
