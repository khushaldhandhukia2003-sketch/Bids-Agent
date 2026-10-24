import React, { useState, useRef, useEffect, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { API, signalDashboardRefresh, userHeaders } from "../config/api";

const CANONICAL_DIVISIONS = [
  "ISD-EPC","RENTAL","C&J","PRO","AUTO","CPD","BB EXPORT","PETROGULF","MRO","TPE","O&G EPC"
];

// ── Import Tab ─────────────────────────────────────────────────
export const VendorImport = () => {
  const [files,         setFiles]         = useState([]);
  const [dragOver,      setDragOver]      = useState(false);
  const [uploading,     setUploading]     = useState(false);
  const [result,        setResult]        = useState(null);
  const [error,         setError]         = useState("");
  const [stats,         setStats]         = useState(null);
  const [productDesc,   setProductDesc]   = useState("");
  const [divisions,     setDivisions]     = useState([]);
  const [divisionId,    setDivisionId]    = useState("");
  const [client,        setClient]        = useState("");

  // Retag state
  const [retagList,     setRetagList]     = useState([]);   // distinct sourcing_rationale values
  const [retagOld,      setRetagOld]      = useState("");
  const [retagNew,      setRetagNew]      = useState("");
  const [retagging,     setRetagging]     = useState(false);
  const [retagMsg,      setRetagMsg]      = useState("");
  const [showRetag,     setShowRetag]     = useState(false);

  const fileRef = useRef();

  const loadStats = () => {
    fetch(`${API}/vendors/master/stats`)
      .then(r => r.json())
      .then(d => { if (d.success) setStats(d.stats); })
      .catch(() => {});
  };

  const loadRetagList = () => {
    fetch(`${API}/vendors/master/import-descriptions`)
      .then(r => r.json())
      .then(d => { if (d.success) setRetagList(d.descriptions || []); })
      .catch(() => {});
  };

  useEffect(() => {
    loadStats();
    loadRetagList();
    fetch(`${API}/rfqs/divisions/all`)
      .then(r => r.json())
      .then(d => setDivisions(d.divisions || []))
      .catch(() => {});
  }, []);

  const handleFile = (incoming) => {
    const arr = incoming instanceof FileList ? [...incoming] : (Array.isArray(incoming) ? incoming : [incoming]);
    const valid = arr.filter(f => ["xlsx","xls","xlsm","csv"].includes(f.name.split(".").pop().toLowerCase()));
    const bad   = arr.filter(f => !["xlsx","xls","xlsm","csv"].includes(f.name.split(".").pop().toLowerCase()));
    if (bad.length) setError(`Unsupported file type(s): ${bad.map(f=>f.name).join(", ")}`);
    else setError("");
    if (valid.length) { setFiles(prev => { const names=new Set(prev.map(f=>f.name)); return [...prev,...valid.filter(f=>!names.has(f.name))]; }); setResult(null); }
  };

  // Clear / refresh button
  const handleClear = () => {
    setFiles([]);
    setProductDesc("");
    setResult(null);
    setError("");
    if (fileRef.current) fileRef.current.value = "";
  };

  const selectedDivisionName = divisions.find(d => String(d.id) === divisionId)?.name || "";

  const handleUpload = async () => {
    if (!files.length) return;
    setUploading(true); setError(""); setResult(null);
    let totalInserted = 0, totalUpdated = 0, totalSkipped = 0;
    const errors = [];
    for (const f of files) {
      const fd = new FormData();
      fd.append("file", f);
      fd.append("product_description", productDesc.trim());
      fd.append("division_id", divisionId);
      fd.append("client", client.trim());
      try {
        const res  = await fetch(`${API}/vendors/import/upload`, { method:"POST", headers: userHeaders(), body:fd });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Import failed");
        totalInserted += data.inserted || 0;
        totalUpdated  += data.updated  || 0;
        totalSkipped  += data.skipped  || 0;
      } catch(e) {
        errors.push(`${f.name}: ${e.message}`);
      }
    }
    setResult({ inserted: totalInserted, updated: totalUpdated, skipped: totalSkipped, errors });
    signalDashboardRefresh();
    setProductDesc("");
    loadStats();
    loadRetagList();
    setUploading(false);
  };

  const handleRetag = async () => {
    if (!retagOld || !retagNew.trim()) return;
    setRetagging(true); setRetagMsg("");
    try {
      const res  = await fetch(`${API}/vendors/master/retag-description`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ old_description: retagOld, new_description: retagNew.trim() }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Update failed");
      setRetagMsg(`✅ Updated ${data.updated} vendors from "${retagOld}" → "${retagNew.trim()}"`);
      setRetagOld(""); setRetagNew("");
      loadRetagList();
    } catch(e) {
      setRetagMsg(`❌ ${e.message}`);
    } finally {
      setRetagging(false);
    }
  };

  const handleExport = (source) => {
    const url = source
      ? `${API}/vendors/master/export/excel?source=${source}`
      : `${API}/vendors/master/export/excel`;
    window.open(url, "_blank");
  };

  return (
    // Fix 3: overflow-y-auto so the page scrolls
    <div className="p-6 max-w-3xl mx-auto overflow-y-auto max-h-[calc(100vh-120px)]">
      <h2 className="text-xl font-bold text-gray-800 mb-1">📥 Import Vendors</h2>
      <p className="text-sm text-gray-500 mb-6">
        Upload an Excel sheet of manually verified vendors. The system auto-detects columns
        and saves everything into your vendor database instantly.
      </p>

      {/* Database stats */}
      {stats && (
        <div className="grid grid-cols-3 gap-3 mb-6">
          {[
            { label: "Total in master DB", value: stats.total,          color: "bg-indigo-50 text-indigo-700" },
            { label: "Manually imported",  value: stats.manual_imports, color: "bg-green-50 text-green-700"   },
            { label: "AI discovered",      value: stats.ai_discovered,  color: "bg-purple-50 text-purple-700" },
          ].map(s => (
            <div key={s.label} className={`${s.color} rounded-xl p-4 text-center border`}>
              <p className="text-2xl font-bold">{s.value ?? 0}</p>
              <p className="text-xs mt-0.5 opacity-80">{s.label}</p>
            </div>
          ))}
        </div>
      )}

      {/* Column format guide */}
      <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 mb-5">
        <p className="text-sm font-semibold text-amber-800 mb-2">📋 Expected Excel columns</p>
        <p className="text-xs text-amber-700 mb-2">
          Column names are detected automatically — no exact match needed:
        </p>
        <div className="grid grid-cols-3 gap-1 text-xs text-amber-700">
          {[
            ["Vendor Name *",          "required"],
            ["Country",                "optional"],
            ["City",                   "optional"],
            ["Email",                  "optional"],
            ["Phone",                  "optional"],
            ["Website",                "optional"],
            ["Brands / Products",      "optional"],
            ["Channels",               "optional"],
          ].map(([field, req]) => (
            <div key={field} className="flex items-center gap-1">
              <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${req==="required"?"bg-red-400":"bg-amber-400"}`}/>
              {field}
            </div>
          ))}
        </div>
      </div>

      {/* Drop zone */}
      <div
        onDragOver={e=>{e.preventDefault();setDragOver(true);}}
        onDragLeave={()=>setDragOver(false)}
        onDrop={e=>{e.preventDefault();setDragOver(false);handleFile(e.dataTransfer.files);}}
        onClick={()=>!uploading&&fileRef.current?.click()}
        className={`border-2 border-dashed rounded-xl px-6 py-8 text-center cursor-pointer transition mb-4
          ${dragOver?"border-indigo-500 bg-indigo-50":
            files.length?"border-green-400 bg-green-50":
            "border-gray-300 hover:border-indigo-400 hover:bg-indigo-50"}`}
      >
        <div className="text-4xl mb-2">{uploading?"⏳":files.length?"✅":"📄"}</div>
        {uploading ? (
          <div className="flex items-center justify-center gap-2 text-indigo-600">
            <div className="w-4 h-4 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin"/>
            <span className="text-sm font-medium">Importing {files.length} file{files.length>1?"s":""}...</span>
          </div>
        ) : files.length ? (
          <div>
            <p className="text-sm font-semibold text-green-700">{files.length} file{files.length>1?"s":""} selected</p>
            <div className="mt-1 space-y-0.5 max-h-24 overflow-y-auto">
              {files.map((f,i)=>(
                <div key={i} className="flex items-center justify-between text-xs text-gray-500 px-2">
                  <span className="truncate max-w-[220px]">{f.name}</span>
                  <button onClick={ev=>{ev.stopPropagation();setFiles(p=>p.filter((_,j)=>j!==i));}}
                    className="ml-2 text-red-400 hover:text-red-600 font-bold">×</button>
                </div>
              ))}
            </div>
            <p className="text-xs text-indigo-500 mt-1">Click to add more files</p>
          </div>
        ) : (
          <div>
            <p className="text-sm font-semibold text-gray-700">Drag & drop or click to upload</p>
            <p className="text-xs text-gray-400 mt-0.5">Excel (.xlsx, .xls, .xlsm) or CSV — multiple files supported</p>
          </div>
        )}
        <input ref={fileRef} type="file" accept=".xlsx,.xls,.xlsm,.csv" multiple
          className="hidden" onChange={e=>handleFile(e.target.files)}/>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-600 rounded-lg px-4 py-3 text-sm mb-4">
          ⚠️ {error}
        </div>
      )}

      {files.length > 0 && !result && (
        <div className="mb-4 space-y-4">
          {/* Division + Client */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-sm font-medium text-gray-700 mb-1 block">Division</label>
              <select value={divisionId} onChange={e => { setDivisionId(e.target.value); setClient(""); }}
                className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 bg-white">
                <option value="">— Select division —</option>
                {(divisions.length > 0 ? divisions : CANONICAL_DIVISIONS.map((n,i) => ({id:i+1,name:n}))).map(d => (
                  <option key={d.id} value={String(d.id)}>{d.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700 mb-1 block">Client</label>
              {selectedDivisionName === "MRO" ? (
                <select value={client} onChange={e => setClient(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 bg-white">
                  <option value="">— Select client —</option>
                  <option value="ADNOC">ADNOC</option>
                  <option value="DEWA">DEWA</option>
                </select>
              ) : (
                <input value={client} onChange={e => setClient(e.target.value)}
                  placeholder="e.g. Saudi Aramco"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500" />
              )}
            </div>
          </div>

          {/* Product description */}
          <div>
            <label className="text-sm font-medium text-gray-700 mb-1 block">
              What product is this vendor list for?
              <span className="text-xs font-normal text-gray-400 ml-2">
                — used to find these vendors in future similar inquiries
              </span>
            </label>
            <input
              value={productDesc}
              onChange={e => setProductDesc(e.target.value)}
              placeholder="e.g. Horizontal Centrifugal Multistage Pump, Air Impact Wrench..."
              className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
            {!productDesc.trim() && (
              <p className="text-xs text-amber-600 mt-1">
                ⚠ If left blank, the product will be inferred from the filename of each file.
              </p>
            )}
          </div>

          <div className="flex gap-2">
            <button onClick={handleUpload} disabled={uploading}
              className="flex-1 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50
                         text-white py-3 rounded-lg font-semibold text-sm transition">
              {uploading ? `Importing ${files.length} file${files.length>1?"s":""}...` : `Import ${files.length} file${files.length>1?"s":""} →`}
            </button>
            <button onClick={handleClear}
              className="px-4 py-3 border border-gray-300 rounded-lg text-sm
                         text-gray-600 hover:bg-gray-50 transition font-medium">
              🔄 Clear
            </button>
          </div>
        </div>
      )}

      {/* Result */}
      {result && (
        <div className="bg-green-50 border border-green-200 rounded-xl p-5 mb-4">
          <p className="text-green-800 font-semibold text-base mb-3">
            ✅ {result.message || `Import complete — ${files.length} file${files.length>1?"s":""} processed`}
          </p>
          <div className="grid grid-cols-4 gap-3 mb-3 text-center text-sm">
            <div className="bg-white rounded-lg p-2 border border-green-100">
              <p className="text-xl font-bold text-green-700">{result.inserted ?? result.saved}</p>
              <p className="text-xs text-gray-500">New</p>
            </div>
            <div className="bg-white rounded-lg p-2 border border-green-100">
              <p className="text-xl font-bold text-blue-600">{result.updated ?? 0}</p>
              <p className="text-xs text-gray-500">Updated</p>
            </div>
            <div className="bg-white rounded-lg p-2 border border-green-100">
              <p className="text-xl font-bold text-gray-500">{result.skipped}</p>
              <p className="text-xs text-gray-500">Skipped (empty)</p>
            </div>
            <div className="bg-white rounded-lg p-2 border border-green-100">
              <p className="text-xl font-bold text-gray-500">{result.total_rows}</p>
              <p className="text-xs text-gray-500">Total rows</p>
            </div>
          </div>
          {result.columns_found?.length > 0 && (
            <p className="text-xs text-green-700 mb-2">
              Columns matched: {result.columns_found.join(", ")}
            </p>
          )}
          {result.errors?.length > 0 && (
            <div className="bg-red-50 border border-red-100 rounded-lg p-3 mt-2 max-h-40 overflow-y-auto">
              <p className="text-xs font-semibold text-red-600 mb-1">⚠️ {result.errors.length} rows had errors:</p>
              {result.errors.map((e,i)=>(
                <p key={i} className="text-xs text-red-500 font-mono">{e}</p>
              ))}
            </div>
          )}
          {result.sample?.length > 0 && (
            <div className="mt-3">
              <p className="text-xs text-green-700 font-semibold mb-1">Sample of imported vendors:</p>
              <div className="space-y-1">
                {result.sample.map((v,i)=>(
                  <div key={i} className="text-xs bg-white rounded px-2 py-1 border border-green-100
                                          flex items-center gap-3 text-gray-600">
                    <span className="font-medium text-gray-800">{v.name}</span>
                    {v.country && <span>{v.country}</span>}
                    {v.email   && <span className="text-blue-500">{v.email}</span>}
                  </div>
                ))}
              </div>
            </div>
          )}
          <div className="flex gap-2 mt-4">
            <button onClick={handleClear}
              className="flex-1 bg-indigo-600 hover:bg-indigo-700 text-white py-2.5 rounded-lg text-sm font-semibold transition">
              ✅ Done
            </button>
            <button onClick={handleClear}
              className="px-4 py-2.5 border border-gray-300 rounded-lg text-sm text-gray-600 hover:bg-gray-50 transition">
              🔄 Import another file
            </button>
          </div>
        </div>
      )}

      {/* Fix 1: Update product description for previous imports */}
      <div className="border border-gray-200 rounded-xl overflow-hidden mb-4">
        <button
          onClick={()=>setShowRetag(!showRetag)}
          className="w-full flex items-center justify-between px-4 py-3
                     bg-gray-50 hover:bg-gray-100 transition text-sm font-medium text-gray-700">
          <span>✏️ Update product description for a previous import</span>
          <span className="text-gray-400">{showRetag ? "▲" : "▼"}</span>
        </button>

        {showRetag && (
          <div className="p-4 bg-white">
            <p className="text-xs text-gray-500 mb-3">
              Select the wrong description you used before and type the correct one.
              This updates all vendors from that import batch at once.
            </p>

            <label className="text-xs font-medium text-gray-600 mb-1 block">
              Current (wrong) description
            </label>
            {retagList.length > 0 ? (
              <select
                value={retagOld}
                onChange={e => setRetagOld(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm
                           focus:outline-none focus:ring-2 focus:ring-indigo-500 mb-3 bg-white">
                <option value="">— select —</option>
                {retagList.map((d, i) => (
                  <option key={i} value={d.description}>
                    {d.description} ({d.count} vendor{d.count !== 1 ? "s" : ""})
                  </option>
                ))}
              </select>
            ) : (
              <p className="text-xs text-gray-400 mb-3 italic">
                No manual imports found yet.
              </p>
            )}

            <label className="text-xs font-medium text-gray-600 mb-1 block">
              New (correct) description
            </label>
            <input
              value={retagNew}
              onChange={e => setRetagNew(e.target.value)}
              placeholder="e.g. Shelter Fabrication Hypochlorite Injection Skid"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm
                         focus:outline-none focus:ring-2 focus:ring-indigo-500 mb-3"
            />

            {retagMsg && (
              <p className={`text-xs mb-3 ${retagMsg.startsWith("✅")?"text-green-600":"text-red-500"}`}>
                {retagMsg}
              </p>
            )}

            <button
              onClick={handleRetag}
              disabled={retagging || !retagOld || !retagNew.trim()}
              className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40
                         text-white px-5 py-2 rounded-lg text-sm font-medium transition">
              {retagging ? "Updating..." : "Update description →"}
            </button>
          </div>
        )}
      </div>

      {/* Export section */}
      <div className="border border-gray-200 rounded-xl p-4">
        <p className="text-sm font-semibold text-gray-700 mb-3">📤 Export vendor database</p>
        <div className="flex gap-2 flex-wrap">
          {[
            { label: "All vendors",      source: null             },
            { label: "Manual imports",   source: "manual_import"  },
            { label: "AI discovered",    source: "ai_discovered"  },
            { label: "Manual overrides", source: "manual_override"},
          ].map(opt => (
            <button key={opt.label} onClick={()=>handleExport(opt.source)}
              className="px-4 py-2 border border-gray-300 rounded-lg text-sm
                         hover:bg-gray-50 transition text-gray-700">
              📥 {opt.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
};


// ── RFQ Import Tab ─────────────────────────────────────────────
// ── Reusable drop-zone ────────────────────────────────────────
const RFQ_ACCEPT = ".xlsx,.xls,.xlsm,.csv,.pdf,.txt,.doc,.docx,.png,.jpg,.jpeg,.webp,.tiff,.bmp";
const VENDOR_ACCEPT = ".xlsx,.xls,.xlsm,.csv";

const FILE_TYPE_ICON = (f) => {
  if (!f) return null;
  const ext = f.name.split('.').pop().toLowerCase();
  if (['pdf'].includes(ext)) return '📄';
  if (['png','jpg','jpeg','webp','tiff','bmp'].includes(ext)) return '🖼️';
  if (['txt','doc','docx'].includes(ext)) return '📝';
  return '📊';
};

const DropZone = ({ file, files, onFile, onFiles, uploading, label, hint, icon, accept, fileRef, multiple }) => {
  const [dragOver, setDragOver] = useState(false);
  const internalRef = React.useRef(null);
  const ref = fileRef || internalRef;
  const ext = accept || RFQ_ACCEPT;
  const isMulti = multiple || !!onFiles;
  const activeFiles = isMulti ? (files || []) : null;
  const hasFiles = isMulti ? activeFiles.length > 0 : !!file;
  const handleIncoming = (incoming) => {
    if (isMulti) {
      const arr = [...(incoming instanceof FileList ? incoming : [incoming])].filter(Boolean);
      if (onFiles) onFiles(arr);
    } else {
      const f = incoming instanceof FileList ? incoming[0] : incoming;
      if (f && onFile) onFile(f);
    }
  };
  const typeIcon = file ? FILE_TYPE_ICON(file) : null;
  return (
    <div
      onDragOver={e=>{e.preventDefault();setDragOver(true);}}
      onDragLeave={()=>setDragOver(false)}
      onDrop={e=>{e.preventDefault();setDragOver(false);handleIncoming(e.dataTransfer.files);}}
      onClick={()=>!uploading&&ref.current?.click()}
      className={`border-2 border-dashed rounded-xl px-4 py-6 text-center cursor-pointer transition
        ${dragOver?"border-purple-500 bg-purple-50":
          hasFiles?"border-green-400 bg-green-50":
          "border-gray-300 hover:border-purple-400 hover:bg-purple-50"}`}
    >
      <div className="text-3xl mb-1">{hasFiles ? (typeIcon || "✅") : icon}</div>
      {isMulti ? (
        activeFiles.length ? (
          <div>
            <p className="text-sm font-semibold text-green-700">{activeFiles.length} file{activeFiles.length>1?"s":""} selected</p>
            <div className="mt-1 space-y-0.5 max-h-20 overflow-y-auto">
              {activeFiles.map((f,i)=>(
                <div key={i} className="flex items-center justify-between text-xs text-gray-500 px-2">
                  <span className="truncate max-w-[160px]">{f.name}</span>
                  <button onClick={ev=>{ev.stopPropagation();if(onFiles)onFiles(activeFiles.filter((_,j)=>j!==i));}}
                    className="ml-2 text-red-400 hover:text-red-600 font-bold">×</button>
                </div>
              ))}
            </div>
            <p className="text-xs text-purple-500 mt-1">Click to add more</p>
          </div>
        ) : (
          <div>
            <p className="text-sm font-semibold text-gray-700">{label}</p>
            <p className="text-xs text-gray-400 mt-1">{hint || "Multiple files supported"}</p>
          </div>
        )
      ) : file ? (
        <div>
          <p className="text-sm font-semibold text-green-700 truncate max-w-[200px] mx-auto">{file.name}</p>
          <p className="text-xs text-gray-400 mt-0.5">{(file.size/1024).toFixed(1)} KB — click to replace</p>
        </div>
      ) : (
        <div>
          <p className="text-sm font-semibold text-gray-700">{label}</p>
          <p className="text-xs text-gray-400 mt-1">{hint || "Excel · CSV · PDF · Image · Text"}</p>
        </div>
      )}
      <input ref={ref} type="file" accept={ext} multiple={isMulti} className="hidden"
        onChange={e=>handleIncoming(e.target.files)}/>
    </div>
  );
};

const LS_KEY = "rfq_import_draft";
const loadDraft = () => { try { return JSON.parse(localStorage.getItem(LS_KEY) || "{}"); } catch { return {}; } };
const _saveDraftImmediate = (patch) => { try { localStorage.setItem(LS_KEY, JSON.stringify({ ...loadDraft(), ...patch })); } catch {} };
let _saveDraftTimer = null;
const saveDraft = (patch) => {
  clearTimeout(_saveDraftTimer);
  _saveDraftTimer = setTimeout(() => _saveDraftImmediate(patch), 400);
};
const clearDraft = () => { try { localStorage.removeItem(LS_KEY); } catch {} };

export const RFQImport = ({ mode = "mto" }) => {
  const tab = mode;
  const navigate = useNavigate();
  const draft = useMemo(loadDraft, []);

  // ── Input mode: "file" | "text" ──
  const [inputMode, setInputMode] = useState(draft.inputMode || "file");

  // ── Text paste import ──
  const [pasteText,       setPasteText]       = useState(draft.pasteText || "");
  const [pasteId,         setPasteId]         = useState(draft.pasteId || "");
  const [pasteResult,     setPasteResult]     = useState(null);
  const [pasteError,      setPasteError]      = useState("");
  const [pasteLoading,    setPasteLoading]    = useState(false);
  const [pasteVendorFile, setPasteVendorFile] = useState(null);

  const handlePasteImport = async () => {
    if (!pasteText.trim()) return;
    setPasteLoading(true); setPasteError(""); setPasteResult(null);
    const inquiryId = pasteId.trim() || `TEXT-${Date.now()}`;
    const fd = new FormData();
    fd.append("text", pasteText.trim());
    fd.append("inquiry_id", inquiryId);
    try {
      const res  = await fetch(`${API}/rfqs/import-rfq-text`, { method: "POST", body: fd });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Import failed");
      // Upload vendor file if provided
      let vendorData = null;
      if (pasteVendorFile) {
        const fd2 = new FormData();
        fd2.append("file", pasteVendorFile);
        fd2.append("inquiry_id", data.inquiry_id || inquiryId);
        const res2 = await fetch(`${API}/rfqs/import-vendors-for-rfq`, { method: "POST", body: fd2 });
        vendorData = await res2.json();
      }
      if (data.inquiry_id) await patchInquiryMeta(data.inquiry_id);
      setPasteResult({ rfq: data, vendor: vendorData });
      clearDraft();
      signalDashboardRefresh();
    } catch(e) {
      setPasteError(e.message);
    } finally {
      setPasteLoading(false);
    }
  };

  // ── Optional metadata fields (client, division, product name) ──
  const [metaClient,  setMetaClient]  = useState("");
  const [metaDivision,setMetaDivision]= useState("");
  const [metaProduct, setMetaProduct] = useState("");

  const patchInquiryMeta = async (inquiryId) => {
    const updates = {};
    if (metaClient.trim())   updates.client = metaClient.trim();
    if (metaDivision.trim()) updates.team   = metaDivision.trim();
    if (!Object.keys(updates).length) return;
    try {
      await fetch(`${API}/rfqs/inquiry/${inquiryId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ inquiry: updates }),
      });
    } catch (_) { /* non-critical — fields can be edited in history */ }
  };

  // ── MTO + Vendor import ──
  const [rfqFiles,    setRfqFiles]    = useState([]);
  const [vendorFile,  setVendorFile]  = useState(null);
  const [mtoResult,   setMtoResult]   = useState(null);
  const [mtoError,    setMtoError]    = useState("");
  const [mtoUploading,setMtoUploading]= useState(false);
  const rfqRef    = useRef();
  const vendorRef = useRef();

  const stemName = (f) => f ? f.name.replace(/\.[^.]+$/, "") : "";

  const handleMtoUpload = async () => {
    if (!rfqFiles.length) return;
    setMtoUploading(true); setMtoError(""); setMtoResult(null);
    try {
      let d1;
      if (rfqFiles.length === 1) {
        // Single file — existing endpoint
        const fd1 = new FormData();
        fd1.append("file", rfqFiles[0]);
        const r1 = await fetch(`${API}/rfqs/import-rfq-excel`, { method: "POST", body: fd1 });
        d1 = await r1.json();
        if (!r1.ok) throw new Error(d1.detail || "RFQ import failed");
      } else {
        // Multiple files — merge into ONE RFQ
        const fd1 = new FormData();
        rfqFiles.forEach(f => fd1.append("files", f));
        const r1 = await fetch(`${API}/rfqs/import-rfq-excel-multi`, { method: "POST", body: fd1 });
        d1 = await r1.json();
        if (!r1.ok) throw new Error(d1.detail || "RFQ import failed");
      }

      let vendorResult = null;
      if (vendorFile) {
        const fd2 = new FormData();
        fd2.append("file", vendorFile);
        if (d1.inquiry_id) fd2.append("inquiry_id", d1.inquiry_id);
        const r2 = await fetch(`${API}/rfqs/import-vendors-for-rfq`, { method: "POST", body: fd2 });
        const d2 = await r2.json();
        if (!r2.ok) throw new Error(d2.detail || "Vendor import failed");
        vendorResult = d2;
      }

      if (d1.inquiry_id) await patchInquiryMeta(d1.inquiry_id);
      setMtoResult({ rfq: d1, vendor: vendorResult });
      signalDashboardRefresh();
    } catch(e) {
      setMtoError(e.message);
    } finally {
      setMtoUploading(false);
    }
  };

  const handleMtoClear = () => {
    setRfqFiles([]); setVendorFile(null); setMtoResult(null); setMtoError("");
    if (rfqRef.current) rfqRef.current.value = "";
    if (vendorRef.current) vendorRef.current.value = "";
  };

  // ── Tracking import (original) ──
  const [tFile,      setTFile]      = useState(null);
  const [tResult,    setTResult]    = useState(null);
  const [tError,     setTError]     = useState("");
  const [tUploading, setTUploading] = useState(false);
  const tRef = useRef();

  const handleTUpload = async () => {
    if (!tFile) return;
    setTUploading(true); setTError(""); setTResult(null);
    const fd = new FormData();
    fd.append("file", tFile);
    try {
      const res  = await fetch(`${API}/rfqs/import`, { method: "POST", headers: userHeaders(), body: fd });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Import failed");
      setTResult(data);
      signalDashboardRefresh();
    } catch(e) {
      setTError(e.message);
    } finally {
      setTUploading(false);
    }
  };

  return (
    <div className="p-6 max-w-3xl mx-auto overflow-y-auto max-h-[calc(100vh-160px)]">
      {tab === "mto" && (
        <>
          <h2 className="text-lg font-bold text-gray-800 mb-1">📦 Import RFQ + Vendor Files</h2>
          <p className="text-sm text-gray-500 mb-4">
            Upload your RFQ file or paste text — AI extracts all items automatically.
          </p>

          {/* Input mode toggle */}
          <div className="flex gap-1 bg-gray-100 rounded-lg p-1 mb-5 w-fit">
            {[["file","📁 Upload File"],["text","✏️ Paste Text"]].map(([m,label])=>(
              <button key={m} onClick={()=>{setInputMode(m);saveDraft({inputMode:m});setPasteResult(null);setMtoResult(null);}}
                className={`px-4 py-2 rounded-md text-sm font-medium transition
                  ${inputMode===m?"bg-white text-purple-700 shadow-sm":"text-gray-600 hover:text-gray-800"}`}>
                {label}
              </button>
            ))}
          </div>

          {/* ── Text paste mode ── */}
          {inputMode === "text" && !pasteResult && (
            <div className="space-y-3 mb-4">
              <div>
                <label className="text-xs font-semibold text-gray-600 mb-1 block">
                  Reference / Inquiry ID <span className="font-normal text-gray-400">(optional)</span>
                </label>
                <input value={pasteId} onChange={e=>{setPasteId(e.target.value);saveDraft({pasteId:e.target.value});}}
                  placeholder="e.g. INQ-2026-001 or leave blank for auto"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"/>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="text-xs font-semibold text-gray-600 mb-1 block">
                    Paste RFQ text, email, or item list
                  </label>
                  <textarea value={pasteText} onChange={e=>{setPasteText(e.target.value);saveDraft({pasteText:e.target.value});}}
                    rows={8} placeholder={"Paste your RFQ content here...\n\nExamples:\n• Email with item list\n• Copy-pasted table from Word/PDF\n• Any text describing what you need"}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500 resize-y font-mono"/>
                </div>
                <div>
                  <label className="text-xs font-semibold text-gray-600 mb-1 block">
                    Vendor List File <span className="font-normal text-gray-400">(optional)</span>
                  </label>
                  <DropZone file={pasteVendorFile} onFile={setPasteVendorFile} uploading={pasteLoading}
                    label="Drag & drop vendor file" hint="Excel · CSV · PDF · Image · Text" icon="🏭"/>
                </div>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 p-3 bg-gray-50 border border-gray-200 rounded-xl">
                <div>
                  <label className="text-xs font-semibold text-gray-600 mb-1 block">Client <span className="font-normal text-gray-400">(optional)</span></label>
                  <input value={metaClient} onChange={e => setMetaClient(e.target.value)} placeholder="Client name"
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"/>
                </div>
                <div>
                  <label className="text-xs font-semibold text-gray-600 mb-1 block">Division / Team <span className="font-normal text-gray-400">(optional)</span></label>
                  <input value={metaDivision} onChange={e => setMetaDivision(e.target.value)} placeholder="e.g. PRO, MRO, C&J"
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"/>
                </div>
                <div>
                  <label className="text-xs font-semibold text-gray-600 mb-1 block">Product Name <span className="font-normal text-gray-400">(optional)</span></label>
                  <input value={metaProduct} onChange={e => setMetaProduct(e.target.value)} placeholder="e.g. Ball Valves, Pumps"
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"/>
                </div>
              </div>
              {pasteError && (
                <div className="bg-red-50 border border-red-200 text-red-600 rounded-lg px-4 py-3 text-sm">
                  ⚠️ {pasteError}
                </div>
              )}
              <div className="flex gap-2">
                <button onClick={handlePasteImport} disabled={pasteLoading||!pasteText.trim()}
                  className="flex-1 bg-purple-600 hover:bg-purple-700 disabled:opacity-50 text-white py-3 rounded-lg font-semibold text-sm transition">
                  {pasteLoading ? "Parsing with AI..." : `Parse & Import${pasteVendorFile ? " + Vendors" : ""} →`}
                </button>
                <button onClick={()=>{setPasteText("");setPasteId("");setPasteError("");setPasteVendorFile(null);clearDraft();}}
                  className="px-4 py-3 border border-gray-300 rounded-lg text-sm text-gray-600 hover:bg-gray-50 transition">
                  Clear
                </button>
              </div>
            </div>
          )}

          {/* Text paste result */}
          {inputMode === "text" && pasteResult && (
            <div className="bg-green-50 border border-green-200 rounded-xl p-5 mb-4">
              <p className="text-green-800 font-semibold mb-3">✅ Import complete</p>
              <div className="grid grid-cols-2 gap-3 text-center text-sm mb-3">
                <div className="bg-white rounded-lg p-3 border border-green-100">
                  <p className="text-2xl font-bold text-green-700">{pasteResult.rfq?.inserted || 0}</p>
                  <p className="text-xs text-gray-500">Line items imported</p>
                </div>
                <div className="bg-white rounded-lg p-3 border border-green-100">
                  <p className="text-2xl font-bold text-blue-600">{pasteResult.vendor?.inserted || 0}</p>
                  <p className="text-xs text-gray-500">Vendors linked</p>
                </div>
              </div>
              {(pasteResult.rfq?.client || pasteResult.rfq?.delivery) && (
                <div className="flex gap-4 text-xs text-green-700 mb-3">
                  {pasteResult.rfq.client   && <span><span className="font-semibold">Client:</span> {pasteResult.rfq.client}</span>}
                  {pasteResult.rfq.delivery && <span><span className="font-semibold">Delivery:</span> {pasteResult.rfq.delivery}</span>}
                </div>
              )}
              <p className="text-xs text-green-700 mb-3">
                Inquiry ID: <span className="font-mono font-semibold">{pasteResult.rfq?.inquiry_id}</span>
                {pasteResult.vendor && " — vendors linked to this inquiry"}
              </p>

              {/* Items Preview */}
              {pasteResult.rfq?.items?.length > 0 && (
                <div className="mt-2 mb-3">
                  <div className="flex items-center justify-between mb-2">
                    <p className="text-xs font-semibold text-gray-700">Extracted Items Preview</p>
                    <button
                      onClick={() => {
                        const items = pasteResult.rfq.items;
                        const inquiryId = pasteResult.rfq.inquiry_id || "rfq";
                        const headers = ["#","Description","Part / Ref","Qty","Unit","Category","Specs"];
                        const rows = items.map((item, i) => [i+1, item.description||"", item.part_number||"", item.quantity||"", item.unit||"", item.category||"", item.specs||""]);
                        const csvContent = [headers, ...rows].map(row => row.map(v=>`"${String(v).replace(/"/g,'""')}"`).join(",")).join("\n");
                        const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement("a");
                        a.href = url; a.download = `${inquiryId}.csv`; a.click();
                        URL.revokeObjectURL(url);
                      }}
                      className="flex items-center gap-1.5 px-3 py-1.5 bg-green-600 hover:bg-green-700 text-white rounded-lg text-xs font-semibold transition">
                      ⬇ Save as CSV
                    </button>
                  </div>
                  <div className="overflow-x-auto rounded-lg border border-green-100">
                    <table className="w-full text-xs">
                      <thead className="bg-green-100 text-green-800">
                        <tr>
                          {["#","Description","Part / Ref","Qty","Unit","Category","Specs"].map(h=>(
                            <th key={h} className="text-left px-3 py-2 font-semibold">{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="bg-white divide-y divide-green-50">
                        {pasteResult.rfq.items.map((item, i) => (
                          <tr key={i} className="hover:bg-green-50">
                            <td className="px-3 py-2 text-gray-400">{i+1}</td>
                            <td className="px-3 py-2 font-medium text-gray-800 max-w-[200px] truncate">{item.description}</td>
                            <td className="px-3 py-2 text-gray-500 font-mono">{item.part_number || "—"}</td>
                            <td className="px-3 py-2 text-gray-700">{item.quantity || "—"}</td>
                            <td className="px-3 py-2 text-gray-500">{item.unit || "—"}</td>
                            <td className="px-3 py-2 text-purple-600">{item.category || "—"}</td>
                            <td className="px-3 py-2 text-gray-400 max-w-[150px] truncate">{item.specs || "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Vendors Preview */}
              {pasteResult.vendor?.vendors?.length > 0 && (
                <div className="mt-3 mb-2">
                  <p className="text-xs font-semibold text-gray-700 mb-2">Vendors Linked Preview</p>
                  <div className="overflow-x-auto rounded-lg border border-green-100">
                    <table className="w-full text-xs">
                      <thead className="bg-green-100 text-green-800">
                        <tr>
                          {["#","Vendor Name","Country","Email","Phone","Brands"].map(h=>(
                            <th key={h} className="text-left px-3 py-2 font-semibold">{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="bg-white divide-y divide-green-50">
                        {pasteResult.vendor.vendors.map((v, i) => (
                          <tr key={i} className="hover:bg-green-50">
                            <td className="px-3 py-2 text-gray-400">{i+1}</td>
                            <td className="px-3 py-2 font-medium text-gray-800 max-w-[180px] truncate">{v.name}</td>
                            <td className="px-3 py-2 text-gray-500">{[v.city, v.country].filter(Boolean).join(', ') || '—'}</td>
                            <td className="px-3 py-2 text-gray-500 max-w-[160px] truncate">{v.email || '—'}</td>
                            <td className="px-3 py-2 text-gray-500">{v.phone || '—'}</td>
                            <td className="px-3 py-2 text-purple-600 max-w-[120px] truncate">{v.brands || '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {pasteResult.vendor.inserted > 50 && (
                    <p className="text-xs text-gray-400 mt-1">Showing first 50 of {pasteResult.vendor.inserted} vendors</p>
                  )}
                </div>
              )}

              <div className="flex items-center justify-between mt-2">
                <button onClick={()=>{setPasteResult(null);setPasteText("");setPasteId("");setPasteVendorFile(null);clearDraft();}}
                  className="text-sm text-blue-600 hover:underline">🔄 Import another</button>
                <button
                  onClick={() => {
                    signalDashboardRefresh();
                    navigate('/dashboard', { state: { tab: 'rfqs' } });
                  }}
                  className="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-700 text-white px-5 py-2.5 rounded-lg text-sm font-semibold transition shadow-sm">
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7"/></svg>
                  Save &amp; View in RFQs →
                </button>
              </div>
            </div>
          )}

          {/* ── File upload mode ── */}
          {inputMode === "file" && (
          <>
          {/* Filename match hint */}
          {rfqFiles.length === 1 && vendorFile && (
            <div className={`rounded-lg px-4 py-2 text-sm mb-4 flex items-center gap-2
              ${stemName(rfqFiles[0])===stemName(vendorFile)?"bg-green-50 border border-green-200 text-green-700":"bg-orange-50 border border-orange-200 text-orange-700"}`}>
              {stemName(rfqFiles[0])===stemName(vendorFile)
                ? "✅ Filenames match — RFQ and vendors will be linked automatically"
                : `⚠️ Filenames differ ("${stemName(rfqFiles[0])}" vs "${stemName(vendorFile)}") — they will be stored separately`}
            </div>
          )}

          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <p className="text-xs font-semibold text-gray-600 mb-2">RFQ / Item List File *</p>
              <DropZone files={rfqFiles} onFiles={incoming=>setRfqFiles(prev=>{const names=new Set(prev.map(f=>f.name));return [...prev,...incoming.filter(f=>!names.has(f.name))]; })}
                uploading={mtoUploading} label="Drag & drop RFQ file(s)" hint="Multiple files supported · Excel · CSV · PDF · Image · Text"
                icon="📋" accept={RFQ_ACCEPT} fileRef={rfqRef} multiple/>
            </div>
            <div>
              <p className="text-xs font-semibold text-gray-600 mb-2">Vendor List File (optional)</p>
              <DropZone file={vendorFile} onFile={setVendorFile} uploading={mtoUploading}
                label="Drag & drop vendor file" icon="🏭" accept={VENDOR_ACCEPT} fileRef={vendorRef}/>
            </div>
          </div>

          <div className="bg-blue-50 border border-blue-100 rounded-lg px-4 py-3 text-xs text-blue-700 mb-4">
            <p className="font-semibold mb-1">Supported RFQ file types:</p>
            <div className="grid grid-cols-2 gap-x-4 mt-1">
              <div>
                <p className="font-medium text-blue-800 mb-0.5">📊 Spreadsheets</p>
                <p>• MTO sheets (TAG NO, TYPE, QTY, SIZE — any row)</p>
                <p>• Ariba/SAP bid templates (Number, Name, Qty, UOM)</p>
                <p>• Any Excel / CSV with item + quantity columns</p>
              </div>
              <div>
                <p className="font-medium text-blue-800 mb-0.5">📄 Documents & Images</p>
                <p>• PDF RFQ documents</p>
                <p>• Scanned images (JPG, PNG, TIFF, WebP)</p>
                <p>• Plain text or Word documents (.txt, .doc, .docx)</p>
              </div>
            </div>
          </div>

          {mtoError && (
            <div className="bg-red-50 border border-red-200 text-red-600 rounded-lg px-4 py-3 text-sm mb-4">
              ⚠️ {mtoError}
            </div>
          )}

          {rfqFiles.length > 0 && !mtoResult && (
            <>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-3 p-3 bg-gray-50 border border-gray-200 rounded-xl">
                <div>
                  <label className="text-xs font-semibold text-gray-600 mb-1 block">Client <span className="font-normal text-gray-400">(optional)</span></label>
                  <input value={metaClient} onChange={e => setMetaClient(e.target.value)} placeholder="Client name"
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"/>
                </div>
                <div>
                  <label className="text-xs font-semibold text-gray-600 mb-1 block">Division / Team <span className="font-normal text-gray-400">(optional)</span></label>
                  <input value={metaDivision} onChange={e => setMetaDivision(e.target.value)} placeholder="e.g. PRO, MRO, C&J"
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"/>
                </div>
                <div>
                  <label className="text-xs font-semibold text-gray-600 mb-1 block">Product Name <span className="font-normal text-gray-400">(optional)</span></label>
                  <input value={metaProduct} onChange={e => setMetaProduct(e.target.value)} placeholder="e.g. Ball Valves, Pumps"
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"/>
                </div>
              </div>
              <div className="flex gap-2 mb-4">
                <button onClick={handleMtoUpload} disabled={mtoUploading}
                  className="flex-1 bg-purple-600 hover:bg-purple-700 disabled:opacity-50 text-white py-3 rounded-lg font-semibold text-sm transition">
                  {mtoUploading ? `Importing ${rfqFiles.length} file${rfqFiles.length>1?"s":""}...` : `Import ${rfqFiles.length} RFQ file${rfqFiles.length>1?"s":""}${vendorFile?" + Vendors":""} →`}
                </button>
                <button onClick={handleMtoClear}
                  className="px-4 py-3 border border-gray-300 rounded-lg text-sm text-gray-600 hover:bg-gray-50 transition">
                  Clear
                </button>
              </div>
            </>
          )}

          {mtoResult && (
            <div className="bg-green-50 border border-green-200 rounded-xl p-5 mb-4">
              <p className="text-green-800 font-semibold mb-3">✅ Import complete</p>
              <div className="grid grid-cols-2 gap-3 text-center text-sm mb-3">
                <div className="bg-white rounded-lg p-3 border border-green-100">
                  <p className="text-2xl font-bold text-green-700">{mtoResult.rfq?.inserted || 0}</p>
                  <p className="text-xs text-gray-500">Line items imported</p>
                </div>
                <div className="bg-white rounded-lg p-3 border border-green-100">
                  <p className="text-2xl font-bold text-blue-600">{mtoResult.vendor?.inserted || 0}</p>
                  <p className="text-xs text-gray-500">Vendors linked</p>
                </div>
              </div>
              {(mtoResult.rfq?.client || mtoResult.rfq?.delivery) && (
                <div className="flex gap-4 text-xs text-green-700 mb-3">
                  {mtoResult.rfq.client   && <span><span className="font-semibold">Client:</span> {mtoResult.rfq.client}</span>}
                  {mtoResult.rfq.delivery && <span><span className="font-semibold">Delivery:</span> {mtoResult.rfq.delivery}</span>}
                </div>
              )}
              <p className="text-xs text-green-700 mb-3">
                Inquiry ID: <span className="font-mono font-semibold">{mtoResult.rfq?.inquiry_id}</span>
                {mtoResult.vendor && " — vendors linked to this inquiry"}
              </p>

              {/* Preview table */}
              {mtoResult.rfq?.items?.length > 0 && (
                <div className="mt-2 mb-3">
                  <div className="flex items-center justify-between mb-2">
                    <p className="text-xs font-semibold text-gray-700">Extracted Items Preview</p>
                    <button
                      onClick={() => {
                        const items = mtoResult.rfq.items;
                        const inquiryId = mtoResult.rfq.inquiry_id || "rfq";
                        const headers = ["#","Description","Part / Ref","Qty","Unit","Category","Specs"];
                        const rows = items.map((item, i) => [
                          i+1,
                          item.description || "",
                          item.part_number || "",
                          item.quantity || "",
                          item.unit || "",
                          item.category || "",
                          item.specs || "",
                        ]);
                        const csvContent = [headers, ...rows]
                          .map(row => row.map(v => `"${String(v).replace(/"/g,'""')}"`).join(","))
                          .join("\n");
                        const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement("a");
                        a.href = url;
                        a.download = `${inquiryId}.csv`;
                        a.click();
                        URL.revokeObjectURL(url);
                      }}
                      className="flex items-center gap-1.5 px-3 py-1.5 bg-green-600 hover:bg-green-700 text-white rounded-lg text-xs font-semibold transition">
                      ⬇ Save as CSV
                    </button>
                  </div>
                  <div className="overflow-x-auto rounded-lg border border-green-100">
                    <table className="w-full text-xs">
                      <thead className="bg-green-100 text-green-800">
                        <tr>
                          <th className="text-left px-3 py-2 font-semibold">#</th>
                          <th className="text-left px-3 py-2 font-semibold">Description</th>
                          <th className="text-left px-3 py-2 font-semibold">Part / Ref</th>
                          <th className="text-left px-3 py-2 font-semibold">Qty</th>
                          <th className="text-left px-3 py-2 font-semibold">Unit</th>
                          <th className="text-left px-3 py-2 font-semibold">Category</th>
                          <th className="text-left px-3 py-2 font-semibold">Specs</th>
                        </tr>
                      </thead>
                      <tbody className="bg-white divide-y divide-green-50">
                        {mtoResult.rfq.items.map((item, i) => (
                          <tr key={i} className="hover:bg-green-50">
                            <td className="px-3 py-2 text-gray-400">{i+1}</td>
                            <td className="px-3 py-2 font-medium text-gray-800 max-w-[200px] truncate">{item.description}</td>
                            <td className="px-3 py-2 text-gray-500 font-mono">{item.part_number || "—"}</td>
                            <td className="px-3 py-2 text-gray-700">{item.quantity || "—"}</td>
                            <td className="px-3 py-2 text-gray-500">{item.unit || "—"}</td>
                            <td className="px-3 py-2 text-purple-600">{item.category || "—"}</td>
                            <td className="px-3 py-2 text-gray-400 max-w-[150px] truncate">{item.specs || "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Vendor Preview */}
              {mtoResult.vendor?.vendors?.length > 0 && (
                <div className="mt-3 mb-2">
                  <p className="text-xs font-semibold text-gray-700 mb-2">Vendors Linked Preview</p>
                  <div className="overflow-x-auto rounded-lg border border-green-100">
                    <table className="w-full text-xs">
                      <thead className="bg-green-100 text-green-800">
                        <tr>
                          <th className="text-left px-3 py-2 font-semibold">#</th>
                          <th className="text-left px-3 py-2 font-semibold">Vendor Name</th>
                          <th className="text-left px-3 py-2 font-semibold">Country</th>
                          <th className="text-left px-3 py-2 font-semibold">Email</th>
                          <th className="text-left px-3 py-2 font-semibold">Phone</th>
                          <th className="text-left px-3 py-2 font-semibold">Brands</th>
                        </tr>
                      </thead>
                      <tbody className="bg-white divide-y divide-green-50">
                        {mtoResult.vendor.vendors.map((v, i) => (
                          <tr key={i} className="hover:bg-green-50">
                            <td className="px-3 py-2 text-gray-400">{i + 1}</td>
                            <td className="px-3 py-2 font-medium text-gray-800 max-w-[180px] truncate">{v.name}</td>
                            <td className="px-3 py-2 text-gray-500">{[v.city, v.country].filter(Boolean).join(', ') || '—'}</td>
                            <td className="px-3 py-2 text-gray-500 max-w-[160px] truncate">{v.email || '—'}</td>
                            <td className="px-3 py-2 text-gray-500">{v.phone || '—'}</td>
                            <td className="px-3 py-2 text-purple-600 max-w-[120px] truncate">{v.brands || '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {mtoResult.vendor.inserted > 50 && (
                    <p className="text-xs text-gray-400 mt-1">Showing first 50 of {mtoResult.vendor.inserted} vendors</p>
                  )}
                </div>
              )}

              <div className="flex items-center justify-between mt-2">
                <button onClick={handleMtoClear} className="text-sm text-blue-600 hover:underline">
                  🔄 Import another file
                </button>
                <button
                  onClick={() => {
                    signalDashboardRefresh();
                    navigate('/dashboard', { state: { tab: 'rfqs' } });
                  }}
                  className="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-700 text-white px-5 py-2.5 rounded-lg text-sm font-semibold transition shadow-sm">
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7"/></svg>
                  Save &amp; View in RFQs →
                </button>
              </div>
            </div>
          )}
          </>
          )}
        </>
      )}

      {tab === "tracking" && (
        <>
          <h2 className="text-lg font-bold text-gray-800 mb-1">📋 Import RFQ Tracking Sheet</h2>
          <p className="text-sm text-gray-500 mb-5">
            Upload your RFQ tracking Excel or CSV file. Data will appear on GM, Manager, and Chairman dashboards instantly.
          </p>

          <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 mb-5">
            <p className="text-sm font-semibold text-blue-800 mb-2">Recognised column headers</p>
            <div className="grid grid-cols-2 gap-1 text-xs text-blue-700">
              {[["Enquiry Ref. No. / RFQ No *","required"],["Package Description","optional"],
                ["Closing Date","optional"],["Status","optional"],["Client","optional"],
                ["Salesperson","optional"],["Quotation Value","optional"],["Division","optional"]]
                .map(([f,r])=>(
                  <div key={f} className="flex items-center gap-1">
                    <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${r==="required"?"bg-red-400":"bg-blue-400"}`}/>
                    {f}
                  </div>
              ))}
            </div>
          </div>

          <DropZone file={tFile} onFile={f=>{setTFile(f);setTError("");setTResult(null);}}
            uploading={tUploading} label="Drag & drop or click to upload" icon="📊" fileRef={tRef}/>

          {tError && (
            <div className="bg-red-50 border border-red-200 text-red-600 rounded-lg px-4 py-3 text-sm mt-4">
              ⚠️ {tError}
            </div>
          )}

          {tFile && !tResult && (
            <div className="flex gap-2 mt-4">
              <button onClick={handleTUpload} disabled={tUploading}
                className="flex-1 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white py-3 rounded-lg font-semibold text-sm transition">
                {tUploading ? "Importing..." : `Import ${tFile.name} →`}
              </button>
              <button onClick={()=>{setTFile(null);setTResult(null);setTError("");if(tRef.current)tRef.current.value="";}}
                className="px-4 py-3 border border-gray-300 rounded-lg text-sm text-gray-600 hover:bg-gray-50 transition">
                Clear
              </button>
            </div>
          )}

          {tResult && (
            <div className="bg-green-50 border border-green-200 rounded-xl p-5 mt-4">
              <p className="text-green-800 font-semibold mb-3">✅ Import complete — dashboards update within 30 seconds</p>
              <div className="grid grid-cols-3 gap-3 text-center text-sm mb-3">
                <div className="bg-white rounded-lg p-3 border border-green-100">
                  <p className="text-2xl font-bold text-green-700">{tResult.inserted}</p>
                  <p className="text-xs text-gray-500">New RFQs</p>
                </div>
                <div className="bg-white rounded-lg p-3 border border-green-100">
                  <p className="text-2xl font-bold text-blue-600">{tResult.updated}</p>
                  <p className="text-xs text-gray-500">Updated</p>
                </div>
                <div className="bg-white rounded-lg p-3 border border-green-100">
                  <p className="text-2xl font-bold text-gray-500">{tResult.skipped}</p>
                  <p className="text-xs text-gray-500">Skipped</p>
                </div>
              </div>
              <button onClick={()=>{setTFile(null);setTResult(null);}} className="text-sm text-blue-600 hover:underline">
                🔄 Clear & import another
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
};


// ── Vendor Directory Tab ───────────────────────────────────────
export const VendorDirectory = () => {
  const PAGE = 50;
  const [query,     setQuery]     = useState("");
  const [results,   setResults]   = useState([]);
  const [total,     setTotal]     = useState(0);
  const [offset,    setOffset]    = useState(0);
  const [loading,   setLoading]   = useState(false);
  const [error,     setError]     = useState("");
  const [editId,         setEditId]         = useState(null);
  const [editData,       setEditData]       = useState({});
  const [editEmails,     setEditEmails]     = useState([]);   // multi-email list for edit form
  const [emailDraft,     setEmailDraft]     = useState("");   // new email being typed
  const [extraLocations, setExtraLocations] = useState([]);   // [{country,city,phone,email}]
  const [saving,         setSaving]         = useState(false);
  const [saveMsg,   setSaveMsg]   = useState("");
  const [addMode,   setAddMode]   = useState(false);
  const [deleting,     setDeleting]     = useState(null);
  const [selected,     setSelected]     = useState(new Set());
  const [bulkDeleting, setBulkDeleting] = useState(false);
  const [lastChecked,  setLastChecked]  = useState(null);   // index of last clicked checkbox for shift+click
  const [sortBy,       setSortBy]       = useState("date_desc");
  const [syncing,      setSyncing]      = useState(false);
  const [syncMsg,      setSyncMsg]      = useState("");
  const [date,         setDate]         = useState("");
  const [colFilters,   setColFilters]   = useState({ name: "", location: "", email: "", phone: "" });
  const [preferredOnly, setPreferredOnly] = useState(false);
  const [togglingPreferred, setTogglingPreferred] = useState(null);
  const [newVendor, setNewVendor] = useState({
    vendor_name:"", country:"", city:"", email:"", phone:"",
    website:"", brands:"", description:"", channel_codes:"",
  });

  const FIELDS = [
    { key:"vendor_name",  label:"Vendor Name",  required:true },
    { key:"country",      label:"Country"                      },
    { key:"city",         label:"City"                         },
    { key:"email",        label:"Email"                        },
    { key:"phone",        label:"Phone"                        },
    { key:"website",      label:"Website"                      },
    { key:"brands",       label:"Brands / Products"            },
    { key:"channel_codes",label:"Channel Codes"                },
    { key:"description",  label:"Description"                  },
  ];

  const load = async (q = query, off = 0, sort = sortBy, d = date, prefOnly = preferredOnly) => {
    setLoading(true); setError("");
    try {
      let url = `${API}/vendors/master/search?q=${encodeURIComponent(q)}&limit=${PAGE}&offset=${off}&sort=${sort}`;
      if (d) url += `&date_from=${d}&date_to=${d}`;
      if (prefOnly) url += `&preferred_only=true`;
      const res  = await fetch(url);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail);
      setResults(data.vendors || []);
      setTotal(data.total || 0);
      setOffset(off);
    } catch(e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const handleSortChange = (newSort) => {
    setSortBy(newSort);
    load(query, 0, newSort, date, preferredOnly);
  };

  const togglePreferredFilter = () => {
    const next = !preferredOnly;
    setPreferredOnly(next);
    load(query, 0, sortBy, date, next);
  };

  const togglePreferred = async (vendor) => {
    setTogglingPreferred(vendor.id);
    try {
      const res = await fetch(`${API}/vendors/master/${vendor.id}/toggle-preferred`, { method: "POST" });
      const data = await res.json();
      if (data.success) {
        setResults(prev => prev.map(v => v.id === vendor.id ? { ...v, is_preferred: data.is_preferred } : v));
      }
    } catch(e) {
      console.error("toggle preferred failed", e);
    } finally {
      setTogglingPreferred(null);
    }
  };

  const handleDateFilter = (d) => {
    setDate(d);
    load(query, 0, sortBy, d);
  };

  // Load all vendors on mount + refresh when import completes
  useEffect(() => {
    load("", 0, sortBy);
    const onRefresh = () => load("", 0, sortBy);
    window.addEventListener('dashboard:refresh', onRefresh);
    return () => window.removeEventListener('dashboard:refresh', onRefresh);
  }, []);

  const handleSearch = () => load(query, 0);

  const startEdit = (vendor) => {
    setEditId(vendor.id);
    const rawEmail = vendor.email || "";
    const parsed = rawEmail.split(/[,;/]+/).map(e => e.trim()).filter(e => e.includes("@"));
    setEditEmails(parsed);
    setEmailDraft("");
    setExtraLocations([]);
    setEditData({
      vendor_name:   vendor.vendor_name   || "",
      country:       vendor.country       || "",
      city:          vendor.city          || "",
      phone:         vendor.phone         || "",
      website:       vendor.website       || "",
      brands:        vendor.brands        || "",
      channel_codes: vendor.channel_codes || "",
      description:   vendor.description   || "",
    });
    setSaveMsg("");
  };

  const addLocation = () =>
    setExtraLocations(p => [...p, { country: "", city: "", phones: [], phoneDraft: "", emails: [], emailDraft: "" }]);

  const removeLocation = (i) =>
    setExtraLocations(p => p.filter((_, idx) => idx !== i));

  const setLocField = (i, field, val) =>
    setExtraLocations(p => p.map((l, idx) => idx === i ? { ...l, [field]: val } : l));

  const addLocEmail = (i) => {
    const loc = extraLocations[i];
    const parsed = (loc.emailDraft || "").split(/[,;\s]+/).map(e => e.trim()).filter(e => e.includes("@"));
    if (!parsed.length) return;
    setExtraLocations(p => p.map((l, idx) => idx === i ? { ...l, emails: [...new Set([...l.emails, ...parsed])], emailDraft: "" } : l));
  };

  const removeLocEmail = (i, ei) =>
    setExtraLocations(p => p.map((l, idx) => idx === i ? { ...l, emails: l.emails.filter((_, k) => k !== ei) } : l));

  const addLocPhone = (i) => {
    const loc = extraLocations[i];
    const val = (loc.phoneDraft || "").trim();
    if (!val) return;
    setExtraLocations(p => p.map((l, idx) => idx === i ? { ...l, phones: [...new Set([...l.phones, val])], phoneDraft: "" } : l));
  };

  const removeLocPhone = (i, pi) =>
    setExtraLocations(p => p.map((l, idx) => idx === i ? { ...l, phones: l.phones.filter((_, k) => k !== pi) } : l));

  const copyMainEmailToLoc = (i) => {
    if (!editEmails.length) return;
    setExtraLocations(p => p.map((l, idx) => idx === i ? { ...l, emails: [...new Set([...l.emails, ...editEmails])] } : l));
  };

  const addEmailToEdit = () => {
    const parsed = emailDraft.split(/[,;\s]+/).map(e => e.trim()).filter(e => e.includes("@"));
    if (parsed.length > 0) setEditEmails(prev => [...new Set([...prev, ...parsed])]);
    setEmailDraft("");
  };
  const removeEmailFromEdit = (idx) => setEditEmails(prev => prev.filter((_, i) => i !== idx));

  const saveEdit = async () => {
    setSaving(true); setSaveMsg("");
    try {
      const emailStr = editEmails.join(" / ");
      const payload = { ...editData, email: emailStr };
      const res = await fetch(`${API}/vendors/master/${editId}`, {
        method:"PATCH", headers:{"Content-Type":"application/json"},
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail);
      if (!res.ok) throw new Error(data.detail);

      // Save each extra location as a new vendor row (same name, different country)
      const validLocs = extraLocations.filter(l => l.country || l.emails.length);
      for (const loc of validLocs) {
        await fetch(`${API}/vendors/master`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            vendor_name:   editData.vendor_name,
            country:       loc.country,
            city:          loc.city,
            phone:         loc.phones.join(" / "),
            email:         loc.emails.join(" / "),
            website:       editData.website,
            brands:        editData.brands,
            channel_codes: editData.channel_codes,
            description:   editData.description,
            source:        "manual",
          }),
        });
      }

      setSaveMsg(validLocs.length ? `✅ Saved + ${validLocs.length} location(s) added` : "✅ Saved");
      setResults(prev => prev.map(v =>
        v.id === editId ? {...v, ...editData, email: emailStr, manually_overridden:true, verification_confidence:1.0} : v
      ));
      setExtraLocations([]);
      setTimeout(() => { setEditId(null); setSaveMsg(""); load(query, offset); }, 1500);
    } catch(e) {
      setSaveMsg(`❌ ${e.message}`);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (vendor) => {
    if (!window.confirm(`Delete "${vendor.vendor_name}" permanently from the database?`)) return;
    setDeleting(vendor.id);
    try {
      const res = await fetch(`${API}/vendors/master/${vendor.id}`, { method:"DELETE" });
      if (!res.ok) { const d = await res.json(); throw new Error(d.detail); }
      setResults(prev => prev.filter(v => v.id !== vendor.id));
      setTotal(t => t - 1);
    } catch(e) {
      alert("Delete failed: " + e.message);
    } finally {
      setDeleting(null);
    }
  };

  const saveNewVendor = async () => {
    if (!newVendor.vendor_name.trim()) return;
    setSaving(true); setSaveMsg("");
    try {
      const res = await fetch(`${API}/vendors/master/add`, {
        method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify(newVendor),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail);
      setSaveMsg("✅ Vendor added");
      setAddMode(false);
      setNewVendor({vendor_name:"",country:"",city:"",email:"",phone:"",website:"",brands:"",description:"",channel_codes:""});
      load(query, 0);
    } catch(e) {
      setSaveMsg(`❌ ${e.message}`);
    } finally {
      setSaving(false);
    }
  };

  const sourceColor = (s) => {
    const map = { manual_import:"bg-green-100 text-green-700", manual_override:"bg-blue-100 text-blue-700", ai_discovered:"bg-purple-100 text-purple-700" };
    return map[s] || "bg-gray-100 text-gray-600";
  };

  const blankCount = results.filter(v => !v.vendor_name?.trim()).length;

  const filteredResults = results.filter(v => {
    const cf = colFilters;
    if (cf.name     && !(v.vendor_name||"").toLowerCase().includes(cf.name.toLowerCase()))     return false;
    if (cf.location && !(`${v.city||""} ${v.country||""}`).toLowerCase().includes(cf.location.toLowerCase())) return false;
    if (cf.email    && !(v.email||"").toLowerCase().includes(cf.email.toLowerCase()))           return false;
    if (cf.phone    && !(v.phone||"").toLowerCase().includes(cf.phone.toLowerCase()))           return false;
    return true;
  });
  const hasColFilter = Object.values(colFilters).some(Boolean);

  const deleteBlankVendors = async () => {
    const blanks = results.filter(v => !v.vendor_name?.trim());
    if (!blanks.length) return;
    if (!window.confirm(`Delete ${blanks.length} nameless/blank vendor records?`)) return;
    for (const v of blanks) {
      await fetch(`${API}/vendors/master/${v.id}`, { method:"DELETE" }).catch(()=>{});
    }
    load(query, offset);
  };

  const allSelected = filteredResults.length > 0 && filteredResults.every(v => selected.has(v.id));
  const someSelected = filteredResults.some(v => selected.has(v.id));

  const toggleSelect = (id, idx, shiftKey) => {
    if (shiftKey && lastChecked !== null) {
      const lo = Math.min(lastChecked, idx);
      const hi = Math.max(lastChecked, idx);
      const rangeIds = filteredResults.slice(lo, hi + 1).map(v => v.id);
      setSelected(prev => {
        const next = new Set(prev);
        rangeIds.forEach(rid => next.add(rid));
        return next;
      });
      setLastChecked(idx);
      return;
    }
    setLastChecked(idx);
    setSelected(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (allSelected) {
      setSelected(prev => { const next = new Set(prev); filteredResults.forEach(v => next.delete(v.id)); return next; });
    } else {
      setSelected(prev => { const next = new Set(prev); filteredResults.forEach(v => next.add(v.id)); return next; });
    }
  };

  const bulkDelete = async () => {
    const ids = [...selected].filter(id => results.some(v => v.id === id));
    if (!ids.length) return;
    if (!window.confirm(`Permanently delete ${ids.length} selected vendor(s)?`)) return;
    setBulkDeleting(true);
    try {
      await fetch(`${API}/vendors/master/bulk-delete`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids }),
      });
      setSelected(new Set());
      load(query, offset);
    } finally {
      setBulkDeleting(false);
    }
  };

  const totalPages = Math.ceil(total / PAGE);
  const currentPage = Math.floor(offset / PAGE) + 1;

  return (
    <div className="flex flex-col flex-1 min-h-0 overflow-y-auto p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-5">
        <div>
          <h2 className="text-lg font-semibold text-gray-800">Vendor Directory</h2>
          <p className="text-sm text-gray-500 mt-0.5">{total} vendors in database</p>
        </div>
      </div>

      {/* Add new vendor */}
      {addMode && (
        <div className="bg-indigo-50 border border-indigo-200 rounded-xl p-5 mt-4 mb-5">
          <h3 className="font-semibold text-indigo-800 mb-3">Add new vendor</h3>
          <div className="grid grid-cols-2 gap-3">
            {FIELDS.map(f => (
              <div key={f.key} className={f.key==="description"?"col-span-2":""}>
                <label className="text-xs font-medium text-gray-600 mb-1 block">
                  {f.label}{f.required&&<span className="text-red-500 ml-0.5">*</span>}
                </label>
                {f.key === "description" ? (
                  <textarea value={newVendor[f.key]} onChange={e=>setNewVendor(p=>({...p,[f.key]:e.target.value}))}
                    rows={2} className="w-full border border-indigo-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none bg-white"/>
                ) : (
                  <input value={newVendor[f.key]} onChange={e=>setNewVendor(p=>({...p,[f.key]:e.target.value}))}
                    className="w-full border border-indigo-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 bg-white"/>
                )}
              </div>
            ))}
          </div>
          {saveMsg && <p className={`text-sm mt-3 ${saveMsg.startsWith("✅")?"text-green-600":"text-red-500"}`}>{saveMsg}</p>}
          <button onClick={saveNewVendor} disabled={saving||!newVendor.vendor_name.trim()}
            className="mt-4 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 text-white px-6 py-2 rounded-lg text-sm font-medium transition">
            {saving ? "Saving..." : "Save vendor →"}
          </button>
        </div>
      )}


      {/* Column filters */}
      <div className="bg-gray-50 border border-gray-200 rounded-xl px-4 py-3 mb-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Column Filters</span>
          {hasColFilter && (
            <button onClick={() => setColFilters({ name: "", location: "", email: "", phone: "" })}
              className="text-xs text-indigo-600 hover:underline font-medium">✕ Clear all</button>
          )}
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          <div>
            <label className="text-xs text-gray-400 mb-1 block">Company Name</label>
            <input value={colFilters.name} onChange={e => setColFilters(f => ({...f, name: e.target.value}))}
              placeholder="Search name..."
              className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-indigo-400"/>
          </div>
          <div>
            <label className="text-xs text-gray-400 mb-1 block">Location</label>
            <input value={colFilters.location} onChange={e => setColFilters(f => ({...f, location: e.target.value}))}
              placeholder="City or country..."
              className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-indigo-400"/>
          </div>
          <div>
            <label className="text-xs text-gray-400 mb-1 block">Email</label>
            <input value={colFilters.email} onChange={e => setColFilters(f => ({...f, email: e.target.value}))}
              placeholder="Search email..."
              className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-indigo-400"/>
          </div>
          <div>
            <label className="text-xs text-gray-400 mb-1 block">Phone</label>
            <input value={colFilters.phone} onChange={e => setColFilters(f => ({...f, phone: e.target.value}))}
              placeholder="Search number..."
              className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-indigo-400"/>
          </div>
        </div>
        {hasColFilter && (
          <div className="flex flex-wrap gap-1.5 mt-2">
            {colFilters.name     && <span className="bg-indigo-100 text-indigo-700 text-xs px-2 py-0.5 rounded-full">Name: {colFilters.name}</span>}
            {colFilters.location && <span className="bg-indigo-100 text-indigo-700 text-xs px-2 py-0.5 rounded-full">Location: {colFilters.location}</span>}
            {colFilters.email    && <span className="bg-indigo-100 text-indigo-700 text-xs px-2 py-0.5 rounded-full">Email: {colFilters.email}</span>}
            {colFilters.phone    && <span className="bg-indigo-100 text-indigo-700 text-xs px-2 py-0.5 rounded-full">Phone: {colFilters.phone}</span>}
          </div>
        )}
      </div>

      {/* Sort */}
      <div className="flex items-center gap-2 mb-4 flex-wrap">
        <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider mr-1">Sort by:</span>
        {[
          { key: "date_desc", label: "Newest first", icon: "↓" },
          { key: "date_asc",  label: "Oldest first", icon: "↑" },
          { key: "name_asc",  label: "A → Z",        icon: ""  },
          { key: "name_desc", label: "Z → A",        icon: ""  },
        ].map(opt => (
          <button key={opt.key} onClick={() => handleSortChange(opt.key)}
            className={`px-4 py-1.5 rounded-full text-xs font-semibold border transition-all
              ${sortBy === opt.key
                ? "bg-indigo-600 text-white border-indigo-600 shadow-sm"
                : "bg-white text-gray-600 border-gray-300 hover:border-indigo-400 hover:text-indigo-600"}`}>
            {opt.icon && <span className="mr-1 font-bold">{opt.icon}</span>}{opt.label}
          </button>
        ))}
        <span className="ml-auto text-xs text-gray-400 italic">Sorts across all {total} vendors</span>
        <button onClick={togglePreferredFilter}
          className={`ml-2 flex items-center gap-1.5 px-4 py-1.5 rounded-full text-xs font-semibold border transition-all
            ${preferredOnly
              ? "bg-amber-500 text-white border-amber-500 shadow-sm"
              : "bg-white text-gray-500 border-gray-300 hover:border-amber-400 hover:text-amber-600"}`}>
          ★ {preferredOnly ? "Showing Preferred" : "Preferred Only"}
        </button>
      </div>

      {/* Date filter */}
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Date:</span>
        <input type="date" value={date}
          onChange={e => handleDateFilter(e.target.value)}
          className="border border-gray-300 rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-indigo-400"/>
        {date && (
          <button onClick={() => handleDateFilter("")} className="text-xs text-indigo-600 hover:underline font-medium">✕ Clear</button>
        )}
        {date && (
          <span className="text-xs bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full">{date}</span>
        )}
      </div>

      {error && <div className="bg-red-50 border border-red-200 text-red-600 rounded-lg px-4 py-3 text-sm mb-4">⚠️ {error}</div>}

      {/* Warn about blank/nameless records */}
      {blankCount > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-sm mb-4 flex items-center justify-between gap-3">
          <span className="text-amber-700">⚠️ {blankCount} records on this page have no vendor name — they are corrupt import rows.</span>
          <button onClick={deleteBlankVendors}
            className="flex-shrink-0 bg-red-500 hover:bg-red-600 text-white px-3 py-1.5 rounded-lg text-xs font-semibold transition">
            Delete {blankCount} blank records
          </button>
        </div>
      )}

      {/* Toolbar: select-all + count + pagination + bulk delete */}
      {total > 0 && (
        <div className="flex items-center justify-between mb-3 gap-3 flex-wrap">
          <div className="flex items-center gap-3">
            {/* Select All checkbox */}
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <input type="checkbox" checked={allSelected} ref={el => { if (el) el.indeterminate = someSelected && !allSelected; }}
                onChange={toggleSelectAll}
                className="w-4 h-4 rounded border-gray-300 text-indigo-600 cursor-pointer"/>
              <span className="text-xs text-gray-500">
                {allSelected ? "Deselect all" : "Select all on page"}
              </span>
            </label>
            <span className="text-xs text-gray-400">
              Showing {offset + 1}–{Math.min(offset + PAGE, total)} of {total}
              {query ? ` for "${query}"` : ""}
            </span>
          </div>

          <div className="flex items-center gap-2">
            {totalPages > 1 && (
              <>
                <button onClick={()=>{ setSelected(new Set()); load(query, offset - PAGE, sortBy, date); }} disabled={offset===0||loading}
                  className="px-3 py-1 rounded-lg border text-xs font-medium disabled:opacity-40 hover:bg-indigo-50 hover:border-indigo-400 hover:text-indigo-700 transition">← Prev</button>
                <span className="text-xs font-semibold text-gray-600 bg-indigo-50 border border-indigo-200 px-3 py-1 rounded-lg">
                  Page {currentPage} of {totalPages}
                </span>
                <button onClick={()=>{ setSelected(new Set()); load(query, offset + PAGE, sortBy, date); }} disabled={offset+PAGE>=total||loading}
                  className="px-3 py-1 rounded-lg border text-xs font-medium disabled:opacity-40 hover:bg-indigo-50 hover:border-indigo-400 hover:text-indigo-700 transition">Next →</button>
              </>
            )}
          </div>
        </div>
      )}

      {/* Bulk delete bar — appears when items are selected */}
      {selected.size > 0 && (
        <div className="flex items-center justify-between bg-red-50 border border-red-200 rounded-lg px-4 py-2.5 mb-3 gap-3">
          <span className="text-sm font-medium text-red-700">{selected.size} vendor{selected.size > 1 ? "s" : ""} selected</span>
          <div className="flex gap-2">
            <button onClick={() => setSelected(new Set())}
              className="px-3 py-1.5 text-xs border border-gray-300 rounded-lg text-gray-600 hover:bg-gray-50 transition">
              Clear selection
            </button>
            <button onClick={bulkDelete} disabled={bulkDeleting}
              className="px-4 py-1.5 bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white text-xs font-semibold rounded-lg transition">
              {bulkDeleting ? "Deleting..." : `🗑 Delete ${selected.size} selected`}
            </button>
          </div>
        </div>
      )}

      {/* Loading skeleton */}
      {loading && results.length === 0 && (
        <div className="space-y-2 mt-2">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="border border-gray-100 bg-white rounded-xl p-3 animate-pulse">
              <div className="flex items-start gap-3">
                <div className="w-4 h-4 bg-gray-200 rounded mt-1 flex-shrink-0" />
                <div className="flex-1 space-y-2">
                  <div className="flex gap-2 flex-wrap">
                    <div className="h-4 bg-gray-200 rounded w-36" />
                    <div className="h-4 bg-gray-100 rounded w-14" />
                    <div className="h-4 bg-gray-100 rounded w-10" />
                  </div>
                  <div className="h-3 bg-gray-100 rounded w-48" />
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Vendor list */}
      {hasColFilter && (
        <p className="text-xs text-gray-500 mb-2">
          Showing {filteredResults.length} of {results.length} loaded vendors matching filters
        </p>
      )}
      <div className="space-y-2">
        {filteredResults.map((vendor, vidx) => (
          <div key={vendor.id}
            className={`border rounded-xl transition
              ${editId===vendor.id
                ? "border-indigo-400 bg-indigo-50 p-4"
                : selected.has(vendor.id)
                  ? "border-red-300 bg-red-50 p-3"
                  : "border-gray-200 bg-white hover:shadow-sm p-3"}`}>

            {editId === vendor.id ? (
              /* ── Edit mode ── */
              <div>
                <div className="grid grid-cols-2 gap-3 mb-3">
                  {FIELDS.filter(f => f.key !== "email").map(f => (
                    <div key={f.key} className={f.key==="description"?"col-span-2":""}>
                      <label className="text-xs font-medium text-gray-500 mb-0.5 block">{f.label}</label>
                      {f.key === "description" ? (
                        <textarea value={editData[f.key]||""} onChange={e=>setEditData(p=>({...p,[f.key]:e.target.value}))}
                          rows={2} className="w-full border border-indigo-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none bg-white"/>
                      ) : (
                        <input value={editData[f.key]||""} onChange={e=>setEditData(p=>({...p,[f.key]:e.target.value}))}
                          className="w-full border border-indigo-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 bg-white"/>
                      )}
                    </div>
                  ))}
                  {/* ── Email — multi-pill editor ── */}
                  <div className="col-span-2">
                    <label className="text-xs font-medium text-gray-500 mb-1 block">Email</label>
                    <div className="flex flex-wrap gap-1.5 mb-1.5">
                      {editEmails.map((e, i) => (
                        <span key={i} className="inline-flex items-center gap-1 text-xs bg-blue-50 text-blue-700 border border-blue-200 px-2 py-0.5 rounded font-mono">
                          {e}
                          <button onClick={() => removeEmailFromEdit(i)} className="text-blue-300 hover:text-red-500 font-bold ml-0.5">×</button>
                        </span>
                      ))}
                      {editEmails.length === 0 && <span className="text-xs text-gray-400 italic">No email — add one below</span>}
                    </div>
                    <div className="flex gap-2">
                      <input value={emailDraft} onChange={e => setEmailDraft(e.target.value)}
                        onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); addEmailToEdit(); } }}
                        placeholder="email@company.com  (Enter or click Add)"
                        className="flex-1 border border-indigo-300 rounded-lg px-3 py-1.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500 bg-white"/>
                      <button onClick={addEmailToEdit}
                        className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white text-xs rounded-lg font-medium transition">
                        + Add
                      </button>
                    </div>
                  </div>
                </div>
                {/* ── Extra Locations ── */}
                <div className="mt-4 border-t border-indigo-100 pt-4">
                  <div className="flex items-center justify-between mb-3">
                    <div>
                      <span className="text-xs font-semibold text-gray-700 uppercase tracking-widest">Other Locations</span>
                      <span className="ml-2 text-xs text-gray-400">same company · different country</span>
                    </div>
                    <button onClick={addLocation}
                      className="flex items-center gap-1.5 text-xs bg-indigo-600 hover:bg-indigo-700 text-white px-3 py-1.5 rounded-lg font-medium transition shadow-sm">
                      <span style={{fontSize:"14px"}}>＋</span> Add Location
                    </button>
                  </div>

                  {extraLocations.length === 0 && (
                    <p className="text-xs text-gray-400 italic py-2">No extra locations yet — click "Add Location" to add UAE, Saudi Arabia, Qatar etc. with their own contact details.</p>
                  )}

                  <div className="space-y-3">
                    {extraLocations.map((loc, i) => (
                      <div key={i} className="rounded-xl bg-white overflow-hidden"
                        style={{border:"1px solid #c7d2fe", borderLeft:"4px solid #6366f1"}}>
                        {/* Location header */}
                        <div className="flex items-center justify-between px-3 py-2 bg-indigo-50 border-b border-indigo-100">
                          <span className="text-xs font-semibold text-indigo-700">
                            Location {i + 1}{loc.country ? ` — ${loc.country}` : ""}
                          </span>
                          <button onClick={() => removeLocation(i)}
                            className="text-xs text-red-400 hover:text-red-600 font-medium px-2 py-0.5 rounded hover:bg-red-50 transition">
                            ✕ Remove
                          </button>
                        </div>

                        <div className="p-3 space-y-3">
                          {/* Country + City */}
                          <div className="grid grid-cols-2 gap-2">
                            <div>
                              <label className="text-xs font-medium text-gray-500 mb-0.5 block">Country</label>
                              <input value={loc.country} onChange={e => setLocField(i, "country", e.target.value)}
                                placeholder="e.g. Saudi Arabia"
                                className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 bg-white"/>
                            </div>
                            <div>
                              <label className="text-xs font-medium text-gray-500 mb-0.5 block">City</label>
                              <input value={loc.city} onChange={e => setLocField(i, "city", e.target.value)}
                                placeholder="e.g. Riyadh"
                                className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 bg-white"/>
                            </div>
                          </div>

                          {/* Emails */}
                          <div>
                            <div className="flex items-center justify-between mb-1">
                              <label className="text-xs font-medium text-gray-500">Email(s)</label>
                              {editEmails.length > 0 && (
                                <button onClick={() => copyMainEmailToLoc(i)}
                                  className="flex items-center gap-1 text-xs bg-indigo-50 border border-indigo-200 text-indigo-600 hover:bg-indigo-100 px-2 py-0.5 rounded-full font-medium transition">
                                  ↙ Copy from main
                                </button>
                              )}
                            </div>
                            <div className="flex flex-wrap gap-1.5 mb-1.5 min-h-[24px]">
                              {loc.emails.map((e, ei) => (
                                <span key={ei} className="inline-flex items-center gap-1 text-xs bg-blue-50 text-blue-700 border border-blue-200 px-2 py-0.5 rounded font-mono">
                                  {e}
                                  <button onClick={() => removeLocEmail(i, ei)} className="text-blue-300 hover:text-red-500 font-bold ml-0.5">×</button>
                                </span>
                              ))}
                              {loc.emails.length === 0 && <span className="text-xs text-gray-400 italic">No email yet</span>}
                            </div>
                            <div className="flex gap-2">
                              <input value={loc.emailDraft}
                                onChange={e => setLocField(i, "emailDraft", e.target.value)}
                                onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); addLocEmail(i); } }}
                                placeholder="email@company.com"
                                className="flex-1 border border-gray-200 rounded-lg px-3 py-1.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-400 bg-white"/>
                              <button onClick={() => addLocEmail(i)}
                                className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white text-xs rounded-lg font-medium transition">
                                + Add
                              </button>
                            </div>
                          </div>

                          {/* Phones */}
                          <div>
                            <label className="text-xs font-medium text-gray-500 mb-1 block">Phone(s)</label>
                            <div className="flex flex-wrap gap-1.5 mb-1.5 min-h-[24px]">
                              {loc.phones.map((ph, pi) => (
                                <span key={pi} className="inline-flex items-center gap-1 text-xs bg-green-50 text-green-700 border border-green-200 px-2 py-0.5 rounded font-mono">
                                  {ph}
                                  <button onClick={() => removeLocPhone(i, pi)} className="text-green-300 hover:text-red-500 font-bold ml-0.5">×</button>
                                </span>
                              ))}
                              {loc.phones.length === 0 && <span className="text-xs text-gray-400 italic">No phone yet</span>}
                            </div>
                            <div className="flex gap-2">
                              <input value={loc.phoneDraft}
                                onChange={e => setLocField(i, "phoneDraft", e.target.value)}
                                onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); addLocPhone(i); } }}
                                placeholder="+966 11 xxx xxxx"
                                className="flex-1 border border-gray-200 rounded-lg px-3 py-1.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-400 bg-white"/>
                              <button onClick={() => addLocPhone(i)}
                                className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white text-xs rounded-lg font-medium transition">
                                + Add
                              </button>
                            </div>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {saveMsg && <p className={`text-sm mb-2 ${saveMsg.startsWith("✅")?"text-green-600":"text-red-500"}`}>{saveMsg}</p>}
                <div className="flex gap-2">
                  <button onClick={saveEdit} disabled={saving}
                    className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 text-white px-5 py-1.5 rounded-lg text-sm font-medium transition">
                    {saving ? "Saving..." : "Save changes"}
                  </button>
                  <button onClick={()=>{setEditId(null);setSaveMsg("");setExtraLocations([]);}}
                    className="px-5 py-1.5 border border-gray-300 rounded-lg text-sm text-gray-600 hover:bg-gray-50 transition">
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              /* ── View mode ── */
              <div className="flex items-start gap-3">
                <input type="checkbox" checked={selected.has(vendor.id)}
                  onChange={(e) => toggleSelect(vendor.id, vidx, e.nativeEvent.shiftKey)}
                  className="mt-1 w-4 h-4 rounded border-gray-300 text-indigo-600 flex-shrink-0 cursor-pointer"/>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap mb-0.5">
                    <span className={`font-semibold text-sm ${vendor.vendor_name?.trim() ? "text-gray-800" : "text-red-400 italic"}`}>
                      {vendor.vendor_name?.trim() || `[No name — ID: ${vendor.id}]`}
                    </span>
                    {vendor.is_preferred && (
                      <span className="text-xs bg-amber-100 text-amber-700 px-2 py-0.5 rounded font-semibold">★ Preferred</span>
                    )}
                    {vendor.manually_overridden && (
                      <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded font-medium">✎ Verified</span>
                    )}
                    <span className={`text-xs px-2 py-0.5 rounded font-medium ${sourceColor(vendor.source)}`}>
                      {vendor.source?.replace(/_/g," ")}
                    </span>
                    {vendor.channel_codes && (
                      <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded">{vendor.channel_codes}</span>
                    )}
                  </div>
                  <div className="flex gap-3 text-xs text-gray-500 flex-wrap">
                    {vendor.country && <span>📍 {vendor.city?`${vendor.city}, `:""}{vendor.country}</span>}
                    {vendor.email && vendor.email.split(/[,;/]+/).map(e=>e.trim()).filter(e=>e).map((e,i)=>(
                      <span key={i} className="text-blue-500 font-mono">{e}</span>
                    ))}
                    {vendor.phone && <span>{vendor.phone}</span>}
                    {vendor.website && (
                      <a href={vendor.website.startsWith("http")?vendor.website:`https://${vendor.website}`}
                        target="_blank" rel="noopener noreferrer"
                        className="text-blue-400 hover:underline" onClick={e=>e.stopPropagation()}>
                        {vendor.website.replace(/https?:\/\/(www\.)?/,"")}
                      </a>
                    )}
                  </div>
                  <div className="flex items-center gap-3 mt-0.5">
                    {vendor.brands && <p className="text-xs text-gray-400 truncate">Brands: {vendor.brands}</p>}
                    {vendor.created_at && (
                      <p className="text-xs text-gray-300 flex-shrink-0">
                        {vendor.source === "ai_discovered" ? "Found" : "Imported"}{" "}
                        {new Date(vendor.created_at).toLocaleDateString("en-GB", { day:"2-digit", month:"short", year:"numeric" })}
                      </p>
                    )}
                  </div>
                </div>
                {/* Action buttons */}
                <div className="flex items-center gap-1.5 flex-shrink-0">
                  <button
                    onClick={() => togglePreferred(vendor)}
                    disabled={togglingPreferred === vendor.id}
                    title={vendor.is_preferred ? "Remove from preferred" : "Mark as preferred supplier"}
                    className={`px-2.5 py-1.5 rounded-lg text-xs font-semibold border transition
                      ${vendor.is_preferred
                        ? "bg-amber-50 border-amber-300 text-amber-600 hover:bg-amber-100"
                        : "border-gray-200 text-gray-400 hover:border-amber-300 hover:text-amber-500 hover:bg-amber-50"}`}>
                    {togglingPreferred === vendor.id ? "..." : vendor.is_preferred ? "★ Preferred" : "☆"}
                  </button>
                  <button onClick={()=>startEdit(vendor)}
                    className="px-3 py-1.5 border border-gray-300 rounded-lg text-xs font-medium text-gray-600 hover:bg-gray-50 transition">
                    ✏️ Edit
                  </button>
                  <button onClick={()=>handleDelete(vendor)} disabled={deleting===vendor.id}
                    className="px-3 py-1.5 border border-red-200 rounded-lg text-xs font-medium text-red-500 hover:bg-red-50 transition disabled:opacity-40">
                    {deleting===vendor.id ? "..." : "🗑 Delete"}
                  </button>
                </div>
              </div>
            )}
          </div>
        ))}

        {results.length===0 && !loading && (
          <div className="text-center py-12 text-gray-400">
            <p className="text-3xl mb-2">🔍</p>
            <p className="text-sm">{query ? `No vendors found for "${query}"` : "No vendors in database"}</p>
          </div>
        )}

        {loading && (
          <div className="text-center py-12 text-gray-400">
            <p className="text-sm">Loading vendors...</p>
          </div>
        )}
      </div>

      {/* Bottom pagination */}
      {totalPages > 1 && !loading && (
        <div className="flex items-center justify-between mt-5 pt-4 border-t border-gray-100 flex-wrap gap-3">
          <button onClick={()=>{ setSelected(new Set()); load(query, offset - PAGE, sortBy, date); }} disabled={offset===0}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg border text-sm font-medium disabled:opacity-40 hover:bg-indigo-50 hover:border-indigo-400 hover:text-indigo-700 transition">
            ← Previous
          </button>

          <div className="flex items-center gap-2">
            {/* Page number pills */}
            {Array.from({ length: totalPages }, (_, i) => i + 1)
              .filter(p => p === 1 || p === totalPages || Math.abs(p - currentPage) <= 2)
              .reduce((acc, p, idx, arr) => {
                if (idx > 0 && p - arr[idx - 1] > 1) acc.push("...");
                acc.push(p);
                return acc;
              }, [])
              .map((p, i) =>
                p === "..." ? (
                  <span key={`ellipsis-${i}`} className="text-gray-400 text-sm px-1">…</span>
                ) : (
                  <button key={p} onClick={() => { setSelected(new Set()); load(query, (p - 1) * PAGE, sortBy, date); }}
                    className={`w-8 h-8 rounded-lg text-xs font-semibold transition
                      ${p === currentPage
                        ? "bg-indigo-600 text-white shadow-sm"
                        : "border border-gray-300 text-gray-600 hover:border-indigo-400 hover:text-indigo-600 hover:bg-indigo-50"}`}>
                    {p}
                  </button>
                )
              )
            }
          </div>

          <button onClick={()=>{ setSelected(new Set()); load(query, offset + PAGE, sortBy, date); }} disabled={offset+PAGE>=total}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg border text-sm font-medium disabled:opacity-40 hover:bg-indigo-50 hover:border-indigo-400 hover:text-indigo-700 transition">
            Next →
          </button>
        </div>
      )}
      <div className="h-4 flex-shrink-0" />
    </div>
  );
};