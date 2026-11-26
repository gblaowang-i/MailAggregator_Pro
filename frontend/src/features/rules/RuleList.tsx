import { FormEvent, useEffect, useState } from "react";
import {
  EmailAccount,
  MailRule,
  MailRuleCreate,
  apiClient
} from "../../api/client";

type ModalMode = "create" | "edit";

export const RuleList = () => {
  const [rules, setRules] = useState<MailRule[]>([]);
  const [accounts, setAccounts] = useState<EmailAccount[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [modalMode, setModalMode] = useState<ModalMode>("create");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [form, setForm] = useState<MailRuleCreate>({
    name: "",
    rule_order: 0,
    account_id: null,
    sender_pattern: "",
    subject_pattern: "",
    body_pattern: "",
    add_labels: [],
    push_telegram: true,
    mark_read: false
  });
  const [newLabel, setNewLabel] = useState("");

  const fetchRules = async () => {
    try {
      setLoading(true);
      setError(null);
      const [rulesRes, accRes] = await Promise.all([
        apiClient.get<MailRule[]>("/rules/"),
        apiClient.get<EmailAccount[]>("/accounts/")
      ]);
      setRules(rulesRes.data);
      setAccounts(accRes.data);
    } catch {
      setError("加载规则失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRules();
  }, []);

  const openCreate = () => {
    setModalMode("create");
    setEditingId(null);
    setForm({
      name: "",
      rule_order: rules.length,
      account_id: null,
      sender_pattern: "",
      subject_pattern: "",
      body_pattern: "",
      add_labels: [],
      push_telegram: true,
      mark_read: false
    });
    setNewLabel("");
    setFormError(null);
    setShowModal(true);
  };

  const openEdit = (r: MailRule) => {
    setModalMode("edit");
    setEditingId(r.id);
    setForm({
      name: r.name || "",
      rule_order: r.rule_order,
      account_id: r.account_id ?? null,
      sender_pattern: r.sender_pattern || "",
      subject_pattern: r.subject_pattern || "",
      body_pattern: r.body_pattern || "",
      add_labels: r.add_labels ? [...r.add_labels] : [],
      push_telegram: r.push_telegram,
      mark_read: r.mark_read
    });
    setNewLabel("");
    setFormError(null);
    setShowModal(true);
  };

  const addLabelToForm = () => {
    const t = newLabel.trim();
    if (!t || (form.add_labels && form.add_labels.includes(t))) return;
    setForm((f) => ({
      ...f,
      add_labels: [...(f.add_labels || []), t]
    }));
    setNewLabel("");
  };

  const removeLabel = (idx: number) => {
    setForm((f) => ({
      ...f,
      add_labels: (f.add_labels || []).filter((_, i) => i !== idx)
    }));
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      setSaving(true);
      setFormError(null);
      const pendingLabel = newLabel.trim();
      const labels = [...(form.add_labels || [])];
      if (pendingLabel && !labels.includes(pendingLabel)) {
        labels.push(pendingLabel);
      }
      const payload: MailRuleCreate = { ...form, add_labels: labels };
      if (modalMode === "create") {
        await apiClient.post<MailRule>("/rules/", payload);
      } else if (editingId) {
        await apiClient.patch(`/rules/${editingId}`, payload);
      }
      setShowModal(false);
      setNewLabel("");
      await fetchRules();
    } catch (err: any) {
      const detail = err.response?.data?.detail;
      setFormError(typeof detail === "string" ? detail : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const deleteRule = async (id: number) => {
    if (!window.confirm("确认删除这条规则？（会同时清理仅由该规则添加的历史标签）")) return;
    try {
      await apiClient.delete(`/rules/${id}`);
      await fetchRules();
    } catch {
      setError("删除失败");
    }
  };

  const accountEmail = (id: number | null) => {
    if (id == null) return "全部账号";
    const a = accounts.find((x) => x.id === id);
    return a ? a.email : `#${id}`;
  };

  return (
    <section className="card">
      <header className="card-header">
        <div>
          <h2>规则管理</h2>
          <p className="card-subtitle">
            按条件匹配邮件后自动打标签、控制推送或标已读
          </p>
        </div>
        <button className="primary-btn" onClick={openCreate}>
          新建规则
        </button>
      </header>

      {loading && <p className="muted">加载中...</p>}
      {error && <p className="error-text">{error}</p>}

      {!loading && !error && rules.length === 0 && (
        <p className="muted">暂无规则，新建后新拉取的邮件将按规则自动打标签或执行动作。</p>
      )}

      {!loading && !error && rules.length > 0 && (
        <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th>名称</th>
              <th>顺序</th>
              <th>适用账号</th>
              <th>条件（发件人/主题/正文）</th>
              <th>添加标签</th>
              <th>推送 TG</th>
              <th>标已读</th>
              <th className="col-actions" style={{ width: 200 }}>操作</th>
            </tr>
          </thead>
          <tbody>
            {rules.map((r) => (
              <tr key={r.id}>
                <td>{r.name || "-"}</td>
                <td>{r.rule_order}</td>
                <td>{accountEmail(r.account_id)}</td>
                <td className="truncate" style={{ maxWidth: 200 }}>
                  {[r.sender_pattern, r.subject_pattern, r.body_pattern]
                    .filter(Boolean)
                    .join(" · ") || "全部邮件"}
                </td>
                <td>
                  {r.add_labels && r.add_labels.length > 0
                    ? r.add_labels.join(", ")
                    : "-"}
                </td>
                <td>{r.push_telegram ? "是" : "否"}</td>
                <td>{r.mark_read ? "是" : "否"}</td>
                <td className="col-actions">
                  <div className="table-actions">
                    <button
                      type="button"
                      className="small-btn"
                      onClick={() => openEdit(r)}
                    >
                      编辑
                    </button>
                    <button
                      type="button"
                      className="small-btn danger"
                      onClick={() => deleteRule(r.id)}
                    >
                      删除
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}

      {showModal && (
        <div className="modal-backdrop" onClick={() => !saving && setShowModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <header className="modal-header">
              <h3>{modalMode === "create" ? "新建规则" : "编辑规则"}</h3>
            </header>
            <form className="modal-body" onSubmit={handleSubmit}>
              <section className="form-section">
                <h4 className="form-section-title">条件（留空表示不限制）</h4>
                <label className="field">
                  <span>规则名称</span>
                  <input
                    type="text"
                    placeholder="便于识别"
                    value={form.name || ""}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, name: e.target.value }))
                    }
                  />
                </label>
                <label className="field">
                  <span>执行顺序</span>
                  <input
                    type="number"
                    min={0}
                    value={form.rule_order ?? 0}
                    onChange={(e) =>
                      setForm((f) => ({
                        ...f,
                        rule_order: Number(e.target.value) || 0
                      }))
                    }
                  />
                </label>
                <label className="field">
                  <span>适用账号</span>
                  <select
                    value={form.account_id ?? ""}
                    onChange={(e) => {
                      const v = e.target.value;
                      setForm((f) => ({
                        ...f,
                        account_id: v === "" ? null : Number(v)
                      }));
                    }}
                  >
                    <option value="">全部账号</option>
                    {accounts.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.email}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>发件人包含</span>
                  <input
                    type="text"
                    placeholder="关键字"
                    value={form.sender_pattern || ""}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, sender_pattern: e.target.value }))
                    }
                  />
                </label>
                <label className="field">
                  <span>主题包含</span>
                  <input
                    type="text"
                    placeholder="关键字"
                    value={form.subject_pattern || ""}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, subject_pattern: e.target.value }))
                    }
                  />
                </label>
                <label className="field">
                  <span>正文包含</span>
                  <input
                    type="text"
                    placeholder="关键字"
                    value={form.body_pattern || ""}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, body_pattern: e.target.value }))
                    }
                  />
                </label>
              </section>
              <section className="form-section">
                <h4 className="form-section-title">动作</h4>
                <div className="field">
                  <span>添加标签</span>
                  <div
                    style={{
                      display: "flex",
                      flexWrap: "wrap",
                      gap: "0.35rem",
                      marginTop: "0.3rem"
                    }}
                  >
                    {(form.add_labels || []).map((l, i) => (
                      <span
                        key={i}
                        className="badge badge-info"
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: "0.25rem"
                        }}
                      >
                        {l}
                        <button
                          type="button"
                          className="link-btn"
                          style={{ padding: 0, fontSize: "0.75rem" }}
                          onClick={() => removeLabel(i)}
                        >
                          移除
                        </button>
                      </span>
                    ))}
                  </div>
                  <div
                    style={{
                      display: "flex",
                      gap: "0.5rem",
                      alignItems: "center",
                      marginTop: "0.4rem"
                    }}
                  >
                    <input
                      type="text"
                      placeholder="输入标签名后添加"
                      value={newLabel}
                      onChange={(e) => setNewLabel(e.target.value)}
                      onKeyDown={(e) =>
                        e.key === "Enter" && (e.preventDefault(), addLabelToForm())
                      }
                      style={{
                        padding: "0.35rem 0.5rem",
                        borderRadius: "0.5rem",
                        border: "1px solid var(--input-border)",
                        background: "var(--input-bg)",
                        color: "var(--text)",
                        fontSize: "0.8rem",
                        width: 160
                      }}
                    />
                    <button
                      type="button"
                      className="small-btn"
                      onClick={addLabelToForm}
                    >
                      添加
                    </button>
                  </div>
                </div>
                <label className="field-inline">
                  <span>匹配后推送 Telegram</span>
                  <label className="checkbox-inline" style={{ cursor: "pointer" }}>
                    <input
                      type="checkbox"
                      checked={form.push_telegram !== false}
                      onChange={(e) =>
                        setForm((f) => ({ ...f, push_telegram: e.target.checked }))
                      }
                    />
                    {form.push_telegram !== false ? "是" : "否"}
                  </label>
                </label>
                <label className="field-inline">
                  <span>匹配后标为已读</span>
                  <label className="checkbox-inline" style={{ cursor: "pointer" }}>
                    <input
                      type="checkbox"
                      checked={form.mark_read === true}
                      onChange={(e) =>
                        setForm((f) => ({ ...f, mark_read: e.target.checked }))
                      }
                    />
                    {form.mark_read ? "是" : "否"}
                  </label>
                </label>
              </section>
              {formError && <p className="error-text">{formError}</p>}
              <footer className="modal-footer">
                <button
                  type="button"
                  className="secondary-btn"
                  onClick={() => setShowModal(false)}
                  disabled={saving}
                >
                  取消
                </button>
                <button
                  type="submit"
                  className="primary-btn"
                  disabled={saving}
                >
                  {saving ? "保存中..." : "保存"}
                </button>
              </footer>
            </form>
          </div>
        </div>
      )}
    </section>
  );
};
