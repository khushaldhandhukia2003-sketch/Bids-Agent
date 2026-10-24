import React, { useState, useEffect } from "react";
import { API } from "../config/api";

const ROLES = [
  { value: "chairman",    label: "Chairman" },
  { value: "developer",   label: "Developer" },
  { value: "manager",     label: "Manager" },
  { value: "procurement", label: "Procurement" },
  { value: "pq_cost",     label: "PQ & Cost Estimation Person" },
];

const ROLE_COLORS = {
  chairman:    "bg-amber-100 text-amber-800 border-amber-200",
  gm:          "bg-blue-100 text-blue-800 border-blue-200",
  manager:     "bg-emerald-100 text-emerald-800 border-emerald-200",
  procurement: "bg-sky-100 text-sky-800 border-sky-200",
  developer:   "bg-violet-100 text-violet-800 border-violet-200",
  pq_cost:     "bg-teal-100 text-teal-800 border-teal-200",
};

const ROLE_LABELS = {
  chairman:    "CHAIRMAN",
  gm:          "GM",
  manager:     "MANAGER",
  procurement: "PROCUREMENT",
  developer:   "DEVELOPER",
  pq_cost:     "PQ & COST",
};

const EMPTY_FORM = { name: "", username: "", password: "", email: "", role: "procurement", division_ids: [] };

export default function UserManagement() {
  const [users, setUsers]           = useState([]);
  const [divisions, setDivisions]   = useState([]);
  const [loading, setLoading]       = useState(true);
  const [showForm, setShowForm]     = useState(false);
  const [form, setForm]             = useState(EMPTY_FORM);
  const [saving, setSaving]         = useState(false);
  const [formError, setFormError]   = useState("");
  const [editUser, setEditUser]     = useState(null);   // user being edited
  const [editDiv, setEditDiv]       = useState(null);   // user whose divisions are being edited
  const [editDivIds, setEditDivIds] = useState([]);
  const [savingDiv, setSavingDiv]   = useState(false);
  const [deletingId, setDeletingId] = useState(null);
  const [showPass, setShowPass]     = useState({});

  const load = () => {
    setLoading(true);
    Promise.all([
      fetch(`${API}/users`).then(r => r.json()),
      fetch(`${API}/divisions`).then(r => r.json()),
    ]).then(([u, d]) => {
      setUsers(u.users || []);
      setDivisions(d.divisions || []);
    }).catch(() => {}).finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  // ── Create user ──────────────────────────────────────────────
  const handleCreate = async (e) => {
    e.preventDefault();
    if (!form.name.trim() || !form.username.trim() || !form.password.trim()) {
      setFormError("Name, username and password are required."); return;
    }
    setSaving(true); setFormError("");
    try {
      const res  = await fetch(`${API}/users`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      const data = await res.json();
      if (!res.ok) { setFormError(data.detail || "Failed to create user"); return; }
      setUsers(prev => [...prev, data.user]);
      setShowForm(false); setForm(EMPTY_FORM);
    } finally {
      setSaving(false);
    }
  };

  // ── Edit user (name / password / role) ───────────────────────
  const handleUpdate = async (e) => {
    e.preventDefault();
    setSaving(true); setFormError("");
    try {
      const res  = await fetch(`${API}/users/${editUser.id}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: editUser.name, password: editUser.password, role: editUser.role }),
      });
      const data = await res.json();
      if (!res.ok) { setFormError(data.detail || "Failed to update"); return; }
      setUsers(prev => prev.map(u => u.id === data.user.id ? data.user : u));
      setEditUser(null);
    } finally {
      setSaving(false);
    }
  };

  // ── Save division assignments ─────────────────────────────────
  const handleSaveDivisions = async () => {
    setSavingDiv(true);
    try {
      const res  = await fetch(`${API}/users/${editDiv.id}/divisions`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ division_ids: editDivIds }),
      });
      const data = await res.json();
      if (res.ok) {
        setUsers(prev => prev.map(u => u.id === data.user.id ? data.user : u));
        setEditDiv(null);
      }
    } finally {
      setSavingDiv(false);
    }
  };

  // ── Delete user ───────────────────────────────────────────────
  const handleDelete = async (id) => {
    if (!window.confirm("Delete this user? This cannot be undone.")) return;
    setDeletingId(id);
    try {
      await fetch(`${API}/users/${id}`, { method: "DELETE" });
      setUsers(prev => prev.filter(u => u.id !== id));
    } finally {
      setDeletingId(null);
    }
  };

  const toggleDiv = (id) =>
    setEditDivIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);

  const toggleFormDiv = (id) =>
    setForm(f => ({ ...f, division_ids: f.division_ids.includes(id) ? f.division_ids.filter(x => x !== id) : [...f.division_ids, id] }));

  if (loading) return (
    <div className="p-8 text-sm text-gray-400">Loading users…</div>
  );

  return (
    <div className="p-6 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-bold text-gray-800">👥 User Management</h2>
          <p className="text-sm text-gray-500 mt-0.5">{users.length} accounts · manage login access and division permissions</p>
        </div>
        <button
          onClick={() => { setShowForm(true); setForm(EMPTY_FORM); setFormError(""); }}
          className="bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium px-4 py-2 rounded-xl flex items-center gap-2 transition"
        >
          <span className="text-lg leading-none">+</span> Add User
        </button>
      </div>

      {/* ── Create form ── */}
      {showForm && (
        <div className="bg-white border border-gray-200 rounded-2xl p-5 mb-6 shadow-sm">
          <h3 className="font-semibold text-gray-700 mb-4">New User</h3>
          <form onSubmit={handleCreate} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-xs font-medium text-gray-500 mb-1 block">Full Name</label>
                <input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
                  placeholder="e.g. Rahul Sharma" />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-500 mb-1 block">Username</label>
                <input value={form.username} onChange={e => setForm(f => ({ ...f, username: e.target.value }))}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
                  placeholder="e.g. Rahul" />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-500 mb-1 block">Password</label>
                <input value={form.password} onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
                  placeholder="e.g. Rahul@2026" />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-500 mb-1 block">Email (optional)</label>
                <input value={form.email} onChange={e => setForm(f => ({ ...f, email: e.target.value }))}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
                  placeholder="e.g. rahul@bhatiabrothers.com" />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-500 mb-1 block">Role</label>
                <select value={form.role} onChange={e => setForm(f => ({ ...f, role: e.target.value }))}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 bg-white">
                  {ROLES.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
                </select>
              </div>
            </div>

            {/* Division access */}
            <div>
              <label className="text-xs font-medium text-gray-500 mb-2 block">Division Access</label>
              <div className="flex flex-wrap gap-2">
                {divisions.map(d => (
                  <button key={d.id} type="button"
                    onClick={() => toggleFormDiv(d.id)}
                    className={`text-xs px-3 py-1.5 rounded-lg border font-medium transition ${
                      form.division_ids.includes(d.id)
                        ? "bg-indigo-600 text-white border-indigo-600"
                        : "bg-white text-gray-600 border-gray-200 hover:border-indigo-300"
                    }`}>
                    {d.name}
                  </button>
                ))}
              </div>
              <p className="text-[11px] text-gray-400 mt-1">
                {form.role === "chairman" || form.role === "gm" || form.role === "manager"
                  ? "⚠ GM / Manager / Chairman auto-get all divisions on login"
                  : form.division_ids.length === 0 ? "No divisions selected — user won't see any data" : `${form.division_ids.length} division(s) selected`}
              </p>
            </div>

            {formError && <p className="text-xs text-red-500">{formError}</p>}
            <div className="flex gap-3 pt-1">
              <button type="submit" disabled={saving}
                className="bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium px-5 py-2 rounded-xl transition disabled:opacity-50">
                {saving ? "Creating…" : "Create User"}
              </button>
              <button type="button" onClick={() => setShowForm(false)}
                className="text-sm text-gray-500 hover:text-gray-700 px-4 py-2 rounded-xl hover:bg-gray-100 transition">
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}

      {/* ── Users table ── */}
      <div className="space-y-3">
        {users.map(u => (
          <div key={u.id} className="bg-white border border-gray-200 rounded-2xl overflow-hidden shadow-sm">
            {/* ── Edit user details ── */}
            {editUser?.id === u.id ? (
              <form onSubmit={handleUpdate} className="p-5 space-y-4">
                <h3 className="font-semibold text-gray-700">Edit — {u.username}</h3>
                <div className="grid grid-cols-3 gap-4">
                  <div>
                    <label className="text-xs font-medium text-gray-500 mb-1 block">Full Name</label>
                    <input value={editUser.name} onChange={e => setEditUser(p => ({ ...p, name: e.target.value }))}
                      className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400" />
                  </div>
                  <div>
                    <label className="text-xs font-medium text-gray-500 mb-1 block">Password</label>
                    <input value={editUser.password} onChange={e => setEditUser(p => ({ ...p, password: e.target.value }))}
                      className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400" />
                  </div>
                  <div>
                    <label className="text-xs font-medium text-gray-500 mb-1 block">Role</label>
                    <select value={editUser.role} onChange={e => setEditUser(p => ({ ...p, role: e.target.value }))}
                      className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400">
                      {ROLES.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
                    </select>
                  </div>
                </div>
                {formError && <p className="text-xs text-red-500">{formError}</p>}
                <div className="flex gap-3">
                  <button type="submit" disabled={saving}
                    className="bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium px-5 py-2 rounded-xl transition disabled:opacity-50">
                    {saving ? "Saving…" : "Save Changes"}
                  </button>
                  <button type="button" onClick={() => { setEditUser(null); setFormError(""); }}
                    className="text-sm text-gray-500 hover:text-gray-700 px-4 py-2 rounded-xl hover:bg-gray-100 transition">
                    Cancel
                  </button>
                </div>
              </form>
            ) : (
              <div className="px-5 py-4 flex items-center gap-4">
                {/* Avatar */}
                <div className="w-10 h-10 rounded-xl bg-indigo-100 flex items-center justify-center flex-shrink-0">
                  <span className="text-sm font-bold text-indigo-700">
                    {(u.name || u.username).slice(0, 2).toUpperCase()}
                  </span>
                </div>

                {/* Info */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-semibold text-gray-800 text-sm">{u.name}</span>
                    <span className={`text-[10px] px-2 py-0.5 rounded border font-semibold uppercase tracking-wide ${ROLE_COLORS[u.role] || "bg-gray-100 text-gray-600 border-gray-200"}`}>
                      {ROLE_LABELS[u.role] || u.role}
                    </span>
                  </div>
                  <p className="text-xs text-gray-400 mt-0.5">
                    @{u.username} · password: {showPass[u.id] ? u.password : "••••••••"}
                    <button onClick={() => setShowPass(p => ({ ...p, [u.id]: !p[u.id] }))}
                      className="ml-1.5 text-indigo-400 hover:text-indigo-600 text-[10px]">
                      {showPass[u.id] ? "hide" : "show"}
                    </button>
                  </p>
                </div>

                {/* Actions */}
                <div className="flex items-center gap-2 flex-shrink-0">
                  <button
                    onClick={() => { setEditDiv(u); setEditDivIds(u.divisions.map(d => d.id)); }}
                    className="text-xs px-3 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:border-indigo-300 hover:text-indigo-600 transition font-medium">
                    Divisions
                  </button>
                  <button
                    onClick={() => { setEditUser({ ...u }); setFormError(""); }}
                    className="text-xs px-3 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:border-blue-300 hover:text-blue-600 transition font-medium">
                    Edit
                  </button>
                  <button
                    onClick={() => handleDelete(u.id)}
                    disabled={deletingId === u.id}
                    className="text-xs px-3 py-1.5 rounded-lg border border-gray-200 text-gray-400 hover:border-red-300 hover:text-red-500 transition disabled:opacity-40">
                    {deletingId === u.id ? "…" : "Delete"}
                  </button>
                </div>
              </div>
            )}

            {/* ── Division chips ── */}
            {editDiv?.id === u.id ? (
              <div className="border-t border-gray-100 px-5 py-4 bg-gray-50">
                <p className="text-xs font-semibold text-gray-500 mb-3">Select divisions this user can access:</p>
                <div className="flex flex-wrap gap-2 mb-4">
                  {divisions.map(d => (
                    <button key={d.id} type="button"
                      onClick={() => toggleDiv(d.id)}
                      className={`text-xs px-3 py-1.5 rounded-lg border font-medium transition ${
                        editDivIds.includes(d.id)
                          ? "bg-indigo-600 text-white border-indigo-600"
                          : "bg-white text-gray-600 border-gray-200 hover:border-indigo-300"
                      }`}>
                      {d.name}
                    </button>
                  ))}
                </div>
                <div className="flex gap-3 items-center">
                  <button onClick={handleSaveDivisions} disabled={savingDiv}
                    className="bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-medium px-4 py-1.5 rounded-lg transition disabled:opacity-50">
                    {savingDiv ? "Saving…" : "Save Divisions"}
                  </button>
                  <button onClick={() => setEditDiv(null)}
                    className="text-xs text-gray-400 hover:text-gray-600 px-3 py-1.5 rounded-lg hover:bg-gray-200 transition">
                    Cancel
                  </button>
                  <span className="text-xs text-gray-400">{editDivIds.length} selected</span>
                </div>
              </div>
            ) : (
              u.divisions.length > 0 && (
                <div className="border-t border-gray-100 px-5 py-2.5 flex flex-wrap gap-1.5">
                  {u.divisions.map(d => (
                    <span key={d.id} className="text-[11px] px-2 py-0.5 bg-slate-100 text-slate-600 rounded-md font-medium border border-slate-200">
                      {d.name}
                    </span>
                  ))}
                </div>
              )
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
