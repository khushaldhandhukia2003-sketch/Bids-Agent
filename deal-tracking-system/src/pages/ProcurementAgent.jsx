import { useState, useRef, useEffect, useMemo, memo } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import Sidebar from "../components/Sidebar";
import { VendorImport, VendorDirectory, RFQImport } from "./VendorImport";
import { API, signalDashboardRefresh, userHeaders } from "../config/api";
// ── Constants ─────────────────────────────────────────────────
const SUPPLIER_CHANNELS = [
  { id: 1,  code: "LAD", label: "Local Authorized Distributors" },
  { id: 2,  code: "GM",  label: "Grey Market / Parallel Import" },
  { id: 3,  code: "OCD", label: "Other Country Distributors" },
  { id: 4,  code: "OEM", label: "OEM Direct Factory" },
  { id: 5,  code: "ISD", label: "Industrial Surplus Dealers" },
  { id: 6,  code: "IGS", label: "Independent Global Stockists" },
  { id: 7,  code: "PSE", label: "Project Subcontractor Excess" },
  { id: 8,  code: "LMR", label: "Local Manufacturing / Reverse Engineering" },
  { id: 9,  code: "FZT", label: "Free Zone Trading Houses" },
  { id: 10, code: "B2B", label: "Industrial B2B Marketplaces" },
  { id: 11, code: "HOA", label: "Hidden Regional OEM Agents" },
  { id: 12, code: "SRC", label: "Service & Repair Companies" },
  { id: 13, code: "BGA", label: "Buying Groups / Procurement Alliances" },
  { id: 14, code: "CIS", label: "Cross-Industry Suppliers" },
  { id: 15, code: "MRO", label: "Online Retail / MRO E-commerce" },
];

const STRATEGIC_METHODS = [
  { id: 16, code: "CBN", label: "Category-Based Supplier Networks" },
  { id: 17, code: "ESP", label: "Emergency Supplier Panel" },
  { id: 18, code: "OHF", label: "Obsolete / Hard-to-Find Supplier Network" },
  { id: 19, code: "MCR", label: "Multi-Channel RFQ Strategy" },
  { id: 20, code: "SBP", label: "Strategic Brand Partnerships" },
  { id: 21, code: "PSS", label: "Partial Stocking Strategy" },
  { id: 22, code: "RRP", label: "Repair + Replacement Proposals" },
  { id: 23, code: "ABP", label: "Alternative Brand Proposal Strategy" },
  { id: 24, code: "PTA", label: "Payment-Term Arbitrage Strategy" },
  { id: 25, code: "SPS", label: "Supplier Performance Segmentation" },
];

const ALL_CHANNELS = [...SUPPLIER_CHANNELS, ...STRATEGIC_METHODS];
const DEFAULT_CHANNEL_IDS = ALL_CHANNELS.filter(ch => ["LAD","OEM","IGS","B2B"].includes(ch.code)).map(ch => ch.id);
const PROC_NAV_TABS = ["Inquiry","Analytics","Import"];
const IMPORT_SUB_TABS = [{ key: "vendors", label: "📥 Import Vendors" }, { key: "rfq_mto", label: "📦 Import RFQ + Vendors" }];

const DELIVERY_COUNTRIES = [
  "UAE", "Saudi Arabia", "Qatar", "Kuwait", "Oman", "Bahrain", "India",
];

const CODE_COLORS = {
  LAD: "bg-blue-100 text-blue-700",   GM:  "bg-yellow-100 text-yellow-700",
  OEM: "bg-purple-100 text-purple-700", ISD: "bg-orange-100 text-orange-700",
  IGS: "bg-green-100 text-green-700",  B2B: "bg-pink-100 text-pink-700",
  OCD: "bg-cyan-100 text-cyan-700",
};

const CATEGORY_COLORS = {
  0: { tag: "bg-purple-100 text-purple-800" },
  1: { tag: "bg-teal-100 text-teal-800"     },
  2: { tag: "bg-amber-100 text-amber-800"   },
  3: { tag: "bg-gray-100 text-gray-700"     },
  4: { tag: "bg-pink-100 text-pink-800"     },
};

const generateInquiryId = () => {
  const year = new Date().getFullYear();
  return `INQ-${year}-${Math.floor(Math.random() * 900) + 100}`;
};

// Use the subject/filename as inquiry ID, falling back to auto-generated
const subjectToInquiryId = (subject) => {
  if (!subject || !subject.trim()) return generateInquiryId();
  // Strip path separators and chars unsafe for a DB key / URL, collapse spaces
  return subject.trim().replace(/[\\/:*?"<>|]/g, "").replace(/\s+/g, " ").trim().slice(0, 120);
};

const generateSearchId = (inquiryId) => {
  const d = new Date();
  const stamp = `${d.getFullYear()}${String(d.getMonth()+1).padStart(2,"0")}${String(d.getDate()).padStart(2,"0")}`;
  return `SRCH-${inquiryId || "GEN"}-${stamp}`;
};

const getErrorMessage = (detail) => {
  if (!detail) return null;
  if (typeof detail === 'object') {
    if (detail.message) return detail.message;
    if (detail.error) return `${detail.error}: ${detail.message || ''}`;
    if (Array.isArray(detail)) {
      return detail.map(d => `${d.loc?.join('.') || 'Field'}: ${d.msg}`).join(', ');
    }
    return JSON.stringify(detail);
  }
  return String(detail);
};

// ── Step Indicator ────────────────────────────────────────────
const STEP_KEYS = [1, "1b", 2, 3, 4];
const StepIndicator = ({ current, onGoTo }) => {
  const steps = ["RFQ Details", "Select Items", "Source Channels", "Find Suppliers", "Review & Save"];
  const stepIndex = { 1: 1, "1b": 2, 2: 3, 3: 4, 4: 5 }[current] || 1;
  return (
    <div className="flex items-center gap-0 px-5 py-0 bg-white border-b border-gray-200 overflow-x-auto flex-shrink-0">
      {steps.map((s, i) => {
        const idx = i + 1;
        const done = idx < stepIndex;
        const active = idx === stepIndex;
        return (
          <div key={s} className="flex items-center shrink-0">
            {done && onGoTo ? (
              <button onClick={() => onGoTo(STEP_KEYS[i])}
                className="flex items-center gap-1.5 px-4 py-3 text-xs font-medium text-indigo-600 hover:text-indigo-800 hover:bg-indigo-50 transition cursor-pointer border-b-2 border-transparent hover:border-indigo-300">
                <svg className="w-3 h-3 text-indigo-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}><path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7"/></svg>
                {s}
              </button>
            ) : (
              <div className={`flex items-center gap-1.5 px-4 py-3 text-xs font-semibold border-b-2 transition
                ${active
                  ? "text-indigo-700 border-indigo-600"
                  : "text-gray-400 border-transparent"}`}>
                <span className={`w-4 h-4 rounded-full flex items-center justify-center text-[10px] font-bold flex-shrink-0
                  ${active ? "bg-indigo-600 text-white" : "bg-gray-200 text-gray-500"}`}>{idx}</span>
                {s}
              </div>
            )}
            {i < steps.length - 1 && (
              <svg className={`w-3.5 h-3.5 flex-shrink-0 ${done ? "text-indigo-300" : "text-gray-300"}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7"/></svg>
            )}
          </div>
        );
      })}
    </div>
  );
};

// ── VendorCard — module level to prevent remount on state change ──
const VendorCard = memo(({ s, kept, isNew, onToggle, onEditEmails, onDelete }) => {
  const emails = s.emails?.length ? s.emails : s.email ? [s.email] : [];
  const websiteUrl = s.website
    ? (s.website.startsWith("http") ? s.website : `https://${s.website}`)
    : null;
  const websiteDisplay = s.website?.replace(/^https?:\/\/(www\.)?/, "") || "";

  const [addingEmail, setAddingEmail] = useState(false);
  const [newEmailDraft, setNewEmailDraft] = useState("");

  const sid = s.supplier_id || s.id || null;
  const removeEmail = (idx) => {
    const updated = emails.filter((_, i) => i !== idx);
    onEditEmails && onEditEmails(s.name, updated, sid);
  };
  const commitAdd = () => {
    const parsed = newEmailDraft.split(/[,;\s]+/).map(e => e.trim()).filter(e => e.includes("@"));
    if (parsed.length > 0) {
      onEditEmails && onEditEmails(s.name, [...new Set([...emails, ...parsed])], sid);
    }
    setNewEmailDraft("");
    setAddingEmail(false);
  };

  const scoreVal = s.score ? Math.round(Math.min(10, typeof s.score === "number" ? (s.score <= 1 ? s.score * 10 : s.score) : parseFloat(s.score))) : null;

  return (
    <div className={`rounded-xl border transition-all duration-150
      ${kept
        ? "border-gray-200 bg-white shadow-sm hover:shadow-md hover:border-indigo-200"
        : "border-red-200 bg-red-50/60 opacity-55"}`}>

      {/* ── Top bar: checkbox · name · badges · score · delete ── */}
      <div className="flex items-start gap-3 px-4 pt-3 pb-2">
        <input type="checkbox" checked={kept} onChange={() => onToggle(s.name)}
          className="mt-1 w-4 h-4 rounded border-gray-300 text-indigo-600 flex-shrink-0 cursor-pointer accent-indigo-600" />

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-semibold text-gray-900 text-sm leading-tight">{s.name}</span>
            {isNew && (
              <span className="inline-flex items-center gap-1 text-[11px] bg-emerald-50 text-emerald-700 border border-emerald-200 px-2 py-0.5 rounded-full font-semibold">
                ✦ New
              </span>
            )}
            {s.preferred && <span className="text-[11px] bg-amber-50 text-amber-700 border border-amber-200 px-2 py-0.5 rounded-full font-semibold">⭐ Preferred</span>}
          </div>

          {/* sub-row: location · channel · source · score */}
          <div className="flex items-center gap-1.5 flex-wrap mt-1">
            {(s.country || s.city) && (
              <span className="inline-flex items-center gap-1 text-[11px] text-gray-500 bg-gray-100 px-2 py-0.5 rounded-md">
                📍 {s.country}{s.city ? ` · ${s.city}` : ""}
              </span>
            )}
            <span className={`text-[11px] font-bold px-2 py-0.5 rounded-md ${CODE_COLORS[s.channel_code] || "bg-gray-100 text-gray-600"}`}>{s.channel_code}</span>
            {s.source === "database"  && <span className="text-[11px] bg-blue-50 text-blue-600 border border-blue-100 px-2 py-0.5 rounded-md">🗄 DB</span>}
            {s.source === "consensus" && <span className="text-[11px] bg-teal-50 text-teal-700 border border-teal-100 px-2 py-0.5 rounded-md font-semibold">🤝 Consensus</span>}
            {(s.source === "groq" || s.source === "groq_ranking") && <span className="text-[11px] bg-orange-50 text-orange-600 border border-orange-100 px-2 py-0.5 rounded-md">⚡ AI</span>}
            {scoreVal !== null && (
              <span className={`text-[11px] font-bold px-2 py-0.5 rounded-md ${scoreVal >= 8 ? "bg-green-50 text-green-700 border border-green-200" : scoreVal >= 6 ? "bg-indigo-50 text-indigo-700 border border-indigo-200" : "bg-gray-50 text-gray-500 border border-gray-200"}`}>
                {scoreVal}/10
              </span>
            )}
          </div>
        </div>

        {onDelete && (
          <button onClick={() => { if (window.confirm(`Remove ${s.name}?`)) onDelete(s.name); }}
            title="Remove vendor"
            className="inline-flex items-center justify-center w-8 h-8 rounded-lg text-gray-300 hover:text-red-500 hover:bg-red-50 active:scale-90 transition flex-shrink-0 cursor-pointer mt-0.5">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
          </button>
        )}
      </div>

      {/* ── Description ── */}
      {(s.description || s.sourcing_rationale || s.brands) && (
        <div className="px-4 pb-2 space-y-0.5">
          {s.description && <p className="text-xs text-gray-500 leading-relaxed">{s.description}</p>}
          {s.sourcing_rationale && s.sourcing_rationale !== s.description && (
            <p className="text-xs text-indigo-400 italic">→ {s.sourcing_rationale}</p>
          )}
          {s.brands && <p className="text-[11px] text-gray-400">Brands: {s.brands}</p>}
        </div>
      )}

      {/* ── Contact details ── */}
      {(emails.length > 0 || s.phone || websiteUrl || onEditEmails) && (
        <div className="px-4 py-2.5 border-t border-gray-100 bg-gray-50/60 rounded-b-xl space-y-2">

          {/* Emails */}
          <div className="flex items-start gap-2 flex-wrap">
            <svg className="w-3.5 h-3.5 text-gray-400 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><path strokeLinecap="round" strokeLinejoin="round" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/></svg>
            <div className="flex items-center gap-1.5 flex-wrap flex-1">
              {emails.length > 0 ? emails.map((e, i) => (
                <span key={i} className="inline-flex items-center gap-1 text-[11px] text-blue-700 bg-blue-50 border border-blue-100 px-2 py-1 rounded-lg font-mono">
                  <a href={`mailto:${e}`} className="hover:underline cursor-pointer">{e}</a>
                  {onEditEmails && (
                    <button onClick={(ev) => { ev.preventDefault(); ev.stopPropagation(); removeEmail(i); }} title="Remove"
                      className="inline-flex items-center justify-center w-5 h-5 ml-0.5 rounded-full text-blue-300 hover:bg-red-100 hover:text-red-600 transition cursor-pointer flex-shrink-0 font-bold text-sm leading-none">×</button>
                  )}
                </span>
              )) : <span className="text-[11px] text-gray-400 italic">No email found</span>}
              {onEditEmails && !addingEmail && (
                <button onClick={() => setAddingEmail(true)}
                  className="text-[11px] text-indigo-600 hover:text-indigo-800 bg-indigo-50 hover:bg-indigo-100 border border-indigo-200 px-2.5 py-1 rounded-lg transition font-semibold cursor-pointer">
                  + Add
                </button>
              )}
            </div>
          </div>

          {addingEmail && (
            <div className="flex items-center gap-2 ml-5">
              <input value={newEmailDraft} onChange={e => setNewEmailDraft(e.target.value)}
                placeholder="email@example.com or paste multiple"
                className="text-xs border border-indigo-300 rounded-lg px-3 py-1.5 font-mono flex-1 focus:outline-none focus:ring-2 focus:ring-indigo-400"
                autoFocus
                onKeyDown={e => { if (e.key === "Enter") commitAdd(); if (e.key === "Escape") { setAddingEmail(false); setNewEmailDraft(""); } }}
              />
              <button onClick={commitAdd} className="text-xs bg-indigo-600 text-white px-3 py-1.5 rounded-lg hover:bg-indigo-700 font-medium cursor-pointer">Add</button>
              <button onClick={() => { setAddingEmail(false); setNewEmailDraft(""); }} className="text-xs bg-white border border-gray-300 text-gray-500 px-3 py-1.5 rounded-lg hover:bg-gray-50 cursor-pointer">✕</button>
            </div>
          )}

          {/* Phone + Website row */}
          {(s.phone || websiteUrl) && (
            <div className="flex items-center gap-4 flex-wrap">
              {s.phone && (
                <div className="flex items-center gap-1.5">
                  <svg className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><path strokeLinecap="round" strokeLinejoin="round" d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z"/></svg>
                  <span className="text-[11px] text-gray-600 font-mono">{s.phone}</span>
                </div>
              )}
              {websiteUrl && (
                <div className="flex items-center gap-1.5">
                  <svg className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><path strokeLinecap="round" strokeLinejoin="round" d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9m-9 9a9 9 0 019-9"/></svg>
                  <a href={websiteUrl} target="_blank" rel="noopener noreferrer"
                    className="text-[11px] text-blue-600 hover:text-blue-800 hover:underline truncate max-w-[200px] cursor-pointer font-medium">
                    {websiteDisplay}
                  </a>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
});

// ── STEP 1 ────────────────────────────────────────────────────
const Step1 = ({ data, setData, onNext, onMultiItem }) => {
  const set = (k, v) => setData(p => ({ ...p, [k]: v }));
  const valid = data.partNumber && data.quantity && data.description;
  const fileRef = useRef(null);
  const [parsing, setParsing] = useState(false);
  const [parsedFile, setParsedFile] = useState(null);
  const [parseError, setParseError] = useState("");
  const [inputMode, setInputMode] = useState("file");
  const [pasteText, setPasteText] = useState("");
  const [pendingMulti, setPendingMulti] = useState(null);
  const [divisions, setDivisions] = useState([]);
  const [aiFilledClient, setAiFilledClient] = useState(false);

  // Load all divisions from API once
  useEffect(() => {
    fetch(`${API}/rfqs/divisions/all`)
      .then(r => r.json())
      .then(d => setDivisions(d.divisions || []))
      .catch(() => setDivisions([]));
  }, []);

  const _fill = (p) => {
    const item = p.items?.[0];
    // Auto-select delivery countries that appear in the parsed document delivery field
    const autoDelivery = (() => {
      if (!p.delivery) return null;
      const raw = p.delivery.toLowerCase();
      const matched = DELIVERY_COUNTRIES.filter(c => raw.includes(c.toLowerCase()));
      return matched.length > 0 ? matched.join(", ") : null;
    })();
    if (p.client) setAiFilledClient(true);
    setData(prev => ({
      ...prev,
      partNumber:  (item?.reference)                       || prev.partNumber,
      description: (item?.description)                    || (p.items?.map(i => i.description).join("; ")) || prev.description,
      quantity:    (item?.quantity)                        || prev.quantity,
      delivery:    autoDelivery                            || prev.delivery,
      customer:    p.client                               || prev.customer,
      specs:       (item?.specs || p.notes)               || prev.specs,
      subject:     prev.subject, // kept from filename set in handleFile
    }));
  };

  const [uploadedFiles, setUploadedFiles] = useState([]); // [{name, file}]

  const handleFiles = async (newFiles) => {
    if (!newFiles || newFiles.length === 0) return;
    const fileArr = Array.from(newFiles);
    // Merge with existing, avoid duplicates by name
    setUploadedFiles(prev => {
      const existingNames = new Set(prev.map(f => f.name));
      const fresh = fileArr.filter(f => !existingNames.has(f.name)).map(f => ({ name: f.name, file: f }));
      return [...prev, ...fresh];
    });
  };

  const removeUploadedFile = (name) => setUploadedFiles(prev => prev.filter(f => f.name !== name));

  const handleFile = async (file) => { handleFiles([file]); };

  const parseFiles = async () => {
    if (uploadedFiles.length === 0) return;
    setParsing(true); setParseError(""); setPendingMulti(null);
    // Auto-set subject from first filename
    set("subject", uploadedFiles[0].name.replace(/\.[^/.]+$/, ""));
    try {
      const fd = new FormData();
      if (uploadedFiles.length === 1) {
        fd.append("file", uploadedFiles[0].file);
        const res = await fetch(`${API}/inquiries/parse-and-group/upload`, { method: "POST", body: fd });
        const json = await res.json();
        if (!res.ok) throw new Error(json.detail || "Parse failed");
        setParsedFile(uploadedFiles.map(f=>f.name).join(", "));
        _fill(json);
        if (json.is_multi_item) setPendingMulti(json);
      } else {
        uploadedFiles.forEach(f => fd.append("files", f.file));
        const res = await fetch(`${API}/inquiries/parse-and-group/upload-multi`, { method: "POST", body: fd });
        const json = await res.json();
        if (!res.ok) throw new Error(json.detail || "Parse failed");
        setParsedFile(uploadedFiles.map(f=>f.name).join(", "));
        _fill(json);
        if (json.is_multi_item) setPendingMulti(json);
      }
    } catch (e) { setParseError(`Could not parse: ${e.message}`); }
    finally { setParsing(false); }
  };

  const handlePaste = async () => {
    if (!pasteText.trim()) return;
    setParsing(true); setParseError(""); setPendingMulti(null);
    try {
      const res = await fetch(`${API}/inquiries/parse-and-group`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: pasteText }),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail || "Parse failed");
      _fill(json);
      if (json.is_multi_item) setPendingMulti(json);
    } catch (e) { setParseError(`Could not parse: ${e.message}`); }
    finally { setParsing(false); }
  };

  const handleProceed = () => {
    if (pendingMulti) { onMultiItem(pendingMulti); }
    else { onNext(); }
  };

  return (
    <div className="p-6">
      <h2 className="text-xl font-bold text-gray-800 mb-1">📋 Step 1 — Inquiry Input</h2>
      <p className="text-sm text-gray-500 mb-4">Upload a document or paste text — AI extracts all items automatically.</p>
      <div className="flex gap-2 mb-4">
        {["file","paste"].map(m => (
          <button key={m} onClick={() => setInputMode(m)}
            className={`px-4 py-1.5 rounded-lg text-sm font-medium border transition
              ${inputMode===m ? "bg-indigo-600 text-white border-indigo-600" : "bg-white text-gray-600 border-gray-300 hover:bg-gray-50"}`}>
            {m === "file" ? "Upload file" : "Paste text"}
          </button>
        ))}
      </div>
      {inputMode === "file" && (
        <div className="mb-4 space-y-3">
          {/* Drop zone */}
          <div onDragOver={e=>e.preventDefault()} onDrop={e=>{e.preventDefault();handleFiles(e.dataTransfer.files);}}
            onClick={()=>!parsing&&fileRef.current?.click()}
            className={`border-2 border-dashed rounded-xl px-5 py-5 flex items-center gap-4 cursor-pointer transition
              ${parsing?"border-indigo-300 bg-indigo-50":"border-gray-300 hover:border-indigo-400 hover:bg-indigo-50"}`}>
            <div className="text-3xl">{parsing?"⏳":"📎"}</div>
            <div className="flex-1">
              {parsing
                ? <div className="flex items-center gap-2 text-indigo-600"><div className="w-4 h-4 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin"/><span className="text-sm font-medium">Extracting items from {uploadedFiles.length} file{uploadedFiles.length!==1?"s":""}...</span></div>
                : <div>
                    <p className="text-sm font-semibold text-gray-700">Attach RFQ / PO / Inquiry Documents</p>
                    <p className="text-xs text-gray-400 mt-0.5">PDF, DOCX, XLSX, PNG, JPG — any format · multiple files allowed</p>
                  </div>}
            </div>
            <input ref={fileRef} type="file" multiple
              accept=".pdf,.docx,.doc,.txt,.csv,.xlsx,.xls,.xlsm,.png,.jpg,.jpeg,.webp,.bmp,.gif"
              className="hidden" onChange={e=>handleFiles(e.target.files)} />
          </div>

          {/* File list */}
          {uploadedFiles.length > 0 && (
            <div className="space-y-1.5">
              {uploadedFiles.map(f => (
                <div key={f.name} className="flex items-center gap-2 bg-gray-50 border border-gray-200 rounded-lg px-3 py-2">
                  <span className="text-base">📄</span>
                  <span className="text-sm text-gray-700 flex-1 truncate">{f.name}</span>
                  {!parsing && (
                    <button onClick={e=>{e.stopPropagation();removeUploadedFile(f.name);}}
                      className="text-gray-400 hover:text-red-500 transition flex-shrink-0">
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>
                    </button>
                  )}
                </div>
              ))}
              <div className="flex items-center gap-2 pt-1">
                <button onClick={parseFiles} disabled={parsing}
                  className="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 text-white px-5 py-2 rounded-lg text-sm font-semibold transition">
                  {parsing
                    ? <><div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"/>Extracting...</>
                    : <>Extract items from {uploadedFiles.length} file{uploadedFiles.length!==1?"s":""} →</>}
                </button>
                {!parsing && <button onClick={()=>setUploadedFiles([])} className="text-xs text-gray-400 hover:text-red-500 transition">Clear all</button>}
              </div>
            </div>
          )}
        </div>
      )}
      {inputMode === "paste" && (
        <div className="mb-4">
          <textarea value={pasteText} onChange={e=>setPasteText(e.target.value)} rows={6}
            placeholder="Paste your inquiry here — email body, table, WhatsApp text, anything..."
            className="w-full border border-gray-300 rounded-xl px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"/>
          <button onClick={handlePaste} disabled={!pasteText.trim()||parsing}
            className="mt-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 text-white px-6 py-2 rounded-lg text-sm font-medium transition flex items-center gap-2">
            {parsing?<><div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"/>Extracting...</>:"Extract items →"}
          </button>
        </div>
      )}
      {parseError && <p className="text-xs text-red-500 mb-4">⚠️ {parseError}</p>}
      {parsedFile && !parsing && !parseError && (
        <div className="bg-green-50 border border-green-200 rounded-lg px-4 py-2.5 mb-3 flex items-center gap-2">
          <span className="text-green-600 text-sm">✅</span>
          <p className="text-xs text-green-700 font-medium">
            Document parsed — fields auto-filled below. Review and edit if needed, then click <strong>Create Inquiry</strong>.
          </p>
        </div>
      )}
      <div className="flex items-center gap-3 my-4">
        <div className="flex-1 h-px bg-gray-200"/><span className="text-xs text-gray-400 font-medium">or fill in manually</span><div className="flex-1 h-px bg-gray-200"/>
      </div>
      <div className="grid grid-cols-2 gap-4">
        {[{label:"Part Number",key:"partNumber",placeholder:"e.g. ABB ACS880-01-045A-3",required:true},
          {label:"Quantity",key:"quantity",placeholder:"e.g. 5 Units",required:true}].map(f=>(
          <div key={f.key}>
            <label className="text-sm font-medium text-gray-700 mb-1 block">{f.label}{f.required&&<span className="text-red-500"> *</span>}</label>
            <input value={data[f.key]} onChange={e=>set(f.key,e.target.value)} placeholder={f.placeholder}
              className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"/>
          </div>
        ))}
        <div>
          <label className="text-sm font-medium text-gray-700 mb-1 block">Division</label>
          <select value={data.team} onChange={e=>{set("team",e.target.value); set("customer","");}}
            className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 bg-white">
            {divisions.length > 0
              ? divisions.map(d => <option key={d.id} value={d.name}>{d.name}</option>)
              : ["ISD-EPC","RENTAL","C&J","PRO","AUTO","CPD","BB EXPORT","PETROGULF","MRO","TPE","O&G EPC"].map(t=><option key={t}>{t}</option>)
            }
          </select>
        </div>
        <div>
          <label className="text-sm font-medium text-gray-700 mb-1 flex items-center gap-2">
            Client
            {aiFilledClient && data.customer && <span className="text-xs bg-indigo-50 text-indigo-600 border border-indigo-200 px-2 py-0.5 rounded-full font-normal">✨ AI filled</span>}
          </label>
          <datalist id="client-suggestions">
            <option value="ADNOC"/>
            <option value="DEWA"/>
            <option value="QatarEnergy"/>
            <option value="ADDC"/>
            <option value="TAQA"/>
            <option value="ENOC"/>
            <option value="Dubai Petroleum Establishment"/>
            <option value="Doha Petroleum Construction Co. W.L.L."/>
            <option value="EPIC"/>
            <option value="ARAMCO"/>
            <option value="Kuwait Oil Company"/>
            <option value="PDO"/>
            <option value="BAPCO"/>
          </datalist>
          <input
            list="client-suggestions"
            value={data.customer}
            onChange={e=>{set("customer",e.target.value);setAiFilledClient(false);}}
            placeholder="AI fills from document, or type / select here"
            className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </div>
      </div>

      {/* Delivery Countries — multi-select checkboxes */}
      {(() => {
        const selected = data.delivery ? data.delivery.split(",").map(c=>c.trim()).filter(Boolean) : [];
        const toggle = (c) => {
          const next = selected.includes(c) ? selected.filter(x=>x!==c) : [...selected, c];
          set("delivery", next.join(", "));
        };
        return (
          <div className="mt-4">
            <label className="text-sm font-medium text-gray-700 mb-2 block">
              Delivery Requirement (Countries)
              {selected.length > 0 && <span className="ml-2 text-xs text-indigo-600 font-normal">{selected.length} selected</span>}
            </label>
            <div className="flex flex-wrap gap-2">
              {DELIVERY_COUNTRIES.map(c => {
                const on = selected.includes(c);
                return (
                  <button key={c} type="button" onClick={()=>toggle(c)}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium border transition-all ${
                      on ? "bg-indigo-600 text-white border-indigo-600 shadow-sm"
                         : "bg-white text-gray-600 border-gray-300 hover:border-indigo-400 hover:text-indigo-600"
                    }`}>
                    <span className={`w-4 h-4 rounded border flex items-center justify-center text-xs flex-shrink-0 ${
                      on ? "bg-white border-white text-indigo-600" : "border-gray-400"
                    }`}>{on ? "✓" : ""}</span>
                    {c}
                  </button>
                );
              })}
            </div>
            {selected.length > 0 && (
              <p className="mt-2 text-xs text-gray-500">Selected: {selected.join(" · ")}</p>
            )}
          </div>
        );
      })()}

      <div className="mt-4">
        <label className="text-sm font-medium text-gray-700 mb-1 block">
          Inquiry <span className="text-red-500">*</span>
        </label>
        <textarea value={data.description} onChange={e=>set("description",e.target.value)} rows={4}
          placeholder="Describe the equipment, part details, use case, urgency..."
          className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"/>
      </div>
      <div className="mt-4">
        <label className="text-sm font-medium text-gray-700 mb-1 block">
          Prompt
          <span className="text-xs text-gray-400 font-normal ml-2">optional — extra instructions for vendor search</span>
        </label>
        <textarea value={data.extraInstructions||""} onChange={e=>set("extraInstructions",e.target.value)} rows={2}
          placeholder="e.g. Focus on GCC suppliers, prefer ISO certified, exclude China..."
          className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"/>
      </div>
      <div className="mt-4">
        <label className="text-sm font-medium text-gray-700 mb-1 block">
          Mail Subject
          <span className="text-xs text-gray-400 font-normal ml-2">appears as title in the vendor Excel export</span>
        </label>
        <input value={data.subject||""} onChange={e=>set("subject",e.target.value)}
          placeholder="e.g. RFQ — GOR/BS682/N O-Ring — DEWA — INQ-2026-218"
          className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"/>
      </div>
      <button onClick={handleProceed} disabled={!valid || parsing}
        className="mt-6 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed text-white px-8 py-3 rounded-lg font-semibold text-sm transition flex items-center gap-2">
        {pendingMulti
          ? `Create Inquiry → (${pendingMulti.items?.length || ""} items detected)`
          : "Create Inquiry →"}
      </button>
    </div>
  );
};

// ── STEP 1b ───────────────────────────────────────────────────
const Step1b = ({ parsedInquiry, completedItems, masterInquiryId, onStartBatch, onBack }) => {
  const items  = parsedInquiry.items  || [];
  const groups = parsedInquiry.category_groups || [];
  const pending = items.filter(it => !completedItems.includes(it.description));
  const [selected, setSelected] = useState([]);
  const [searchMode, setSearchMode] = useState("individual");
  const done = completedItems.length;
  const multiSelected = selected.length > 1;

  const toggleItem = (desc) => setSelected(p => p.includes(desc) ? p.filter(d=>d!==desc) : [...p,desc]);
  const toggleAll = () => {
    const pd = pending.map(it=>it.description);
    setSelected(pd.every(d=>selected.includes(d)) ? [] : pd);
  };
  const getCat = (desc) => {
    const idx = groups.findIndex(g=>g.items.some(it=>it.description===desc));
    return { cat: groups[idx], idx };
  };
  const selectedItems = items.filter(it=>selected.includes(it.description));

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-1">
        <h2 className="text-xl font-bold text-gray-800">🔍 Step 1b — Select items to search</h2>
        <button onClick={onBack} className="text-sm text-gray-400 hover:text-gray-600">← Back</button>
      </div>
      <p className="text-sm text-gray-500 mb-4">Tick one or more items, choose how to search, then proceed.</p>
      <div className="flex flex-wrap gap-2 mb-4">
        {parsedInquiry.client && <span className="bg-indigo-50 text-indigo-700 text-xs font-medium px-3 py-1 rounded-full border border-indigo-200">Client: {parsedInquiry.client}</span>}
        <span className="bg-gray-100 text-gray-600 text-xs font-medium px-3 py-1 rounded-full">Delivery: {parsedInquiry.delivery||"UAE"}</span>
        {parsedInquiry.closing_date && <span className="bg-amber-50 text-amber-700 text-xs font-medium px-3 py-1 rounded-full border border-amber-200">Closes: {parsedInquiry.closing_date}</span>}
        <span className={`text-xs font-medium px-3 py-1 rounded-full border ${done===items.length&&items.length>0?"bg-green-50 text-green-700 border-green-200":"bg-gray-50 text-gray-600 border-gray-200"}`}>{done}/{items.length} done</span>
        <span className="bg-indigo-50 text-indigo-600 text-xs font-medium px-3 py-1 rounded-full border border-indigo-100 font-mono">{masterInquiryId}</span>
      </div>
      <div className="w-full bg-gray-100 rounded-full h-1.5 mb-5">
        <div className="bg-indigo-500 h-1.5 rounded-full transition-all duration-500" style={{width:`${items.length?(done/items.length)*100:0}%`}}/>
      </div>
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden mb-5">
        <div className="grid grid-cols-[36px_1fr_110px_110px] gap-2 px-4 py-2 bg-gray-50 border-b border-gray-200 items-center">
          <input type="checkbox" checked={pending.length>0&&pending.every(it=>selected.includes(it.description))} onChange={toggleAll}
            className="w-4 h-4 rounded border-gray-300 text-indigo-600 cursor-pointer"/>
          {["Description","Reference","Category"].map(h=><span key={h} className="text-xs font-semibold text-gray-400 uppercase tracking-wide">{h}</span>)}
        </div>
        {items.map((item, idx) => {
          const isDone = completedItems.includes(item.description);
          const isChecked = selected.includes(item.description);
          const { cat, idx: catIdx } = getCat(item.description);
          const colors = CATEGORY_COLORS[catIdx % 5] || CATEGORY_COLORS[0];
          return (
            <div key={idx} onClick={()=>!isDone&&toggleItem(item.description)}
              className={`grid grid-cols-[36px_1fr_110px_110px] gap-2 px-4 py-3 border-b border-gray-100 last:border-b-0 items-center transition
                ${isDone?"bg-green-50 cursor-default opacity-60":isChecked?"bg-indigo-50 cursor-pointer":"hover:bg-gray-50 cursor-pointer"}`}>
              <div onClick={e=>e.stopPropagation()}>
                {isDone ? <span className="text-green-500 text-base ml-0.5">✓</span>
                  : <input type="checkbox" checked={isChecked} onChange={()=>toggleItem(item.description)}
                      className="w-4 h-4 rounded border-gray-300 text-indigo-600 cursor-pointer"/>}
              </div>
              <div>
                <span className={`text-sm leading-snug ${isDone?"line-through text-gray-400":isChecked?"text-indigo-800 font-medium":"text-gray-800"}`}>{item.description}</span>
                {item.quantity&&!isDone&&<span className="text-xs text-gray-400 ml-2">Qty: {item.quantity} {item.unit||""}</span>}
              </div>
              <span className="text-xs text-gray-400 font-mono truncate">{item.reference||"—"}</span>
              {cat ? <span className={`text-xs font-medium px-2 py-0.5 rounded ${colors.tag}`}>{cat.category_name}</span>
                   : <span className="text-xs text-gray-400">—</span>}
            </div>
          );
        })}
      </div>
      {parsedInquiry.notes && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 mb-5">
          <p className="text-xs font-semibold text-amber-700 mb-1">⚠ Important notes</p>
          <p className="text-xs text-amber-600">{parsedInquiry.notes}</p>
        </div>
      )}
      {selected.length > 0 && (
        <div className="bg-indigo-50 border border-indigo-200 rounded-xl p-4 mb-5">
          <p className="text-sm font-semibold text-indigo-800 mb-3">
            {selected.length} item{selected.length!==1?"s":""} selected{multiSelected?" — how would you like to search?":""}
          </p>
          {multiSelected && (
            <div className="flex gap-3">
              {[{val:"individual",title:"Individual search",desc:"One focused search per item, done back to back."},
                {val:"combined", title:"Combined search",   desc:"One search for all selected items together."}].map(opt=>(
                <label key={opt.val} className={`flex-1 flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition
                  ${searchMode===opt.val?"border-indigo-400 bg-white":"border-indigo-200 bg-indigo-50 hover:bg-white"}`}>
                  <input type="radio" name="searchMode" value={opt.val} checked={searchMode===opt.val}
                    onChange={()=>setSearchMode(opt.val)} className="mt-0.5 text-indigo-600"/>
                  <div><p className="text-sm font-semibold text-indigo-800">{opt.title}</p><p className="text-xs text-indigo-500 mt-0.5">{opt.desc}</p></div>
                </label>
              ))}
            </div>
          )}
        </div>
      )}
      <div className="flex items-center gap-3">
        <button onClick={()=>onStartBatch(selectedItems, selected.length===1?"individual":searchMode)} disabled={selected.length===0}
          className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed text-white px-8 py-3 rounded-lg font-semibold text-sm transition">
          {selected.length===0?"Select items to search":selected.length===1?"Search this item →"
            :searchMode==="combined"?`Search ${selected.length} items together →`:`Search ${selected.length} items individually →`}
        </button>
        {pending.length>selected.length&&<span className="text-xs text-gray-400">{pending.length-selected.length} not selected</span>}
      </div>
    </div>
  );
};

// ── STEP 2 ────────────────────────────────────────────────────
const Step2 = ({ channels, setChannels, methods, setMethods, activeBatch, searchMode, onNext, onBack, autoDetected }) => {
  const toggle = (set, id) => set(p=>p.includes(id)?p.filter(x=>x!==id):[...p,id]);
  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-1">
        <h2 className="text-xl font-bold text-gray-800">🗂️ Step 2 — Category Select</h2>
        <button onClick={onBack} className="text-sm text-gray-400 hover:text-gray-600">← Back</button>
      </div>
      {activeBatch?.length>0&&(
        <div className="bg-indigo-50 border border-indigo-200 rounded-lg px-4 py-3 mb-4">
          <p className="text-xs font-semibold text-indigo-600 mb-1">{activeBatch.length===1?"Searching for":searchMode==="combined"?`Combined — ${activeBatch.length} items`:`Individual — ${activeBatch.length} items`}</p>
          {activeBatch.map((item,i)=><p key={i} className="text-sm font-bold text-indigo-800 leading-snug">{activeBatch.length>1?`${i+1}. `:""}{item.description}</p>)}
        </div>
      )}
      {autoDetected && (
        <div className="bg-indigo-50 border border-indigo-200 rounded-lg px-4 py-2.5 mb-3 flex items-center gap-2">
          <span className="text-indigo-500 text-sm">✦</span>
          <p className="text-xs text-indigo-700">Channels auto-selected based on item categories. Review and adjust if needed.</p>
        </div>
      )}
      <p className="text-sm text-gray-500 mb-5">Select sourcing channels and methods for this search.</p>
      <div className="grid grid-cols-2 gap-6">
        {[[SUPPLIER_CHANNELS,"A — 15 Supplier Channels",channels,setChannels],
          [STRATEGIC_METHODS,"B — 10 Strategic Methods",methods,setMethods]].map(([list,title,sel,setSel])=>(
          <div key={title}>
            <div className="flex justify-between items-center mb-3">
              <h3 className="font-semibold text-gray-700 text-sm">{title}</h3>
              <span className="text-indigo-600 text-xs font-semibold">{sel.length} selected</span>
            </div>
            <div className="space-y-2">
              {list.map(ch=>{
                const s=sel.includes(ch.id);
                return (
                  <div key={ch.id} onClick={()=>toggle(setSel,ch.id)}
                    className={`flex items-center justify-between px-3 py-2.5 rounded-lg border cursor-pointer transition text-sm
                      ${s?"border-indigo-400 bg-indigo-50":"border-gray-200 hover:border-gray-300 bg-white"}`}>
                    <div className="flex items-center gap-2">
                      <div className={`w-4 h-4 rounded border flex items-center justify-center flex-shrink-0 ${s?"bg-indigo-600 border-indigo-600":"border-gray-400"}`}>
                        {s&&<svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}><path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7"/></svg>}
                      </div>
                      <span className={`font-medium ${s?"text-indigo-800":"text-gray-700"}`}>{ch.label}</span>
                    </div>
                    <span className={`text-xs font-bold px-2 py-0.5 rounded ${CODE_COLORS[ch.code]||"bg-gray-100 text-gray-600"}`}>{ch.code}</span>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
      <button onClick={onNext} disabled={channels.length===0}
        className="mt-6 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 text-white px-8 py-3 rounded-lg font-semibold text-sm transition flex items-center gap-2">
        Discover Suppliers →
        {channels.length>0&&<span className="text-indigo-200 text-xs font-normal">Searching {channels.length} channels</span>}
      </button>
    </div>
  );
};

// ── STEP 3 — Supplier Discovery ───────────────────────────────
const Step3 = ({ activeBatch, searchMode, inquiry, channels, suppliers, setSuppliers, loading, setLoading, onNext, onBack, vendorEmailOverrides, setVendorEmailOverrides, step3State, setStep3State }) => {
  const s = step3State;
  const set3 = (key, val) => setStep3State(prev => ({ ...prev, [key]: typeof val === 'function' ? val(prev[key]) : val }));

  const discovered     = s.discovered;     const setDiscovered     = v => set3('discovered', v);
  const dbVendors      = s.dbVendors;      const setDbVendors      = v => set3('dbVendors', v);
  const newVendors     = s.newVendors;     const setNewVendors     = v => set3('newVendors', v);
  const dbSummary      = s.dbSummary;      const setDbSummary      = v => set3('dbSummary', v);
  const discSummary    = s.discSummary;    const setDiscSummary    = v => set3('discSummary', v);
  const discoveringNew = s.discoveringNew; const setDiscoveringNew = v => set3('discoveringNew', v);
  const refreshing     = s.refreshing;     const setRefreshing     = v => set3('refreshing', v);
  const targetCount    = s.targetCount;    const setTargetCount    = v => set3('targetCount', v);
  const targetInput    = s.targetInput;    const setTargetInput    = v => set3('targetInput', v);
  const error          = s.error;          const setError          = v => set3('error', v);
  const keepMap          = s.keepMap;          const setKeepMap          = v => set3('keepMap', v);
  const blacklistedNames = s.blacklistedNames; const setBlacklistedNames = v => set3('blacklistedNames', v);
  const newlyAdded       = s.newlyAdded;       const setNewlyAdded       = v => set3('newlyAdded', v);
  const everSeen         = s.everSeen;         const setEverSeen         = v => set3('everSeen', v);
  const refreshCount   = s.refreshCount;   const setRefreshCount   = v => set3('refreshCount', v);
  const chatInput      = s.chatInput;      const setChatInput      = v => set3('chatInput', v);
  const chatHistory    = s.chatHistory;    const setChatHistory    = v => set3('chatHistory', v);
  const chatSending    = s.chatSending;    const setChatSending    = v => set3('chatSending', v);
  const discoveryProgress  = s.discoveryProgress;   // {log:[], vendors:[]}
  const discoverySearchId  = s.discoverySearchId;

  // Abort controller for cancelling discovery fetch
  const discoveryAbort = useRef(null);

  const stopDiscovery = () => {
    if (discoveryAbort.current) { discoveryAbort.current.abort(); discoveryAbort.current = null; }
    setDiscoveringNew(false);
    setRefreshing(false);
  };

  // Abort any in-flight discovery when leaving this step so state is cleanly preserved
  useEffect(() => {
    return () => {
      if (discoveryAbort.current) { discoveryAbort.current.abort(); discoveryAbort.current = null; }
    };
  }, []);

  // Poll discovery progress while search is running
  useEffect(() => {
    if (!discoveringNew || !discoverySearchId) return;
    const iv = setInterval(async () => {
      try {
        const r = await fetch(`${API}/vendors/discovery-progress/${discoverySearchId}`);
        if (r.ok) {
          const d = await r.json();
          if (d.log?.length || d.vendors?.length) set3('discoveryProgress', {log: d.log||[], vendors: d.vendors||[]});
        }
      } catch {}
    }, 2000);
    return () => clearInterval(iv);
  }, [discoveringNew, discoverySearchId]);  // eslint-disable-line react-hooks/exhaustive-deps

  // Drag-to-reorder state for AI vendor list
  const dragIdx = useRef(null);
  const handleDragStart = (i) => { dragIdx.current = i; };
  const handleDragEnter = (i) => {
    if (dragIdx.current === null || dragIdx.current === i) return;
    setNewVendors(prev => {
      const arr = [...prev];
      const [item] = arr.splice(dragIdx.current, 1);
      arr.splice(i, 0, item);
      dragIdx.current = i;
      return arr;
    });
  };

  const selectedChannels = SUPPLIER_CHANNELS.filter(c=>channels.includes(c.id));
  const selectedCodes = selectedChannels.map(c=>c.code);
  const buildDesc = (extra="") => {
    const d = activeBatch.map(it => it.description).join("; ");
    const specsPart = inquiry.specs ? ` Specifications: ${inquiry.specs}` : "";
    const base = `${d}${specsPart}`;
    return extra ? `${base}. Additional requirements: ${extra}` : base;
  };
  const buildRef  = () => activeBatch.map(it=>it.reference).filter(Boolean).join(", ")||inquiry.partNumber;
  const extractBrand = () => {
    const known=["ABB","Siemens","Schneider","Honeywell","Emerson","Parker","Danfoss","Grundfos","Yokogawa","Flowserve","Spirax","Endress"];
    const t=buildDesc().toUpperCase(); return known.find(b=>t.includes(b.toUpperCase()))||null;
  };
  const extractCountry = (delivery) => {
    if (!delivery) return null;
    // ISO-2 in parentheses, e.g. "Turkmenistan (TM)"
    const iso2Map = {AE:"UAE",SA:"Saudi Arabia",QA:"Qatar",KW:"Kuwait",OM:"Oman",BH:"Bahrain",IQ:"Iraq",IR:"Iran",IN:"India",PK:"Pakistan",TR:"Turkey",EG:"Egypt",JO:"Jordan",GB:"United Kingdom",DE:"Germany",US:"United States",CN:"China",SG:"Singapore",MY:"Malaysia",KR:"South Korea",JP:"Japan",TM:"Turkmenistan",KZ:"Kazakhstan",AZ:"Azerbaijan",UZ:"Uzbekistan",TJ:"Tajikistan",KG:"Kyrgyzstan",GE:"Georgia",AM:"Armenia",RU:"Russia",UA:"Ukraine",FR:"France",IT:"Italy",ES:"Spain",NL:"Netherlands",AU:"Australia",CA:"Canada",BR:"Brazil",NG:"Nigeria",ZA:"South Africa"};
    const iso2 = delivery.match(/\(([A-Z]{2})\)/);
    if (iso2 && iso2Map[iso2[1]]) return iso2Map[iso2[1]];
    // If simple short string (no commas or 1 comma), use as-is
    const parts = delivery.split(",").map(p=>p.trim()).filter(Boolean);
    if (parts.length <= 2) return delivery.trim();
    // Scan for known country name
    const known = ["saudi arabia","united arab emirates","uae","turkmenistan","kazakhstan","azerbaijan","uzbekistan","india","pakistan","turkey","egypt","jordan","iraq","iran","oman","kuwait","bahrain","qatar","united kingdom","germany","france","italy","spain","netherlands","china","singapore","malaysia","south korea","australia","russia","ukraine","nigeria","south africa","kenya","ethiopia","ghana","thailand","vietnam","indonesia","philippines","bangladesh","sri lanka","nepal","morocco","algeria","tunisia","libya"];
    const dl = delivery.toLowerCase();
    for (const c of known.sort((a,b)=>b.length-a.length)) {
      if (new RegExp('\\b'+c+'\\b').test(dl)) {
        // return properly cased version from original string
        const idx = dl.indexOf(c);
        return delivery.slice(idx, idx+c.length);
      }
    }
    // Fallback: last non-numeric segment
    for (let i = parts.length-1; i >= 0; i--) {
      if (parts[i].length > 3 && !/^\d+$/.test(parts[i])) return parts[i];
    }
    return delivery.trim();
  };
  const extractCode = (t) => t ? SUPPLIER_CHANNELS.find(c=>t.toLowerCase().includes(c.label.toLowerCase()))?.code||null : null;
  const norm = (results, source) => (results||[]).map(v=>({
    name: v.supplier_name||v.name, country: v.country||"—", city: v.city||"",
    channel_code: extractCode(v.supplier_type||"")||v.channel_code||selectedCodes[0]||"LAD",
    authorization_type: v.authorization_type||v.supplier_type||"",
    priority_rank: v.priority_rank||null,
    rfq_response_probability: v.rfq_response_probability||"",
    quotation_speed: v.quotation_speed||"",
    description: v.match_reasons
      ? `Matched on: ${v.match_reasons.join(", ")}`
      : (v.description || v.relevance_reason || ""),
    email: v.contact_email||v.email||"", phone: v.phone||"", website: v.website||"",
    emails: (() => {
      const raw = v.emails?.length ? v.emails : (v.contact_email||v.email) ? [v.contact_email||v.email] : [];
      // flatten any comma-separated strings (e.g. from DB email column)
      return [...new Set(raw.flatMap(e => e.split(/[,;]+/).map(x=>x.trim()).filter(x=>x.includes("@"))))];
    })(),
    brands: v.brands||v.products_brands_handled||"",
    score: v.score||v.confidence_score, preferred: v.preferred, source,
    sourcing_rationale: v.sourcing_rationale || v.relevance_reason || v.description || "",
  }));

  const runDbSearch = async () => {
    setLoading(true); setError("");
    try {
      const category = activeBatch[0]?.description.split(" ").slice(0,4).join(" ");

      // ── Step 1: preferred supplier pre-check ──────────────────
      const prefParams = new URLSearchParams();
      if (category) prefParams.set("category", category);
      const prefRes = await fetch(`${API}/suppliers/preferred?${prefParams}`).catch(() => null);
      const prefData = prefRes?.ok ? await prefRes.json() : null;
      const preferredVendors = (prefData?.preferred_vendors || []).map(v => ({
        name:               v.vendor_name,
        country:            v.country,
        city:               v.city,
        email:              v.email,
        phone:              v.phone,
        website:            v.website,
        brands:             v.brands,
        channel_code:       v.channel_codes,
        confidence_score:   (v.verification_confidence || 0.9) * 10,
        sourcing_rationale: v.sourcing_rationale || "Pre-agreed preferred supplier",
        source:             "database",
        preferred:          true,
        _preferredTag:      true,
      }));

      // ── Step 2: regular DB search ─────────────────────────────
      const res = await fetch(`${API}/suppliers/search`, { method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({ keywords: buildDesc().slice(0,200),
          product_category: category,
          brand: extractBrand(), country: extractCountry(inquiry.delivery), channel_codes: selectedCodes, top_n: 10 }) });
      if (!res.ok) {
        const errData = await res.json();
        throw new Error(getErrorMessage(errData.detail) || "DB search failed");
      }
      const data = await res.json();
      const dbResults = norm(data.results,"database");

      // ── Merge: preferred first (deduplicated), then rest ──────
      const prefNames = new Set(preferredVendors.map(v => v.name?.toLowerCase()));
      const filteredDb = dbResults.filter(v => !prefNames.has(v.name?.toLowerCase()));
      const merged = [...preferredVendors, ...filteredDb];

      setDbVendors(merged); setSuppliers(merged); setDbSummary(data.query_summary||""); setDiscovered(true);
      const km={}; merged.forEach(v=>{km[v.name]=true;}); setKeepMap(km); setNewlyAdded(new Set());
      setEverSeen(new Set(merged.map(v=>v.name).filter(Boolean)));
    } catch(e){setError(`Database search failed: ${e.message}`);}
    finally{setLoading(false);}
  };

  // Normalize vendor name for fuzzy blacklist matching (strips legal suffixes)
  const normVendorName = (n) =>
    (n||"").toLowerCase()
      .replace(/\b(llc|ltd|inc|corp|co|group|trading|fze|fzc|saog|saoc|wll|bsc|pvt|private|limited)\b/g, "")
      .replace(/[^\w\s]/g, "").replace(/\s+/g, " ").trim();

  const isBlacklisted = (vendorName) => {
    if (blacklistedNames.has(vendorName)) return true;
    const norm = normVendorName(vendorName);
    for (const bl of blacklistedNames) {
      if (normVendorName(bl) === norm) return true;
    }
    return false;
  };

  const runDiscovery = async (extra="", isRefresh=false, appendMode=false) => {
    const sid = `disc-${Date.now()}-${Math.random().toString(36).slice(2,8)}`;
    set3("discoverySearchId", sid);
    set3("discoveryProgress", {log:[], vendors:[]});
    setDiscoveringNew(true); setError("");
    const controller = new AbortController();
    discoveryAbort.current = controller;
    try {
      const existing=[...everSeen];
      const blacklisted=[...blacklistedNames];
      // Send all existing websites so backend can skip their domains on Serper/LLM
      const existingWebsites = [
        ...suppliers.map(v=>v.website).filter(Boolean),
        ...newVendors.map(v=>v.website).filter(Boolean),
      ];
      const res = await fetch(`${API}/vendors/discover`, { method:"POST", headers:{"Content-Type":"application/json"},
        signal: controller.signal,
        body: JSON.stringify({ part_number:buildRef(), description:buildDesc(extra),
          quantity:activeBatch[0]?.quantity||inquiry.quantity||null,
          delivery:inquiry.delivery||null, specs:inquiry.specs||null,
          brand:extractBrand(), channel_codes:selectedCodes,
          channel_labels: selectedChannels.map(c => `${c.code}: ${c.label}`),
          existing_vendors:existing, existing_websites:existingWebsites,
          blacklisted_vendors:blacklisted,
          extra_instructions:inquiry.extraInstructions||null,
          target_count: 20, search_id: sid }) });
      if(!res.ok) { const d=(await res.json()).detail; throw new Error(typeof d==="object"?(d.message||d.error||JSON.stringify(d)):d||"Discovery failed"); }
      const data = await res.json();
      if (data.success && (!data.vendors || data.vendors.length === 0)) {
        setDiscSummary(data.query_summary || "AI discovery found no new vendors. Check the database results above.");
        setDiscoveringNew(false);
        discoveryAbort.current = null;
        return;
      }
      const n = norm(data.vendors, data.vendors?.[0]?.source||"groq")
        .filter(v => !isBlacklisted(v.name));
      const newNames = new Set(n.map(v=>v.name));
      setNewlyAdded(prev => appendMode ? new Set([...prev, ...newNames]) : newNames);
      setEverSeen(prev => new Set([...prev, ...newNames]));
      if(isRefresh) setRefreshCount(c=>c+1);
      if(appendMode) {
        // Keep ALL existing vendors as-is, just append non-duplicate new ones at the bottom
        setNewVendors(prev => {
          const existingNames = new Set(prev.map(v=>v.name));
          const fresh = n.filter(v => !existingNames.has(v.name));
          return [...prev, ...fresh];
        });
        setSuppliers(prev => {
          const existingNames = new Set(prev.map(v=>v.name));
          const fresh = n.filter(v => !existingNames.has(v.name));
          return [...prev, ...fresh];
        });
        setKeepMap(prev => { const km2={...prev}; n.forEach(v=>{if(!(v.name in km2)) km2[v.name]=true;}); return km2; });
        setDiscSummary(`Added ${n.filter(v=>!([...everSeen]).includes(v.name)).length} more vendors`);
        return;
      } else {
        // Non-append: keep checked vendors, replace unchecked with new ones
        setNewVendors(prev => {
          const kept = prev.filter(v => keepMap[v.name] !== false);
          const keptNames = new Set(kept.map(v=>v.name));
          return [...kept, ...n.filter(v => !keptNames.has(v.name))];
        });
        setSuppliers(prev => {
          const kept = prev.filter(v => keepMap[v.name] !== false);
          const keptNames = new Set(kept.map(v=>v.name));
          return [...kept, ...n.filter(v => !keptNames.has(v.name))];
        });
      }
      setKeepMap(prev => { const km2={...prev}; n.forEach(v=>{if(!(v.name in km2)) km2[v.name]=true;}); return km2; });
      setDiscSummary(data.query_summary||"");
    } catch(e){
      if (e.name !== 'AbortError') setError(`Discovery failed: ${e.message}`);
    } finally {
      discoveryAbort.current = null;
      setDiscoveringNew(false);
    }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    // Only remove vendors the user explicitly unchecked (keepMap===false); keep all others
    setDbVendors(p => p.filter(v => keepMap[v.name] !== false));
    setNewVendors(p => p.filter(v => keepMap[v.name] !== false));
    const last = chatHistory.filter(m=>m.role==="user").slice(-1)[0]?.text||"";
    await runDiscovery(last, true, false); setRefreshing(false);
  };

  const handleChat = async () => {
    if(!chatInput.trim()) return;
    const inst=chatInput.trim();
    setChatHistory(p=>[...p,{role:"user",text:inst}]); setChatInput(""); setChatSending(true);
    try {
      await runDiscovery(inst, false);
      setChatHistory(p=>[...p,{role:"system",text:`Search updated: "${inst}" — new vendors added.`}]);
    } catch(e){setChatHistory(p=>[...p,{role:"system",text:`Error: ${e.message}`}]);}
    setChatSending(false);
  };

  const toggleKeep = (name) => {
    const isKept = keepMap[name] !== false;
    if (isKept) {
      // Being unchecked → permanently blacklist this vendor
      setBlacklistedNames(bl => new Set([...bl, name]));
    } else {
      // Being re-checked → remove from blacklist
      setBlacklistedNames(bl => { const n = new Set(bl); n.delete(name); return n; });
    }
    setKeepMap(p => ({...p, [name]: !isKept}));
  };
  const allVendors  = useMemo(() => [...dbVendors, ...newVendors], [dbVendors, newVendors]);
  const keptCount   = useMemo(() => allVendors.filter(v => keepMap[v.name] !== false).length, [allVendors, keepMap]);
  const unKeptCount = useMemo(() => allVendors.filter(v => keepMap[v.name] === false).length,  [allVendors, keepMap]);

  const handleEditEmails = (vendorName, newEmails, supplierId) => {
    const patch = v => v.name === vendorName
      ? { ...v, emails: newEmails, email: newEmails[0] || v.email }
      : v;
    setSuppliers(prev => prev.map(patch));
    setDbVendors(prev => prev.map(patch));
    setNewVendors(prev => prev.map(patch));
    if (setVendorEmailOverrides) {
      setVendorEmailOverrides(prev => ({ ...prev, [vendorName]: newEmails }));
    }
    // Persist to DB for database-sourced vendors
    if (supplierId && newEmails.length > 0) {
      fetch(`${API}/suppliers/update-email`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ supplier_id: supplierId, email: newEmails[0] }),
      })
        .then(r => r.ok ? r.json() : Promise.reject(r.status))
        .then(() => console.log(`✅ Email saved to DB for ${vendorName}`))
        .catch(e => console.warn(`⚠️ Could not save email to DB for ${vendorName}:`, e));
    }
  };

  const handleDeleteVendor = (vendorName) => {
    setDbVendors(prev => prev.filter(v => v.name !== vendorName));
    setNewVendors(prev => prev.filter(v => v.name !== vendorName));
    setSuppliers(prev => prev.filter(v => v.name !== vendorName));
    setKeepMap(prev => { const n = {...prev}; delete n[vendorName]; return n; });
  };

  return (
    <div className="p-3 sm:p-6 overflow-x-hidden">
      <div className="flex items-center justify-between mb-1">
        <h2 className="text-xl font-bold text-gray-800">🔍 Step 3 — Supplier Discovery</h2>
        <button onClick={onBack} className="text-sm text-gray-400 hover:text-gray-600">← Back</button>
      </div>
      <div className="bg-indigo-50 border border-indigo-200 rounded-lg px-4 py-3 mb-4">
        <p className="text-xs font-semibold text-indigo-500 mb-0.5">{activeBatch.length===1?"Searching for":searchMode==="combined"?"Combined search":`Individual — ${activeBatch.length} items`}</p>
        {activeBatch.map((item,i)=><p key={i} className="text-sm font-bold text-indigo-800 leading-snug">{activeBatch.length>1?`${i+1}. `:""}{item.description}</p>)}
        <div className="flex gap-4 mt-1 text-xs text-indigo-400">
          <span>Delivery: {inquiry.delivery||"UAE"}</span>
          {activeBatch[0]?.quantity&&<span>Qty: {activeBatch[0].quantity}</span>}
        </div>
      </div>
      {error&&<div className="bg-red-50 border border-red-200 text-red-600 rounded-lg px-4 py-3 text-sm mb-4">⚠️ {error}</div>}
      {!discovered&&!loading&&<button onClick={runDbSearch} className="bg-indigo-600 hover:bg-indigo-700 text-white px-8 py-3 rounded-lg font-semibold text-sm transition">🗄️ Search Existing Database</button>}
      {loading&&<div className="flex items-center gap-3 py-8 text-indigo-600"><div className="w-6 h-6 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin"/><span className="font-medium">Searching supplier database...</span></div>}

      {discovered&&!loading&&(
        <>
          <div className="border border-gray-200 rounded-2xl mb-4 overflow-hidden shadow-sm">
            {dbVendors.length>0&&(
              <div className="p-4">
                <div className="flex items-center gap-2 mb-3">
                  <div className="flex items-center gap-2 bg-blue-50 border border-blue-200 px-3 py-1.5 rounded-xl">
                    <svg className="w-3.5 h-3.5 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4"/></svg>
                    <span className="text-xs font-bold text-blue-700">{dbVendors.length} from Database</span>
                  </div>
                </div>
                {dbSummary&&<p className="text-xs text-gray-400 mb-3 italic">{dbSummary}</p>}
                <div className="space-y-2.5">{dbVendors.map(s=><VendorCard key={s.name} s={s} kept={keepMap[s.name]!==false} isNew={newlyAdded.has(s.name)} onToggle={toggleKeep} onEditEmails={handleEditEmails} onDelete={handleDeleteVendor}/>)}</div>
              </div>
            )}
            {newVendors.length>0&&(
              <div className="p-4 border-t border-gray-100">
                <div className="flex items-center gap-2 mb-3 flex-wrap">
                  <div className="flex items-center gap-1.5 bg-purple-50 border border-purple-200 px-3 py-1.5 rounded-xl">
                    <span className="text-purple-600 text-sm">🤖</span>
                    <span className="text-xs font-bold text-purple-700">{newVendors.length} AI Vendors</span>
                  </div>
                  <div className="flex items-center gap-1.5 bg-teal-50 border border-teal-200 px-3 py-1.5 rounded-xl">
                    <span className="text-teal-600 text-sm">🤝</span>
                    <span className="text-xs font-bold text-teal-700">{newVendors.filter(v=>v.source==="consensus").length} Consensus</span>
                  </div>
                  {refreshCount>0&&(
                    <div className="flex items-center gap-1.5 bg-emerald-50 border border-emerald-200 px-3 py-1.5 rounded-xl">
                      <span className="text-xs font-bold text-emerald-700">✦ Round {refreshCount} · {newlyAdded.size} new</span>
                    </div>
                  )}
                </div>
                {discSummary&&<p className="text-xs text-gray-400 mb-3 italic">{discSummary}</p>}
                <div className="space-y-2.5">
                  {newVendors.map((s, i) => (
                    <div key={s.name} draggable
                      onDragStart={() => handleDragStart(i)}
                      onDragEnter={() => handleDragEnter(i)}
                      onDragEnd={() => { dragIdx.current = null; }}
                      onDragOver={e => e.preventDefault()}
                      className="cursor-grab active:cursor-grabbing [&_a]:cursor-pointer [&_button]:cursor-pointer [&_input]:cursor-pointer select-none">
                      <VendorCard s={s} kept={keepMap[s.name]!==false} isNew={newlyAdded.has(s.name)} onToggle={toggleKeep} onEditEmails={handleEditEmails} onDelete={handleDeleteVendor}/>
                    </div>
                  ))}
                </div>
                {/* Find More + Refresh — shown only when not actively discovering */}
                {!discoveringNew&&!refreshing&&(
                  <div className="flex items-center gap-2 mt-4 pt-3 border-t border-purple-100 flex-wrap">

                    <button onClick={()=>runDiscovery("",false,true)}
                      className="flex items-center gap-2 bg-purple-600 hover:bg-purple-700 active:scale-95 text-white px-4 py-2 rounded-xl font-semibold text-sm transition-all shadow-sm">
                      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}><circle cx="11" cy="11" r="8"/><path strokeLinecap="round" d="M21 21l-4.35-4.35"/></svg>
                      Find Suppliers
                    </button>

                    {/* Refresh unselected */}
                    <button onClick={handleRefresh} disabled={unKeptCount===0}
                      className="flex items-center gap-2 bg-white border border-orange-300 hover:bg-orange-50 active:scale-95 disabled:opacity-35 disabled:cursor-not-allowed text-orange-600 px-4 py-2 rounded-xl font-semibold text-sm transition-all shadow-sm">
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
                      Refresh{unKeptCount > 0 ? ` (${unKeptCount})` : ""}
                    </button>

                    {/* Find More AI Suppliers — inline beside Refresh */}
                    {newVendors.length>0&&<FindMoreBar onFindMore={async (n)=>{
                      const sid=`disc-${Date.now()}-${Math.random().toString(36).slice(2,8)}`;
                      set3("discoverySearchId",sid);set3("discoveryProgress",{log:[],vendors:[]});
                      setDiscoveringNew(true);setError("");
                      const controller=new AbortController();discoveryAbort.current=controller;
                      try{
                        const existing=[...everSeen];const blacklisted=[...blacklistedNames];
                        const existingWebsites=[...suppliers.map(v=>v.website).filter(Boolean),...newVendors.map(v=>v.website).filter(Boolean)];
                        const res=await fetch(`${API}/vendors/discover`,{method:"POST",headers:{"Content-Type":"application/json"},
                          signal:controller.signal,
                          body:JSON.stringify({part_number:buildRef(),description:buildDesc(""),
                            quantity:activeBatch[0]?.quantity||inquiry.quantity||null,
                            delivery:inquiry.delivery||null,specs:inquiry.specs||null,
                            brand:extractBrand(),channel_codes:selectedCodes,
                            channel_labels:selectedChannels.map(c=>`${c.code}: ${c.label}`),
                            existing_vendors:existing,existing_websites:existingWebsites,
                            blacklisted_vendors:blacklisted,
                            extra_instructions:inquiry.extraInstructions||null,
                            target_count:n,search_id:sid})});
                        if(!res.ok){const d=(await res.json()).detail;throw new Error(typeof d==="object"?(d.message||d.error||JSON.stringify(d)):d||"Discovery failed");}
                        const data=await res.json();
                        if(data.vendors?.length){
                          const n2=data.vendors.map(v=>({...v,isNew:true}));
                          const newNames=new Set(n2.map(v=>v.name));
                          setEverSeen(p=>new Set([...p,...newNames]));
                          setNewlyAdded(p=>new Set([...p,...newNames]));
                          setNewVendors(prev=>{const kept=prev.filter(v=>keepMap[v.name]!==false);const kn=new Set(kept.map(v=>v.name));return[...kept,...n2.filter(v=>!kn.has(v.name))];});
                          setSuppliers(prev=>{const kept=prev.filter(v=>keepMap[v.name]!==false);const kn=new Set(kept.map(v=>v.name));return[...kept,...n2.filter(v=>!kn.has(v.name))];});
                        }
                      }catch(e){if(e.name!=="AbortError")setError(e.message);}
                      setDiscoveringNew(false);discoveryAbort.current=null;
                    }}/>}
                  </div>
                )}
              </div>
            )}
          </div>

          {!discoveringNew&&!refreshing&&newVendors.length===0&&(
            <div className="flex items-center gap-3 mb-4 flex-wrap">
              
              {/* Discover button */}
              <button onClick={()=>runDiscovery("",false)}
                className="flex items-center gap-2 bg-purple-600 hover:bg-purple-700 active:scale-95 text-white px-5 py-2.5 rounded-xl font-semibold text-sm transition-all shadow-sm">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}><circle cx="11" cy="11" r="8"/><path strokeLinecap="round" d="M21 21l-4.35-4.35"/></svg>
                Discover Suppliers
              </button>
            </div>
          )}
          <RestrictedCompanies sessionRestricted={allVendors.filter(v=>keepMap[v.name]===false).map(v=>v.name)} />

          {(discoveringNew||refreshing)&&(()=>{
            const vendors  = discoveryProgress?.vendors || [];
            const verified = vendors.filter(v=>v.status==="verified").length;
            const dropped  = vendors.filter(v=>v.status==="dropped").length;
            const total    = vendors.length;
            const phase    = (discoveryProgress?.log||[]).filter(l=>l.startsWith("[Step")).slice(-1)[0]||"";
            return (
              <div className="mb-4 rounded-xl overflow-hidden border border-gray-800 bg-gray-950">
                {/* ── Header ── */}
                <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-800">
                  <div className="w-3 h-3 border-2 border-purple-400 border-t-transparent rounded-full animate-spin flex-shrink-0"/>
                  <span className="text-white font-semibold text-sm">
                    {refreshing ? "Refreshing…" : "Discovering vendors…"}
                  </span>
                  {total > 0 && (
                    <span className="text-xs text-gray-400">
                      <span className="text-green-400 font-semibold">{verified}</span> found
                      {dropped>0 && <> · <span className="text-red-400">{dropped}</span> skipped</>}
                      {" "}/ {total} checked
                    </span>
                  )}
                  <button
                    onClick={stopDiscovery}
                    className="ml-auto flex items-center gap-1.5 px-3 py-1 bg-red-600 hover:bg-red-700 text-white text-xs font-semibold rounded-lg transition flex-shrink-0">
                    ⏹ Stop
                  </button>
                </div>

                {/* ── Phase line ── */}
                {phase && (
                  <div className="px-4 py-1.5 bg-gray-900 text-purple-300 text-xs font-mono border-b border-gray-800">
                    {phase}
                  </div>
                )}

                {/* ── Vendor rows ── */}
                <div className="divide-y divide-gray-800/60 max-h-64 overflow-y-auto">
                  {vendors.length === 0 ? (
                    <div className="px-4 py-4 text-xs text-gray-500 font-mono animate-pulse">
                      AI searching for vendor names…
                    </div>
                  ) : vendors.map((v,i) => {
                    const cfg = {
                      queued:    {icon:"·", bar:"bg-gray-700",  label:"text-gray-500"},
                      searching: {icon:"›", bar:"bg-blue-500",  label:"text-blue-300"},
                      verified:  {icon:"✓", bar:"bg-green-500", label:"text-green-300"},
                      manual:    {icon:"!", bar:"bg-yellow-500",label:"text-yellow-300"},
                      dropped:   {icon:"✗", bar:"bg-red-700",   label:"text-red-400"},
                    }[v.status] || {icon:"·", bar:"bg-gray-700", label:"text-gray-500"};

                    return (
                      <div key={i} className="flex items-start gap-3 px-4 py-2.5 hover:bg-gray-900/40">
                        {/* status bar */}
                        <div className={`w-0.5 self-stretch rounded-full flex-shrink-0 ${cfg.bar}`}/>
                        {/* icon + name */}
                        <div className="flex flex-col min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span className={`text-xs font-mono font-bold ${cfg.label}`}>{cfg.icon}</span>
                            <span className="text-white text-sm font-medium truncate">{v.name}</span>
                            {v.status==="searching" && (
                              <span className="text-blue-400 text-xs animate-pulse ml-1">searching…</span>
                            )}
                          </div>
                          {/* detail row */}
                          <div className="flex gap-3 mt-0.5 text-xs flex-wrap">
                            {v.source && (
                              <span className="text-purple-400">via {v.source}</span>
                            )}
                            {v.website && (
                              <span className="text-gray-500 truncate max-w-[160px]">{v.website.replace(/^https?:\/\//,"")}</span>
                            )}
                            {v.email && (
                              <span className="text-green-400 truncate max-w-[220px]">{v.email}</span>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })()}

          {allVendors.length>0&&!discoveringNew&&!refreshing&&(
            <div className="bg-white border border-gray-200 rounded-xl px-4 py-3 mb-4 flex items-center justify-between shadow-sm">
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-green-500 inline-block"/>
                  <span className="text-sm font-bold text-green-700">{keptCount} selected</span>
                </div>
                {unKeptCount>0&&(
                  <div className="flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-orange-400 inline-block"/>
                    <span className="text-sm font-medium text-orange-600">{unKeptCount} unselected</span>
                  </div>
                )}
              </div>
              <p className="text-xs text-gray-400">Uncheck vendors to replace · use Refresh to swap them</p>
            </div>
          )}

          {/* Chat refinement */}
          <div className="border border-gray-200 rounded-xl overflow-hidden mb-5">
            <div className="bg-gray-50 px-4 py-2.5 border-b border-gray-200">
              <p className="text-sm font-semibold text-gray-700">💬 Refine vendor search</p>
              <p className="text-xs text-gray-400 mt-0.5">Tell the AI what you need — results will be added above</p>
            </div>
            {chatHistory.length>0&&(
              <div className="px-4 py-3 space-y-2 max-h-40 overflow-y-auto bg-white">
                {chatHistory.map((msg,i)=>(
                  <div key={i} className={`text-xs rounded-lg px-3 py-2 max-w-[85%] ${msg.role==="user"?"bg-indigo-50 text-indigo-800 ml-auto text-right":"bg-gray-100 text-gray-600"}`}>{msg.text}</div>
                ))}
              </div>
            )}
            <div className="flex gap-2 p-3 bg-white border-t border-gray-100">
              <input value={chatInput} onChange={e=>setChatInput(e.target.value)} onKeyDown={e=>e.key==="Enter"&&!e.shiftKey&&handleChat()}
                placeholder='e.g. "only Qatar suppliers" or "must be Flowserve authorized"'
                className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"/>
              <button onClick={handleChat} disabled={!chatInput.trim()||chatSending}
                className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 text-white px-4 py-2 rounded-lg text-sm font-medium transition flex items-center gap-1.5">
                {chatSending?<div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"/>:"Search"}
              </button>
            </div>
          </div>

          {keptCount>0&&!discoveringNew&&!refreshing&&(
            <button onClick={()=>{setSuppliers(allVendors.filter(v=>keepMap[v.name]!==false));onNext(allVendors.filter(v=>keepMap[v.name]!==false));}}
              className="bg-indigo-600 hover:bg-indigo-700 text-white px-8 py-3 rounded-lg font-semibold text-sm transition">
              Proceed to Save → ({keptCount} vendors selected)
            </button>
          )}
        </>
      )}
    </div>
  );
};

// ── STEP 4 — Save (was Step 5) ────────────────────────────────
const Step4Save = ({ activeBatch, searchMode, inquiry, suppliers, masterInquiryId, parsedInquiry, searchId, completedItems, onSaveAndReturn, onDone, onBack, vendorEmailOverrides }) => {
  const navigate = useNavigate();
  const [vendorChannels,  setVendorChannels]  = useState({});  // vendor name → [codes]
  const [saving,          setSaving]          = useState(false);
  const [saved,           setSaved]           = useState(false);
  const [saveError,       setSaveError]       = useState("");
  const [showPreview,     setShowPreview]     = useState(false);

  const isMulti    = !!parsedInquiry;
  const totalItems  = parsedInquiry?.items?.length || 0;
  // +1 because current batch items haven't been added to completedItems state yet (added on return)
  const doneCount   = (completedItems?.length || 0) + (activeBatch?.length || 0);
  const allItemsDone = isMulti && totalItems > 0 && doneCount >= totalItems;
  const newVendors  = suppliers.filter(s => s.source !== "database");
  const dbVendors  = suppliers.filter(s => s.source === "database");

  const itemDesc = activeBatch?.length > 1
    ? activeBatch.map(it => it.description).join("; ")
    : (activeBatch?.[0]?.description || inquiry.description);

  const category = parsedInquiry?.category_groups?.find(g =>
    g.items.some(it => it.description === activeBatch?.[0]?.description)
  )?.category_name || null;

  // Pre-populate channels instantly from vendor's discovered channel_code (no API call needed)
  useEffect(() => {
    const updates = {};
    for (const v of newVendors) {
      if (!vendorChannels[v.name]) {
        updates[v.name] = [v.channel_code || "IGS"];
      }
    }
    if (Object.keys(updates).length > 0) {
      setVendorChannels(p => ({ ...p, ...updates }));
    }
  }, []);

  const toggleVendorChannel = (vendorName, code) => {
    setVendorChannels(prev => {
      const current = prev[vendorName] || [];
      return {
        ...prev,
        [vendorName]: current.includes(code)
          ? current.filter(c => c !== code)
          : [...current, code],
      };
    });
  };

  // Helper — throws with detail if response is not ok
  const checkedPost = async (url, body) => {
    const res = await fetch(url, {
      method: "POST", headers: { "Content-Type": "application/json", ...userHeaders() },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
      throw new Error(getErrorMessage(err.detail) || `HTTP ${res.status} at ${url}`);
    }
    return res.json();
  };

  const handleDownload = async (mode = "combined") => {
    try {
      // Build email overrides map
      const emailOverrides = {};
      suppliers.forEach(v => {
        const overrideArr = vendorEmailOverrides?.[v.name];
        const arr = overrideArr || v.emails || (v.email ? [v.email] : []);
        if (arr.length > 0) emailOverrides[v.name] = arr.join(" / ");
      });

      // Send full vendor list inline so export works even before Save is clicked
      const inlineVendors = suppliers.map(v => {
        const overrideArr = vendorEmailOverrides?.[v.name];
        const emails = overrideArr || v.emails || (v.email ? [v.email] : []);
        return {
          name:    v.name,
          country: v.country || "",
          city:    v.city || "",
          email:   emails[0] || v.email || "",
          emails,
          phone:   v.phone || "",
          website: v.website || "",
          brands:  v.brands || "",
          score:   v.score || null,
          channel_code: (vendorChannels[v.name] || [v.channel_code || "IGS"])[0],
        };
      });

      const inquiryMeta = {
        client:       parsedInquiry?.client || inquiry.customer || "",
        delivery:     parsedInquiry?.delivery || inquiry.delivery || "",
        closing_date: parsedInquiry?.closing_date || "",
        team:         inquiry.team || "",
      };

      const res = await fetch(`${API}/vendors/export-with-emails/${masterInquiryId}?mode=${mode}&subject=${encodeURIComponent(inquiry.subject||"")}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email_overrides: emailOverrides, vendors: inlineVendors.length > 0 ? inlineVendors : null, inquiry_meta: inquiryMeta }),
      });
      if (!res.ok) throw new Error(`Export failed: ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      const safeSubject = (inquiry.subject||masterInquiryId).replace(/[\\/:*?"<>|]/g,"_").trim() || masterInquiryId;
      a.href = url; a.download = `${safeSubject}.xlsx`;
      document.body.appendChild(a); a.click();
      document.body.removeChild(a); URL.revokeObjectURL(url);
    } catch (e) { alert("Download failed: " + e.message); }
  };

  const handleSave = async () => {
    setSaving(true); setSaveError("");
    try {
      const channelCodesUsed = [...new Set(suppliers.map(s => s.channel_code))].join(", ");

      // ── Step 1: Guarantee inquiry record exists FIRST ────────
      // Without this, vendors save but the inquiry can never be found for export
      if (isMulti) {
        // Multi-item: inquiry_master was created on upload — verify it exists
        // by calling create with ON CONFLICT DO UPDATE (safe to call again)
        await checkedPost(`${API}/inquiries/master/create`, {
          inquiry_id:   masterInquiryId,
          client:       parsedInquiry?.client || null,
          delivery:     parsedInquiry?.delivery || inquiry.delivery || null,
          closing_date: parsedInquiry?.closing_date || null,
          notes:        parsedInquiry?.notes || null,
          team:         inquiry.team || null,
          total_items:  parsedInquiry?.item_count || parsedInquiry?.items?.length || 1,
          is_draft:     false,
        });
      } else {
        // Single-item: write to inquiry_history
        await checkedPost(`${API}/inquiries/save`, {
          inquiry_id:        masterInquiryId,
          part_number:       inquiry.partNumber || null,
          description:       inquiry.description || itemDesc,
          specs:             inquiry.specs || null,
          quantity:          inquiry.quantity || null,
          delivery:          inquiry.delivery || null,
          customer:          inquiry.customer || null,
          team:              inquiry.team || null,
          channel_codes:     channelCodesUsed,
          suppliers_found:   dbVendors.map(s => s.name).join(", "),
          new_vendors_found: newVendors.map(s => s.name).join(", "),
          rfq_count:         0,
        });
      }

      // ── Step 2: Save search log ──────────────────────────────
      await checkedPost(`${API}/vendors/search-log/create`, {
        search_id:         searchId,
        inquiry_id:        masterInquiryId || null,
        team:              inquiry.team || null,
        engineer:          null,
        items_searched:    itemDesc,
        search_mode:       searchMode,
        channels_used:     channelCodesUsed,
        db_vendors_found:  dbVendors.length,
        new_vendors_found: newVendors.length,
      });

      // ── Step 3: Save ALL kept vendors (DB + new) so email edits persist ────
      const allKept = suppliers;
      if (allKept.length > 0) {
        const vendorsPayload = allKept.map(v => {
          // prefer parent-level override (most reliable), then emails array, then single email
          const overrideEmails = vendorEmailOverrides?.[v.name];
          const emailsArr = overrideEmails || v.emails || (v.email ? [v.email] : []);
          const emailStr = emailsArr.length > 0 ? emailsArr.join(" / ") : (v.email || null);
          console.log(`[save] ${v.name} → emails:`, emailsArr, "→", emailStr);
          return ({
          vendor_name:        v.name,
          country:            v.country || null,
          city:               v.city || null,
          email:              emailStr,
          phone:              v.phone || null,
          website:            v.website || null,
          brands:             v.brands || null,
          description:        v.description || null,
          sourcing_rationale: v.sourcing_rationale || null,
          confidence_score:   v.score ? (v.score <= 1 ? parseFloat((v.score * 10).toFixed(1)) : v.score) : null,
          source:             v.source || null,
          channel_codes:      vendorChannels[v.name] || [v.channel_code || "IGS"],
        });});
        await checkedPost(`${API}/vendors/save`, {
          search_id:  searchId,
          inquiry_id: masterInquiryId || null,
          vendors:    vendorsPayload,
        });
        signalDashboardRefresh();

        // ── Phase 5B: Log pipeline decisions for self-learning ──
        try {
          const decisionPayload = allKept.map(v => ({
            vendor_name:      v.name,
            vendor_source:    v.source || null,
            channel_used:     (vendorChannels[v.name] || [v.channel_code])?.[0] || null,
            semantic_score:   v._semantic_relevance ?? null,
            confidence_score: v.score ? (v.score <= 1 ? parseFloat((v.score * 10).toFixed(1)) : v.score) : null,
            was_selected:     true,
          }));
          await fetch(`${API}/vendors/pipeline/log`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              inquiry_id:       masterInquiryId || null,
              search_id:        searchId,
              item_description: activeBatch.map(i => i.description).join("; "),
              vendors:          decisionPayload,
            }),
          });
        } catch(e) {
          console.warn("Pipeline log failed (non-critical):", e);
        }
      }

      // ── Step 4: Save line items (multi only) ─────────────────
      if (isMulti) {
        for (const item of activeBatch) {
          await checkedPost(`${API}/inquiries/line-item/save`, {
            inquiry_id:      masterInquiryId,
            line_ref:        item.reference || null,
            description:     item.description,
            quantity:        item.quantity || null,
            unit:            item.unit || null,
            category,
            channel_codes:   channelCodesUsed,
            suppliers_found: dbVendors.map(s => s.name).join(", "),
            new_vendors:     newVendors.map(s => s.name).join(", "),
            rfq_count:       0,
          });
        }
      }

      setSaved(true);
    } catch (e) {
      console.error("Save failed:", e.message);
      setSaveError(`Save failed: ${e.message}`);
    }
    finally { setSaving(false); }
  };

  return (
    <div className="p-4 sm:p-6">
      {/* Excel preview modal */}
      {showPreview && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-4xl max-h-[85vh] flex flex-col">
            <div className="flex items-center justify-between px-6 py-4 border-b flex-shrink-0">
              <div>
                <h3 className="text-lg font-bold text-gray-800">Excel Preview</h3>
                <p className="text-xs text-gray-500 mt-0.5">{suppliers.length} vendors · {inquiry.subject || masterInquiryId}</p>
              </div>
              <button onClick={() => setShowPreview(false)} className="text-gray-400 hover:text-gray-700 text-2xl leading-none font-light">×</button>
            </div>
            <div className="overflow-auto flex-1">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-xs text-gray-500 uppercase sticky top-0">
                  <tr>
                    {["#","Vendor Name","Auth Type","Email","Phone","City","Response %","Speed","Website"].map(h => (
                      <th key={h} className="px-3 py-3 text-left whitespace-nowrap font-semibold tracking-wide">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {suppliers.map((s, i) => {
                    const emails = vendorEmailOverrides?.[s.name] || s.emails || (s.email ? [s.email] : []);
                    const authType = s.authorization_type || s.supplier_type || "—";
                    const isAuthorized = authType.toLowerCase().includes("authorized") || authType.toLowerCase().includes("oem");
                    const speedColor = s.quotation_speed === "Very High" ? "bg-green-100 text-green-700"
                      : s.quotation_speed === "High" ? "bg-blue-100 text-blue-700"
                      : s.quotation_speed === "Medium" ? "bg-yellow-100 text-yellow-700"
                      : "bg-gray-100 text-gray-500";
                    return (
                      <tr key={i} className="hover:bg-gray-50">
                        <td className="px-3 py-2.5 text-gray-400 text-xs">{s.priority_rank || i + 1}</td>
                        <td className="px-3 py-2.5 font-medium text-gray-800 max-w-[160px]">
                          {s.is_preferred && <span className="text-yellow-500 mr-1">⭐</span>}
                          {s.name}
                        </td>
                        <td className="px-3 py-2.5">
                          <span className={`text-xs px-2 py-0.5 rounded font-medium ${isAuthorized ? "bg-green-100 text-green-700" : "bg-orange-100 text-orange-600"}`}>
                            {authType.length > 30 ? authType.slice(0, 28) + "…" : authType}
                          </span>
                        </td>
                        <td className="px-3 py-2.5 text-blue-600 font-mono text-xs max-w-[160px] truncate">{emails.join(", ") || "—"}</td>
                        <td className="px-3 py-2.5 text-gray-600 font-mono text-xs whitespace-nowrap">{s.phone || "—"}</td>
                        <td className="px-3 py-2.5 text-gray-500 text-xs whitespace-nowrap">{s.city || s.country || "UAE"}</td>
                        <td className="px-3 py-2.5 text-gray-700 text-xs font-semibold whitespace-nowrap">{s.rfq_response_probability || "—"}</td>
                        <td className="px-3 py-2.5">
                          {s.quotation_speed
                            ? <span className={`text-xs px-2 py-0.5 rounded font-medium ${speedColor}`}>{s.quotation_speed}</span>
                            : <span className="text-gray-400 text-xs">—</span>}
                        </td>
                        <td className="px-3 py-2.5 text-xs">
                          {s.website
                            ? <a href={s.website} target="_blank" rel="noreferrer" className="text-blue-500 hover:underline truncate max-w-[120px] block">{s.website.replace(/^https?:\/\/(www\.)?/, "")}</a>
                            : <span className="text-gray-400">—</span>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="border-t px-6 py-4 flex gap-3 justify-end flex-shrink-0 flex-wrap">
              <button onClick={() => setShowPreview(false)}
                className="px-4 py-2 border border-gray-300 rounded-lg text-sm text-gray-600 hover:bg-gray-50 transition">
                Close
              </button>
              <button onClick={() => { setShowPreview(false); handleDownload("combined"); }}
                className="px-6 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg text-sm font-semibold transition">
                📥 Download All Vendors
              </button>
              <button onClick={() => { setShowPreview(false); handleDownload("by_item"); }}
                className="px-6 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-semibold transition">
                📄 Download by Item
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="flex items-center justify-between mb-1">
        <h2 className="text-xl font-bold text-gray-800">💾 Step 4 — Review & Save</h2>
        {!saved && <button onClick={onBack} className="text-sm text-gray-400 hover:text-gray-600">← Back</button>}
      </div>

      {!saved ? (
        <>
          <div className="bg-indigo-50 border border-indigo-200 rounded-lg px-4 py-3 mb-5">
            <p className="text-xs text-indigo-500 mb-0.5">Saving results for</p>
            <p className="text-sm font-bold text-indigo-800 leading-snug">{itemDesc}</p>
            {isMulti && <p className="text-xs text-indigo-400 mt-0.5 font-mono">{masterInquiryId}</p>}
          </div>

          {/* Summary cards */}
          <div className="grid grid-cols-3 gap-3 mb-5">
            {[
              ["DB Vendors",  dbVendors.length,  "text-blue-600",   "bg-blue-50 border-blue-100"],
              ["New Vendors", newVendors.length,  "text-purple-600", "bg-purple-50 border-purple-100"],
              ["Total Kept",  suppliers.length,   "text-green-600",  "bg-green-50 border-green-100"],
            ].map(([label, count, tc, bg]) => (
              <div key={label} className={`${bg} border rounded-xl p-3 text-center`}>
                <p className={`text-2xl font-bold ${tc}`}>{count}</p>
                <p className="text-xs text-gray-500 mt-0.5">{label}</p>
              </div>
            ))}
          </div>

          {/* New vendors — channel review */}
          {newVendors.length > 0 && (
            <div className="mb-5">
              <h3 className="font-semibold text-gray-700 text-sm mb-2">
                📋 New Vendor Channel Classification
                <span className="text-xs font-normal text-gray-400 ml-2">Auto-detected — edit if needed before saving</span>
              </h3>
              <div className="space-y-3">
                {newVendors.map(v => {
                  const codes = vendorChannels[v.name] || [];
                  return (
                    <div key={v.name} className="border border-gray-200 rounded-xl p-4 bg-white">
                      <div className="flex items-start justify-between mb-2">
                        <div>
                          <p className="font-semibold text-gray-800 text-sm">{v.name}</p>
                          <p className="text-xs text-gray-400">{v.country}{v.city ? ` · ${v.city}` : ""} · {v.source}</p>
                        </div>
                        <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded font-medium">
                            {codes.length} channel{codes.length !== 1 ? "s" : ""}
                          </span>
                      </div>
                      {/* Channel toggles */}
                      <div className="flex flex-wrap gap-1.5 mt-2">
                        {ALL_CHANNELS.map(ch => {
                          const active = codes.includes(ch.code);
                          return (
                            <button key={ch.code} onClick={() => toggleVendorChannel(v.name, ch.code)}
                              className={`text-xs px-2 py-0.5 rounded font-medium border transition
                                ${active
                                  ? (CODE_COLORS[ch.code] || "bg-indigo-100 text-indigo-700") + " border-transparent"
                                  : "bg-white text-gray-400 border-gray-200 hover:border-gray-400"}`}>
                              {ch.code}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {saveError && <div className="bg-red-50 border border-red-200 text-red-600 rounded-lg px-4 py-3 text-sm mb-4">⚠️ {saveError}</div>}

          <button onClick={handleSave} disabled={saving}
            className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white px-8 py-3 rounded-lg font-semibold text-sm transition">
            {saving ? "💾 Saving..." : "💾 Confirm & Save"}
          </button>
        </>
      ) : (
        <div className="text-center py-8">
          <div className="text-5xl mb-4">✅</div>
          <h3 className="text-xl font-bold text-gray-800 mb-2">Saved!</h3>
          <p className="text-gray-500 text-sm mb-5">
            {suppliers.length} vendors saved · {newVendors.length} new vendors added to discovery database
          </p>

          {/* Multi-item: show download only when ALL items in this inquiry are done */}
          {isMulti && allItemsDone && (
            <div className="bg-green-50 border border-green-200 rounded-xl p-4 mb-5 text-left">
              <p className="text-sm font-semibold text-green-800 mb-3">
                All items complete — download your vendor list
              </p>
              <div className="flex gap-3 flex-wrap justify-center">
                <button onClick={() => setShowPreview(true)}
                  className="inline-flex items-center gap-2 bg-white border border-gray-300 hover:bg-gray-50 text-gray-700 px-5 py-2.5 rounded-lg text-sm font-semibold transition">
                  👁 Preview
                </button>
                <button onClick={() => handleDownload("combined")}
                  className="inline-flex items-center gap-2 bg-green-600 hover:bg-green-700 text-white px-5 py-2.5 rounded-lg text-sm font-semibold transition">
                  📥 Download All Vendors
                </button>
                <button onClick={() => handleDownload("by_item")}
                  className="inline-flex items-center gap-2 bg-indigo-600 hover:bg-indigo-700 text-white px-5 py-2.5 rounded-lg text-sm font-semibold transition">
                  📄 Download by Item
                </button>
              </div>
            </div>
          )}

          {/* Multi-item: items still remaining */}
          {isMulti && !allItemsDone && (
            <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 mb-5 text-sm text-amber-700">
              {totalItems - doneCount} item{totalItems - doneCount !== 1 ? "s" : ""} remaining — complete all items to download the full vendor list
            </div>
          )}

          {/* Single item: always show download */}
          {!isMulti && masterInquiryId && (
            <div className="mb-5 flex gap-3 flex-wrap justify-center">
              <button onClick={() => setShowPreview(true)}
                className="inline-flex items-center gap-2 bg-white border border-gray-300 hover:bg-gray-50 text-gray-700 px-5 py-2.5 rounded-lg text-sm font-semibold transition">
                👁 Preview
              </button>
              <button onClick={() => handleDownload("combined")}
                className="inline-flex items-center gap-2 bg-green-600 hover:bg-green-700 text-white px-5 py-2.5 rounded-lg text-sm font-semibold transition">
                📥 Download Vendor List (Excel)
              </button>
            </div>
          )}

          <div className="mt-2">
            {isMulti ? (
              <button onClick={() => {
                if (allItemsDone) { onDone && onDone(); }
                else { onSaveAndReturn && onSaveAndReturn(); }
              }}
                className="bg-indigo-600 hover:bg-indigo-700 text-white px-8 py-3 rounded-lg font-semibold text-sm transition">
                {allItemsDone ? "Done ✔" : "← Back to Item List"}
              </button>
            ) : (
              <button onClick={() => onDone && onDone()}
                className="bg-indigo-600 hover:bg-indigo-700 text-white px-8 py-3 rounded-lg font-semibold text-sm transition">
                Done ✔
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

// ── Analytics Dashboard ───────────────────────────────────────
const AnalyticsDashboard = () => {
  const [data,    setData]    = useState(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState("");

  useEffect(() => {
    fetch(`${API}/vendors/analytics`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(e => { setError(e.message); setLoading(false); });
  }, []);

  const exportCSV = () => { window.open(`${API}/vendors/analytics/export`, "_blank"); };

  if (loading) return <div className="p-8 text-center text-gray-500 text-sm">Loading analytics...</div>;
  if (error)   return <div className="p-8 text-center text-red-500 text-sm">⚠️ {error}</div>;
  if (!data)   return null;

  const maxCount = Math.max(...(data.by_channel||[]).map(c => c.vendor_count), 1);

  // Build team × channel matrix
  const teams    = [...new Set((data.by_team||[]).map(r => r.team))].sort();
  const teamMap  = {};
  (data.by_team||[]).forEach(r => {
    if (!teamMap[r.team]) teamMap[r.team] = {};
    teamMap[r.team][r.channel_code] = r.vendor_count;
  });

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-bold text-gray-800">📊 Vendor Discovery Analytics</h2>
          <p className="text-sm text-gray-500 mt-0.5">
            {data.total_vendors} vendors discovered across {data.total_searches} searches
          </p>
        </div>
        <button onClick={exportCSV}
          className="bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition">
          📥 Export CSV
        </button>
      </div>

      {/* Channel bar chart */}
      <h3 className="font-semibold text-gray-700 text-sm mb-3">Vendors per Channel (all teams)</h3>
      <div className="bg-white border border-gray-200 rounded-xl p-4 mb-6 overflow-x-auto">
        <div className="space-y-2 min-w-[400px]">
          {(data.by_channel||[]).map(ch => (
            <div key={ch.code} className="flex items-center gap-3">
              <span className={`text-xs font-bold px-2 py-0.5 rounded w-12 text-center flex-shrink-0 ${CODE_COLORS[ch.code]||"bg-gray-100 text-gray-600"}`}>{ch.code}</span>
              <div className="flex-1 bg-gray-100 rounded-full h-5 relative overflow-hidden">
                <div className={`h-full rounded-full transition-all duration-500 ${ch.vendor_count > 0 ? "bg-indigo-400" : "bg-gray-200"}`}
                  style={{width:`${(ch.vendor_count/maxCount)*100}%`}}/>
                {ch.vendor_count > 0 && (
                  <span className="absolute right-2 top-0 h-full flex items-center text-xs font-semibold text-indigo-800">{ch.vendor_count}</span>
                )}
              </div>
              <span className="text-xs text-gray-400 w-48 flex-shrink-0 truncate">{ch.label}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Team by team matrix */}
      {teams.length > 0 && (
        <>
          <h3 className="font-semibold text-gray-700 text-sm mb-3">Team-by-Team Breakdown</h3>
          <div className="bg-white border border-gray-200 rounded-xl overflow-hidden mb-4">
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="bg-gray-50 border-b border-gray-200">
                    <th className="px-3 py-2.5 text-left font-semibold text-gray-600">Channel</th>
                    {teams.map(t => <th key={t} className="px-3 py-2.5 text-center font-semibold text-gray-600">{t}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {ALL_CHANNELS.map((ch, i) => {
                    const hasAny = teams.some(t => (teamMap[t]||{})[ch.code] > 0);
                    if (!hasAny) return null;
                    return (
                      <tr key={ch.code} className={i % 2 === 0 ? "bg-white" : "bg-gray-50"}>
                        <td className="px-3 py-2 font-medium text-gray-700">
                          <span className={`text-xs font-bold px-1.5 py-0.5 rounded mr-1.5 ${CODE_COLORS[ch.code]||"bg-gray-100 text-gray-600"}`}>{ch.code}</span>
                          {ch.label}
                        </td>
                        {teams.map(t => {
                          const count = (teamMap[t]||{})[ch.code] || 0;
                          return (
                            <td key={t} className="px-3 py-2 text-center">
                              {count > 0
                                ? <span className="bg-indigo-100 text-indigo-700 font-semibold px-2 py-0.5 rounded">{count}</span>
                                : <span className="text-gray-300">—</span>}
                            </td>
                          );
                        })}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {teams.length === 0 && data.total_vendors === 0 && (
        <div className="bg-gray-50 border border-gray-200 rounded-xl p-8 text-center text-gray-400 text-sm">
          No vendor data yet. Complete a supplier search and save results to see analytics here.
        </div>
      )}
    </div>
  );
};

// ── Find More Bar ─────────────────────────────────────────────
const FindMoreBar = ({ onFindMore }) => {
  const [count, setCount] = useState(5);
  const [loading, setLoading] = useState(false);
  const presets = [5, 10, 15];
  return (
    <div className="flex items-center gap-2 bg-indigo-50 border border-indigo-200 rounded-xl px-4 py-2.5 flex-wrap">
      <span className="text-sm font-medium text-indigo-700 whitespace-nowrap">Find more AI suppliers:</span>
      {presets.map(n=>(
        <button key={n} onClick={async()=>{setLoading(true);await onFindMore(n);setLoading(false);}}
          disabled={loading}
          className="text-xs px-3 py-1.5 rounded-lg bg-white border border-indigo-300 text-indigo-700 font-semibold hover:bg-indigo-100 disabled:opacity-40 transition">
          +{n}
        </button>
      ))}
      <span className="text-indigo-400 text-xs">or</span>
      <input type="number" min={1} max={50} value={count}
        onChange={e=>setCount(Math.max(1,Math.min(50,Number(e.target.value))))}
        className="w-14 text-sm border border-indigo-300 rounded-lg px-2 py-1 text-center focus:outline-none focus:ring-2 focus:ring-indigo-400"/>
      <button onClick={async()=>{setLoading(true);await onFindMore(count);setLoading(false);}}
        disabled={loading||!count}
        className="text-xs px-3 py-1.5 rounded-lg bg-indigo-600 text-white font-semibold hover:bg-indigo-700 disabled:opacity-40 transition flex items-center gap-1">
        {loading?<><div className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin"/>Finding...</>:"Find"}
      </button>
    </div>
  );
};

// ── History Page ─────────────────────────────────────────────
// ── Restricted Companies (permanent blacklist) ────────────────
const RestrictedCompanies = ({ sessionRestricted = [] }) => {
  const [list,     setList]     = useState([]);
  const [input,    setInput]    = useState("");
  const [reason,   setReason]   = useState("");
  const [open,     setOpen]     = useState(false);
  const [saving,   setSaving]   = useState(false);
  const prevSessionLen = useRef(0);
  useEffect(() => {
    if (sessionRestricted.length > prevSessionLen.current) setOpen(true);
    prevSessionLen.current = sessionRestricted.length;
  }, [sessionRestricted.length]);

  const load = () =>
    fetch(`${API}/discovery/blacklist`).then(r=>r.json()).then(d=>setList(d.blacklist||[])).catch(()=>{});

  useEffect(()=>{ load(); }, []);

  const add = async () => {
    const name = input.trim();
    if (!name) return;
    setSaving(true);
    try {
      await fetch(`${API}/discovery/blacklist`, {
        method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({ company_name: name, reason: reason.trim() }),
      });
      setInput(""); setReason("");
      load();
    } finally { setSaving(false); }
  };

  const remove = async (id) => {
    await fetch(`${API}/discovery/blacklist/${id}`, { method:"DELETE" });
    setList(prev => prev.filter(e=>e.id!==id));
  };

  const clearAll = async () => {
    if (!window.confirm(`Remove all ${list.length} restricted companies?`)) return;
    await fetch(`${API}/discovery/blacklist/clear-all`, { method:"DELETE" });
    setList([]);
  };

  return (
    <div className="mb-4 border border-gray-200 rounded-xl overflow-hidden">
      <button onClick={()=>setOpen(o=>!o)}
        className="w-full flex items-center justify-between px-4 py-2.5 bg-gray-50 hover:bg-gray-100 transition text-left">
        <span className="text-sm font-semibold text-gray-700 flex items-center gap-2">
          <svg className="w-4 h-4 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636"/></svg>
          Restricted Companies
          {(list.length + sessionRestricted.length) > 0 && <span className="ml-1 text-xs bg-red-100 text-red-600 px-1.5 py-0.5 rounded-full font-medium">{list.length + sessionRestricted.length}</span>}
        </span>
        <svg className={`w-4 h-4 text-gray-400 transition-transform ${open?"rotate-180":""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7"/></svg>
      </button>
      {open && (
        <div className="px-4 pb-4 pt-3 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs text-gray-500">These companies will never appear in vendor discovery results.</p>
            {list.length > 0 && (
              <button onClick={clearAll}
                className="text-xs text-red-500 hover:text-red-700 underline font-medium whitespace-nowrap shrink-0">
                Clear All ({list.length})
              </button>
            )}
          </div>
          {/* Add form */}
          <div className="flex gap-2 flex-wrap">
            <input value={input} onChange={e=>setInput(e.target.value)}
              onKeyDown={e=>e.key==="Enter"&&add()}
              placeholder="Company name…"
              className="flex-1 min-w-[160px] border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-red-400"
            />
            <input value={reason} onChange={e=>setReason(e.target.value)}
              placeholder="Reason (optional)"
              className="flex-1 min-w-[120px] border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-gray-300"
            />
            <button onClick={add} disabled={saving||!input.trim()}
              className="bg-red-500 hover:bg-red-600 disabled:opacity-40 text-white px-3 py-1.5 rounded-lg text-sm font-semibold transition">
              {saving?"…":"+ Add"}
            </button>
          </div>
          {/* List */}
          {list.length === 0 && sessionRestricted.length === 0 && <p className="text-xs text-gray-400 italic">No companies restricted yet.</p>}
          <div className="space-y-1.5 max-h-48 overflow-y-auto">
            {sessionRestricted.map(name=>(
              <div key={`sess-${name}`} className="flex items-center justify-between bg-orange-50 border border-orange-200 rounded-lg px-3 py-2">
                <div>
                  <span className="text-sm font-medium text-gray-800">{name}</span>
                  <span className="ml-2 text-xs text-orange-500 font-medium">deselected · this RFQ only</span>
                </div>
              </div>
            ))}
            {list.map(e=>(
              <div key={e.id} className="flex items-center justify-between bg-red-50 border border-red-100 rounded-lg px-3 py-2">
                <div>
                  <span className="text-sm font-medium text-gray-800">{e.company_name}</span>
                  {e.reason && <span className="ml-2 text-xs text-gray-400">{e.reason}</span>}
                </div>
                <button onClick={()=>remove(e.id)} className="text-red-400 hover:text-red-600 transition ml-3 flex-shrink-0">
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

const EVENT_ICONS = {
  rfq_import:       "📂",
  vendor_discovery: "🔍",
  vendor_import:    "📥",
};
const EVENT_LABELS = {
  rfq_import:       "RFQ Import",
  vendor_discovery: "Vendor Discovery",
  vendor_import:    "Vendor Import",
};
const EVENT_COLORS = {
  rfq_import:       "bg-blue-50 text-blue-700 border-blue-100",
  vendor_discovery: "bg-purple-50 text-purple-700 border-purple-100",
  vendor_import:    "bg-green-50 text-green-700 border-green-100",
};

const HistoryPage = () => {
  const [inquiries,    setInquiries]    = useState([]);
  const [imports,      setImports]      = useState([]);
  const [activities,   setActivities]   = useState([]);
  const [loading,      setLoading]      = useState(true);
  const [actLoading,   setActLoading]   = useState(true);
  const [error,        setError]        = useState("");
  const [search,       setSearch]       = useState("");
  const [dateFilter,   setDateFilter]   = useState("");
  const [historyTab,        setHistoryTab]        = useState("activity");
  const [confirmDelete,     setConfirmDelete]     = useState(null);
  const [deleting,          setDeleting]          = useState(null);
  const [userFilter,        setUserFilter]        = useState("");
  const [roleFilter,        setRoleFilter]        = useState("");
  const [usersList,         setUsersList]         = useState([]);
  const [confirmImportDel,  setConfirmImportDel]  = useState(null);
  const [deletingImport,    setDeletingImport]    = useState(null);

  const loadActivities = (uFilter = userFilter, rFilter = roleFilter) => {
    setActLoading(true);
    const params = new URLSearchParams({ limit: 100 });
    if (uFilter) params.set("username", uFilter);
    if (rFilter) params.set("user_role", rFilter);
    fetch(`${API}/history?${params}`)
      .then(r => r.json())
      .then(d => { setActivities(d.events || []); })
      .catch(() => {})
      .finally(() => setActLoading(false));
  };

  const loadUsers = () => {
    fetch(`${API}/history/users`)
      .then(r => r.json())
      .then(d => setUsersList(d.users || []))
      .catch(() => {});
  };

  const loadHistory = () => {
    fetch(`${API}/inquiries/history`)
      .then(r => r.json())
      .then(d => { setInquiries(d.inquiries || []); setImports(d.imports || []); setLoading(false); })
      .catch(e => { setError(e.message); setLoading(false); });
  };

  useEffect(() => {
    loadHistory();
    loadActivities();
    loadUsers();
    window.addEventListener('dashboard:refresh', () => { loadHistory(); loadActivities(); });
    return () => window.removeEventListener('dashboard:refresh', () => { loadHistory(); loadActivities(); });
  }, []);

  const handleImportDelete = async (id) => {
    setDeletingImport(id);
    try {
      const res = await fetch(`${API}/vendors/import-log/${id}`, { method: "DELETE" });
      const data = await res.json().catch(() => ({}));
      setImports(prev => prev.filter(imp => imp.id !== id));
      setConfirmImportDel(null);
      if (data.vendors_deleted > 0) {
        signalDashboardRefresh();
      }
    } finally {
      setDeletingImport(null);
    }
  };

  const filtered = useMemo(() => inquiries.filter(inq => {
    const q = search.toLowerCase();
    if (q && !inq.inquiry_id?.toLowerCase().includes(q)
           && !inq.client?.toLowerCase().includes(q)
           && !inq.delivery?.toLowerCase().includes(q)) return false;
    if (dateFilter) {
      const created = new Date(inq.created_at).toISOString().slice(0, 10);
      if (created !== dateFilter) return false;
    }
    return true;
  }), [inquiries, search, dateFilter]);

  const hasFilters = search || dateFilter;
  const clearFilters = () => { setSearch(""); setDateFilter(""); };

  const handleDelete = async (inquiryId) => {
    setDeleting(inquiryId);
    setConfirmDelete(null);
    try {
      const res = await fetch(`${API}/vendors/delete-by-inquiry/${encodeURIComponent(inquiryId)}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Delete failed");
      setInquiries(prev => prev.filter(i => i.inquiry_id !== inquiryId));
      signalDashboardRefresh();
    } catch (e) {
      alert("Could not delete: " + e.message);
    } finally {
      setDeleting(null);
    }
  };

  if (error) return <div className="p-8 text-center text-red-500 text-sm">⚠️ {error}</div>;

  return (
    <div className="p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-xl font-bold text-gray-800">📋 History</h2>
          <p className="text-sm text-gray-500 mt-0.5">
            {loading ? "Loading..." : `${activities.length} events · ${inquiries.length} inquiries · ${imports.length} vendor imports`}
          </p>
        </div>
        {hasFilters && historyTab === "inquiries" && (
          <button onClick={clearFilters} className="text-xs text-blue-500 hover:underline">✕ Clear filters</button>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-5 border-b border-gray-200">
        <button onClick={() => setHistoryTab("activity")}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition -mb-px ${historyTab === "activity" ? "border-indigo-600 text-indigo-700" : "border-transparent text-gray-500 hover:text-gray-700"}`}>
          ⏱ Activity ({activities.length})
        </button>
        <button onClick={() => setHistoryTab("inquiries")}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition -mb-px ${historyTab === "inquiries" ? "border-indigo-600 text-indigo-700" : "border-transparent text-gray-500 hover:text-gray-700"}`}>
          📋 Inquiries ({inquiries.length})
        </button>
        <button onClick={() => setHistoryTab("imports")}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition -mb-px ${historyTab === "imports" ? "border-indigo-600 text-indigo-700" : "border-transparent text-gray-500 hover:text-gray-700"}`}>
          📥 Vendor Imports ({imports.length})
        </button>
      </div>

      {/* ── Activity Tab ── */}
      {historyTab === "activity" && (
        <div className="space-y-3">
          {/* Person / Role filters */}
          <div className="flex gap-3 flex-wrap items-center mb-2">
            <select
              value={userFilter}
              onChange={e => { setUserFilter(e.target.value); loadActivities(e.target.value, roleFilter); }}
              className="text-xs border border-gray-200 rounded-lg px-3 py-1.5 bg-white text-gray-700 focus:outline-none focus:ring-1 focus:ring-indigo-400"
            >
              <option value="">All users</option>
              {usersList.map(u => (
                <option key={u.username} value={u.username}>{u.username}</option>
              ))}
            </select>
            <select
              value={roleFilter}
              onChange={e => { setRoleFilter(e.target.value); loadActivities(userFilter, e.target.value); }}
              className="text-xs border border-gray-200 rounded-lg px-3 py-1.5 bg-white text-gray-700 focus:outline-none focus:ring-1 focus:ring-indigo-400"
            >
              <option value="">All roles</option>
              {[...new Set(usersList.map(u => u.role).filter(Boolean))].map(r => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
            {(userFilter || roleFilter) && (
              <button onClick={() => { setUserFilter(""); setRoleFilter(""); loadActivities("", ""); }}
                className="text-xs text-blue-500 hover:underline">✕ Clear</button>
            )}
          </div>

          {actLoading && <p className="text-sm text-gray-400">Loading activity…</p>}
          {!actLoading && activities.length === 0 && (
            <div className="bg-gray-50 border border-gray-200 rounded-xl p-10 text-center text-gray-400 text-sm">
              No activity logged yet. Import RFQs or run vendor discovery to see events here.
            </div>
          )}
          {!actLoading && activities.map((ev) => (
            <div key={ev.id} className="bg-white border border-gray-200 rounded-xl px-5 py-4 hover:shadow-sm transition">
              <div className="flex items-start gap-3">
                <span className="text-2xl mt-0.5">{EVENT_ICONS[ev.event_type] || "📌"}</span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-semibold text-gray-800 text-sm">{ev.title}</span>
                    <span className={`text-xs px-2 py-0.5 rounded border font-medium ${EVENT_COLORS[ev.event_type] || "bg-gray-100 text-gray-600 border-gray-200"}`}>
                      {EVENT_LABELS[ev.event_type] || ev.event_type}
                    </span>
                    {ev.username && (
                      <span className="text-xs px-2 py-0.5 rounded bg-slate-100 text-slate-600 border border-slate-200 font-medium">
                        👤 {ev.username}{ev.user_role ? ` · ${ev.user_role}` : ""}
                      </span>
                    )}
                  </div>
                  {ev.detail && <p className="text-xs text-gray-500 mt-0.5">{ev.detail}</p>}
                  <p className="text-xs text-gray-400 mt-1">
                    {ev.created_at ? new Date(ev.created_at).toLocaleString("en-GB", {day:"2-digit",month:"short",year:"numeric",hour:"2-digit",minute:"2-digit"}) : ""}
                  </p>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── Vendor Imports Tab ── */}
      {historyTab === "imports" && (
        <div className="space-y-3">
          {loading && <p className="text-sm text-gray-400">Loading...</p>}
          {!loading && imports.length === 0 && (
            <div className="bg-gray-50 border border-gray-200 rounded-xl p-10 text-center text-gray-400 text-sm">
              No vendor files imported yet. Go to the Import tab to upload a vendor list.
            </div>
          )}
          {!loading && imports.map((imp, i) => (
            <div key={imp.id ?? i} className="bg-white border border-gray-200 rounded-xl px-5 py-4 flex items-center justify-between hover:shadow-sm transition">
              <div>
                <p className="text-sm font-semibold text-gray-800">📄 {imp.filename}</p>
                <p className="text-xs text-gray-400 mt-0.5">
                  {new Date(imp.imported_at).toLocaleDateString("en-GB", {day:"2-digit",month:"short",year:"numeric"})}
                  {" · "}
                  {new Date(imp.imported_at).toLocaleTimeString("en-GB", {hour:"2-digit",minute:"2-digit"})}
                </p>
              </div>
              <div className="flex items-center gap-6">
                <div className="flex gap-6 text-center">
                  <div><p className="text-lg font-bold text-green-600">{imp.saved}</p><p className="text-xs text-gray-400">New</p></div>
                  <div><p className="text-lg font-bold text-blue-600">{imp.updated}</p><p className="text-xs text-gray-400">Updated</p></div>
                  <div><p className="text-lg font-bold text-gray-400">{imp.skipped}</p><p className="text-xs text-gray-400">Skipped</p></div>
                  <div><p className="text-lg font-bold text-gray-700">{imp.total_rows}</p><p className="text-xs text-gray-400">Total rows</p></div>
                </div>
                {confirmImportDel === imp.id ? (
                  <div className="flex gap-1.5">
                    <button onClick={() => handleImportDelete(imp.id)} disabled={deletingImport === imp.id}
                      className="bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white px-3 py-1.5 rounded-lg text-xs font-semibold transition">
                      {deletingImport === imp.id ? "…" : "Confirm"}
                    </button>
                    <button onClick={() => setConfirmImportDel(null)}
                      className="bg-gray-100 hover:bg-gray-200 text-gray-600 px-3 py-1.5 rounded-lg text-xs font-semibold transition">
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button onClick={() => setConfirmImportDel(imp.id)}
                    className="bg-red-50 hover:bg-red-100 text-red-600 border border-red-200 px-3 py-1.5 rounded-lg text-xs font-semibold transition">
                    🗑 Delete
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── Inquiries Tab ── */}
      {historyTab === "inquiries" && (
        <div>
          {/* Filters */}
          <div className="flex gap-3 mb-5 flex-wrap">
            <input value={search} onChange={e => setSearch(e.target.value)}
              placeholder="Search by ID, client, delivery…"
              className="flex-1 min-w-[200px] border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
            <input type="date" value={dateFilter} onChange={e => setDateFilter(e.target.value)}
              className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              title="Filter by creation date" />
          </div>

          {/* Skeleton */}
          {loading && (
            <div className="space-y-3">
              {[...Array(4)].map((_, i) => (
                <div key={i} className="bg-white border border-gray-100 rounded-xl px-5 py-4 animate-pulse">
                  <div className="flex items-center justify-between">
                    <div className="flex-1 space-y-2">
                      <div className="flex gap-2 flex-wrap">
                        <div className="h-4 bg-gray-200 rounded w-32" />
                        <div className="h-4 bg-gray-100 rounded w-20" />
                        <div className="h-4 bg-gray-100 rounded w-16" />
                      </div>
                      <div className="h-3 bg-gray-100 rounded w-64" />
                    </div>
                    <div className="ml-4 flex flex-col gap-2">
                      <div className="h-7 bg-gray-200 rounded-lg w-24" />
                      <div className="h-7 bg-gray-100 rounded-lg w-24" />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {!loading && filtered.length === 0 && (
            <div className="bg-gray-50 border border-gray-200 rounded-xl p-10 text-center text-gray-400 text-sm">
              {hasFilters ? "No inquiries match your filters." : "No inquiries saved yet."}
            </div>
          )}

          {!loading && filtered.length > 0 && (
            <div className="space-y-3">
              {filtered.map(inq => {
                const complete = inq.completed_items >= inq.total_items && inq.total_items > 0;
                return (
                  <div key={inq.inquiry_id} className="bg-white border border-gray-200 rounded-xl px-5 py-4 flex items-center justify-between hover:shadow-sm transition">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-3 flex-wrap mb-1">
                        <span className="font-semibold text-gray-800 text-sm">{inq.inquiry_id}</span>
                        {inq.client && inq.client !== "Unknown" && (
                          <span className="text-xs bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded border border-indigo-100">{inq.client}</span>
                        )}
                        {inq.team && <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded">{inq.team}</span>}
                        <span className={`text-xs px-2 py-0.5 rounded font-medium ${complete ? "bg-green-100 text-green-700" : "bg-amber-100 text-amber-700"}`}>
                          {inq.completed_items}/{inq.total_items} items
                        </span>
                      </div>
                      <div className="flex gap-4 text-xs text-gray-400 flex-wrap">
                        {inq.delivery     && <span>Delivery: {inq.delivery}</span>}
                        {inq.closing_date && <span>Closes: {inq.closing_date}</span>}
                        <span>{inq.new_vendor_count} new vendors discovered</span>
                        <span>Saved: {new Date(inq.created_at).toLocaleDateString("en-GB", {day:"2-digit",month:"short",year:"numeric"})}</span>
                      </div>
                    </div>
                    <div className="ml-4 flex-shrink-0 flex flex-col gap-2">
                      <a href={`${API}/vendors/export/${inq.inquiry_id}?mode=combined`}
                        target="_blank" rel="noopener noreferrer"
                        className="inline-flex items-center gap-2 bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded-lg text-xs font-semibold transition">
                        📥 All Vendors
                      </a>
                      <a href={`${API}/vendors/export/${inq.inquiry_id}?mode=by_item`}
                        target="_blank" rel="noopener noreferrer"
                        className="inline-flex items-center gap-2 bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg text-xs font-semibold transition">
                        📄 By Item
                      </a>
                      {confirmDelete === inq.inquiry_id ? (
                        <div className="flex gap-1.5">
                          <button onClick={() => handleDelete(inq.inquiry_id)} disabled={deleting === inq.inquiry_id}
                            className="flex-1 bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white px-3 py-2 rounded-lg text-xs font-semibold transition">
                            {deleting === inq.inquiry_id ? "…" : "Confirm"}
                          </button>
                          <button onClick={() => setConfirmDelete(null)}
                            className="flex-1 bg-gray-100 hover:bg-gray-200 text-gray-600 px-3 py-2 rounded-lg text-xs font-semibold transition">
                            Cancel
                          </button>
                        </div>
                      ) : (
                        <button onClick={() => setConfirmDelete(inq.inquiry_id)}
                          className="inline-flex items-center justify-center gap-2 bg-red-50 hover:bg-red-100 text-red-600 border border-red-200 px-4 py-2 rounded-lg text-xs font-semibold transition">
                          🗑 Delete
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

// ── Session-storage persistence helpers ───────────────────────
const SS_KEY = "proc_agent_state";
const loadSS = () => { try { return JSON.parse(sessionStorage.getItem(SS_KEY) || "{}"); } catch { return {}; } };
const saveSS = (val) => { try { sessionStorage.setItem(SS_KEY, JSON.stringify(val)); } catch {} };
const serS3 = (s) => ({ ...s, blacklistedNames:[...(s.blacklistedNames||[])], newlyAdded:[...(s.newlyAdded||[])], everSeen:[...(s.everSeen||[])] });
const desS3 = (s) => ({ ...s, blacklistedNames:new Set(s.blacklistedNames||[]), newlyAdded:new Set(s.newlyAdded||[]), everSeen:new Set(s.everSeen||[]), discoveringNew:false, refreshing:false, chatSending:false });
const DEFAULT_S3 = { discovered:false, dbVendors:[], newVendors:[], dbSummary:"", discSummary:"", discoveringNew:false, refreshing:false, targetCount:20, targetInput:"20", /* locked: 10 DB + 20 AI */ error:"", keepMap:{}, blacklistedNames:new Set(), newlyAdded:new Set(), everSeen:new Set(), refreshCount:0, chatInput:"", chatHistory:[], chatSending:false, discoveryProgress:{log:[],vendors:[]}, discoverySearchId:null };

// ── Main Component ────────────────────────────────────────────
export default function ProcurementAgent() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { logout } = useAuth();
  const [navTab,     setNavTab]     = useState("Inquiry");

  useEffect(() => {
    const tab = searchParams.get("tab");
    const map = { history: "History", vendors: "Vendors", analytics: "Analytics", import: "Import" };
    setNavTab(map[tab] || "Inquiry");
  }, [searchParams]);
  const [importTab,  setImportTab]  = useState("vendors");

  // Clear saved state on browser hard-refresh so the form starts blank
  if (typeof performance !== "undefined") {
    const navType = performance.getEntriesByType?.("navigation")?.[0]?.type;
    if (navType === "reload") sessionStorage.removeItem(SS_KEY);
  }

  // Restore all wizard state from sessionStorage on mount
  const _ss = loadSS();
  const [step,    setStep]    = useState(_ss.step    || 1);
  const [loading, setLoading] = useState(false);

  const [inquiry,         setInquiry]         = useState(_ss.inquiry || { partNumber:"", customer:"", quantity:"", delivery:"", team:"EPC", description:"", specs:"", subject:"", extraInstructions:"" });
  const [parsedInquiry,   setParsedInquiry]   = useState(_ss.parsedInquiry   || null);
  const [masterInquiryId, setMasterInquiryId] = useState(_ss.masterInquiryId || null);
  const [searchId,        setSearchId]        = useState(_ss.searchId        || null);
  const [activeBatch,     setActiveBatch]     = useState(_ss.activeBatch     || []);
  const [searchMode,      setSearchMode]      = useState(_ss.searchMode      || "individual");
  const [completedItems,  setCompletedItems]  = useState(_ss.completedItems  || []);

  const [channels,  setChannels]  = useState(_ss.channels  || DEFAULT_CHANNEL_IDS);
  const [methods,   setMethods]   = useState(_ss.methods   || []);
  const [suppliers, setSuppliers] = useState(_ss.suppliers || []);
  // email overrides keyed by vendor name — survives step transitions
  const [vendorEmailOverrides, setVendorEmailOverrides] = useState(_ss.vendorEmailOverrides || {});

  // Step 3 state lifted here so it survives back/forward navigation
  const [step3State, setStep3State] = useState(_ss.step3State ? desS3(_ss.step3State) : DEFAULT_S3);

  // Keep a ref with current state so the debounced saver always has the latest values
  const stateRef = useRef({});
  stateRef.current = { step, inquiry, parsedInquiry, masterInquiryId, searchId, activeBatch, searchMode, completedItems, channels, methods, suppliers, vendorEmailOverrides, step3State };

  // Debounced persist — saves 800ms after the last change, not on every keystroke
  useEffect(() => {
    const t = setTimeout(() => {
      const s = stateRef.current;
      saveSS({ ...s, step3State: serS3(s.step3State) });
    }, 800);
    return () => clearTimeout(t);
  }, [step, inquiry, parsedInquiry, masterInquiryId, searchId, activeBatch, searchMode, completedItems, channels, methods, suppliers, vendorEmailOverrides, step3State]);

  // Browser back interception
  useEffect(() => {
    const handle = () => {
      setStep(prev => { const o=[1,"1b",2,3,4]; const i=o.indexOf(prev); return i>0?o[i-1]:prev; });
      window.history.pushState(null,"",window.location.href);
    };
    window.history.pushState(null,"",window.location.href);
    window.addEventListener("popstate",handle);
    return ()=>window.removeEventListener("popstate",handle);
  }, []);
  useEffect(()=>{window.history.pushState({step},"",window.location.href);},[step]);

  const createMaster = async (data, id) => {
    try {
      // item_count from backend, fallback to items array length
      const totalItems = data.item_count || data.items?.length || 0;
      const res = await fetch(`${API}/inquiries/master/create`, { method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({ inquiry_id:id, client:inquiry.customer||data.client||null, delivery:data.delivery||null,
          closing_date:data.closing_date||null, notes:inquiry.subject||data.notes||null, team:inquiry.team, total_items:totalItems,
          is_draft: true }) });
      if (!res.ok) {
        const err = await res.json();
        console.error("Master create failed:", err.detail);
      } else {
        console.log("✅ Master inquiry created:", id, "items:", totalItems);
      }
    } catch(e){ console.error("Master create error:", e.message); }
  };

  const handleMultiItem = async (data) => {
    const newId = subjectToInquiryId(inquiry.subject);
    setParsedInquiry(data); setMasterInquiryId(newId); setCompletedItems([]);
    await createMaster(data, newId);
    setStep("1b");
  };

  const handleStartBatch = (selectedItems, mode) => {
    // Only reset Step 3 state if the selected items actually changed
    const prevDescs = activeBatch.map(it => it.description).sort().join("|");
    const newDescs  = selectedItems.map(it => it.description).sort().join("|");
    const itemsChanged = prevDescs !== newDescs;

    setActiveBatch(selectedItems); setSearchMode(mode);
    if (itemsChanged) {
      setSuppliers([]); setSearchId(generateSearchId(masterInquiryId));
      setStep3State(DEFAULT_S3);
    }

    // Auto-detect channels from the category groups of selected items
    {
      const selectedDescs = new Set(selectedItems.map(it => it.description));
      const suggestedCodes = new Set();
      if (parsedInquiry?.category_groups?.length > 0) {
        parsedInquiry.category_groups.forEach(group => {
          const groupHasSelectedItem = group.items.some(it => selectedDescs.has(it.description));
          if (groupHasSelectedItem && group.suggested_channels) {
            group.suggested_channels.forEach(code => suggestedCodes.add(code.toUpperCase()));
          }
        });
      }
      const autoIds = suggestedCodes.size > 0
        ? ALL_CHANNELS.filter(ch => suggestedCodes.has(ch.code.toUpperCase())).map(ch => ch.id)
        : DEFAULT_CHANNEL_IDS;
      setChannels(autoIds);
      setMethods([]);
    }

    setStep(2);
  };

  // Step 3 → Step 4: receive final kept suppliers
  const handleStep3Next = (keptSuppliers) => {
    setSuppliers(keptSuppliers); setStep(4);
  };

  const handleSaveAndReturn = () => {
    setCompletedItems(p => [...p, ...activeBatch.map(it=>it.description).filter(d=>!p.includes(d))]);
    setActiveBatch([]); setSuppliers([]);
    setStep3State(DEFAULT_S3);
    setStep("1b");
  };

  const handleDone = () => {
    sessionStorage.removeItem(SS_KEY);
    // Reset all wizard state so the next visit starts completely fresh
    setStep(1);
    setInquiry({ partNumber:"", customer:"", quantity:"", delivery:"", team:"EPC", description:"", specs:"", subject:"", extraInstructions:"" });
    setParsedInquiry(null);
    setMasterInquiryId(null);
    setSearchId(null);
    setActiveBatch([]);
    setSearchMode("individual");
    setCompletedItems([]);
    setChannels(DEFAULT_CHANNEL_IDS);
    setMethods([]);
    setSuppliers([]);
    setVendorEmailOverrides({});
    setStep3State(DEFAULT_S3);
    navigate("/");
  };

  const handleSingleNext = () => {
    const id = subjectToInquiryId(inquiry.subject);
    setMasterInquiryId(id);
    setActiveBatch([{ description:inquiry.description, reference:inquiry.partNumber, quantity:inquiry.quantity }]);
    setSearchMode("individual");
    // Only mint a new search ID if the inquiry itself changed — reuse existing ID for re-runs of the same inquiry
    if (masterInquiryId !== id) setSearchId(generateSearchId(id));
    // Auto-detect channels from single-item parsed RFQ; fall back to core defaults
    const codes = parsedInquiry?.category_groups?.[0]?.suggested_channels;
    const autoIds = codes?.length > 0
      ? ALL_CHANNELS.filter(ch => codes.map(c => c.toUpperCase()).includes(ch.code)).map(ch => ch.id)
      : DEFAULT_CHANNEL_IDS;
    setChannels(autoIds);
    setMethods([]);
    setStep(2);
  };

  return (
    <div className="flex h-screen bg-gray-50">
      <Sidebar activeTab="procurement" setActiveTab={() => {}} />

      <div className="flex flex-col flex-1 min-w-0 h-screen">
      {navTab === "Analytics" ? (
        <div className="flex-1 min-h-0 overflow-auto"><AnalyticsDashboard/></div>
      ) : navTab === "History" ? (
        <div className="flex-1 min-h-0 overflow-auto"><HistoryPage/></div>
      ) : navTab === "Import" ? (
        <div className="flex-1 min-h-0 overflow-auto flex flex-col">
          {/* Import sub-tab switcher */}
          <div className="flex gap-2 px-6 pt-4 pb-0 border-b border-gray-200 bg-white">
            {IMPORT_SUB_TABS.map(t => (
              <button key={t.key} onClick={() => setImportTab(t.key)}
                className={`px-5 py-2.5 text-sm font-medium border-b-2 transition -mb-px
                  ${importTab === t.key
                    ? "border-blue-600 text-blue-700"
                    : "border-transparent text-gray-500 hover:text-gray-700"}`}>
                {t.label}
              </button>
            ))}
          </div>
          <div className="flex-1 overflow-auto">
            {importTab === "rfq_mto" ? <RFQImport mode="mto"/> : <VendorImport/>}
          </div>
        </div>
      ) : navTab === "Vendors" ? (
        <div className="flex-1 min-h-0 overflow-auto"><VendorDirectory/></div>
      ) : (
        <>
          <StepIndicator current={step} onGoTo={s => { if (s !== step) setStep(s); }}/>
          <div className="flex-1 min-h-0 overflow-auto">
            <div className="max-w-5xl mx-auto">
              <div className="bg-white rounded-xl border border-gray-200 m-4 shadow-sm">
                {step===1    && <Step1 data={inquiry} setData={setInquiry} onNext={handleSingleNext} onMultiItem={handleMultiItem}/>}
                {step==="1b" && <Step1b parsedInquiry={parsedInquiry} completedItems={completedItems} masterInquiryId={masterInquiryId} onStartBatch={handleStartBatch} onBack={()=>setStep(1)}/>}
                {step===2    && <Step2 channels={channels} setChannels={setChannels} methods={methods} setMethods={setMethods} activeBatch={activeBatch} searchMode={searchMode} onNext={()=>setStep(3)} onBack={()=>setStep(parsedInquiry?"1b":1)} autoDetected={!!parsedInquiry}/>}
                {step===3    && <Step3 activeBatch={activeBatch} searchMode={searchMode} inquiry={inquiry} channels={channels} suppliers={suppliers} setSuppliers={setSuppliers} loading={loading} setLoading={setLoading} onNext={handleStep3Next} onBack={()=>setStep(2)} vendorEmailOverrides={vendorEmailOverrides} setVendorEmailOverrides={setVendorEmailOverrides} step3State={step3State} setStep3State={setStep3State}/>}
                {step===4    && <Step4Save activeBatch={activeBatch} searchMode={searchMode} inquiry={inquiry} suppliers={suppliers} masterInquiryId={masterInquiryId} parsedInquiry={parsedInquiry} searchId={searchId} completedItems={completedItems} onSaveAndReturn={parsedInquiry?handleSaveAndReturn:undefined} onDone={handleDone} onBack={()=>setStep(3)} vendorEmailOverrides={vendorEmailOverrides}/>}
              </div>
            </div>
          </div>
        </>
      )}
      </div>
    </div>
  );
}