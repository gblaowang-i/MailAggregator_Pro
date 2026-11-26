import { useEffect, useState } from "react";
import axios from "axios";
import { AccountList } from "./features/accounts/AccountList";
import { EmailList } from "./features/emails/EmailList";
import { RuleList } from "./features/rules/RuleList";
import { Stats } from "./features/stats/Stats";
import { Settings } from "./features/settings/Settings";
import { Login } from "./features/auth/Login";
import {
  AuthConfig,
  apiClient,
  getApiToken,
  logout,
  setApiToken,
  AUTH_UNAUTHORIZED_EVENT
} from "./api/client";

type View = "accounts" | "emails" | "rules" | "settings";
type Theme = "dark" | "light";

const THEME_KEY = "mail-tool-theme";
const AUTH_CONFIG_URL = "/api/auth/config";

export const App = () => {
  const [view, setView] = useState<View>("accounts");
  const [selectedAccountId, setSelectedAccountId] = useState<number | null>(null);
  const [pollInfo, setPollInfo] = useState<string>("");
  const [theme, setTheme] = useState<Theme>("dark");
  const [needLogin, setNeedLogin] = useState<boolean | null>(null);
  const [authConfig, setAuthConfig] = useState<AuthConfig>({
    login_required: false,
    api_token_required: false,
    reset_available: false
  });

  useEffect(() => {
    const saved = (localStorage.getItem(THEME_KEY) as Theme | null) ?? "dark";
    const next: Theme = saved === "light" ? "light" : "dark";
    setTheme(next);
    document.documentElement.dataset.theme = next;
  }, []);

  useEffect(() => {
    const checkAuth = async () => {
      try {
        const res = await axios.get<Partial<AuthConfig>>(AUTH_CONFIG_URL);
        const cfg: AuthConfig = {
          login_required: !!res.data?.login_required,
          api_token_required: !!res.data?.api_token_required,
          reset_available: !!res.data?.reset_available
        };
        setAuthConfig(cfg);
        const needAuth = cfg.login_required || cfg.api_token_required;
        if (!needAuth) {
          setNeedLogin(false);
          return;
        }
        const token = getApiToken();
        if (!token) {
          setNeedLogin(true);
          return;
        }
        // Verify stored token before rendering main views to avoid a 401 flash.
        try {
          await apiClient.get("/auth/me");
          setNeedLogin(false);
        } catch {
          setApiToken(null);
          setNeedLogin(true);
        }
      } catch {
        setNeedLogin(false);
      }
    };
    checkAuth();
  }, []);

  useEffect(() => {
    const onUnauthorized = () => {
      axios
        .get<Partial<AuthConfig>>(AUTH_CONFIG_URL)
        .then((res) => {
          setAuthConfig({
            login_required: !!res.data?.login_required,
            api_token_required: !!res.data?.api_token_required,
            reset_available: !!res.data?.reset_available
          });
        })
        .catch(() => {});
      setNeedLogin(true);
    };
    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  const toggleTheme = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.dataset.theme = next;
    localStorage.setItem(THEME_KEY, next);
  };

  useEffect(() => {
    const fetchHealth = async () => {
      try {
        const res = await axios.get("/api/health");
        const poller = (res.data as any)?.poller;
        if (poller?.last_finished_at) {
          setPollInfo(`上次轮询完成：${new Date(poller.last_finished_at).toLocaleString()}`);
        } else if (poller?.last_started_at) {
          setPollInfo(
            `轮询进行中：自 ${new Date(poller.last_started_at).toLocaleTimeString()} 起`,
          );
        } else {
          // Hide until we have a first run; avoids always showing a placeholder.
          setPollInfo("");
        }
      } catch {
        setPollInfo("无法获取轮询状态");
      }
    };

    fetchHealth();
    const id = setInterval(fetchHealth, 15000);
    return () => clearInterval(id);
  }, []);

  if (needLogin === true) {
    return (
      <Login
        onSuccess={() => setNeedLogin(false)}
        theme={theme}
        onToggleTheme={toggleTheme}
        authConfig={authConfig}
      />
    );
  }
  if (needLogin === null) {
    return (
      <div className="app-root" style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: "100vh" }}>
        <p className="muted">加载中…</p>
      </div>
    );
  }

  return (
    <div className="app-root">
      <header className="app-header">
        <div className="app-header-left">
          <span className="logo-dot" />
          <div>
            <h1>MailAggregator Console</h1>
            {pollInfo && (
              <p className="muted" style={{ fontSize: "0.7rem", marginTop: "0.15rem" }}>
                {pollInfo}
              </p>
            )}
          </div>
        </div>
        <nav className="app-nav">
          <button
            className={view === "accounts" ? "nav-btn active" : "nav-btn"}
            onClick={() => setView("accounts")}
          >
            账号管理
          </button>
          <button
            className={view === "emails" ? "nav-btn active" : "nav-btn"}
            onClick={() => {
              setSelectedAccountId(null);
              setView("emails");
            }}
          >
            邮件列表
          </button>
          <button
            className={view === "rules" ? "nav-btn active" : "nav-btn"}
            onClick={() => setView("rules")}
          >
            规则管理
          </button>
          <button
            className={view === "settings" ? "nav-btn active" : "nav-btn"}
            onClick={() => setView("settings")}
          >
            控制台
          </button>
          {getApiToken() && (
            <>
              <span className="nav-sep" aria-hidden="true" />
              <button
                className="nav-btn"
                type="button"
                onClick={() => logout()}
              >
                退出
              </button>
            </>
          )}
          <button
            className="nav-btn nav-icon-btn"
            onClick={toggleTheme}
            type="button"
            title={theme === "dark" ? "切换到日间" : "切换到夜间"}
            aria-label={theme === "dark" ? "切换到日间" : "切换到夜间"}
          >
            {theme === "dark" ? (
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <circle
                  cx="12"
                  cy="12"
                  r="6.2"
                  fill="#fef08a"
                  stroke="#f59e0b"
                  strokeWidth="1.6"
                />
                <g fill="#f59e0b">
                  <rect x="11.4" y="1.8" width="1.2" height="3.0" rx="0.6" />
                  <rect x="11.4" y="19.2" width="1.2" height="3.0" rx="0.6" />
                  <rect x="1.8" y="11.4" width="3.0" height="1.2" rx="0.6" />
                  <rect x="19.2" y="11.4" width="3.0" height="1.2" rx="0.6" />
                  <rect
                    x="4.1"
                    y="4.1"
                    width="1.2"
                    height="2.8"
                    rx="0.6"
                    transform="rotate(-45 4.7 5.5)"
                  />
                  <rect
                    x="18.7"
                    y="17.1"
                    width="1.2"
                    height="2.8"
                    rx="0.6"
                    transform="rotate(-45 19.3 18.5)"
                  />
                  <rect
                    x="17.1"
                    y="4.1"
                    width="2.8"
                    height="1.2"
                    rx="0.6"
                    transform="rotate(-45 18.5 4.7)"
                  />
                  <rect
                    x="4.1"
                    y="18.7"
                    width="2.8"
                    height="1.2"
                    rx="0.6"
                    transform="rotate(-45 5.5 19.3)"
                  />
                </g>
              </svg>
            ) : (
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path
                  d="M20.6 15.2c-1.1.5-2.3.7-3.6.7-4.4 0-8-3.6-8-8 0-1.4.3-2.7.9-3.8-3.6 1-6.2 4.3-6.2 8.2 0 4.7 3.8 8.5 8.5 8.5 3.7 0 6.9-2.4 8.4-5.6Z"
                  fill="#f8fafc"
                  stroke="#2563eb"
                  strokeWidth="1.6"
                  strokeLinejoin="round"
                />
                <path
                  d="M18.8 14.8c-.8.3-1.6.4-2.5.4-3.6 0-6.5-2.9-6.5-6.5 0-1 .2-2 .7-2.8"
                  fill="none"
                  stroke="rgba(37, 99, 235, 0.35)"
                  strokeWidth="1.4"
                  strokeLinecap="round"
                />
              </svg>
            )}
          </button>
        </nav>
      </header>

      <main className="app-main">
        {view === "accounts" && (
          <AccountList
            selectedAccountId={selectedAccountId}
            onSelectAccount={setSelectedAccountId}
            onViewEmails={(id) => {
              setSelectedAccountId(id);
              setView("emails");
            }}
          />
        )}
        {view === "emails" && <EmailList accountId={selectedAccountId} />}
        {view === "rules" && <RuleList />}
        {view === "settings" && (
          <div style={{ display: "grid", gap: "0.9rem" }}>
            <Settings />
            <Stats />
          </div>
        )}
      </main>
    </div>
  );
};


