import type { DecisionPhase, PhaseExecution } from "./types";

function beijingTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai", hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(new Date(value));
}

export function phaseExecutionCopy(execution: PhaseExecution | undefined, phase: DecisionPhase): { label: string; detail: string } | null {
  if (!execution || execution.status === "completed") return null;
  if (execution.status === "scheduled") {
    const suffix = phase === "intraday" ? "首次生成" : "生成";
    return {
      label: `计划 ${beijingTime(execution.next_scheduled_at ?? execution.scheduled_at)} ${suffix}`,
      detail: "尚未到计划时间，不会提前编造结论。",
    };
  }
  if (execution.status === "running") {
    return { label: "正在生成可核验结果", detail: "任务已经开始，完成前不展示推测内容。" };
  }
  if (execution.status === "failed") {
    return { label: "本次生成失败", detail: "失败已记入运行记录，系统不会用虚构内容补位。" };
  }
  return { label: "已到计划时间，尚无可核验结果", detail: "调度未产出完整记录，请稍后刷新或检查运行状态。" };
}
