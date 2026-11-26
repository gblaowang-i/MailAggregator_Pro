import { FormEvent, useEffect, useState } from "react";
import axios from "axios";
import { AuthConfig, setApiToken } from "../../api/client";

const AUTH_CONFIG_URL = "/api/auth/config";
const LOGIN_URL = "/api/auth/login";
const ME_URL = "/api/auth/me";
const RESET_PASSWORD_URL = "/api/auth/reset-password";

export interface LoginProps {
  onSuccess: () => void;
  theme?: "dark" | "light";
  onToggleTheme?: () => void;
  authConfig?: AuthConfig;
}

type AuthView = "login" | "token" | "reset";

export const Login = ({ onSuccess, theme = "dark", onToggleTheme, authConfig }: LoginProps) => {
  const [loginEnabled, setLoginEnabled] = useState<boolean>(authConfig?.login_required ?? true);
  const [tokenEnabled, setTokenEnabled] = useState<boolean>(authConfig?.api_token_required ?? false);
  const [resetAvailable, setResetAvailable] = useState<boolean>(authConfig?.reset_available ?? false);
  const [view, setView] = useState<AuthView>(
    authConfig && !authConfig.login_required && authConfig.api_token_required ? "token" : "login"
  );
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [apiTokenInput, setApiTokenInput] = useState("");
  const [resetToken, setResetToken] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newPasswordConfirm, setNewPasswordConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    axios
      .get<Partial<AuthConfig>>(AUTH_CONFIG_URL)
      .then((res) => {
        const loginReq = !!res.data?.login_required;
        const tokenReq = !!res.data?.api_token_required;
        setLoginEnabled(loginReq);
        setTokenEnabled(tokenReq);
        setResetAvailable(!!res.data?.reset_available);
        if (!loginReq && tokenReq) {
          setView("token");
        }
      })
      .catch(() => {});
  }, []);

  const handleLogin = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(null);
    setLoading(true);
    try {
      const res = await axios.post<{ access_token: string }>(LOGIN_URL, {
        username: username.trim(),
        password
      });
      const token = res.data?.access_token;
      if (token) {
        setApiToken(token);
        onSuccess();
      } else {
        setError("登录响应异常");
      }
    } catch (err: unknown) {
      const ax = err as { response?: { data?: { detail?: string } } };
      const detail = ax.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "登录失败，请检查用户名和密码");
    } finally {
      setLoading(false);
    }
  };

  const handleTokenLogin = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(null);
    const trimmed = apiTokenInput.trim();
    if (!trimmed) {
      setError("请输入 API Token");
      return;
    }
    setLoading(true);
    try {
      await axios.get(ME_URL, {
        headers: { Authorization: `Bearer ${trimmed}` }
      });
      setApiToken(trimmed);
      onSuccess();
    } catch {
      setError("API Token 无效，请核对后重试");
    } finally {
      setLoading(false);
    }
  };

  const handleReset = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(null);
    if (newPassword !== newPasswordConfirm) {
      setError("两次输入的新密码不一致");
      return;
    }
    if (newPassword.length < 6) {
      setError("新密码至少 6 位");
      return;
    }
    setLoading(true);
    try {
      await axios.post(RESET_PASSWORD_URL, {
        reset_token: resetToken.trim(),
        new_password: newPassword
      });
      setSuccess("密码已重置，请使用新密码登录");
      setResetToken("");
      setNewPassword("");
      setNewPasswordConfirm("");
      window.setTimeout(() => {
        setView("login");
        setSuccess(null);
      }, 2000);
    } catch (err: unknown) {
      const ax = err as { response?: { data?: { detail?: string } } };
      setError(typeof ax.response?.data?.detail === "string" ? ax.response.data.detail : "重置失败，请检查重置令牌");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-page">
      {onToggleTheme && (
        <button
          type="button"
          className="auth-theme-toggle"
          onClick={onToggleTheme}
          title={theme === "dark" ? "切换到日间" : "切换到夜间"}
          aria-label={theme === "dark" ? "切换到日间" : "切换到夜间"}
        >
          {theme === "dark" ? (
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <circle cx="12" cy="12" r="6.2" fill="#fef08a" stroke="#f59e0b" strokeWidth="1.6" />
              <g fill="#f59e0b">
                <rect x="11.4" y="1.8" width="1.2" height="3.0" rx="0.6" />
                <rect x="11.4" y="19.2" width="1.2" height="3.0" rx="0.6" />
                <rect x="1.8" y="11.4" width="3.0" height="1.2" rx="0.6" />
                <rect x="19.2" y="11.4" width="3.0" height="1.2" rx="0.6" />
                <rect x="4.1" y="4.1" width="1.2" height="2.8" rx="0.6" transform="rotate(-45 4.7 5.5)" />
                <rect x="18.7" y="17.1" width="1.2" height="2.8" rx="0.6" transform="rotate(-45 19.3 18.5)" />
                <rect x="17.1" y="4.1" width="2.8" height="1.2" rx="0.6" transform="rotate(-45 18.5 4.7)" />
                <rect x="4.1" y="18.7" width="2.8" height="1.2" rx="0.6" transform="rotate(-45 5.5 19.3)" />
              </g>
            </svg>
          ) : (
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M20.6 15.2c-1.1.5-2.3.7-3.6.7-4.4 0-8-3.6-8-8 0-1.4.3-2.7.9-3.8-3.6 1-6.2 4.3-6.2 8.2 0 4.7 3.8 8.5 8.5 8.5 3.7 0 6.9-2.4 8.4-5.6Z" fill="#f8fafc" stroke="#2563eb" strokeWidth="1.6" strokeLinejoin="round" />
              <path d="M18.8 14.8c-.8.3-1.6.4-2.5.4-3.6 0-6.5-2.9-6.5-6.5 0-1 .2-2 .7-2.8" fill="none" stroke="rgba(37, 99, 235, 0.35)" strokeWidth="1.4" strokeLinecap="round" />
            </svg>
          )}
        </button>
      )}
      <div className="auth-page-inner">
        <div className="auth-card">
          <div className="auth-logo" aria-hidden>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
              <polyline points="22,6 12,13 2,6" />
            </svg>
          </div>
          {view === "login" ? (
            <>
              <h2>登录</h2>
              <p className="auth-subtitle">使用管理员账号登录 MailAggregator 控制台</p>
              <form className="auth-form" onSubmit={handleLogin}>
                <div className="auth-field">
                  <label htmlFor="login-username">用户名</label>
                  <input
                    id="login-username"
                    type="text"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    autoComplete="username"
                    required
                    disabled={loading}
                    placeholder="管理员用户名"
                  />
                </div>
                <div className="auth-field">
                  <label htmlFor="login-password">密码</label>
                  <input
                    id="login-password"
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    autoComplete="current-password"
                    required
                    disabled={loading}
                    placeholder="登录密码"
                  />
                </div>
                {error && <p className="auth-error">{error}</p>}
                <button type="submit" className="auth-submit" disabled={loading}>
                  {loading ? "登录中…" : "登录"}
                </button>
                <div className="auth-links" style={{ display: "flex", flexDirection: "column", gap: "0.45rem" }}>
                  {resetAvailable && (
                    <button
                      type="button"
                      className="auth-link"
                      onClick={() => { setView("reset"); setError(null); setSuccess(null); }}
                    >
                      忘记密码？使用重置令牌
                    </button>
                  )}
                  {tokenEnabled && (
                    <button
                      type="button"
                      className="auth-link"
                      onClick={() => { setView("token"); setError(null); setSuccess(null); }}
                    >
                      改用 API Token 认证
                    </button>
                  )}
                </div>
              </form>
            </>
          ) : view === "token" ? (
            <>
              <h2>API Token 认证</h2>
              <p className="auth-subtitle">服务端已启用 API_TOKEN 鉴权，请输入配置的 Token</p>
              <form className="auth-form" onSubmit={handleTokenLogin}>
                <div className="auth-field">
                  <label htmlFor="api-token-input">API Token</label>
                  <input
                    id="api-token-input"
                    type="password"
                    value={apiTokenInput}
                    onChange={(e) => setApiTokenInput(e.target.value)}
                    autoComplete="off"
                    required
                    disabled={loading}
                    placeholder="输入后端配置的 API_TOKEN"
                  />
                </div>
                {error && <p className="auth-error">{error}</p>}
                <button type="submit" className="auth-submit" disabled={loading}>
                  {loading ? "验证中…" : "进入控制台"}
                </button>
                {loginEnabled && (
                  <p className="auth-links">
                    <button
                      type="button"
                      className="auth-link"
                      onClick={() => { setView("login"); setError(null); setSuccess(null); }}
                    >
                      改用管理员账号登录
                    </button>
                  </p>
                )}
              </form>
            </>
          ) : (
            <>
              <h2>重置密码</h2>
              <p className="auth-subtitle">在 .env 中配置 ADMIN_RESET_TOKEN 后，在此填写令牌与新密码</p>
              <form className="auth-form" onSubmit={handleReset}>
                <div className="auth-field">
                  <label htmlFor="reset-token">重置令牌</label>
                  <input
                    id="reset-token"
                    type="password"
                    value={resetToken}
                    onChange={(e) => setResetToken(e.target.value)}
                    autoComplete="off"
                    required
                    disabled={loading}
                    placeholder="与 .env 中 ADMIN_RESET_TOKEN 一致"
                  />
                </div>
                <div className="auth-field">
                  <label htmlFor="reset-new">新密码</label>
                  <input
                    id="reset-new"
                    type="password"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    autoComplete="new-password"
                    required
                    disabled={loading}
                    placeholder="至少 6 位"
                    minLength={6}
                  />
                </div>
                <div className="auth-field">
                  <label htmlFor="reset-confirm">确认新密码</label>
                  <input
                    id="reset-confirm"
                    type="password"
                    value={newPasswordConfirm}
                    onChange={(e) => setNewPasswordConfirm(e.target.value)}
                    autoComplete="new-password"
                    required
                    disabled={loading}
                    placeholder="再次输入新密码"
                    minLength={6}
                  />
                </div>
                {error && <p className="auth-error">{error}</p>}
                {success && <p className="auth-success">{success}</p>}
                <button type="submit" className="auth-submit" disabled={loading}>
                  {loading ? "提交中…" : "重置密码"}
                </button>
                <p className="auth-links">
                  <button
                    type="button"
                    className="auth-link"
                    onClick={() => { setView("login"); setError(null); setSuccess(null); }}
                  >
                    返回登录
                  </button>
                </p>
              </form>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

