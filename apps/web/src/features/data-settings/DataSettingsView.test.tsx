import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { describe, expect, it, vi } from "vitest";

import { DataSettingsView } from "./DataSettingsView";
import type { StockPreparation } from "../stock-cockpit/types";
import type { AISettingsView } from "./types";

describe("DataSettingsView", () => {
  it("loads settings and saves normally under React StrictMode", async () => {
    const saveAI = vi.fn().mockResolvedValue({ configured: true, base_url: "https://strict.example/v1", model: "strict-model", api_key_hint: "****rict" });
    const refresh = vi.fn();
    render(<StrictMode><DataSettingsView loadAI={() => Promise.resolve({ configured: true, base_url: "https://strict.example/v1", model: "strict-model", api_key_hint: "****init" })} saveAI={saveAI} deleteAI={vi.fn()} onAIChanged={refresh} /></StrictMode>);
    expect(await screen.findByText("密钥已保存 · ****init")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("新密钥"), { target: { value: "strict-secret" } });
    fireEvent.click(screen.getByRole("button", { name: "保存 AI 配置" }));
    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
  });
  it("shows masked AI state without rendering the secret", async () => {
    render(<DataSettingsView loadAI={() => Promise.resolve({ configured: true, base_url: "http://localhost:11434/v1", model: "local-model", api_key_hint: "****alue" })} saveAI={vi.fn()} deleteAI={vi.fn()} />);
    expect(await screen.findByText("密钥已保存 · ****alue")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("secret-value")).not.toBeInTheDocument();
    expect(screen.getByLabelText("新密钥")).toHaveValue("");
  });

  it("saves and clears explicitly, then requests a cockpit refresh", async () => {
    const saveAI = vi.fn().mockResolvedValue({ configured: true, base_url: "https://ai.example/v1", model: "model", api_key_hint: "****1234" });
    const deleteAI = vi.fn().mockResolvedValue({ configured: false, base_url: null, model: null, api_key_hint: null });
    const refresh = vi.fn();
    render(<DataSettingsView loadAI={() => Promise.resolve({ configured: false, base_url: null, model: null, api_key_hint: null })} saveAI={saveAI} deleteAI={deleteAI} onAIChanged={refresh} />);
    await screen.findByText("尚未配置 AI");
    fireEvent.change(screen.getByLabelText("API 地址"), { target: { value: "https://ai.example/v1" } });
    fireEvent.change(screen.getByLabelText("模型"), { target: { value: "model" } });
    fireEvent.change(screen.getByLabelText("新密钥"), { target: { value: "secret-value" } });
    fireEvent.click(screen.getByRole("button", { name: "保存 AI 配置" }));
    await waitFor(() => expect(saveAI).toHaveBeenCalledWith({ base_url: "https://ai.example/v1", model: "model", api_key: "secret-value" }, expect.any(AbortSignal)));
    expect(refresh).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "清除 AI 配置" }));
    await waitFor(() => expect(deleteAI).toHaveBeenCalledTimes(1));
    expect(refresh).toHaveBeenCalledTimes(2);
  });

  it("ignores a stale retry after the selected symbol changes", async () => {
    let resolveOld!: (value: StockPreparation) => void;
    const prepare = vi.fn(() => new Promise<StockPreparation>((resolve) => { resolveOld = resolve; }));
    const base = { loadAI: () => Promise.resolve({ configured: false, base_url: null, model: null, api_key_hint: null }), saveAI: vi.fn(), deleteAI: vi.fn() };
    const view = render(<DataSettingsView {...base} symbol="600000" prepare={prepare} />);
    await screen.findByText("尚未配置 AI");
    fireEvent.click(screen.getByRole("button", { name: "重试当前股票数据" }));
    view.rerender(<DataSettingsView {...base} symbol="000001" prepare={prepare} />);
    await act(async () => resolveOld({ symbol: "600000", status: "partial", refreshed: false, started_at: "2026-07-16T10:00:00+08:00", completed_at: "2026-07-16T10:00:01+08:00", sources: [] }));
    expect(screen.getByText("选择一只 A 股后，这里会显示各类数据的最新状态。")).toBeInTheDocument();
  });

  it("reenables preparation retry after switching symbols during an old retry", async () => {
    const prepare = vi.fn(() => new Promise<StockPreparation>(() => undefined));
    const base = { loadAI: () => Promise.resolve({ configured: false, base_url: null, model: null, api_key_hint: null }), saveAI: vi.fn(), deleteAI: vi.fn(), prepare };
    const view = render(<DataSettingsView {...base} symbol="600000" />);
    await screen.findByText("尚未配置 AI");
    fireEvent.click(screen.getByRole("button", { name: "重试当前股票数据" }));
    expect(screen.getByRole("button", { name: "重试当前股票数据" })).toBeDisabled();
    view.rerender(<DataSettingsView {...base} symbol="000001" />);
    expect(screen.getByRole("button", { name: "重试当前股票数据" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "重试当前股票数据" }));
    expect(prepare).toHaveBeenCalledTimes(2);
  });

  it("clears an obsolete AI busy state when context changes", async () => {
    const saveAI = vi.fn(() => new Promise<AISettingsView>(() => undefined));
    const loadAI = vi.fn(() => Promise.resolve({ configured: false, base_url: null, model: null, api_key_hint: null }));
    const view = render(<DataSettingsView loadAI={loadAI} saveAI={saveAI} deleteAI={vi.fn()} symbol="600000" />);
    await screen.findByText("尚未配置 AI");
    fireEvent.change(screen.getByLabelText("API 地址"), { target: { value: "https://ai.example/v1" } });
    fireEvent.change(screen.getByLabelText("模型"), { target: { value: "model" } });
    fireEvent.change(screen.getByLabelText("新密钥"), { target: { value: "secret" } });
    fireEvent.click(screen.getByRole("button", { name: "保存 AI 配置" }));
    view.rerender(<DataSettingsView loadAI={loadAI} saveAI={saveAI} deleteAI={vi.fn()} symbol="000001" />);
    await waitFor(() => expect(loadAI).toHaveBeenCalledTimes(2));
    fireEvent.change(screen.getByLabelText("API 地址"), { target: { value: "https://new.example/v1" } });
    fireEvent.change(screen.getByLabelText("模型"), { target: { value: "new-model" } });
    fireEvent.change(screen.getByLabelText("新密钥"), { target: { value: "new-secret" } });
    expect(screen.getByRole("button", { name: "保存 AI 配置" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "保存 AI 配置" }));
    expect(saveAI).toHaveBeenCalledTimes(2);
  });

  it("maps source failure reasons without exposing internal text", async () => {
    const preparation: StockPreparation = { symbol: "600000", status: "partial", refreshed: false, started_at: "2026-07-16T10:00:00+08:00", completed_at: "2026-07-16T10:00:01+08:00", sources: [{ name: "news", status: "partial", observed_at: null, reason: "SECRET_PROVIDER_STACK" }] };
    render(<DataSettingsView loadAI={() => Promise.resolve({ configured: false, base_url: null, model: null, api_key_hint: null })} saveAI={vi.fn()} deleteAI={vi.fn()} symbol="600000" preparation={preparation} />);
    expect(await screen.findByText("来源暂未提供详细原因")).toBeInTheDocument();
    expect(screen.queryByText(/SECRET|STACK/)).not.toBeInTheDocument();
  });

  it("explains when no verified news is linked to the selected stock", async () => {
    const preparation: StockPreparation = { symbol: "600000", status: "partial", refreshed: false, started_at: "2026-07-16T10:00:00+08:00", completed_at: "2026-07-16T10:00:01+08:00", sources: [{ name: "news", status: "partial", observed_at: null, reason: "news_no_verified_symbol_events" }] };
    render(<DataSettingsView loadAI={() => Promise.resolve({ configured: false, base_url: null, model: null, api_key_hint: null })} saveAI={vi.fn()} deleteAI={vi.fn()} symbol="600000" preparation={preparation} />);
    expect(await screen.findByText("暂未找到与这只股票直接相关且已核实的新闻")).toBeInTheDocument();
  });

  it("shows industry and fund-flow availability with beginner-friendly errors", async () => {
    const preparation: StockPreparation = {
      symbol: "600000", status: "partial", refreshed: false,
      started_at: "2026-07-16T10:00:00+08:00", completed_at: "2026-07-16T10:00:01+08:00",
      sources: [
        { name: "classification", status: "partial", observed_at: null, reason: "classification offline" },
        { name: "fund_flow", status: "partial", observed_at: null, reason: "fund flow offline" },
      ],
    };
    render(<DataSettingsView loadAI={() => Promise.resolve({ configured: false, base_url: null, model: null, api_key_hint: null })} saveAI={vi.fn()} deleteAI={vi.fn()} symbol="600000" preparation={preparation} />);

    expect(await screen.findByText("行业与板块")).toBeInTheDocument();
    expect(screen.getByText("资金流")).toBeInTheDocument();
    expect(screen.getByText("行业与板块来源暂不可用，请稍后重试")).toBeInTheDocument();
    expect(screen.getByText("资金流来源暂不可用，请稍后重试")).toBeInTheDocument();
    expect(screen.queryByText(/offline/i)).not.toBeInTheDocument();
  });

  it("uses the effective state returned after deleting local settings", async () => {
    const deleteAI = vi.fn().mockResolvedValue({ configured: true, base_url: "https://env.example/v1", model: "env-model", api_key_hint: "****env1" });
    render(<DataSettingsView loadAI={() => Promise.resolve({ configured: true, base_url: "https://local.example/v1", model: "local", api_key_hint: "****ocal" })} saveAI={vi.fn()} deleteAI={deleteAI} />);
    await screen.findByText("密钥已保存 · ****ocal");
    fireEvent.click(screen.getByRole("button", { name: "清除 AI 配置" }));
    expect(await screen.findByText("密钥已保存 · ****env1")).toBeInTheDocument();
    expect(screen.getByLabelText("API 地址")).toHaveValue("https://env.example/v1");
  });

  it("does not refresh the cockpit when a save finishes after unmount", async () => {
    let finish!: (value: AISettingsView) => void;
    const saveAI = vi.fn(() => new Promise<AISettingsView>((resolve) => { finish = resolve; }));
    const refresh = vi.fn();
    const view = render(<DataSettingsView loadAI={() => Promise.resolve({ configured: false, base_url: null, model: null, api_key_hint: null })} saveAI={saveAI} deleteAI={vi.fn()} onAIChanged={refresh} />);
    await screen.findByText("尚未配置 AI");
    fireEvent.change(screen.getByLabelText("API 地址"), { target: { value: "https://ai.example/v1" } });
    fireEvent.change(screen.getByLabelText("模型"), { target: { value: "model" } });
    fireEvent.change(screen.getByLabelText("新密钥"), { target: { value: "secret" } });
    fireEvent.click(screen.getByRole("button", { name: "保存 AI 配置" }));
    view.unmount();
    await act(async () => finish({ configured: true, base_url: "https://ai.example/v1", model: "model", api_key_hint: "****cret" }));
    expect(refresh).not.toHaveBeenCalled();
  });
});
