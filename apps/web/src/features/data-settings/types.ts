import type { StockPreparation } from "../stock-cockpit/types";

export type AISettingsView = {
  configured: boolean;
  base_url: string | null;
  model: string | null;
  api_key_hint: string | null;
};

export type AISettingsInput = { base_url: string; model: string; api_key: string };
export type PreparationLoader = (symbol: string, signal?: AbortSignal) => Promise<StockPreparation>;
export type AISettingsLoader = (signal?: AbortSignal) => Promise<AISettingsView>;
export type AISettingsSaver = (input: AISettingsInput, signal?: AbortSignal) => Promise<AISettingsView>;
export type AISettingsDeleter = (signal?: AbortSignal) => Promise<AISettingsView>;
