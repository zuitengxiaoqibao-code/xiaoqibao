import type { AISettingsInput, AISettingsView } from "./types";

async function settingsRequest(path: string, init?: RequestInit): Promise<AISettingsView> {
  const response = await fetch(path, init);
  if (!response.ok) throw new Error(`AI 设置请求失败 (${response.status})`);
  return response.json();
}

export const loadAISettings = () => settingsRequest("/api/v1/settings/ai");
export const saveAISettings = (input: AISettingsInput) => settingsRequest("/api/v1/settings/ai", {
  method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
});
export const deleteAISettings = () => settingsRequest("/api/v1/settings/ai", { method: "DELETE" });
