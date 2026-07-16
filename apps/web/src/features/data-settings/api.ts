import type { AISettingsInput, AISettingsView } from "./types";

async function settingsRequest(path: string, init?: RequestInit): Promise<AISettingsView> {
  const response = await fetch(path, init);
  if (!response.ok) throw new Error(`AI 设置请求失败 (${response.status})`);
  return response.json();
}

export const loadAISettings = (signal?: AbortSignal) => settingsRequest("/api/v1/settings/ai", { signal });
export const saveAISettings = (input: AISettingsInput, signal?: AbortSignal) => settingsRequest("/api/v1/settings/ai", {
  method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input), signal,
});
export const deleteAISettings = (signal?: AbortSignal) => settingsRequest("/api/v1/settings/ai", { method: "DELETE", signal });
