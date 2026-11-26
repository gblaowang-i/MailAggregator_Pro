import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  EmailAccount,
  EmailListResponse,
  EmailRecord,
  EmailRecordDetail,
  apiClient,
  extractApiError,
  formatLocalDateTime
} from "../../api/client";
import { MAIL_PROVIDERS } from "../../config/mailProviders";

interface Props {
  accountId: number | null;
}

type TimeRangeKey = "all" | "24h" | "7d" | "30d";

export const EmailList = ({ accountId }: Props) => {
  const [accounts, setAccounts] = useState<EmailAccount[]>([]);
  const [accountFilter, setAccountFilter] = useState<number | null>(accountId);
  const [accountSearch, setAccountSearch] = useState("");
  const [brandFilter, setBrandFilter] = useState<string>("");
  const [emails, setEmails] = useState<EmailRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [fetchingRemote, setFetchingRemote] = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);
  const [selectedEmail, setSelectedEmail] = useState<EmailRecordDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [detailTab, setDetailTab] = useState<"text" | "html">("text");
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [keyword, setKeyword] = useState("");
  const [debouncedKeyword, setDebouncedKeyword] = useState("");
  const [timeRange, setTimeRange] = useState<TimeRangeKey>("all");
  const [readFilter, setReadFilter] = useState<"all" | "unread" | "read">("all");
  const [labelFilter, setLabelFilter] = useState("");
  const [debouncedLabel, setDebouncedLabel] = useState("");
  const [applyingRules, setApplyingRules] = useState(false);

  const listReqIdRef = useRef(0);
  const detailReqIdRef = useRef(0);

  useEffect(() => {
    apiClient.get<EmailAccount[]>("/accounts/").then((r) => setAccounts(r.data)).catch(() => {});
  }, []);

  useEffect(() => {
    setAccountFilter(accountId);
    setPage(1);
  }, [accountId]);

  useEffect(() => {
    const id = window.setTimeout(() => {
      setDebouncedKeyword(keyword.trim());
      setPage(1);
    }, 300);
    return () => window.clearTimeout(id);
  }, [keyword]);

  useEffect(() => {
    const id = window.setTimeout(() => {
      setDebouncedLabel(labelFilter.trim());
      setPage(1);
    }, 300);
    return () => window.clearTimeout(id);
  }, [labelFilter]);

  const fetchEmails = useCallback(async (silent = false) => {
    const reqId = ++listReqIdRef.current;
    try {
      if (!silent) {
        setLoading(true);
        setError(null);
      }
      const params: Record<string, string | number | boolean> = { page, page_size: pageSize };
      if (accountFilter) {
        params.account_id = accountFilter;
      } else if (brandFilter) {
        params.provider = brandFilter;
      }
      if (debouncedKeyword) params.keyword = debouncedKeyword;
      if (readFilter === "unread") params.is_read = false;
      if (readFilter === "read") params.is_read = true;
      if (debouncedLabel) params.label = debouncedLabel;
      if (timeRange !== "all") {
        const now = new Date();
        const fromDate = new Date(now);
        if (timeRange === "24h") fromDate.setTime(now.getTime() - 24 * 60 * 60 * 1000);
        else if (timeRange === "7d") fromDate.setTime(now.getTime() - 7 * 24 * 60 * 60 * 1000);
        else fromDate.setTime(now.getTime() - 30 * 24 * 60 * 60 * 1000);
        params.date_from = fromDate.toISOString();
        params.date_to = now.toISOString();
      }
      const res = await apiClient.get<EmailListResponse>("/emails/", { params });
      if (reqId !== listReqIdRef.current) return;
      setEmails(res.data.items);
      setTotal(res.data.total);
    } catch (e) {
      if (reqId !== listReqIdRef.current) return;
      if (!silent) setError(extractApiError(e, "加载邮件失败"));
    } finally {
      if (reqId === listReqIdRef.current && !silent) {
        setLoading(false);
      }
    }
  }, [accountFilter, brandFilter, page, pageSize, debouncedKeyword, timeRange, readFilter, debouncedLabel]);

  useEffect(() => {
    fetchEmails();
  }, [fetchEmails]);

  // 静默自动刷新：定期后台拉取最新邮件列表，不影响当前界面状态。
  useEffect(() => {
    const intervalMs = 20_000;
    const id = window.setInterval(() => {
      fetchEmails(true);
    }, intervalMs);
    return () => window.clearInterval(id);
  }, [fetchEmails]);

  const filteredAccountsForSelect = useMemo(() => {
    let list = accounts;
    if (brandFilter) {
      list = list.filter((a) => (a.provider || "custom") === brandFilter);
    }
    if (accountSearch.trim()) {
      const q = accountSearch.trim().toLowerCase();
      list = list.filter((a) => a.email.toLowerCase().includes(q));
    }
    return list;
  }, [accounts, brandFilter, accountSearch]);

  const openDetail = async (id: number) => {
    const reqId = ++detailReqIdRef.current;
    setDetailOpen(true);
    setSelectedEmail(null);
    setDetailTab("text");
    setLoadingDetail(true);
    setError(null);
    try {
      const res = await apiClient.get<EmailRecordDetail>(`/emails/${id}`);
      if (reqId !== detailReqIdRef.current) return;
      setSelectedEmail(res.data);
      setEmails((prev) =>
        prev.map((m) => (m.id === id ? { ...m, is_read: true } : m))
      );
    } catch (err) {
      if (reqId !== detailReqIdRef.current) return;
      setDetailOpen(false);
      setError(extractApiError(err, "加载邮件详情失败"));
    } finally {
      if (reqId === detailReqIdRef.current) {
        setLoadingDetail(false);
      }
    }
  };

  const closeDetail = () => {
    detailReqIdRef.current += 1;
    setDetailOpen(false);
    setSelectedEmail(null);
  };

  const applyRulesToExisting = async () => {
    try {
      setApplyingRules(true);
      setError(null);
      setNotice(null);
      const res = await apiClient.post<{ updated: number; total: number; message?: string }>(
        "/emails/apply-rules",
        undefined,
        { timeout: 120000 }
      );
      await fetchEmails();
      setNotice(
        `${res.data.message || "已重算标签"}：更新 ${res.data.updated} / 共 ${res.data.total} 封`
      );
    } catch (err) {
      setError(extractApiError(err, "应用规则失败"));
    } finally {
      setApplyingRules(false);
    }
  };

  const fetchRemote = async () => {
    if (!accountFilter) {
      setError("请先在上方选择要拉取的账号");
      return;
    }
    try {
      setFetchingRemote(true);
      setError(null);
      setNotice(null);
      const res = await apiClient.post<{ inserted?: number }>(
        `/emails/accounts/${accountFilter}/fetch_once`,
        undefined,
        { timeout: 120000 }
      );
      await fetchEmails();
      const count = Number(res.data?.inserted || 0);
      setNotice(count > 0 ? `拉取完成，新增/更新 ${count} 封邮件` : "拉取完成，暂无新邮件");
    } catch (err) {
      setError(extractApiError(err, "拉取邮件失败"));
    } finally {
      setFetchingRemote(false);
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const goPrev = () => setPage((p) => Math.max(1, p - 1));
  const goNext = () => setPage((p) => Math.min(totalPages, p + 1));

  return (
    <section className="card">
      <header className="card-header">
        <div>
          <h2>邮件列表</h2>
          <p className="card-subtitle">
            {accountFilter
              ? "当前筛选单个账号"
              : brandFilter
                ? `当前筛选品牌：${MAIL_PROVIDERS.find((p) => p.key === brandFilter)?.label ?? brandFilter}`
                : "显示所有账号的邮件"}
          </p>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "0.35rem", flexWrap: "wrap" }}>
            <select
              value={brandFilter}
              onChange={(e) => {
                setBrandFilter(e.target.value);
                setAccountFilter(null);
                setPage(1);
              }}
              style={{
                padding: "0.35rem 0.5rem",
                borderRadius: "0.5rem",
                border: "1px solid var(--input-border)",
                background: "var(--input-bg)",
                color: "var(--text)",
                fontSize: "0.8rem",
                minWidth: 100
              }}
            >
              <option value="">全部品牌</option>
              {MAIL_PROVIDERS.map((p) => (
                <option key={p.key} value={p.key}>
                  {p.label}
                </option>
              ))}
            </select>
            <input
              type="text"
              placeholder="搜索账号"
              value={accountSearch}
              onChange={(e) => setAccountSearch(e.target.value)}
              style={{
                padding: "0.35rem 0.5rem",
                borderRadius: "0.5rem",
                border: "1px solid var(--input-border)",
                background: "var(--input-bg)",
                color: "var(--text)",
                fontSize: "0.8rem",
                width: 100
              }}
            />
            <select
              value={accountFilter ?? ""}
              onChange={(e) => {
                const v = e.target.value;
                setAccountFilter(v === "" ? null : Number(v));
                setPage(1);
              }}
              style={{
                padding: "0.35rem 0.5rem",
                borderRadius: "0.5rem",
                border: "1px solid var(--input-border)",
                background: "var(--input-bg)",
                color: "var(--text)",
                fontSize: "0.8rem",
                minWidth: 180
              }}
            >
              <option value="">全部账号</option>
              {filteredAccountsForSelect.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.email}
                </option>
              ))}
            </select>
          </div>
          <input
            type="text"
            placeholder="搜索主题 / 发件人 / 摘要"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                setDebouncedKeyword(keyword.trim());
                setPage(1);
              }
            }}
            style={{
              padding: "0.35rem 0.5rem",
              borderRadius: "0.5rem",
              border: "1px solid var(--input-border)",
              background: "var(--input-bg)",
              color: "var(--text)",
              fontSize: "0.8rem",
              minWidth: 160
            }}
          />
          <select
            value={timeRange}
            onChange={(e) => {
              setTimeRange(e.target.value as TimeRangeKey);
              setPage(1);
            }}
            style={{
              padding: "0.35rem 0.5rem",
              borderRadius: "0.5rem",
              border: "1px solid var(--input-border)",
              background: "var(--input-bg)",
              color: "var(--text)",
              fontSize: "0.8rem"
            }}
          >
            <option value="all">全部时间</option>
            <option value="24h">最近 24 小时</option>
            <option value="7d">最近 7 天</option>
            <option value="30d">最近 30 天</option>
          </select>
          <select
            value={readFilter}
            onChange={(e) => {
              setReadFilter(e.target.value as "all" | "unread" | "read");
              setPage(1);
            }}
            style={{
              padding: "0.35rem 0.5rem",
              borderRadius: "0.5rem",
              border: "1px solid var(--input-border)",
              background: "var(--input-bg)",
              color: "var(--text)",
              fontSize: "0.8rem"
            }}
          >
            <option value="all">全部</option>
            <option value="unread">未读</option>
            <option value="read">已读</option>
          </select>
          <input
            type="text"
            placeholder="按标签筛选"
            value={labelFilter}
            onChange={(e) => setLabelFilter(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                setDebouncedLabel(labelFilter.trim());
                setPage(1);
              }
            }}
            style={{
              padding: "0.35rem 0.5rem",
              borderRadius: "0.5rem",
              border: "1px solid var(--input-border)",
              background: "var(--input-bg)",
              color: "var(--text)",
              fontSize: "0.8rem",
              width: 100
            }}
          />
          <button
            className="secondary-btn"
            type="button"
            onClick={() => {
              setDebouncedKeyword(keyword.trim());
              setDebouncedLabel(labelFilter.trim());
              setPage(1);
              void fetchEmails();
            }}
          >
            搜索
          </button>
          <button
            className="secondary-btn"
            type="button"
            onClick={applyRulesToExisting}
            disabled={applyingRules}
            title="刷新并按当前规则重算标签（会清除旧标签），并按规则可选标已读"
          >
            {applyingRules ? "刷新中..." : "刷新（重算标签）"}
          </button>
          <button
            className="primary-btn"
            type="button"
            style={{ paddingInline: "0.8rem", fontSize: "0.75rem" }}
            onClick={fetchRemote}
            disabled={fetchingRemote}
          >
            {fetchingRemote ? "拉取中..." : "从邮箱拉取一次"}
          </button>
        </div>
      </header>

      {loading && <p className="muted">加载中...</p>}
      {error && <p className="error-text">{error}</p>}
      {notice && <p className="success-text">{notice}</p>}

      {!loading && !error && emails.length === 0 && (
        <p className="muted">还没有任何邮件记录。</p>
      )}

      {!loading && emails.length > 0 && (
        <>
          <div className="table-scroll">
            <table className="data-table email-table">
            <thead>
              <tr>
                <th>标签</th>
                <th className="col-time">时间</th>
                <th className="col-account">收件账号</th>
                <th className="col-sender">发件人</th>
                <th className="col-subject">主题</th>
                <th>摘要</th>
              </tr>
            </thead>
            <tbody>
              {emails.map((m) => {
                const timeStr = formatLocalDateTime(m.received_at);
                return (
                  <tr
                    key={m.id}
                    className={"row-selectable" + (m.is_read === false ? " email-unread" : "")}
                    onClick={() => openDetail(m.id)}
                  >
                    <td className="email-labels-cell">
                      {(m.labels && m.labels.length > 0)
                        ? (
                            <span className="email-labels-wrap">
                              {m.labels.map((l) => (
                                <span key={l} className="badge badge-info" title={l}>
                                  {l}
                                </span>
                              ))}
                            </span>
                          )
                        : <span className="email-labels-empty">无</span>}
                    </td>
                    <td className="col-time truncate" title={timeStr}>
                      {timeStr}
                    </td>
                    <td className="col-account truncate" title={m.account_email}>
                      {m.account_email}
                    </td>
                    <td className="col-sender truncate" title={m.sender}>
                      {m.sender}
                    </td>
                    <td className="col-subject truncate" title={m.subject}>
                      {m.is_read === false ? <strong>{m.subject || "(无主题)"}</strong> : (m.subject || "(无主题)")}
                    </td>
                    <td className="truncate">{m.content_summary}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          </div>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginTop: "0.75rem",
              fontSize: "0.8rem"
            }}
          >
            <span className="muted">
              共 {total} 条 · 第 {page} / {totalPages} 页
            </span>
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <button
                className="secondary-btn"
                type="button"
                onClick={goPrev}
                disabled={page <= 1}
              >
                上一页
              </button>
              <button
                className="secondary-btn"
                type="button"
                onClick={goNext}
                disabled={page >= totalPages}
              >
                下一页
              </button>
            </div>
          </div>
        </>
      )}

      {detailOpen && (
        <div className="modal-backdrop" onClick={closeDetail}>
          <div className="modal modal-lg" onClick={(e) => e.stopPropagation()}>
            <header className="modal-header modal-header-row">
              <div style={{ minWidth: 0 }}>
                <h3 className="truncate" title={selectedEmail?.subject || ""}>
                  {loadingDetail ? "加载中..." : (selectedEmail?.subject || "(无主题)")}
                </h3>
                {selectedEmail && (
                  <div className="modal-meta">
                    <span className="truncate" title={selectedEmail.account_email}>
                      收件账号：{selectedEmail.account_email}
                    </span>
                    <span className="truncate" title={selectedEmail.sender}>
                      发件人：{selectedEmail.sender}
                    </span>
                    <span>时间：{formatLocalDateTime(selectedEmail.received_at)}</span>
                  </div>
                )}
              </div>
              <button
                className="icon-btn"
                type="button"
                onClick={closeDetail}
                title="关闭"
              >
                ×
              </button>
            </header>

            <div className="modal-content">
              {loadingDetail ? (
                <p className="muted">加载中...</p>
              ) : selectedEmail ? (
                <>
                  {selectedEmail.body_html && (
                    <div style={{ display: "flex", gap: "0.4rem" }}>
                      <button
                        type="button"
                        className={detailTab === "text" ? "small-btn active-tab" : "small-btn"}
                        onClick={() => setDetailTab("text")}
                      >
                        纯文本
                      </button>
                      <button
                        type="button"
                        className={detailTab === "html" ? "small-btn active-tab" : "small-btn"}
                        onClick={() => setDetailTab("html")}
                      >
                        HTML 预览
                      </button>
                    </div>
                  )}
                  {detailTab === "html" && selectedEmail.body_html ? (
                    <iframe
                      title="邮件 HTML 内容"
                      sandbox=""
                      srcDoc={selectedEmail.body_html}
                      className="email-html-frame"
                    />
                  ) : (
                    <pre className="email-pre">
                      {selectedEmail.body_text ||
                        selectedEmail.content_summary ||
                        "(无可用正文内容)"}
                    </pre>
                  )}
                </>
              ) : null}
              <footer className="modal-footer">
                <button
                  className="secondary-btn"
                  type="button"
                  onClick={closeDetail}
                >
                  关闭
                </button>
              </footer>
            </div>
          </div>
        </div>
      )}
    </section>
  );
};


