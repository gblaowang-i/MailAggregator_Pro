import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import axios from "axios";
import { AuthConfig, apiClient, extractApiError, getApiToken, setApiToken } from "../../api/client";

interface SettingsForm {
  telegram_bot_token: string;
  telegram_chat_id: string;
  poll_interval_seconds: number;
  webhook_url: string;
  api_token: string;
}

const defaultForm: SettingsForm = {
  telegram_bot_token: "",
  telegram_chat_id: "",
  poll_interval_seconds: 300,
  webhook_url: "",
  api_token: ""
};

export const Settings = () => {
  const [form, setForm] = useState<SettingsForm>(defaultForm);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [consoleToken, setConsoleToken] = useState("");
  const [consoleSaved, setConsoleSaved] = useState(false);
  const [loginEnabled, setLoginEnabled] = useState(false);
  const [changePwdCurrent, setChangePwdCurrent] = useState("");
  const [changePwdNew, setChangePwdNew] = useState("");
  const [changePwdConfirm, setChangePwdConfirm] = useState("");
  const [changePwdLoading, setChangePwdLoading] = useState(false);
  const [changePwdError, setChangePwdError] = useState<string | null>(null);
  const [changePwdSuccess, setChangePwdSuccess] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const fetchSettings = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const [res, authRes] = await Promise.all([
        apiClient.get<SettingsForm>("/settings"),
        axios.get<Partial<AuthConfig>>("/api/auth/config").catch(() => ({ data: {} as Partial<AuthConfig> }))
      ]);
      setForm({ ...defaultForm, ...res.data });
      setLoginEnabled(!!authRes.data?.login_required);
    } catch (err) {
      setError(extractApiError(err, "加载设置失败"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSettings();
    setConsoleToken(getApiToken() || "");
  }, [fetchSettings]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      setSaving(true);
      setError(null);
      setSuccessMsg(null);
      await apiClient.patch("/settings", {
        telegram_bot_token: form.telegram_bot_token.trim() || null,
        telegram_chat_id: form.telegram_chat_id.trim() || null,
        poll_interval_seconds: Math.max(5, Number(form.poll_interval_seconds) || 300),
        webhook_url: form.webhook_url.trim() || null,
        api_token: form.api_token.trim() || null
      });
      setSuccessMsg("已保存");
      window.setTimeout(() => setSuccessMsg(null), 3000);
    } catch (err) {
      setError(extractApiError(err, "保存失败"));
    } finally {
      setSaving(false);
    }
  };

  const saveConsoleToken = () => {
    const trimmed = consoleToken.trim();
    setApiToken(trimmed || null);
    setConsoleToken(trimmed);
    setConsoleSaved(true);
    window.setTimeout(() => setConsoleSaved(false), 2000);
  };

  const exportConfig = async () => {
    try {
      setError(null);
      const res = await apiClient.get<Record<string, unknown>>("/settings/export");
      const blob = new Blob([JSON.stringify(res.data, null, 2)], {
        type: "application/json"
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "mail-tool-config.json";
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(extractApiError(err, "导出失败"));
    }
  };

  const handleChangePassword = async (e: FormEvent) => {
    e.preventDefault();
    setChangePwdError(null);
    setChangePwdSuccess(false);
    if (changePwdNew !== changePwdConfirm) {
      setChangePwdError("两次输入的新密码不一致");
      return;
    }
    if (changePwdNew.trim().length < 6) {
      setChangePwdError("新密码至少 6 位");
      return;
    }
    setChangePwdLoading(true);
    try {
      await apiClient.post("/auth/change-password", {
        current_password: changePwdCurrent,
        new_password: changePwdNew
      });
      setChangePwdSuccess(true);
      setChangePwdCurrent("");
      setChangePwdNew("");
      setChangePwdConfirm("");
      window.setTimeout(() => setChangePwdSuccess(false), 3000);
    } catch (err) {
      setChangePwdError(extractApiError(err, "修改失败"));
    } finally {
      setChangePwdLoading(false);
    }
  };

  const importConfig = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    try {
      const text = await file.text();
      const data = JSON.parse(text) as Record<string, unknown>;
      if (!window.confirm("导入将覆盖当前配置与邮箱账号，是否继续？")) return;
      setError(null);
      setSuccessMsg(null);
      const settingsObj =
        data.settings && typeof data.settings === "object"
          ? (data.settings as Record<string, unknown>)
          : data;
      if (Array.isArray(data.accounts)) {
        const res = await apiClient.post<{ imported_accounts?: number }>(
          "/settings/import",
          {
            settings: settingsObj,
            accounts: data.accounts
          },
          { timeout: 60000 }
        );
        setSuccessMsg(`导入成功（已同步 ${res.data?.imported_accounts ?? 0} 个账号）`);
      } else {
        await apiClient.patch("/settings", settingsObj);
        setSuccessMsg("导入设置成功");
      }
      await fetchSettings();
      window.setTimeout(() => setSuccessMsg(null), 4000);
    } catch (err) {
      setError(extractApiError(err, "导入失败，请确认文件为有效 JSON 配置"));
    }
  };

  if (loading) {
    return (
      <section className="card">
        <p className="muted">加载中...</p>
      </section>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
      {loginEnabled && (
        <section className="card">
          <header className="card-header">
            <div>
              <h2>修改密码</h2>
              <p className="card-subtitle">修改控制台登录密码（保存后立即生效）</p>
            </div>
          </header>
          <form onSubmit={handleChangePassword} className="change-pwd-form">
            {changePwdError && <p className="error-text">{changePwdError}</p>}
            {changePwdSuccess && (
              <p className="success-text" style={{ marginBottom: "0.5rem" }}>
                密码已修改
              </p>
            )}
            <div className="change-pwd-row">
              <label className="field">
                <span>当前密码</span>
                <input
                  type="password"
                  autoComplete="current-password"
                  value={changePwdCurrent}
                  onChange={(e) => setChangePwdCurrent(e.target.value)}
                  required
                  disabled={changePwdLoading}
                />
              </label>
              <label className="field">
                <span>新密码</span>
                <input
                  type="password"
                  autoComplete="new-password"
                  value={changePwdNew}
                  onChange={(e) => setChangePwdNew(e.target.value)}
                  required
                  disabled={changePwdLoading}
                  minLength={6}
                  placeholder="至少 6 位"
                />
              </label>
              <label className="field">
                <span>确认新密码</span>
                <input
                  type="password"
                  autoComplete="new-password"
                  value={changePwdConfirm}
                  onChange={(e) => setChangePwdConfirm(e.target.value)}
                  required
                  disabled={changePwdLoading}
                  minLength={6}
                />
              </label>
              <button type="submit" className="primary-btn" disabled={changePwdLoading}>
                {changePwdLoading ? "提交中…" : "修改密码"}
              </button>
            </div>
          </form>
        </section>
      )}

      <section className="card settings-page">
        <header className="card-header">
          <div>
            <h2>系统设置</h2>
            <p className="card-subtitle">
              修改后保存即生效，会覆盖 .env 中对应项（仅本机 DB 存储）
            </p>
          </div>
        </header>

        {error && <p className="error-text">{error}</p>}
        {successMsg && <p className="success-text">{successMsg}</p>}

      <form onSubmit={handleSubmit} className="settings-form-h">
        <div className="settings-grid">
          <h4 className="form-section-title">Telegram 推送</h4>
          <h4 className="form-section-title">轮询与 Webhook</h4>
          <h4 className="form-section-title">API 鉴权</h4>

          <label className="field">
            <span>Bot Token</span>
            <input
              type="password"
              autoComplete="off"
              placeholder="留空则关闭 Telegram 推送"
              value={form.telegram_bot_token}
              onChange={(e) => setForm((f) => ({ ...f, telegram_bot_token: e.target.value }))}
            />
          </label>
          <label className="field">
            <span>全局轮询间隔（秒）</span>
            <input
              type="number"
              min={5}
              value={form.poll_interval_seconds}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  poll_interval_seconds: Math.max(5, Number(e.target.value) || 5)
                }))
              }
            />
          </label>
          <label className="field">
            <span>API Token</span>
            <input
              type="password"
              autoComplete="off"
              placeholder="设置后，请求需带 Authorization: Bearer <token>；留空则关闭鉴权"
              value={form.api_token}
              onChange={(e) => setForm((f) => ({ ...f, api_token: e.target.value }))}
            />
            <p className="muted" style={{ fontSize: "0.75rem", marginTop: "0.25rem" }}>
              已启用登录时可不填，仅用账号密码 + JWT 即可；仅当需要脚本或外部服务调用接口时再设置。
            </p>
          </label>

          <label className="field">
            <span>Chat ID</span>
            <input
              type="text"
              autoComplete="off"
              placeholder="接收推送的 Telegram Chat ID，留空则关闭"
              value={form.telegram_chat_id}
              onChange={(e) => setForm((f) => ({ ...f, telegram_chat_id: e.target.value }))}
            />
          </label>
          <label className="field">
            <span>Webhook URL</span>
            <input
              type="url"
              autoComplete="off"
              placeholder="新邮件时 POST 的地址，留空则关闭"
              value={form.webhook_url}
              onChange={(e) => setForm((f) => ({ ...f, webhook_url: e.target.value }))}
            />
          </label>
          <div />
        </div>

        <section className="form-section settings-full">
          <h4 className="form-section-title">本机控制台 Token</h4>
          <p className="muted" style={{ marginBottom: "0.5rem" }}>
            仅在未使用登录、而用 API Token 鉴权时需要：在此保存与后端一致的 Token，浏览器请求会自动带上。使用账号登录时无需填写。
          </p>
          <div className="field-inline" style={{ flexWrap: "wrap", gap: "0.5rem" }}>
            <input
              type="password"
              autoComplete="off"
              placeholder="与上方 API Token 一致"
              value={consoleToken}
              onChange={(e) => setConsoleToken(e.target.value)}
              style={{
                padding: "0.4rem 0.55rem",
                borderRadius: "0.5rem",
                border: "1px solid var(--input-border)",
                background: "var(--input-bg)",
                color: "var(--text)",
                fontSize: "0.8rem",
                minWidth: 200
              }}
            />
            <button type="button" className="secondary-btn" onClick={saveConsoleToken}>
              {consoleSaved ? "已保存" : "保存到本机"}
            </button>
          </div>
        </section>

        <footer className="modal-footer" style={{ marginTop: "1rem", paddingTop: "0.75rem" }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", alignItems: "center" }}>
            <button type="submit" className="primary-btn" disabled={saving}>
              {saving ? "保存中..." : "保存设置"}
            </button>
            <button type="button" className="secondary-btn" onClick={exportConfig}>
              导出配置
            </button>
            <button
              type="button"
              className="secondary-btn"
              onClick={() => fileInputRef.current?.click()}
            >
              导入配置
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".json,application/json"
              style={{ display: "none" }}
              onChange={importConfig}
            />
          </div>
          <p className="muted" style={{ fontSize: "0.75rem", marginTop: "0.5rem" }}>
            导出文件包含敏感信息，请妥善保存。
          </p>
        </footer>
      </form>
    </section>
    </div>
  );
};

