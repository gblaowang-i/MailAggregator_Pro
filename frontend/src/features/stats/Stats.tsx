import { FormEvent, useEffect, useMemo, useState } from "react";
import { apiClient, extractApiError } from "../../api/client";

type Overview = {
  totals: {
    emails: number;
    unread: number;
    accounts: number;
    oldest_received_at: string | null;
    newest_received_at: string | null;
  };
  trend: {
    daily: { date: string; count: number }[];
    weekly: { week_start: string; count: number }[];
  };
  by_account: {
    account_id: number;
    account_email: string;
    total: number;
    unread: number;
    share: number;
  }[];
  db: { path: string | null; size_bytes: number | null };
};

type CleanupResult =
  | {
      dry_run: true;
      keep_days: number | null;
      keep_per_account: number | null;
      cutoff: string | null;
      would_delete: number;
      details: { by_days: number; by_overflow: number };
    }
  | {
      dry_run: false;
      keep_days: number | null;
      keep_per_account: number | null;
      cutoff: string | null;
      deleted: number;
      details: { by_days: number; by_overflow: number };
      vacuumed: boolean;
    };

type ArchiveResult = {
  count: number;
  deleted?: number;
  file_name: string | null;
  download_url: string | null;
  cutoff?: string;
};

export const Stats = () => {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [keepDays, setKeepDays] = useState<string>("");
  const [keepPerAcc, setKeepPerAcc] = useState<string>("");
  const [vacuum, setVacuum] = useState(false);
  const [cleaning, setCleaning] = useState(false);
  const [cleanupRes, setCleanupRes] = useState<CleanupResult | null>(null);
  const [cleanupErr, setCleanupErr] = useState<string | null>(null);
  const [savingDefaults, setSavingDefaults] = useState(false);
  const [defaultsSavedMsg, setDefaultsSavedMsg] = useState<string | null>(null);

  const [archiveDays, setArchiveDays] = useState<string>("30");
  const [archiveDelete, setArchiveDelete] = useState(false);
  const [archiving, setArchiving] = useState(false);
  const [archiveRes, setArchiveRes] = useState<ArchiveResult | null>(null);
  const [archiveErr, setArchiveErr] = useState<string | null>(null);
  const [archiveDownloading, setArchiveDownloading] = useState(false);

  const dbSizeText = useMemo(() => {
    const n = overview?.db?.size_bytes;
    if (!n || n <= 0) return "-";
    const kb = n / 1024;
    if (kb < 1024) return `${kb.toFixed(1)} KB`;
    const mb = kb / 1024;
    if (mb < 1024) return `${mb.toFixed(1)} MB`;
    const gb = mb / 1024;
    return `${gb.toFixed(2)} GB`;
  }, [overview?.db?.size_bytes]);

  const fetchAll = async () => {
    try {
      setLoading(true);
      setError(null);
      const [ovRes, settingsRes] = await Promise.all([
        apiClient.get<Overview>("/stats/overview?days=60"),
        apiClient.get<any>("/settings"),
      ]);
      setOverview(ovRes.data);
      setKeepDays(
        settingsRes.data?.retention_keep_days != null
          ? String(settingsRes.data.retention_keep_days)
          : "",
      );
      setKeepPerAcc(
        settingsRes.data?.retention_keep_per_account != null
          ? String(settingsRes.data.retention_keep_per_account)
          : "",
      );
    } catch {
      setError("加载统计失败（请检查后端是否启动，以及本机控制台 Token 是否已设置）");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAll();
  }, []);

  const parseOptInt = (s: string): number | null => {
    const t = s.trim();
    if (!t) return null;
    const n = Number(t);
    if (!Number.isFinite(n) || n <= 0) return null;
    return Math.floor(n);
  };

  const submitCleanup = async (forceDryRun: boolean) => {
    setCleanupErr(null);
    setCleanupRes(null);
    setDefaultsSavedMsg(null);

    if (!forceDryRun) {
      const ok = window.confirm("确认执行清理？此操作会永久删除符合条件的邮件记录（建议先点击「预览清理」确认数量）。");
      if (!ok) return;
    }

    setCleaning(true);
    try {
      const payload = {
        keep_days: parseOptInt(keepDays),
        keep_per_account: parseOptInt(keepPerAcc),
        use_settings_defaults: false,
        dry_run: forceDryRun,
        vacuum: !forceDryRun && vacuum,
      };
      const res = await apiClient.post<CleanupResult>("/stats/cleanup", payload, {
        timeout: 120000,
      });
      setCleanupRes(res.data);
      if (!forceDryRun) {
        await fetchAll();
      }
    } catch (err) {
      setCleanupErr(extractApiError(err, "清理失败"));
    } finally {
      setCleaning(false);
    }
  };

  const saveDefaults = async (e: FormEvent) => {
    e.preventDefault();
    setSavingDefaults(true);
    setCleanupErr(null);
    setDefaultsSavedMsg(null);
    try {
      await apiClient.patch("/settings", {
        retention_keep_days: parseOptInt(keepDays),
        retention_keep_per_account: parseOptInt(keepPerAcc),
      });
      setDefaultsSavedMsg("默认保留策略已保存");
      window.setTimeout(() => setDefaultsSavedMsg(null), 3000);
    } catch (err) {
      setCleanupErr(extractApiError(err, "保存默认策略失败"));
    } finally {
      setSavingDefaults(false);
    }
  };

  const doArchive = async () => {
    setArchiveErr(null);
    setArchiveRes(null);
    const days = parseOptInt(archiveDays);
    if (!days) {
      setArchiveErr("请输入有效的归档天数");
      return;
    }
    if (archiveDelete) {
      const ok = window.confirm(`确认导出早于 ${days} 天的邮件并在导出后从数据库永久删除？`);
      if (!ok) return;
    }
    setArchiving(true);
    try {
      const res = await apiClient.post<ArchiveResult>(
        "/stats/archive",
        {
          older_than_days: days,
          delete_after: archiveDelete,
          limit: 0,
        },
        { timeout: 120000 },
      );
      setArchiveRes(res.data);
      await fetchAll();
    } catch (err) {
      setArchiveErr(extractApiError(err, "归档失败"));
    } finally {
      setArchiving(false);
    }
  };

  const downloadArchiveFile = async () => {
    if (!archiveRes?.file_name) return;
    setArchiveDownloading(true);
    try {
      const res = await apiClient.get(`/stats/archive/${archiveRes.file_name}`, {
        responseType: "blob",
        timeout: 120000,
      });
      const url = URL.createObjectURL(res.data as Blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = archiveRes.file_name;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setArchiveErr(extractApiError(err, "下载归档文件失败，请重试"));
    } finally {
      setArchiveDownloading(false);
    }
  };

  return (
    <section className="card">
      <header className="card-header">
        <div>
          <h2>统计与清理</h2>
          <p className="card-subtitle">分类、占比与邮件存储策略（清理/归档）</p>
        </div>
        <button className="secondary-btn" onClick={fetchAll} disabled={loading}>
          {loading ? "刷新中..." : "刷新"}
        </button>
      </header>

      {error && <p className="error-text">{error}</p>}
      {!error && !overview && loading && <p className="muted">加载中...</p>}

      {overview && (
        <>
          <section className="form-section" style={{ marginTop: 0 }}>
            <h4 className="form-section-title">基础统计</h4>
            <div className="stats-kpi-row">
              <div className="stats-kpi-item">
                <div className="muted" style={{ fontSize: "0.75rem" }}>邮件总数</div>
                <div style={{ fontSize: "1.15rem", fontWeight: 700 }}>{overview.totals.emails}</div>
              </div>
              <div className="stats-kpi-item">
                <div className="muted" style={{ fontSize: "0.75rem" }}>未读</div>
                <div style={{ fontSize: "1.15rem", fontWeight: 700 }}>{overview.totals.unread}</div>
              </div>
              <div className="stats-kpi-item">
                <div className="muted" style={{ fontSize: "0.75rem" }}>已读</div>
                <div style={{ fontSize: "1.15rem", fontWeight: 700 }}>{overview.totals.emails - overview.totals.unread}</div>
              </div>
              <div className="stats-kpi-item">
                <div className="muted" style={{ fontSize: "0.75rem" }}>账号数</div>
                <div style={{ fontSize: "1.15rem", fontWeight: 700 }}>{overview.totals.accounts}</div>
              </div>
              <div className="stats-kpi-item stats-kpi-storage">
                <div className="muted" style={{ fontSize: "0.75rem" }}>存储量</div>
                <div style={{ fontSize: "0.9rem", fontWeight: 700 }}>{dbSizeText}</div>
                {overview.db?.path && (
                  <div className="muted" style={{ fontSize: "0.7rem", marginTop: "0.15rem", wordBreak: "break-all" }}>
                    {overview.db.path}
                  </div>
                )}
              </div>
            </div>
          </section>

          <section className="form-section">
            <h4 className="form-section-title">每日 / 每周趋势</h4>
            <div className="stats-trend-cols">
              <div>
                <div className="muted" style={{ fontSize: "0.75rem", marginBottom: "0.35rem" }}>最近 60 天（按天）</div>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>日期</th>
                      <th style={{ width: 120 }}>收件量</th>
                    </tr>
                  </thead>
                  <tbody>
                    {overview.trend.daily.slice(-14).map((x) => (
                      <tr key={x.date}>
                        <td>{x.date}</td>
                        <td>{x.count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="muted" style={{ fontSize: "0.72rem", marginTop: "0.35rem" }}>
                  为避免表格过长，仅展示最近 14 天；统计本身按 60 天计算。
                </p>
              </div>
              <div>
                <div className="muted" style={{ fontSize: "0.75rem", marginBottom: "0.35rem" }}>按周（以周一为起始）</div>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>周起始</th>
                      <th style={{ width: 120 }}>收件量</th>
                    </tr>
                  </thead>
                  <tbody>
                    {overview.trend.weekly.slice(-12).map((x) => (
                      <tr key={x.week_start}>
                        <td>{x.week_start}</td>
                        <td>{x.count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </section>

          <section className="form-section">
            <h4 className="form-section-title">各账号邮件占比</h4>
            <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>账号</th>
                  <th style={{ width: 90 }}>总数</th>
                  <th style={{ width: 90 }}>未读</th>
                  <th style={{ width: 110 }}>占比</th>
                </tr>
              </thead>
              <tbody>
                {overview.by_account.map((a) => (
                  <tr key={a.account_id}>
                    <td className="truncate" title={a.account_email}>
                      {a.account_email}
                    </td>
                    <td>{a.total}</td>
                    <td>{a.unread}</td>
                    <td>{(a.share * 100).toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          </section>

          <section className="form-section">
            <h4 className="form-section-title">邮件存储策略（清理）</h4>
            <form onSubmit={saveDefaults}>
              <label className="field">
                <span>仅保留最近 N 天（留空表示不启用该条件）</span>
                <input
                  type="number"
                  min={1}
                  placeholder="例如：90"
                  value={keepDays}
                  onChange={(e) => setKeepDays(e.target.value)}
                />
              </label>
              <label className="field">
                <span>每个账号仅保留最近 N 封（留空表示不启用该条件）</span>
                <input
                  type="number"
                  min={1}
                  placeholder="例如：5000"
                  value={keepPerAcc}
                  onChange={(e) => setKeepPerAcc(e.target.value)}
                />
              </label>

              <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center" }}>
                <label className="checkbox-inline" style={{ cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={vacuum}
                    onChange={(e) => setVacuum(e.target.checked)}
                  />
                  清理后 VACUUM（回收 SQLite 磁盘空间）
                </label>
              </div>

              <div className="table-actions" style={{ marginTop: "0.6rem" }}>
                <button
                  type="button"
                  className="small-btn"
                  onClick={() => submitCleanup(true)}
                  disabled={cleaning}
                >
                  {cleaning ? "计算中..." : "预览清理"}
                </button>
                <button
                  type="button"
                  className="small-btn danger"
                  onClick={() => submitCleanup(false)}
                  disabled={cleaning}
                  title="会真正删除邮件记录（建议先预览）"
                >
                  {cleaning ? "清理中..." : "执行清理"}
                </button>
                <button type="submit" className="small-btn" disabled={savingDefaults || cleaning}>
                  {savingDefaults ? "保存中..." : "保存为默认策略"}
                </button>
              </div>

              {cleanupErr && <p className="error-text" style={{ marginTop: "0.4rem" }}>{cleanupErr}</p>}
              {defaultsSavedMsg && <p className="success-text" style={{ marginTop: "0.4rem" }}>{defaultsSavedMsg}</p>}
              {cleanupRes && (
                <div style={{ marginTop: "0.45rem" }}>
                  {cleanupRes.dry_run ? (
                    <p className="muted">
                      预览：将删除 <b>{cleanupRes.would_delete}</b> 封（按天 {cleanupRes.details.by_days}，按超量 {cleanupRes.details.by_overflow}）
                    </p>
                  ) : (
                    <p className="muted">
                      已删除 <b>{cleanupRes.deleted}</b> 封（按天 {cleanupRes.details.by_days}，按超量 {cleanupRes.details.by_overflow}）
                      {cleanupRes.vacuumed ? "，已 VACUUM" : ""}
                    </p>
                  )}
                </div>
              )}
            </form>
          </section>

          <section className="form-section">
            <h4 className="form-section-title">历史归档（导出）</h4>
            <label className="field-inline" style={{ flexWrap: "wrap" }}>
              <span>归档早于 N 天的邮件</span>
              <input
                type="number"
                min={1}
                value={archiveDays}
                onChange={(e) => setArchiveDays(e.target.value)}
              />
              <label className="checkbox-inline" style={{ cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={archiveDelete}
                  onChange={(e) => setArchiveDelete(e.target.checked)}
                />
                导出后删除
              </label>
              <button type="button" className="small-btn" onClick={doArchive} disabled={archiving}>
                {archiving ? "归档中..." : "导出归档"}
              </button>
            </label>
            {archiveErr && <p className="error-text">{archiveErr}</p>}
            {archiveRes && (
              <div style={{ marginTop: "0.4rem" }}>
                {archiveRes.count === 0 ? (
                  <p className="muted">没有符合条件的历史邮件</p>
                ) : (
                  <p className="muted">
                    已导出 <b>{archiveRes.count}</b> 封
                    {archiveRes.deleted ? `，并删除 ${archiveRes.deleted} 封` : ""}。
                    {archiveRes.download_url && archiveRes.file_name && (
                      <>
                        {" "}
                        <button
                          type="button"
                          className="small-btn"
                          onClick={downloadArchiveFile}
                          disabled={archiveDownloading}
                          style={{ marginLeft: "0.25rem" }}
                        >
                          {archiveDownloading ? "下载中…" : "下载归档文件"}
                        </button>
                      </>
                    )}
                  </p>
                )}
              </div>
            )}
          </section>
        </>
      )}
    </section>
  );
};


