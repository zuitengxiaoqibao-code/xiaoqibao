import { CheckCircle2, Database, KeyRound, RefreshCw, ShieldAlert } from "lucide-react";
import { useEffect, useState } from "react";

import { friendlyError } from "../../shared/friendlyError";
import type { StockPreparation } from "../stock-cockpit/types";
import type { AISettingsInput, AISettingsView, PreparationLoader } from "./types";

const AUTO_SYNC_KEY = "qibao.autoSync";
export function isAutoSyncEnabled(): boolean { return window.localStorage.getItem(AUTO_SYNC_KEY) !== "false"; }

type Props = {
  loadAI: () => Promise<AISettingsView>;
  saveAI: (input: AISettingsInput) => Promise<AISettingsView>;
  deleteAI: () => Promise<AISettingsView>;
  symbol?: string | null;
  prepare?: PreparationLoader;
  preparation?: StockPreparation | null;
  onAIChanged?: () => void;
};

const sourceNames = { quote: "实时行情", history: "历史走势", finance: "基本面", news: "新闻事件" } as const;

export function DataSettingsView({ loadAI, saveAI, deleteAI, symbol, prepare, preparation: initialPreparation, onAIChanged }: Props) {
  const [settings, setSettings] = useState<AISettingsView | null>(null);
  const [baseUrl, setBaseUrl] = useState(""); const [model, setModel] = useState(""); const [apiKey, setApiKey] = useState("");
  const [autoSync, setAutoSync] = useState(isAutoSyncEnabled);
  const [preparation, setPreparation] = useState(initialPreparation ?? null);
  const [busy, setBusy] = useState(false); const [message, setMessage] = useState("");
  useEffect(() => { let active = true; loadAI().then((value) => { if (active) { setSettings(value); setBaseUrl(value.base_url ?? ""); setModel(value.model ?? ""); } }).catch((error) => active && setMessage(friendlyError(error, "AI 设置"))); return () => { active = false; }; }, [loadAI]);
  useEffect(() => setPreparation(initialPreparation ?? null), [initialPreparation]);
  const retry = async () => { if (!symbol || !prepare) return; setBusy(true); setMessage(""); try { setPreparation(await prepare(symbol)); } catch (error) { setMessage(friendlyError(error, "数据同步")); } finally { setBusy(false); } };
  const save = async () => { setBusy(true); setMessage(""); try { const value = await saveAI({ base_url: baseUrl, model, api_key: apiKey }); setSettings(value); setApiKey(""); onAIChanged?.(); } catch (error) { setMessage(friendlyError(error, "AI 设置")); } finally { setBusy(false); } };
  const clear = async () => { setBusy(true); setMessage(""); try { setSettings(await deleteAI()); setBaseUrl(""); setModel(""); setApiKey(""); onAIChanged?.(); } catch (error) { setMessage(friendlyError(error, "AI 设置")); } finally { setBusy(false); } };
  return <main className="beginner-page data-settings-view"><header><p className="eyebrow">数据设置</p><h1>数据源与 AI</h1><p>自动补齐公开数据，并在本机保存 AI 连接信息。研判规则不由 AI 改写。</p></header>
    {message && <div className="cockpit-error" role="alert"><ShieldAlert size={16} />{message}</div>}
    <section className="settings-section"><div className="settings-heading"><div><Database size={20} /><span><h2>公开数据同步</h2><p>选择股票后检查行情、走势、基本面和新闻。</p></span></div><label className="toggle-control"><input type="checkbox" checked={autoSync} onChange={(event) => { setAutoSync(event.target.checked); window.localStorage.setItem(AUTO_SYNC_KEY, String(event.target.checked)); }} /><span>自动同步</span></label></div>
      {preparation ? <div className="source-status-list">{preparation.sources.map((source) => <article key={source.name}><div>{source.status === "ready" ? <CheckCircle2 size={17} /> : <ShieldAlert size={17} />}<b>{sourceNames[source.name]}</b><span>{source.status === "ready" ? "可用" : "待补齐"}</span></div><small>最后成功：{source.observed_at ? new Date(source.observed_at).toLocaleString("zh-CN", { hour12: false }) : "暂无成功记录"}</small>{source.reason && <p>本次未完成，可稍后重试。</p>}</article>)}</div> : <p className="settings-empty">选择一只 A 股后，这里会显示各类数据的最新状态。</p>}
      <button type="button" className="settings-action secondary" disabled={!symbol || !prepare || busy} onClick={() => void retry()}><RefreshCw size={16} />重试当前股票数据</button>
    </section>
    <section className="settings-section"><div className="settings-heading"><div><KeyRound size={20} /><span><h2>AI 补充解释</h2><p>{settings?.configured ? `密钥已保存 · ${settings.api_key_hint ?? "已脱敏"}` : "尚未配置 AI"}</p></span></div></div>
      <div className="settings-form"><label>API 地址<input aria-label="API 地址" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://api.example.com/v1" /></label><label>模型<input aria-label="模型" value={model} onChange={(event) => setModel(event.target.value)} placeholder="模型名称" /></label><label>新密钥<input aria-label="新密钥" type="password" autoComplete="new-password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={settings?.configured ? "留空不会显示旧密钥" : "仅保存在本机"} /></label></div>
      <div className="settings-actions"><button type="button" className="settings-action" disabled={busy || !baseUrl || !model || !apiKey} onClick={() => void save()}>保存 AI 配置</button><button type="button" className="settings-action danger" disabled={busy || !settings?.configured} onClick={() => void clear()}>清除 AI 配置</button></div>
    </section>
  </main>;
}
