import React, { useState, useEffect } from 'react';
import { API } from '../config/api';

// ── Stats Card ──────────────────────────────────────────
export const StatCard = ({ label, value, icon, color = 'blue' }) => {
    const colors = {
        blue:   'bg-blue-50 text-blue-600 border-blue-100',
        green:  'bg-green-50 text-green-600 border-green-100',
        purple: 'bg-purple-50 text-purple-600 border-purple-100',
        orange: 'bg-orange-50 text-orange-600 border-orange-100',
        yellow: 'bg-yellow-50 text-yellow-600 border-yellow-100',
    };

    return (
        <div className={`rounded-xl border p-5 ${colors[color]}`}>
            <div className="flex items-center justify-between mb-2">
                <p className="text-sm font-medium opacity-80">{label}</p>
                <span className="text-2xl">{icon}</span>
            </div>
            <p className="text-3xl font-bold">{value ?? '—'}</p>
        </div>
    );
};

// ── Data Table ───────────────────────────────────────────
const DataTableInner = ({ columns, rows, emptyMessage = 'No data found', onRowClick, fillHeight = false }) => {
    return (
        <div className={`bg-white rounded-xl shadow overflow-hidden flex flex-col ${fillHeight ? 'flex-1 min-h-0' : ''}`}>
            <div className={`overflow-x-auto overflow-y-scroll ${fillHeight ? 'flex-1 min-h-0' : 'max-h-[60vh]'}`}
                 style={{ scrollbarWidth: 'thin', scrollbarColor: '#cbd5e1 #f1f5f9' }}>
                <table className="w-full text-sm">
                    <thead className="bg-gray-50 border-b border-gray-200 sticky top-0 z-10">
                        <tr>
                            {columns.map(col => (
                                <th key={col.key} className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider bg-gray-50">
                                    {col.label}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                        {rows.length === 0 ? (
                            <tr>
                                <td colSpan={columns.length} className="text-center py-12 text-gray-400">
                                    {emptyMessage}
                                </td>
                            </tr>
                        ) : rows.map((row, i) => (
                            <tr key={row.enquiry_ref_no || row.id || i}
                                onClick={() => onRowClick?.(row)}
                                className={`hover:bg-blue-50 transition-colors ${onRowClick ? 'cursor-pointer' : ''}`}>
                                {columns.map(col => (
                                    <td key={col.key} className="px-4 py-3 text-gray-700">
                                        {col.render ? col.render(row[col.key], row) : (row[col.key] ?? '—')}
                                    </td>
                                ))}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
};
export const DataTable = React.memo(DataTableInner);

// ── Status Badge ─────────────────────────────────────────
export const StatusBadge = ({ status }) => {
    const styles = {
        open:      'bg-green-100 text-green-700',
        closed:    'bg-gray-100 text-gray-600',
        pending:   'bg-yellow-100 text-yellow-700',
        approved:  'bg-blue-100 text-blue-700',
        rejected:  'bg-red-100 text-red-700',
    };
    return (
        <span className={`px-2.5 py-1 rounded-full text-xs font-medium capitalize ${styles[status] || 'bg-gray-100 text-gray-500'}`}>
            {status || 'N/A'}
        </span>
    );
};

// ── Inquiry Detail Modal ──────────────────────────────────
export const InquiryModal = ({ inquiryId, onClose }) => {
    const [data,               setData]               = useState(null);
    const [vendors,            setVendors]            = useState([]);
    const [activeTab,          setActiveTab]          = useState('items');
    const [loading,            setLoading]            = useState(true);
    const [error,              setError]              = useState('');
    const [editMode,           setEditMode]           = useState(false);
    const [editTitle,          setEditTitle]          = useState('');
    const [editInquiry,        setEditInquiry]        = useState({});
    const [editItems,          setEditItems]          = useState([]);
    const [deletedItemIds,     setDeletedItemIds]     = useState([]);
    const [editVendors,        setEditVendors]        = useState([]);
    const [deletedVendorNames, setDeletedVendorNames] = useState([]);
    const [saving,             setSaving]             = useState(false);
    const [saveMsg,            setSaveMsg]            = useState('');

    // Outcome / bid tracking state
    const [outcome,         setOutcome]         = useState(null);   // current bid record from API
    const [outcomeForm,     setOutcomeForm]     = useState({});
    const [outcomeSaving,   setOutcomeSaving]   = useState(false);
    const [outcomeMsg,      setOutcomeMsg]      = useState('');

    const loadData = () => {
        setLoading(true); setError(''); setData(null); setVendors([]);
        Promise.all([
            fetch(`${API}/rfqs/inquiry/${encodeURIComponent(inquiryId)}`).then(r => r.json()),
            fetch(`${API}/rfqs/inquiry/${encodeURIComponent(inquiryId)}/vendors`).then(r => r.json()),
            fetch(`${API}/bids/by-inquiry/${encodeURIComponent(inquiryId)}`).then(r => r.json()).catch(() => ({ bids: [] })),
        ])
            .then(([d, v, b]) => {
                if (d.success) {
                    setData(d);
                    setEditInquiry({ client: d.inquiry.client || '', notes: d.inquiry.notes || '', delivery: d.inquiry.delivery || '' });
                    setEditItems(d.items.map(it => ({ ...it })));
                } else setError(d.detail || 'Failed');
                if (v.success) {
                    setVendors(v.vendors || []);
                    setEditVendors((v.vendors || []).map(vv => ({ ...vv, _new: false })));
                }
                const latest = (b.bids || [])[0] || null;
                setOutcome(latest);
                setOutcomeForm(latest ? {
                    status:          latest.status || 'bid_sent',
                    quotation_value: latest.quotation_value ?? '',
                    order_value:     latest.order_value ?? '',
                    lost_reason:     latest.lost_reason || '',
                    competitor_name: latest.competitor_name || '',
                    notes:           latest.notes || '',
                    outcome_date:    latest.outcome_date || '',
                } : { status: 'bid_sent', quotation_value: '', order_value: '', lost_reason: '', competitor_name: '', notes: '', outcome_date: '' });
            })
            .catch(() => setError('Could not load inquiry'))
            .finally(() => setLoading(false));
    };

    const saveOutcome = async () => {
        setOutcomeSaving(true); setOutcomeMsg('');
        try {
            const res = await fetch(`${API}/bids/by-inquiry/${encodeURIComponent(inquiryId)}/status`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    ...outcomeForm,
                    quotation_value: outcomeForm.quotation_value !== '' ? Number(outcomeForm.quotation_value) : null,
                    order_value:     outcomeForm.order_value     !== '' ? Number(outcomeForm.order_value)     : null,
                    outcome_date:    outcomeForm.outcome_date    || null,
                }),
            });
            const json = await res.json();
            if (!res.ok) throw new Error(json.detail || 'Save failed');
            setOutcomeMsg('✅ Saved');
            // Refresh bids for this inquiry
            const b = await fetch(`${API}/bids/by-inquiry/${encodeURIComponent(inquiryId)}`).then(r => r.json()).catch(() => ({ bids: [] }));
            setOutcome((b.bids || [])[0] || null);
        } catch (e) {
            setOutcomeMsg(`❌ ${e.message}`);
        } finally {
            setOutcomeSaving(false);
        }
    };

    useEffect(() => {
        if (!inquiryId) return;
        setActiveTab('items'); setEditMode(false); setSaveMsg(''); setOutcomeMsg('');
        setDeletedItemIds([]); setDeletedVendorNames([]);
        loadData();
    }, [inquiryId]);

    const enterEdit = () => {
        setDeletedItemIds([]); setDeletedVendorNames([]);
        setEditItems(data.items.map(it => ({ ...it })));
        setEditVendors(vendors.map(vv => ({ ...vv, _new: false })));
        setEditInquiry({ client: data.inquiry.client || '', notes: data.inquiry.notes || '', delivery: data.inquiry.delivery || '' });
        setEditTitle(inquiryId);
        setEditMode(true); setSaveMsg('');
    };

    const cancelEdit = () => {
        setEditMode(false); setSaveMsg('');
        setDeletedItemIds([]); setDeletedVendorNames([]);
    };

    const handleSave = async () => {
        setSaving(true); setSaveMsg('');
        try {
            const existingItems = editItems.filter(it => it.id && !it._new);
            const newItems      = editItems.filter(it => it._new);
            const existingVendors = editVendors.filter(v => !v._new);
            const newVendors      = editVendors.filter(v => v._new);

            const res = await fetch(`${API}/rfqs/inquiry/${encodeURIComponent(inquiryId)}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    inquiry:              { ...editInquiry, new_inquiry_id: editTitle.trim() !== inquiryId ? editTitle.trim() : undefined },
                    items:                existingItems,
                    new_items:            newItems,
                    deleted_item_ids:     deletedItemIds,
                    vendors:              existingVendors,
                    new_vendors:          newVendors,
                    deleted_vendor_names: deletedVendorNames,
                }),
            });
            const json = await res.json();
            if (!res.ok) throw new Error(json.detail || 'Save failed');
            setSaveMsg('✅ Saved');
            setEditMode(false);
            setDeletedItemIds([]); setDeletedVendorNames([]);
            loadData();
        } catch (e) {
            setSaveMsg(`❌ ${e.message}`);
        } finally {
            setSaving(false);
        }
    };

    const addItem = () => setEditItems(prev => [...prev, { _new: true, description: '', quantity: '', unit: '', category: '', status: 'pending' }]);

    const removeItem = (i) => {
        const item = editItems[i];
        if (item.id) setDeletedItemIds(prev => [...prev, item.id]);
        setEditItems(prev => prev.filter((_, idx) => idx !== i));
    };

    const addVendor = () => setEditVendors(prev => [...prev, { _new: true, name: '', email: '', phone: '', website: '', country: '', city: '', brands: '' }]);

    const removeVendor = (i) => {
        const v = editVendors[i];
        if (!v._new) setDeletedVendorNames(prev => [...prev, v.name]);
        setEditVendors(prev => prev.filter((_, idx) => idx !== i));
    };

    const setVendorField = (i, field, val) =>
        setEditVendors(prev => prev.map((v, idx) => idx === i ? { ...v, [field]: val } : v));

    if (!inquiryId) return null;

    const statusColor = s => ({
        done:        'bg-green-100 text-green-700',
        pending:     'bg-yellow-100 text-yellow-700',
        in_progress: 'bg-blue-100 text-blue-700',
    }[s] || 'bg-gray-100 text-gray-500');

    const inp = "w-full text-sm text-gray-800 bg-white border border-indigo-300 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-indigo-400";
    const inpSm = "text-xs border border-indigo-300 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-indigo-400 bg-white";

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
             style={{ backgroundColor: 'rgba(0,0,0,0.45)' }}
             onClick={onClose}>
            <div className="bg-white rounded-2xl shadow-2xl w-full max-w-4xl max-h-[90vh] flex flex-col"
                 onClick={e => e.stopPropagation()}>

                {/* Header */}
                <div className="flex items-start justify-between px-6 py-4 border-b gap-3">
                    <div className="flex-1 min-w-0">
                        {editMode ? (
                            <input
                                className="text-base font-bold text-gray-800 font-mono bg-white border border-indigo-300 rounded-lg px-3 py-1 focus:outline-none focus:ring-2 focus:ring-indigo-400 w-full max-w-lg"
                                value={editTitle}
                                onChange={e => setEditTitle(e.target.value)}
                            />
                        ) : (
                            <h2 className="text-lg font-bold text-gray-800 font-mono leading-tight">{inquiryId}</h2>
                        )}
                        {data && (
                            <p className="text-sm text-gray-500 mt-1">
                                {data.inquiry.client && <span className="font-medium text-gray-700">{data.inquiry.client} · </span>}
                                {data.inquiry.division_name} · {data.items.length} item{data.items.length !== 1 ? 's' : ''}
                                {data.inquiry.created_at && (
                                    <span> · {new Date(data.inquiry.created_at).toLocaleDateString()}</span>
                                )}
                            </p>
                        )}
                    </div>
                    <div className="flex items-center gap-2 flex-shrink-0 mt-0.5">
                        {data && !editMode && (
                            <button onClick={enterEdit}
                                className="px-3 py-1.5 text-xs bg-indigo-50 text-indigo-600 hover:bg-indigo-100 rounded-lg font-medium transition">
                                ✏️ Edit
                            </button>
                        )}
                        {editMode && (
                            <>
                                <button onClick={handleSave} disabled={saving}
                                    className="px-3 py-1.5 text-xs bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white rounded-lg font-medium transition">
                                    {saving ? 'Saving…' : '✓ Save'}
                                </button>
                                <button onClick={cancelEdit}
                                    className="px-3 py-1.5 text-xs border border-gray-300 text-gray-600 hover:bg-gray-50 rounded-lg font-medium transition">
                                    Cancel
                                </button>
                            </>
                        )}
                        {saveMsg && <span className={`text-xs font-medium ${saveMsg.startsWith('✅') ? 'text-green-600' : 'text-red-500'}`}>{saveMsg}</span>}
                        <button onClick={onClose}
                            className="w-8 h-8 flex items-center justify-center rounded-full bg-gray-100 hover:bg-gray-200 text-gray-500 text-lg transition">
                            ×
                        </button>
                    </div>
                </div>

                {/* Tabs */}
                {data && (
                    <div className="flex gap-1 px-6 pt-3 border-b">
                        {[
                            { id: 'items',   label: `Items (${editMode ? editItems.length : data.items.length})` },
                            { id: 'vendors', label: `Vendors (${editMode ? editVendors.length : vendors.length})` },
                            { id: 'outcome', label: '📊 Outcome' },
                        ].map(t => (
                            <button key={t.id} onClick={() => setActiveTab(t.id)}
                                className={`px-4 py-2 text-sm font-medium border-b-2 transition -mb-px ${
                                    activeTab === t.id
                                        ? 'border-indigo-600 text-indigo-600'
                                        : 'border-transparent text-gray-500 hover:text-gray-700'
                                }`}>
                                {t.label}
                            </button>
                        ))}
                    </div>
                )}

                {/* Body */}
                <div className="flex-1 overflow-y-auto px-6 py-4">
                    {loading && (
                        <div className="flex items-center justify-center py-16">
                            <div className="w-8 h-8 border-4 border-blue-500 border-t-transparent rounded-full animate-spin"/>
                        </div>
                    )}
                    {error && <p className="text-red-500 text-sm py-8 text-center">{error}</p>}

                    {data && activeTab === 'items' && (
                        <>
                            {/* Summary strip */}
                            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
                                <div className="bg-gray-50 rounded-xl p-3 border border-gray-100">
                                    <p className="text-xs text-gray-400 uppercase mb-1">Client</p>
                                    {editMode
                                        ? <input className={inp} value={editInquiry.client || ''} onChange={e => setEditInquiry(p => ({ ...p, client: e.target.value }))} placeholder="Client name"/>
                                        : <p className="font-semibold text-gray-800">{data.inquiry.client || '—'}</p>}
                                </div>
                                <div className="bg-gray-50 rounded-xl p-3 border border-gray-100">
                                    <p className="text-xs text-gray-400 uppercase mb-1">Team</p>
                                    {editMode
                                        ? <input className={inp} value={editInquiry.team || ''} onChange={e => setEditInquiry(p => ({ ...p, team: e.target.value }))} placeholder="Division / Team"/>
                                        : <p className="font-semibold text-gray-800">{data.inquiry.division_name || data.inquiry.team || '—'}</p>}
                                </div>
                                <div className="bg-gray-50 rounded-xl p-3 border border-gray-100">
                                    <p className="text-xs text-gray-400 uppercase mb-1">Delivery</p>
                                    {editMode
                                        ? <input className={inp} value={editInquiry.delivery || ''} onChange={e => setEditInquiry(p => ({ ...p, delivery: e.target.value }))} placeholder="Delivery location"/>
                                        : <p className="font-semibold text-gray-800">{data.inquiry.delivery || '—'}</p>}
                                </div>
                                <div className="bg-gray-50 rounded-xl p-3 border border-gray-100 text-center">
                                    <p className="text-xs text-gray-400 uppercase mb-1">Items</p>
                                    <p className="font-semibold text-gray-800">{editMode ? editItems.length : data.items.length}</p>
                                </div>
                            </div>

                            {/* Notes */}
                            {(editMode || data.inquiry.notes) && (
                                <div className="mb-4">
                                    <p className="text-xs text-gray-400 uppercase mb-1">Notes</p>
                                    {editMode
                                        ? <textarea rows={2} className={`${inp} resize-none`} value={editInquiry.notes || ''} onChange={e => setEditInquiry(p => ({ ...p, notes: e.target.value }))} placeholder="Notes…"/>
                                        : <p className="text-sm text-gray-600">{data.inquiry.notes}</p>}
                                </div>
                            )}

                            {/* Line items */}
                            <div className="flex items-center justify-between mb-3">
                                <h3 className="text-sm font-semibold text-gray-600 uppercase tracking-wide">Line Items</h3>
                                {editMode && (
                                    <button onClick={addItem} className="text-xs bg-indigo-50 text-indigo-600 hover:bg-indigo-100 px-3 py-1 rounded-lg font-medium transition">
                                        + Add Item
                                    </button>
                                )}
                            </div>
                            <div className="space-y-3">
                                {(editMode ? editItems : data.items).map((item, i) => (
                                    <div key={item.id || `new-${i}`} className={`border rounded-xl p-4 transition ${editMode ? 'border-indigo-200 bg-indigo-50/30' : 'border-gray-200 hover:border-blue-200'}`}>
                                        <div className="flex items-start justify-between gap-3 mb-2">
                                            <span className="text-xs font-mono bg-gray-100 text-gray-500 px-2 py-0.5 rounded flex-shrink-0">#{i + 1}</span>
                                            {editMode ? (
                                                <div className="flex flex-1 gap-2 flex-wrap">
                                                    <input placeholder="Qty" className={`${inpSm} w-16`} value={item.quantity || ''}
                                                        onChange={e => setEditItems(prev => prev.map((it, idx) => idx === i ? { ...it, quantity: e.target.value } : it))}/>
                                                    <input placeholder="Unit" className={`${inpSm} w-20`} value={item.unit || ''}
                                                        onChange={e => setEditItems(prev => prev.map((it, idx) => idx === i ? { ...it, unit: e.target.value } : it))}/>
                                                    <input placeholder="Category" className={`${inpSm} w-28`} value={item.category || ''}
                                                        onChange={e => setEditItems(prev => prev.map((it, idx) => idx === i ? { ...it, category: e.target.value } : it))}/>
                                                    <select className={inpSm} value={item.status || ''}
                                                        onChange={e => setEditItems(prev => prev.map((it, idx) => idx === i ? { ...it, status: e.target.value } : it))}>
                                                        <option value="">Status</option>
                                                        <option value="pending">Pending</option>
                                                        <option value="in_progress">In Progress</option>
                                                        <option value="done">Done</option>
                                                    </select>
                                                    <button onClick={() => removeItem(i)} className="ml-auto text-xs text-red-400 hover:text-red-600 px-2 py-1 rounded hover:bg-red-50 transition">✕ Remove</button>
                                                </div>
                                            ) : (
                                                <div className="flex items-center gap-2 flex-wrap flex-1">
                                                    {item.category && <span className="text-xs bg-blue-50 text-blue-600 px-2 py-0.5 rounded">{item.category}</span>}
                                                    {item.status && <span className={`text-xs px-2 py-0.5 rounded font-medium ${statusColor(item.status)}`}>{item.status}</span>}
                                                    <span className="text-xs text-gray-500 ml-auto whitespace-nowrap">{item.quantity} {item.unit}</span>
                                                </div>
                                            )}
                                        </div>
                                        {editMode ? (
                                            <textarea rows={3} className={`${inp} mt-1 resize-none`} value={item.description || ''}
                                                onChange={e => setEditItems(prev => prev.map((it, idx) => idx === i ? { ...it, description: e.target.value } : it))}
                                                placeholder="Item description…"/>
                                        ) : (
                                            <p className="text-sm text-gray-700 leading-relaxed"
                                               dangerouslySetInnerHTML={{ __html: item.description || '—' }}/>
                                        )}
                                        {!editMode && item.channel_codes && (
                                            <p className="text-xs text-gray-400 mt-2">Channels: {item.channel_codes}</p>
                                        )}
                                    </div>
                                ))}
                            </div>
                        </>
                    )}

                    {data && activeTab === 'vendors' && (
                        <>
                            <div className="flex items-center justify-between mb-3">
                                <h3 className="text-sm font-semibold text-gray-600 uppercase tracking-wide">
                                    Vendors ({editMode ? editVendors.length : vendors.length})
                                </h3>
                                {editMode && (
                                    <button onClick={addVendor} className="text-xs bg-indigo-50 text-indigo-600 hover:bg-indigo-100 px-3 py-1 rounded-lg font-medium transition">
                                        + Add Vendor
                                    </button>
                                )}
                            </div>

                            {(editMode ? editVendors : vendors).length === 0 ? (
                                <div className="text-center py-16 text-gray-400">
                                    <p className="text-3xl mb-3">🔍</p>
                                    <p className="font-medium text-gray-500">No vendors found for this inquiry</p>
                                    {editMode && <p className="text-sm mt-1">Click "+ Add Vendor" to add one manually.</p>}
                                </div>
                            ) : (
                                <div className="space-y-3">
                                    {(editMode ? editVendors : vendors).map((v, i) => (
                                        <div key={v.id || `v-${i}`} className={`border rounded-xl p-4 transition ${editMode ? 'border-indigo-200 bg-indigo-50/30' : 'border-gray-200 hover:border-indigo-200'}`}>
                                            {editMode ? (
                                                <div className="space-y-2">
                                                    <div className="flex items-center gap-2">
                                                        <input className={`${inp} flex-1 font-semibold`} value={v.name || ''} placeholder="Vendor / Company name"
                                                            onChange={e => setVendorField(i, 'name', e.target.value)}/>
                                                        <button onClick={() => removeVendor(i)} className="text-xs text-red-400 hover:text-red-600 px-2 py-1 rounded hover:bg-red-50 transition whitespace-nowrap">✕ Remove</button>
                                                    </div>
                                                    <div className="grid grid-cols-2 gap-2">
                                                        <input className={inp} value={v.email || ''} placeholder="Email"
                                                            onChange={e => setVendorField(i, 'email', e.target.value)}/>
                                                        <input className={inp} value={v.phone || ''} placeholder="Phone"
                                                            onChange={e => setVendorField(i, 'phone', e.target.value)}/>
                                                        <input className={inp} value={v.website || ''} placeholder="Website"
                                                            onChange={e => setVendorField(i, 'website', e.target.value)}/>
                                                        <input className={inp} value={v.country || ''} placeholder="Country"
                                                            onChange={e => setVendorField(i, 'country', e.target.value)}/>
                                                        <input className={inp} value={v.city || ''} placeholder="City"
                                                            onChange={e => setVendorField(i, 'city', e.target.value)}/>
                                                        <input className={inp} value={v.brands || ''} placeholder="Brands / Products"
                                                            onChange={e => setVendorField(i, 'brands', e.target.value)}/>
                                                    </div>
                                                </div>
                                            ) : (
                                                <div className="flex items-start justify-between gap-3">
                                                    <div className="flex-1 min-w-0">
                                                        <p className="font-semibold text-gray-800 text-sm">{v.name}</p>
                                                        <div className="flex flex-wrap gap-x-4 gap-y-1 mt-1">
                                                            {v.country && <span className="text-xs text-gray-500">📍 {[v.city, v.country].filter(Boolean).join(', ')}</span>}
                                                            {v.email   && <span className="text-xs text-gray-500">✉️ {v.email}</span>}
                                                            {v.phone   && <span className="text-xs text-gray-500">📞 {v.phone}</span>}
                                                            {v.website && <a href={v.website.startsWith('http') ? v.website : `https://${v.website}`} target="_blank" rel="noreferrer" className="text-xs text-indigo-500 hover:underline" onClick={e => e.stopPropagation()}>🌐 Website</a>}
                                                        </div>
                                                        {v.brands && <p className="text-xs text-gray-400 mt-1">Brands: {v.brands}</p>}
                                                    </div>
                                                    {v.source && (
                                                        <span className="text-xs bg-gray-100 text-gray-500 px-2 py-1 rounded-full whitespace-nowrap flex-shrink-0">{v.source}</span>
                                                    )}
                                                </div>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            )}
                        </>
                    )}

                    {/* ── Outcome Tab ── */}
                    {data && activeTab === 'outcome' && (() => {
                        const BID_STATUSES = [
                            { value: 'bid_sent',    label: 'Bid Sent',    color: 'bg-blue-100 text-blue-700' },
                            { value: 'quoted',      label: 'Quoted',      color: 'bg-yellow-100 text-yellow-700' },
                            { value: 'won',         label: 'Won',         color: 'bg-green-100 text-green-700' },
                            { value: 'lost',        label: 'Lost',        color: 'bg-red-100 text-red-700' },
                            { value: 'no_response', label: 'No Response', color: 'bg-gray-100 text-gray-500' },
                        ];
                        const current = BID_STATUSES.find(s => s.value === (outcomeForm.status || 'bid_sent'));
                        return (
                            <div className="max-w-2xl space-y-5">
                                <div>
                                    <p className="text-xs text-gray-400 uppercase mb-2 font-semibold tracking-wide">Bid Status</p>
                                    <div className="flex flex-wrap gap-2">
                                        {BID_STATUSES.map(s => (
                                            <button key={s.value}
                                                onClick={() => setOutcomeForm(p => ({ ...p, status: s.value }))}
                                                className={`px-3 py-1.5 rounded-full text-xs font-semibold border-2 transition ${
                                                    outcomeForm.status === s.value
                                                        ? `${s.color} border-current`
                                                        : 'bg-white text-gray-400 border-gray-200 hover:border-gray-300'
                                                }`}>
                                                {s.label}
                                            </button>
                                        ))}
                                    </div>
                                </div>

                                <div className="grid grid-cols-2 gap-4">
                                    <div>
                                        <label className="text-xs text-gray-400 uppercase mb-1 block font-semibold tracking-wide">Quotation Value (AED)</label>
                                        <input type="number" className={inp}
                                            value={outcomeForm.quotation_value}
                                            onChange={e => setOutcomeForm(p => ({ ...p, quotation_value: e.target.value }))}
                                            placeholder="0.00"/>
                                    </div>
                                    <div>
                                        <label className="text-xs text-gray-400 uppercase mb-1 block font-semibold tracking-wide">Order Value (AED)</label>
                                        <input type="number" className={inp}
                                            value={outcomeForm.order_value}
                                            onChange={e => setOutcomeForm(p => ({ ...p, order_value: e.target.value }))}
                                            placeholder="0.00"/>
                                    </div>
                                </div>

                                {(outcomeForm.status === 'lost') && (
                                    <div className="grid grid-cols-2 gap-4">
                                        <div>
                                            <label className="text-xs text-gray-400 uppercase mb-1 block font-semibold tracking-wide">Lost Reason</label>
                                            <input className={inp}
                                                value={outcomeForm.lost_reason}
                                                onChange={e => setOutcomeForm(p => ({ ...p, lost_reason: e.target.value }))}
                                                placeholder="e.g. Price, delivery time…"/>
                                        </div>
                                        <div>
                                            <label className="text-xs text-gray-400 uppercase mb-1 block font-semibold tracking-wide">Competitor</label>
                                            <input className={inp}
                                                value={outcomeForm.competitor_name}
                                                onChange={e => setOutcomeForm(p => ({ ...p, competitor_name: e.target.value }))}
                                                placeholder="Competitor name"/>
                                        </div>
                                    </div>
                                )}

                                <div>
                                    <label className="text-xs text-gray-400 uppercase mb-1 block font-semibold tracking-wide">Outcome Date</label>
                                    <input type="date" className={`${inp} w-48`}
                                        value={outcomeForm.outcome_date}
                                        onChange={e => setOutcomeForm(p => ({ ...p, outcome_date: e.target.value }))}/>
                                </div>

                                <div>
                                    <label className="text-xs text-gray-400 uppercase mb-1 block font-semibold tracking-wide">Notes</label>
                                    <textarea rows={3} className={`${inp} resize-none`}
                                        value={outcomeForm.notes}
                                        onChange={e => setOutcomeForm(p => ({ ...p, notes: e.target.value }))}
                                        placeholder="Additional notes…"/>
                                </div>

                                <div className="flex items-center gap-3 pt-1">
                                    <button onClick={saveOutcome} disabled={outcomeSaving}
                                        className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-sm rounded-lg font-medium transition">
                                        {outcomeSaving ? 'Saving…' : '💾 Save Outcome'}
                                    </button>
                                    {outcomeMsg && (
                                        <span className={`text-sm font-medium ${outcomeMsg.startsWith('✅') ? 'text-green-600' : 'text-red-500'}`}>
                                            {outcomeMsg}
                                        </span>
                                    )}
                                    {outcome && (
                                        <span className={`ml-auto text-xs px-2.5 py-1 rounded-full font-semibold ${current?.color}`}>
                                            Current: {current?.label}
                                        </span>
                                    )}
                                </div>

                                {!outcome && (
                                    <p className="text-xs text-gray-400">No outcome recorded yet. Set a status and save to track this bid.</p>
                                )}
                            </div>
                        );
                    })()}
                </div>
            </div>
        </div>
    );
};

// ── Loading Spinner ───────────────────────────────────────
export const LoadingScreen = ({ message = 'Loading...' }) => (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
            <div className="w-10 h-10 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-3"></div>
            <p className="text-gray-500 text-sm">{message}</p>
        </div>
    </div>
);