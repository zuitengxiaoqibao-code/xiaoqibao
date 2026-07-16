import { AlertTriangle, ArchiveRestore, CheckCircle2, Clock3, DatabaseBackup, Pause, Play, RotateCcw, ServerCog } from "lucide-react";
import { useEffect, useState } from "react";

import type { BackupRecord, BackupVerification, OperationsStatus } from "./types";

type Props = {
  loadStatus: () => Promise<OperationsStatus>;
  setSchedulerPaused: (paused: boolean) => Promise<OperationsStatus["scheduler"]>;
  createBackup: () => Promise<BackupRecord>;
  verifyBackup: (backupId: string) => Promise<BackupVerification>;
  runManualJob: (phase: string, tradingDate: string) => Promise<{ report_id: string }>;
};

const phaseName = { premarket: "盘前", intraday: "盘中", postclose: "盘后" };
const schedule = [["09:20", "盘前情报"], ["10:30", "盘中一检"], ["13:30", "盘中二检"], ["14:30", "盘中三检"], ["15:30", "盘后复盘"]];
const bytes = (value: number) => value >= 1048576 ? `${(value / 1048576).toFixed(2)} MB` : `${(value / 1024).toFixed(1)} KB`;

export function OperationsView(props: Props) {
  const [status, setStatus] = useState<OperationsStatus | null>(null);
  const [error, setError] = useState("");
  const [acting, setActing] = useState("");
  const [tradingDate, setTradingDate] = useState(new Date().toISOString().slice(0, 10));
  const [verification, setVerification] = useState<BackupVerification | null>(null);
  const [notice, setNotice] = useState("");

  async function reload() { setError(""); try { setStatus(await props.loadStatus()); } catch (reason) { setError(reason instanceof Error ? reason.message : "运维状态读取失败"); } }
  useEffect(() => { void reload(); }, [props.loadStatus]);
  async function toggleScheduler() { if (!status) return; const paused = !status.scheduler.paused; setActing("scheduler"); setError(""); try { const scheduler = await props.setSchedulerPaused(paused); setStatus({ ...status, scheduler }); setNotice(paused ? "调度已暂停" : "调度已恢复"); } catch (reason) { setError(reason instanceof Error ? reason.message : "调度操作失败"); } finally { setActing(""); } }
  async function backup() { if (!status) return; setActing("backup"); setError(""); try { const created = await props.createBackup(); setStatus({ ...status, backups: [created, ...status.backups] }); setNotice(`备份已创建 ${created.backup_id}`); } catch (reason) { setError(reason instanceof Error ? reason.message : "备份创建失败"); } finally { setActing(""); } }
  async function verify(backupId: string) { setActing(`verify:${backupId}`); setError(""); try { setVerification(await props.verifyBackup(backupId)); } catch (reason) { setError(reason instanceof Error ? reason.message : "备份验证失败"); } finally { setActing(""); } }
  async function manual(phase: "premarket" | "intraday" | "postclose") { setActing(`manual:${phase}`); setError(""); try { const result = await props.runManualJob(phase, tradingDate); setNotice(`补跑已归档 ${result.report_id}`); await reload(); } catch (reason) { setError(reason instanceof Error ? reason.message : "手动补跑失败"); } finally { setActing(""); } }

  if (!status && !error) return <main className="operations-domain"><div className="operations-loading"><Clock3 size={18}/>正在读取运维状态...</div></main>;
  return <main className="operations-domain">
    <header className="operations-header"><div><p className="eyebrow">工部 / DATA OPERATIONS</p><h1>数据与运维中心</h1><p>本地任务调度、故障补跑、一致性备份与恢复验证</p></div><div className={`scheduler-switch ${status?.scheduler.paused ? "paused" : "running"}`}><span>{status?.scheduler.paused ? "PAUSED" : "RUNNING"}</span><button onClick={() => void toggleScheduler()} disabled={acting !== ""}>{status?.scheduler.paused ? <Play size={15}/> : <Pause size={15}/>} {status?.scheduler.paused ? "恢复调度" : "暂停调度"}</button></div></header>
    {error && <div className="operations-error" role="alert"><AlertTriangle size={17}/>{error}<button onClick={() => void reload()}>重试</button></div>}
    {notice && <div className="operations-notice" role="status"><CheckCircle2 size={16}/>{notice}</div>}
    <section className="schedule-console"><header><ServerCog size={17}/><div><h2>尚书省自动调度</h2><small>交易日 · 北京时间 · 失败最多尝试 3 次</small></div></header><div className="schedule-track">{schedule.map(([time, label]) => <div key={time}><time>{time}</time><span>{label}</span></div>)}</div></section>
    <section className="manual-console"><div><h2>故障补跑</h2><small>暂停状态下仍可执行，结果进入追加式任务日志</small></div><label>补跑交易日<input aria-label="补跑交易日" type="date" value={tradingDate} onChange={(event) => setTradingDate(event.target.value)}/></label><div>{(["premarket", "intraday", "postclose"] as const).map((phase) => <button key={phase} disabled={acting !== "" || !tradingDate} onClick={() => void manual(phase)}><RotateCcw size={14}/>补跑{phaseName[phase]}</button>)}</div></section>
    <section className="job-ledger"><header><h2>任务运行账本</h2><small>{status?.scheduler.jobs.length ?? 0} 个调度槽位</small></header>{status?.scheduler.jobs.length === 0 ? <p className="operations-empty">暂无任务运行记录</p> : status?.scheduler.jobs.slice().reverse().map((job) => <article key={job.job_key}><span className={`job-state ${job.status}`}/><div><b>{phaseName[job.phase]} · {job.trading_date} · {job.slot}</b><small>{job.trigger === "manual" ? "手动补跑" : "自动调度"} · {new Date(job.occurred_at).toLocaleString("zh-CN")}</small></div><div><strong>{job.status === "completed" ? "已完成" : job.error_code}</strong><small>累计尝试 {job.attempts} 次</small></div></article>)}</section>
    <section className="backup-console"><header><div><h2>本地备份与恢复验证</h2><small>SQLite 在线快照 · DuckDB checkpoint · SHA-256 清单</small></div><button onClick={() => void backup()} disabled={acting !== ""}><DatabaseBackup size={15}/>创建一致性备份</button></header>{verification && <div className={`verification-result ${verification.valid && verification.restore_drill_passed ? "passed" : "failed"}`}>{verification.valid && verification.restore_drill_passed ? <CheckCircle2/> : <AlertTriangle/>}<div><b>{verification.restore_drill_passed ? "恢复演练通过" : "恢复演练失败"}</b><small>校验 {verification.checked_files} 个文件{verification.mismatched_files.length ? ` · 异常 ${verification.mismatched_files.join(", ")}` : " · 哈希一致"}</small></div></div>}<div className="backup-ledger">{status?.backups.length === 0 ? <p className="operations-empty">尚未创建本地备份</p> : status?.backups.map((item) => <article key={item.backup_id}><ArchiveRestore size={17}/><div><b>{item.backup_id}</b><small>{new Date(item.created_at).toLocaleString("zh-CN")} · {item.file_count} 文件 · {bytes(item.total_bytes)}</small></div><button aria-label="执行恢复演练" disabled={acting !== ""} onClick={() => void verify(item.backup_id)}>{acting === `verify:${item.backup_id}` ? "演练中" : "执行恢复演练"}</button></article>)}</div></section>
  </main>;
}
