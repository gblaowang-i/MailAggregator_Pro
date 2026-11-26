import axios from "axios";

const API_TOKEN_KEY = "mail-tool-api-token";
export const AUTH_UNAUTHORIZED_EVENT = "auth:unauthorized";

export const apiClient = axios.create({
  baseURL: "/api",
  timeout: 30000
});

apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem(API_TOKEN_KEY);
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

apiClient.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem(API_TOKEN_KEY);
      window.dispatchEvent(new CustomEvent(AUTH_UNAUTHORIZED_EVENT));
    }
    return Promise.reject(err);
  }
);

/** 设置 API Token（用于后端启用 API_TOKEN 时的鉴权，或登录后保存 JWT） */
export function setApiToken(token: string | null): void {
  if (token) localStorage.setItem(API_TOKEN_KEY, token);
  else localStorage.removeItem(API_TOKEN_KEY);
}

export function getApiToken(): string | null {
  return localStorage.getItem(API_TOKEN_KEY);
}

/** 登出：清除本地 Token 并触发未认证事件 */
export function logout(): void {
  setApiToken(null);
  window.dispatchEvent(new CustomEvent(AUTH_UNAUTHORIZED_EVENT));
}

/**
 * Parse backend ISO datetime string safely as UTC when no timezone offset is present.
 */
export function parseUtcDate(value?: string | null): Date | null {
  if (!value) return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  const hasTz = /[zZ]$|[+-]\d{2}:?\d{2}$/.test(trimmed);
  const normalized = hasTz ? trimmed : `${trimmed}Z`;
  const d = new Date(normalized);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function formatLocalDateTime(value?: string | null): string {
  const d = parseUtcDate(value);
  return d ? d.toLocaleString() : "-";
}

/** Extract a human-readable detail message from an Axios/FastAPI error response. */
export function extractApiError(err: unknown, fallback: string): string {
  if (axios.isAxiosError(err)) {
    const detail = (err.response?.data as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === "string" && detail.trim()) {
      return detail;
    }
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0] as { msg?: string };
      if (typeof first?.msg === "string" && first.msg.trim()) {
        return first.msg;
      }
    }
    if (err.code === "ECONNABORTED") {
      return `${fallback}（请求超时）`;
    }
  }
  return fallback;
}

export interface AuthConfig {
  login_required: boolean;
  api_token_required: boolean;
  reset_available: boolean;
}

export interface EmailAccount {
  id: number;
  email: string;
  provider?: string;
  host: string;
  port: number;
  is_active: boolean;
  sort_order?: number;
  telegram_push_enabled?: boolean;
  push_template?: string; // full_email | full | short | title_only
  poll_interval_seconds?: number | null;
}

export interface TelegramFilterRule {
  id: number;
  account_id: number;
  field: string; // sender | domain | subject | body
  mode: string; // allow | deny
  value: string;
  rule_order: number;
}

export interface AccountPollStatus {
  account_id: number;
  last_started_at?: string | null;
  last_finished_at?: string | null;
  last_success_at?: string | null;
  last_error?: string | null;
}

export interface CreateAccountPayload {
  email: string;
  provider?: string;
  host?: string;
  port?: number;
  is_active?: boolean;
  app_password: string;
  telegram_push_enabled?: boolean;
  push_template?: string;
  poll_interval_seconds?: number | null;
}

export interface EmailRecord {
  id: number;
  message_id: string;
  account_id: number;
  account_email: string;
  subject: string;
  sender: string;
  content_summary: string;
  received_at: string;
  is_read?: boolean;
  labels?: string[];
}

export interface EmailRecordDetail extends EmailRecord {
  body_text?: string | null;
  body_html?: string | null;
}

export interface EmailListResponse {
  items: EmailRecord[];
  total: number;
  page: number;
  page_size: number;
}

export interface MailRule {
  id: number;
  name: string;
  rule_order: number;
  account_id: number | null;
  sender_pattern: string;
  subject_pattern: string;
  body_pattern: string;
  add_labels: string[];
  push_telegram: boolean;
  mark_read: boolean;
}

export interface MailRuleCreate {
  name?: string;
  rule_order?: number;
  account_id?: number | null;
  sender_pattern?: string;
  subject_pattern?: string;
  body_pattern?: string;
  add_labels?: string[];
  push_telegram?: boolean;
  mark_read?: boolean;
}

export interface MailRuleUpdate {
  name?: string;
  rule_order?: number;
  account_id?: number | null;
  sender_pattern?: string;
  subject_pattern?: string;
  body_pattern?: string;
  add_labels?: string[];
  push_telegram?: boolean;
  mark_read?: boolean;
}

export interface StatsOverview {
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
}

