import { afterEach, describe, expect, it, vi } from "vitest";

import { loadSnapshot } from "./api";

describe("loadSnapshot", () => {
  afterEach(() => vi.restoreAllMocks());

  it("surfaces the compliance action instead of a generic status", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
      detail: {
        code: "source_authorization_required",
        message: "请先在礼部完成腾讯行情授权并确认免责声明",
      },
    }), { status: 403, headers: { "Content-Type": "application/json" } }));

    await expect(loadSnapshot("600000")).rejects.toThrow(
      "请先在礼部完成腾讯行情授权并确认免责声明",
    );
  });
});
