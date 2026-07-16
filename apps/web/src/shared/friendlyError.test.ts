import { describe, expect, it } from "vitest";
import { friendlyError } from "./friendlyError";

describe("friendlyError", () => {
  it("classifies errors without exposing backend text", () => {
    expect(friendlyError(new Error("礼部 auth failed https://secret/api key=abc"), "新闻数据")).toBe("数据源尚未配置，请在数据设置中检查连接。");
    expect(friendlyError(new Error("TypeError: Failed to fetch provider=secret"), "行情数据")).toBe("网络连接失败，请检查网络后重试。");
    expect(friendlyError(new Error("internal timeout stack /srv/app.py"), "风险数据")).toBe("请求超时，请稍后重试。");
    expect(friendlyError(new Error("SECRET_CODE_X9"), "风险数据")).toBe("风险数据暂不可用，请稍后重试。");
  });
});
