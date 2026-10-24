import { useState, useRef, useEffect } from "react";
import { API } from "../config/api";

const WORKFLOW_STAGES = [
  { id: "inquiry",  icon: "📋", label: "Inquiry & Docs" },
  { id: "drawing",  icon: "📐", label: "Drawing Analysis" },
  { id: "boq",      icon: "✅", label: "BOQ Verification" },
  { id: "material", icon: "🔩", label: "Material ID" },
  { id: "takeoff",  icon: "📊", label: "Quantity Take-Off" },
  { id: "weight",   icon: "⚖️", label: "Weight Calc" },
  { id: "scope",    icon: "🎯", label: "Scope Confirmation" },
  { id: "review",   icon: "🔍", label: "Final Review" },
];

const SUGGESTED_PROMPTS = [
  { stage: "inquiry",  text: "Review this document and summarize the full scope of inquiry" },
  { stage: "drawing",  text: "Analyse the drawing and identify all structural components, dimensions and fabrication requirements" },
  { stage: "boq",      text: "Cross-verify this BOQ against the drawing and flag any discrepancies" },
  { stage: "material", text: "Identify all required material types and grades from this document" },
  { stage: "takeoff",  text: "Extract and quantify all components including plates, members, bolts and rods" },
  { stage: "weight",   text: "Calculate the estimated material weight using standard engineering formulas" },
  { stage: "scope",    text: "Confirm the full scope of supply including fabrication, surface treatment and assembly" },
  { stage: "review",   text: "Do a final review — check for missing components, incorrect quantities or unclear scope" },
];

const FILE_ICONS = {
  pdf: "📄", dwg: "📐", dxf: "📐",
  xlsx: "📊", xls: "📊", csv: "📊",
  docx: "📝", doc: "📝", txt: "📝",
  png: "🖼️", jpg: "🖼️", jpeg: "🖼️",
};
const getFileIcon = (name) => FILE_ICONS[name?.split(".").pop().toLowerCase()] || "📎";
const getFileExt  = (name) => name?.split(".").pop().toUpperCase();

// ── Structured Drawing Card ───────────────────────────────────
const Badge = ({ text, color = "gray" }) => {
  const colors = {
    blue:   "bg-blue-100 text-blue-700",
    green:  "bg-green-100 text-green-700",
    purple: "bg-purple-100 text-purple-700",
    orange: "bg-orange-100 text-orange-700",
    red:    "bg-red-100 text-red-700",
    gray:   "bg-gray-100 text-gray-600",
    indigo: "bg-indigo-100 text-indigo-700",
  };
  return <span className={`text-xs px-2 py-0.5 rounded-full font-semibold ${colors[color] || colors.gray}`}>{text}</span>;
};

const KV = ({ label, value }) => (
  <div className="flex justify-between py-1 border-b border-gray-50 last:border-0">
    <span className="text-xs text-gray-400">{label}</span>
    <span className="text-xs font-semibold text-gray-700 font-mono text-right max-w-[55%]">{value || "—"}</span>
  </div>
);

const CollapsibleSection = ({ title, icon, children, defaultOpen = true }) => {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border border-gray-100 rounded-lg overflow-hidden mb-2">
      <button onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-2 bg-gray-50 hover:bg-gray-100 transition text-left">
        <span className="flex items-center gap-2 text-xs font-semibold text-gray-700">
          <span>{icon}</span>{title}
        </span>
        <span className="text-gray-400 text-xs">{open ? "▲" : "▼"}</span>
      </button>
      {open && <div className="px-4 py-3">{children}</div>}
    </div>
  );
};

const DrawingCard = ({ data }) => {
  if (!data) return null;
  return (
    <div className="bg-white border border-gray-200 rounded-2xl overflow-hidden shadow-sm w-full mt-2">
      <div className="bg-indigo-700 text-white px-5 py-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 mb-1 flex-wrap">
              <span className="text-xs font-mono bg-indigo-600 px-2 py-0.5 rounded">{data.documentInfo?.dwgNo || "—"}</span>
              {data.documentInfo?.rev && <span className="text-xs bg-indigo-500 px-2 py-0.5 rounded font-bold">REV {data.documentInfo.rev}</span>}
            </div>
            <p className="text-sm font-bold leading-snug">{data.projectInfo?.dwgTitle || "Drawing"}</p>
            <p className="text-indigo-200 text-xs mt-0.5">{data.projectInfo?.projectTitle}</p>
          </div>
          <div className="text-right text-xs text-indigo-200 flex-shrink-0">
            <p>{data.documentInfo?.size} · {data.documentInfo?.sheet}</p>
            <p>Proposal: {data.documentInfo?.proposalNo}</p>
          </div>
        </div>
        <div className="grid grid-cols-3 gap-2 mt-3 pt-3 border-t border-indigo-600">
          {[["Company", data.projectInfo?.company], ["Contractor", data.projectInfo?.contractor], ["Vendor", data.projectInfo?.vendor]].map(([l, v]) => (
            <div key={l}>
              <p className="text-xs text-indigo-300">{l}</p>
              <p className="text-xs font-semibold">{v || "—"}</p>
            </div>
          ))}
        </div>
      </div>

      <div className="p-4 space-y-1">
        {data.skidSizes && (
          <CollapsibleSection title="Skid Dimensions" icon="📦">
            <div className="grid grid-cols-2 gap-x-6">
              {Object.entries(data.skidSizes).map(([k, v]) => (
                <KV key={k} label={k.charAt(0).toUpperCase() + k.slice(1)} value={v} />
              ))}
            </div>
          </CollapsibleSection>
        )}
        {data.connections?.length > 0 && (
          <CollapsibleSection title="Nozzle Connections" icon="🔌">
            <div className="space-y-2">
              {data.connections.map((c, i) => (
                <div key={i} className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Badge text={c.tag} color="blue" />
                    <Badge text={c.type} color={c.type === "INLET" ? "green" : "orange"} />
                  </div>
                  <span className="text-xs font-mono font-semibold text-gray-700">{c.spec}</span>
                </div>
              ))}
            </div>
          </CollapsibleSection>
        )}
        {data.revisionHistory?.length > 0 && (
          <CollapsibleSection title="Revision History" icon="📋" defaultOpen={false}>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="bg-gray-50">
                    {["Rev", "Description", "Drwn", "Dsn'd", "Rvw'd", "App'd", "Date"].map(h => (
                      <th key={h} className="px-2 py-1.5 text-left text-gray-500 font-semibold">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {data.revisionHistory.map(r => (
                    <tr key={r.rev} className={r.rev === data.documentInfo?.rev ? "bg-indigo-50" : ""}>
                      <td className="px-2 py-1.5"><Badge text={r.rev} color={r.rev === data.documentInfo?.rev ? "indigo" : "gray"} /></td>
                      <td className="px-2 py-1.5 text-gray-600">{r.description}</td>
                      <td className="px-2 py-1.5 font-mono text-gray-500">{r.drwn}</td>
                      <td className="px-2 py-1.5 font-mono text-gray-500">{r.dsnD}</td>
                      <td className="px-2 py-1.5 font-mono text-gray-500">{r.rvwD}</td>
                      <td className="px-2 py-1.5 font-mono text-gray-500">{r.appD}</td>
                      <td className="px-2 py-1.5 text-gray-500">{r.date}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CollapsibleSection>
        )}
        {data.flowMeters?.length > 0 && (
          <CollapsibleSection title="Flow Meters" icon="🌀">
            <div className="grid grid-cols-2 gap-3">
              {data.flowMeters.map((fm, i) => (
                <div key={i} className="bg-blue-50 border border-blue-100 rounded-lg p-3">
                  <div className="flex items-center gap-2 mb-2">
                    <Badge text={fm.tag} color="blue" />
                    <span className="text-xs font-semibold text-blue-800">{fm.duty}</span>
                  </div>
                  {fm.straight && <>
                    <KV label="Upstream" value={fm.straight.upstream} />
                    <KV label="Downstream" value={fm.straight.downstream} />
                  </>}
                </div>
              ))}
            </div>
          </CollapsibleSection>
        )}
        {data.instruments?.length > 0 && (
          <CollapsibleSection title="Instruments & Tags" icon="🎛️" defaultOpen={false}>
            <div className="grid grid-cols-2 gap-2">
              {data.instruments.map((inst, i) => (
                <div key={i} className="flex items-center gap-2 bg-gray-50 rounded-lg px-3 py-2">
                  <Badge text={inst.tag} color="orange" />
                  <span className="text-xs text-gray-600">{inst.description}</span>
                </div>
              ))}
            </div>
          </CollapsibleSection>
        )}
        {data.valves?.length > 0 && (
          <CollapsibleSection title="Valves" icon="🔧" defaultOpen={false}>
            <div className="grid grid-cols-2 gap-2">
              {data.valves.map((v, i) => (
                <div key={i} className="flex items-center justify-between bg-gray-50 rounded-lg px-3 py-2">
                  <div className="flex items-center gap-2">
                    <Badge text={v.type} color="purple" />
                    <span className="text-xs text-gray-500">{v.location}</span>
                  </div>
                  <span className="text-xs font-bold text-gray-700">×{v.qty}</span>
                </div>
              ))}
            </div>
          </CollapsibleSection>
        )}
        {data.analyzerSystems?.length > 0 && (
          <CollapsibleSection title="Analyzer Systems" icon="🔬" defaultOpen={false}>
            {data.analyzerSystems.map((a, i) => (
              <div key={i} className="flex items-center justify-between py-2 border-b border-gray-50 last:border-0">
                <div className="flex items-center gap-2">
                  <Badge text={a.tag} color="green" />
                  <span className="text-xs font-semibold text-gray-700">{a.description}</span>
                </div>
                <span className="text-xs text-gray-400">{a.location}</span>
              </div>
            ))}
          </CollapsibleSection>
        )}
        {data.pipingDistances?.length > 0 && (
          <CollapsibleSection title="Piping Distances" icon="📏" defaultOpen={false}>
            <div className="grid grid-cols-2 gap-2">
              {data.pipingDistances.map((p, i) => (
                <div key={i} className="flex items-center justify-between bg-gray-50 rounded-lg px-3 py-2">
                  <span className="text-xs text-gray-600">{p.ref}</span>
                  <span className="text-xs font-mono font-bold text-indigo-700">{p.distance}</span>
                </div>
              ))}
            </div>
          </CollapsibleSection>
        )}
        {data.reducers?.length > 0 && (
          <CollapsibleSection title="Reducers" icon="🔩" defaultOpen={false}>
            <div className="grid grid-cols-2 gap-2">
              {data.reducers.map((r, i) => (
                <div key={i} className="flex items-center justify-between bg-gray-50 rounded-lg px-3 py-2">
                  <span className="text-xs font-mono font-semibold text-gray-700">{r.description}</span>
                  <Badge text={r.location} color="gray" />
                </div>
              ))}
            </div>
          </CollapsibleSection>
        )}
        {data.inquiryScope     && <InquiryScopeCard data={data} />}
        {data.drawingAnalysis  && <DrawingAnalysisCard data={data} />}
        {data.boqItems         && <BOQCard data={data} />}
        {data.materials        && <MaterialCard data={data} />}
        {data.quantityItems    && <TakeoffCard data={data} />}
        {data.weightCalculations && <WeightCard data={data} />}
        {data.scopeItems       && <ScopeCard data={data} />}
        {data.reviewChecklist  && <ReviewCard data={data} />}
      </div>
    </div>
  );
};

// ── Message Bubble ────────────────────────────────────────────
const MessageBubble = ({ msg }) => {
  const isUser = msg.role === "user";
  return (
    <div className={`flex gap-3 ${isUser ? "flex-row-reverse" : "flex-row"} mb-4`}>
      <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs flex-shrink-0 font-bold
        ${isUser ? "bg-indigo-600 text-white" : "bg-gray-800 text-white"}`}>
        {isUser ? "S" : "AI"}
      </div>
      <div className={`max-w-[78%] flex flex-col gap-2 ${isUser ? "items-end" : "items-start"}`}>
        {msg.files?.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {msg.files.map((f, i) => (
              <div key={i} className="flex items-center gap-2 bg-white border border-gray-200 rounded-xl px-3 py-2 shadow-sm">
                <span className="text-lg">{getFileIcon(f.name)}</span>
                <div>
                  <p className="text-xs font-semibold text-gray-700 max-w-[140px] truncate">{f.name}</p>
                  <p className="text-xs text-gray-400">{getFileExt(f.name)} · {(f.size / 1024).toFixed(1)} KB</p>
                </div>
              </div>
            ))}
          </div>
        )}
        {msg.text && (
          <div className={`px-4 py-3 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap shadow-sm
            ${isUser
              ? "bg-indigo-600 text-white rounded-tr-sm"
              : "bg-white border border-gray-200 text-gray-800 rounded-tl-sm"}`}>
            {msg.text}
          </div>
        )}
        {msg.drawingData && <DrawingCard data={msg.drawingData} />}
        {msg.stage && (
          <div className="flex items-center gap-1 text-xs text-gray-400">
            <span>{WORKFLOW_STAGES.find(s => s.id === msg.stage)?.icon}</span>
            <span>{WORKFLOW_STAGES.find(s => s.id === msg.stage)?.label}</span>
          </div>
        )}
        <span className="text-xs text-gray-400">
          {new Date(msg.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
        </span>
      </div>
    </div>
  );
};

const TypingIndicator = ({ isPDF }) => (
  <div className="flex gap-3 mb-4">
    <div className="w-8 h-8 rounded-full bg-gray-800 text-white flex items-center justify-center text-xs font-bold flex-shrink-0">AI</div>
    <div className="bg-white border border-gray-200 rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm">
      <div className="flex items-center gap-2">
        <div className="flex gap-1">
          <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
          <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
          <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
        </div>
        <span className="text-xs text-gray-400">
          {isPDF ? "Extracting & parsing drawing data..." : "Thinking..."}
        </span>
      </div>
    </div>
  </div>
);

// ── Parse via backend ─────────────────────────────────────────
const parseDocumentViaBackend = async (file, userPrompt, stage) => {
  const formData = new FormData();
  formData.append("file",        file);
  formData.append("stage",       stage || "drawing");
  formData.append("user_prompt", userPrompt || "");

  const res  = await fetch(`${API}/document/parse`, {
    method: "POST",
    body:   formData,
  });
  const json = await res.json();
  if (!json.success) throw new Error(json.detail || "Parsing failed");
  return json.data;
};

// ── Chat via backend (with memory) ───────────────────────────
const chatViaBackend = async ({ message, history, summary, drawingContext, stage }) => {
  const res = await fetch(`${API}/chat/message`, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      history,
      summary:         summary  || null,
      drawing_context: drawingContext || null,
      stage:           stage    || null,
    }),
  });
  const json = await res.json();
  if (!res.ok) throw new Error(json.detail || "Chat failed");
  return json; // { reply, new_summary, should_summarise }
};

// ── Main Component ────────────────────────────────────────────
export default function SubhashProcurement() {
  const [messages, setMessages] = useState([{
    id: 1, role: "ai", ts: Date.now(),
    text: "Hello Team 👋\n\nI'm your Fabrication Estimation Assistant. Attach any engineering document (DWG, BOQ, BOM, PDF) and I'll extract and structure all the data for you automatically.\n\nYou can also select a workflow stage from the left panel to guide the analysis.",
  }]);
  const [input, setInput]             = useState("");
  const [files, setFiles]             = useState([]);
  const [rawFiles, setRawFiles]       = useState([]);
  const [activeStage, setActiveStage] = useState(null);
  const [isTyping, setIsTyping]       = useState(false);
  const [dragOver, setDragOver]       = useState(false);

  // ── Memory state ─────────────────────────────────────────
  // chatHistory: array of { role: "user"|"assistant", content: string }
  //   — sent to backend on every message so Groq has full context
  const [chatHistory, setChatHistory]       = useState([]);
  // rollingSummary: string — compressed summary of older messages
  const [rollingSummary, setRollingSummary] = useState(null);
  // drawingContext: JSON string of last parsed PDF — persists for follow-ups
  const [drawingContext, setDrawingContext] = useState(null);

  const fileRef   = useRef();
  const bottomRef = useRef();
  const inputRef  = useRef();

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isTyping]);

  const addFiles = (newFiles) => {
    const arr = Array.from(newFiles);
    setRawFiles(prev => [...prev, ...arr]);
    setFiles(prev => [...prev, ...arr.map(f => ({ name: f.name, size: f.size, type: f.type }))]);
  };

  const removeFile = (i) => {
    setFiles(prev => prev.filter((_, idx) => idx !== i));
    setRawFiles(prev => prev.filter((_, idx) => idx !== i));
  };

  const isPDF = (name) => name?.toLowerCase().endsWith(".pdf");

  const handleSend = async () => {
    if (!input.trim() && files.length === 0) return;

    const userMsg = {
      id: Date.now(), role: "user", ts: Date.now(),
      text:  input.trim() || null,
      files: files.length > 0 ? [...files] : null,
      stage: activeStage,
    };
    setMessages(prev => [...prev, userMsg]);

    const currentInput    = input.trim();
    const currentRawFiles = [...rawFiles];
    const hasPDF          = currentRawFiles.some(f => isPDF(f.name));

    setInput("");
    setFiles([]);
    setRawFiles([]);
    setIsTyping(true);

    try {
      if (hasPDF) {
        // ── PDF path: parse document, then store context ──
        const pdfFile = currentRawFiles.find(f => isPDF(f.name));
        try {
          const drawingData = await parseDocumentViaBackend(pdfFile, currentInput, activeStage);

          // Persist drawing context as a compact JSON string for follow-up questions
          const contextStr = JSON.stringify(drawingData);
          setDrawingContext(contextStr);

          const summaryText = drawingData.summary || `Extracted and structured all data from ${pdfFile.name}.`;

          // Add to chat history so follow-ups know this was discussed
          setChatHistory(prev => [
            ...prev,
            { role: "user",      content: currentInput || `Analyse ${pdfFile.name}` },
            { role: "assistant", content: summaryText },
          ]);

          setIsTyping(false);
          setMessages(prev => [...prev, {
            id: Date.now(), role: "ai", ts: Date.now(),
            text: summaryText,
            drawingData,
          }]);
        } catch (e) {
          setIsTyping(false);
          setMessages(prev => [...prev, {
            id: Date.now(), role: "ai", ts: Date.now(),
            text: `❌ Could not parse **${pdfFile.name}**.\n\nError: ${e.message}\n\nMake sure FastAPI is running on port 8000 and ANTHROPIC_API_KEY is set in .env`,
          }]);
        }

      } else {
        // ── Text / follow-up path: call Groq with full memory ──
        try {
          const result = await chatViaBackend({
            message:        currentInput,
            history:        chatHistory.slice(-12),
            summary:        rollingSummary,
            drawingContext: drawingContext,
            stage:          activeStage,
          });

          // Update rolling summary if backend says we should
          if (result.new_summary) {
            setRollingSummary(result.new_summary);
          }

          // Append this exchange to chat history
          setChatHistory(prev => [
            ...prev,
            { role: "user",      content: currentInput },
            { role: "assistant", content: result.reply },
          ]);

          setIsTyping(false);
          setMessages(prev => [...prev, {
            id: Date.now(), role: "ai", ts: Date.now(),
            text: result.reply,
            stage: activeStage,
          }]);
        } catch (e) {
          setIsTyping(false);
          setMessages(prev => [...prev, {
            id: Date.now(), role: "ai", ts: Date.now(),
            text: `❌ Chat error: ${e.message}\n\nMake sure FastAPI is running on port 8000 and GROQ_API_KEY is set in .env`,
          }]);
        }
      }
    } catch {
      setIsTyping(false);
      setMessages(prev => [...prev, {
        id: Date.now(), role: "ai", ts: Date.now(),
        text: "Something went wrong. Please try again.",
      }]);
    }
  };

  const handleStageClick = (stage) => {
    setActiveStage(stage.id);
    const prompt = SUGGESTED_PROMPTS.find(p => p.stage === stage.id);
    setInput(prompt?.text || "");
    inputRef.current?.focus();
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); }
  };

  // Clear conversation memory (new session)
  const handleNewSession = () => {
    setChatHistory([]);
    setRollingSummary(null);
    setDrawingContext(null);
    setMessages([{
      id: Date.now(), role: "ai", ts: Date.now(),
      text: "New session started. Attach a document or ask a question.",
    }]);
  };

  return (
    <div className="flex h-screen bg-gray-50 overflow-hidden">
      <script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js" />

      {/* ── Left Sidebar ── */}
      <div className="w-64 bg-gray-900 text-white flex flex-col flex-shrink-0">
        <div className="p-5 border-b border-gray-700">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-lg">⚙️</span>
            <h2 className="font-bold text-sm">Estimation Workflow</h2>
          </div>
          <p className="text-xs text-gray-400">Fabrication Costing</p>
        </div>
        <div className="flex-1 p-3 overflow-y-auto">
          <p className="text-xs text-gray-500 uppercase font-medium mb-3 px-2">Workflow Stages</p>
          {WORKFLOW_STAGES.map((stage, i) => (
            <button key={stage.id} onClick={() => handleStageClick(stage)}
              className={`w-full text-left px-3 py-2.5 rounded-lg mb-1 text-sm transition flex items-center gap-3
                ${activeStage === stage.id ? "bg-indigo-600 text-white" : "text-gray-300 hover:bg-gray-800"}`}>
              <span>{stage.icon}</span>
              <span className="text-xs font-semibold flex-1 truncate">{stage.label}</span>
              <span className={`text-xs flex-shrink-0 ${activeStage === stage.id ? "text-indigo-200" : "text-gray-600"}`}>{i + 1}</span>
            </button>
          ))}
        </div>

        {/* Memory status indicator */}
        <div className="px-4 py-3 border-t border-gray-700">
          <div className="flex items-center justify-between mb-2">
            <p className="text-xs text-gray-500 uppercase font-medium">Session Memory</p>
            {(chatHistory.length > 0 || drawingContext) && (
              <button onClick={handleNewSession}
                className="text-xs text-red-400 hover:text-red-300 transition">
                Clear
              </button>
            )}
          </div>
          <div className="space-y-1">
            <div className="flex items-center justify-between text-xs">
              <span className="text-gray-400">Messages</span>
              <span className={chatHistory.length > 0 ? "text-green-400" : "text-gray-600"}>
                {chatHistory.length > 0 ? `${chatHistory.length / 2 | 0} exchanges` : "none"}
              </span>
            </div>
            <div className="flex items-center justify-between text-xs">
              <span className="text-gray-400">Document</span>
              <span className={drawingContext ? "text-green-400" : "text-gray-600"}>
                {drawingContext ? "✓ loaded" : "none"}
              </span>
            </div>
            {rollingSummary && (
              <div className="flex items-center justify-between text-xs">
                <span className="text-gray-400">Summary</span>
                <span className="text-indigo-400">✓ active</span>
              </div>
            )}
          </div>
        </div>

        <div className="p-4 border-t border-gray-700">
          <p className="text-xs text-gray-500 uppercase font-medium mb-2">Accepted Files</p>
          <div className="flex flex-wrap gap-1">
            {["PDF","DWG","BOQ","BOM","XLSX","DOCX","TXT"].map(t => (
              <span key={t} className="text-xs bg-gray-800 text-gray-400 px-2 py-0.5 rounded font-mono">{t}</span>
            ))}
          </div>
          <p className="text-xs text-indigo-400 mt-3 flex items-center gap-1">
            ✨ PDF files are auto-parsed
          </p>
        </div>
      </div>

      {/* ── Main Chat ── */}
      <div className="flex-1 flex flex-col min-w-0">
        <div className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between flex-shrink-0">
          <div>
            <h1 className="text-lg font-bold text-gray-800">Fabrication Estimation</h1>
            <p className="text-xs text-gray-500 mt-0.5">
              {activeStage
                ? `Active: ${WORKFLOW_STAGES.find(s => s.id === activeStage)?.icon} ${WORKFLOW_STAGES.find(s => s.id === activeStage)?.label}`
                : drawingContext
                  ? "Document loaded — ask any follow-up question"
                  : "Attach a PDF to auto-extract drawing data"}
            </p>
          </div>
          <div className="flex items-center gap-3">
            {activeStage && (
              <button onClick={() => setActiveStage(null)} className="text-xs text-gray-400 hover:text-gray-600">✕ Clear stage</button>
            )}
            <div className="w-8 h-8 rounded-full bg-indigo-600 text-white flex items-center justify-center text-sm font-bold">S</div>
            <div>
              <p className="text-sm font-semibold text-gray-800">Subhash</p>
              <p className="text-xs text-gray-400">Estimation Team</p>
            </div>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-6 py-4"
          onDragOver={e => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={e => { e.preventDefault(); setDragOver(false); addFiles(e.dataTransfer.files); }}>

          {dragOver && (
            <div className="fixed inset-0 bg-indigo-600 bg-opacity-10 border-4 border-dashed border-indigo-400 z-50 flex items-center justify-center pointer-events-none">
              <div className="bg-white rounded-2xl px-8 py-6 shadow-2xl text-center">
                <div className="text-5xl mb-3">📎</div>
                <p className="text-lg font-bold text-indigo-700">Drop files to attach</p>
                <p className="text-sm text-gray-500 mt-1">PDFs will be auto-parsed</p>
              </div>
            </div>
          )}

          {messages.map(msg => <MessageBubble key={msg.id} msg={msg} />)}
          {isTyping && <TypingIndicator isPDF={rawFiles.some(f => isPDF(f.name))} />}
          <div ref={bottomRef} />
        </div>

        {/* ── Input Area ── */}
        <div className="bg-white border-t border-gray-200 px-4 py-3 flex-shrink-0">
          {files.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-3">
              {files.map((f, i) => (
                <div key={i} className={`flex items-center gap-2 rounded-xl px-3 py-1.5 text-xs border
                  ${isPDF(f.name) ? "bg-indigo-50 border-indigo-200" : "bg-gray-50 border-gray-200"}`}>
                  <span>{getFileIcon(f.name)}</span>
                  <span className={`font-medium max-w-[120px] truncate ${isPDF(f.name) ? "text-indigo-700" : "text-gray-700"}`}>{f.name}</span>
                  {isPDF(f.name) && <span className="text-indigo-400 text-xs">✨ will parse</span>}
                  <span className="text-gray-400">{(f.size / 1024).toFixed(0)}KB</span>
                  <button onClick={() => removeFile(i)} className="text-gray-400 hover:text-red-500 ml-1 font-bold">✕</button>
                </div>
              ))}
            </div>
          )}

          {activeStage && (
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs bg-indigo-100 text-indigo-700 px-2 py-1 rounded-full font-medium flex items-center gap-1">
                {WORKFLOW_STAGES.find(s => s.id === activeStage)?.icon}
                {WORKFLOW_STAGES.find(s => s.id === activeStage)?.label}
              </span>
              <span className="text-xs text-gray-400">active stage</span>
            </div>
          )}

          <div className="flex items-end gap-2">
            <button onClick={() => fileRef.current?.click()}
              className="flex-shrink-0 w-10 h-10 rounded-xl border border-gray-200 hover:border-indigo-400 hover:bg-indigo-50 flex items-center justify-center text-gray-400 hover:text-indigo-600 transition text-xl">
              📎
              <input ref={fileRef} type="file" multiple
                accept=".pdf,.dwg,.dxf,.docx,.doc,.txt,.xlsx,.xls,.csv,.png,.jpg,.jpeg"
                className="hidden" onChange={e => addFiles(e.target.files)} />
            </button>

            <div className="flex-1">
              <textarea ref={inputRef} value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={
                  files.some(f => isPDF(f.name))
                    ? "Add a note or question about the PDF, or just hit send to auto-extract..."
                    : drawingContext
                      ? "Ask a follow-up question about the document..."
                      : "Attach a PDF or type your question... (Enter to send)"
                }
                rows={1}
                className="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 resize-none leading-relaxed max-h-32 overflow-y-auto"
                style={{ minHeight: "42px" }}
                onInput={e => {
                  e.target.style.height = "auto";
                  e.target.style.height = Math.min(e.target.scrollHeight, 128) + "px";
                }}
              />
            </div>

            <button onClick={handleSend}
              disabled={!input.trim() && files.length === 0}
              className="flex-shrink-0 w-10 h-10 rounded-xl bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center text-white transition">
              <svg className="w-4 h-4 rotate-90" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
              </svg>
            </button>
          </div>
          <p className="text-xs text-gray-400 mt-1.5 ml-12">Drop files anywhere · Enter to send · PDFs are auto-parsed ✨</p>
        </div>
      </div>
    </div>
  );
}

// ── Stage-specific card renderers (unchanged) ─────────────────
const InquiryScopeCard = ({ data }) => {
  const s = data.inquiryScope || {};
  return (
    <CollapsibleSection title="Inquiry Scope" icon="📋">
      <KV label="Client" value={s.client} />
      <KV label="Project" value={s.projectName} />
      <KV label="Delivery Location" value={s.deliveryLocation} />
      <KV label="Required Date" value={s.requiredDate} />
      <KV label="Special Requirements" value={s.specialRequirements} />
      {s.documentsProvided?.length > 0 && (
        <div className="mt-2">
          <p className="text-xs text-gray-400 mb-1">Documents Provided</p>
          <div className="flex flex-wrap gap-1">
            {s.documentsProvided.map((d, i) => <Badge key={i} text={d} color="blue" />)}
          </div>
        </div>
      )}
    </CollapsibleSection>
  );
};

const DrawingAnalysisCard = ({ data }) => {
  const a = data.drawingAnalysis || {};
  return (
    <CollapsibleSection title="Drawing Analysis" icon="📐">
      <KV label="Overall Design" value={a.overallDesign} />
      <KV label="Dimensions" value={a.dimensions} />
      <KV label="Welding Requirements" value={a.weldingRequirements} />
      <KV label="Fabrication Notes" value={a.fabricationNotes} />
      {a.structuralComponents?.length > 0 && (
        <div className="mt-2">
          <p className="text-xs text-gray-400 mb-1">Structural Components</p>
          <div className="flex flex-wrap gap-1">
            {a.structuralComponents.map((c, i) => <Badge key={i} text={c} color="purple" />)}
          </div>
        </div>
      )}
    </CollapsibleSection>
  );
};

const BOQCard = ({ data }) => {
  const items = data.boqItems || [];
  const discrep = data.discrepancies || [];
  return (
    <>
      <CollapsibleSection title={`BOQ Items (${items.length})`} icon="📊">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead><tr className="bg-gray-50">
              {["No.", "Description", "Unit", "Qty", "Remarks"].map(h => (
                <th key={h} className="px-2 py-1.5 text-left text-gray-500 font-semibold">{h}</th>
              ))}
            </tr></thead>
            <tbody className="divide-y divide-gray-100">
              {items.map((item, i) => (
                <tr key={i} className="hover:bg-gray-50">
                  <td className="px-2 py-1.5 font-mono text-gray-500">{item.itemNo || i + 1}</td>
                  <td className="px-2 py-1.5 text-gray-700">{item.description}</td>
                  <td className="px-2 py-1.5 text-gray-500">{item.unit}</td>
                  <td className="px-2 py-1.5 font-bold text-indigo-700">{item.quantity}</td>
                  <td className="px-2 py-1.5 text-gray-400 italic">{item.remarks}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CollapsibleSection>
      {discrep.length > 0 && (
        <CollapsibleSection title={`Discrepancies (${discrep.length})`} icon="⚠️">
          {discrep.map((d, i) => (
            <div key={i} className="flex items-start gap-2 py-2 border-b border-gray-50 last:border-0">
              <Badge text={d.severity} color={d.severity === "high" ? "red" : d.severity === "medium" ? "orange" : "gray"} />
              <div>
                <p className="text-xs font-semibold text-gray-700">{d.item}</p>
                <p className="text-xs text-gray-500">{d.issue}</p>
              </div>
            </div>
          ))}
        </CollapsibleSection>
      )}
      {data.missingItems?.length > 0 && (
        <CollapsibleSection title="Missing Items" icon="❌">
          <div className="flex flex-wrap gap-1">
            {data.missingItems.map((m, i) => <Badge key={i} text={m} color="red" />)}
          </div>
        </CollapsibleSection>
      )}
    </>
  );
};

const MaterialCard = ({ data }) => {
  const materials = data.materials || [];
  const summary = data.materialSummary || {};
  return (
    <>
      <CollapsibleSection title="Material List" icon="🔩">
        <div className="space-y-2">
          {materials.map((m, i) => (
            <div key={i} className="bg-gray-50 rounded-lg px-3 py-2.5">
              <div className="flex items-center gap-2 mb-1 flex-wrap">
                <span className="text-xs font-semibold text-gray-700">{m.component}</span>
                <Badge text={m.form} color="purple" />
                {m.grade && <Badge text={m.grade} color="blue" />}
              </div>
              <div className="flex gap-4 text-xs text-gray-500">
                <span>Type: {m.materialType}</span>
                {m.spec && <span>Spec: {m.spec}</span>}
              </div>
              {m.remarks && <p className="text-xs text-gray-400 mt-1 italic">{m.remarks}</p>}
            </div>
          ))}
        </div>
      </CollapsibleSection>
      <CollapsibleSection title="Material Summary" icon="📋">
        <KV label="Primary Material" value={summary.primaryMaterial} />
        <KV label="Surface Treatment" value={summary.surfaceTreatment} />
        <KV label="Special Requirements" value={summary.specialRequirements} />
        {summary.steelGrades?.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {summary.steelGrades.map((g, i) => <Badge key={i} text={g} color="indigo" />)}
          </div>
        )}
      </CollapsibleSection>
    </>
  );
};

const TakeoffCard = ({ data }) => {
  const items = data.quantityItems || [];
  const typeColors = { plate: "blue", structural: "purple", pipe: "green", bolt: "orange", valve: "red", instrument: "indigo", other: "gray" };
  return (
    <CollapsibleSection title={`Quantity Take-Off (${items.length} items)`} icon="📊">
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead><tr className="bg-gray-50">
            {["Tag", "Description", "Type", "Size", "Qty", "Unit"].map(h => (
              <th key={h} className="px-2 py-1.5 text-left text-gray-500 font-semibold">{h}</th>
            ))}
          </tr></thead>
          <tbody className="divide-y divide-gray-100">
            {items.map((item, i) => (
              <tr key={i} className="hover:bg-gray-50">
                <td className="px-2 py-1.5 font-mono text-gray-500">{item.tag || "—"}</td>
                <td className="px-2 py-1.5 text-gray-700 max-w-[160px] truncate">{item.description}</td>
                <td className="px-2 py-1.5"><Badge text={item.type} color={typeColors[item.type] || "gray"} /></td>
                <td className="px-2 py-1.5 font-mono text-gray-600">{item.size}</td>
                <td className="px-2 py-1.5 font-bold text-indigo-700">{item.quantity}</td>
                <td className="px-2 py-1.5 text-gray-500">{item.unit}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.takeoffSummary?.hiddenFabricationItems?.length > 0 && (
        <div className="mt-3">
          <p className="text-xs text-gray-400 mb-1">Hidden Fabrication Items</p>
          <div className="flex flex-wrap gap-1">
            {data.takeoffSummary.hiddenFabricationItems.map((h, i) => <Badge key={i} text={h} color="orange" />)}
          </div>
        </div>
      )}
    </CollapsibleSection>
  );
};

const WeightCard = ({ data }) => {
  const calcs = data.weightCalculations || [];
  const summary = data.weightSummary || {};
  return (
    <>
      <CollapsibleSection title="Weight Calculations" icon="⚖️">
        <div className="space-y-2">
          {calcs.map((c, i) => (
            <div key={i} className="bg-gray-50 rounded-lg px-3 py-2.5">
              <div className="flex justify-between items-start">
                <div>
                  <p className="text-xs font-semibold text-gray-700">{c.component}</p>
                  <p className="text-xs text-gray-500">{c.material} · {c.dimensions}</p>
                  {c.formula && <p className="text-xs text-indigo-500 font-mono mt-0.5">{c.formula}</p>}
                </div>
                <span className="text-sm font-bold text-indigo-700 flex-shrink-0 ml-3">{c.calculatedWeight} {c.unit}</span>
              </div>
            </div>
          ))}
        </div>
      </CollapsibleSection>
      <CollapsibleSection title="Weight Summary" icon="📋">
        <KV label="Structural Weight" value={summary.totalStructuralWeight} />
        <KV label="Piping Weight" value={summary.totalPipingWeight} />
        <KV label="Instrument Weight" value={summary.totalInstrumentWeight} />
        <div className="mt-2 pt-2 border-t border-gray-100">
          <div className="flex justify-between">
            <span className="text-xs font-bold text-gray-600">Grand Total</span>
            <span className="text-sm font-bold text-indigo-700">{summary.grandTotal || "—"}</span>
          </div>
        </div>
        {summary.weightBasis && <p className="text-xs text-gray-400 mt-2 italic">{summary.weightBasis}</p>}
      </CollapsibleSection>
      {data.skidSizes && (
        <CollapsibleSection title="Skid Dimensions" icon="📦">
          <div className="grid grid-cols-2 gap-x-6">
            {Object.entries(data.skidSizes).map(([k, v]) => <KV key={k} label={k} value={v} />)}
          </div>
        </CollapsibleSection>
      )}
    </>
  );
};

const ScopeCard = ({ data }) => {
  const items = data.scopeItems || [];
  return (
    <>
      <CollapsibleSection title="Scope of Supply" icon="🎯">
        <div className="space-y-1.5">
          {items.map((s, i) => (
            <div key={i} className="flex items-start gap-3 py-1.5 border-b border-gray-50 last:border-0">
              <span className={`text-sm flex-shrink-0 ${s.included ? "text-green-500" : "text-red-400"}`}>
                {s.included ? "✅" : "❌"}
              </span>
              <div>
                <p className="text-xs font-semibold text-gray-700">{s.activity}</p>
                <p className="text-xs text-gray-500">{s.description}</p>
                {s.remarks && <p className="text-xs text-gray-400 italic">{s.remarks}</p>}
              </div>
            </div>
          ))}
        </div>
      </CollapsibleSection>
      {data.exclusions?.length > 0 && (
        <CollapsibleSection title="Exclusions" icon="🚫" defaultOpen={false}>
          <div className="flex flex-wrap gap-1">{data.exclusions.map((e, i) => <Badge key={i} text={e} color="red" />)}</div>
        </CollapsibleSection>
      )}
      {data.assumptions?.length > 0 && (
        <CollapsibleSection title="Assumptions" icon="💡" defaultOpen={false}>
          <div className="space-y-1">
            {data.assumptions.map((a, i) => <p key={i} className="text-xs text-gray-600">• {a}</p>)}
          </div>
        </CollapsibleSection>
      )}
    </>
  );
};

const ReviewCard = ({ data }) => {
  const checklist = data.reviewChecklist || [];
  const summary = data.reviewSummary || {};
  const statusColor = { approved: "green", "needs-revision": "orange", rejected: "red" };
  return (
    <>
      <CollapsibleSection title="Review Checklist" icon="✅">
        <div className="space-y-2">
          {checklist.map((c, i) => (
            <div key={i} className="flex items-start gap-3 py-1.5 border-b border-gray-50 last:border-0">
              <span className="text-sm flex-shrink-0">
                {c.status === "pass" ? "✅" : c.status === "fail" ? "❌" : "⚠️"}
              </span>
              <div className="flex-1">
                <p className="text-xs font-semibold text-gray-700">{c.checkItem}</p>
                <p className="text-xs text-gray-500">{c.finding}</p>
                {c.recommendation && <p className="text-xs text-blue-500 italic">→ {c.recommendation}</p>}
              </div>
              <Badge text={c.status} color={c.status === "pass" ? "green" : c.status === "fail" ? "red" : "orange"} />
            </div>
          ))}
        </div>
      </CollapsibleSection>
      <CollapsibleSection title="Review Summary" icon="📋">
        <div className="flex items-center justify-between mb-3 p-2 rounded-lg bg-gray-50">
          <span className="text-xs font-semibold text-gray-600">Overall Status</span>
          <Badge text={summary.overallStatus || "pending"} color={statusColor[summary.overallStatus] || "gray"} />
        </div>
        <KV label="Scope Clarity" value={summary.scopeClarity} />
        <KV label="Cost Accuracy" value={summary.costAccuracy} />
        {summary.finalRemarks && <p className="text-xs text-gray-500 mt-2 italic">{summary.finalRemarks}</p>}
        {summary.missingComponents?.length > 0 && (
          <div className="mt-2">
            <p className="text-xs text-red-500 font-medium mb-1">Missing Components</p>
            <div className="flex flex-wrap gap-1">{summary.missingComponents.map((m, i) => <Badge key={i} text={m} color="red" />)}</div>
          </div>
        )}
      </CollapsibleSection>
    </>
  );
};