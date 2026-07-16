import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DataSettingsView } from "./DataSettingsView";

describe("DataSettingsView", () => {
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
    await waitFor(() => expect(saveAI).toHaveBeenCalledWith({ base_url: "https://ai.example/v1", model: "model", api_key: "secret-value" }));
    expect(refresh).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "清除 AI 配置" }));
    await waitFor(() => expect(deleteAI).toHaveBeenCalledTimes(1));
    expect(refresh).toHaveBeenCalledTimes(2);
  });
});
