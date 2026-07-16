function errorText(caught: unknown): string {
  if (caught instanceof Error) return `${caught.name} ${caught.message}`.toLowerCase();
  return typeof caught === "string" ? caught.toLowerCase() : "";
}

export function friendlyError(caught: unknown, context: string): string {
  const text = errorText(caught);
  if (/auth|unauthori[sz]ed|forbidden|credential|api[ _-]?key|not configured|unconfigured|missing config|授权|未配置/.test(text)) return "数据源尚未配置，请在数据设置中检查连接。";
  if (/failed to fetch|network|econn|enotfound|socket|连接失败|网络/.test(text)) return "网络连接失败，请检查网络后重试。";
  if (/timeout|timed out|etimedout|超时/.test(text)) return "请求超时，请稍后重试。";
  if (/not found|404|no data|没有找到|无可用数据/.test(text)) return "没有找到可用数据。";
  return `${context}暂不可用，请稍后重试。`;
}
