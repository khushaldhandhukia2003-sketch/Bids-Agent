import React, { useState, useEffect, useCallback } from 'react';
import { API } from '../config/api';
import { useAuth } from '../context/AuthContext';

// Pending = bid_sent + quoted + no_response grouped under one bucket
const STATUS_CFG = {
    bid_sent:    { label: 'Bid Sent',    bucket: 'pending', color: 'bg-blue-100 text-blue-700',     dot: 'bg-blue-500' },
    quoted:      { label: 'Quoted',      bucket: 'pending', color: 'bg-purple-100 text-purple-700', dot: 'bg-purple-500' },
    no_response: { label: 'No Response', bucket: 'pending', color: 'bg-gray-100 text-gray-500',     dot: 'bg-gray-400' },
    won:         { label: 'Won',         bucket: 'won',     color: 'bg-green-100 text-green-700',   dot: 'bg-green-500' },
    lost:        { label: 'Lost',        bucket: 'lost',    color: 'bg-red-100 text-red-700',       dot: 'bg-red-400' },
};

const BUCKETS = [
    { id: 'all',     label: 'All Bids' },
    { id: 'pending', label: 'Pending' },
    { id: 'won',     label: 'Won' },
    { id: 'lost',    label: 'Lost' },
];

const fmt     = n => n == null ? '—' : Number(n).toLocaleString('en-AE', { minimumFractionDigits: 0 });
const fmtDate = d => d ? new Date(d).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: '2-digit' }) : '—';

function StatusBadge({ status }) {
    const c = STATUS_CFG[status] || STATUS_CFG.bid_sent;
    return (
        <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold ${c.color}`}>
            <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${c.dot}`} />
            {c.label}
        </span>
    );
}


export default function BidsTracker() {
    const { user } = useAuth();
    const [bids,      setBids]      = useState([]);
    const [loading,   setLoading]   = useState(true);
    const [syncing,   setSyncing]   = useState(false);
    const [syncMsg,   setSyncMsg]   = useState('');
    const [bucket,    setBucket]    = useState('all');
    const [filterDiv, setFilterDiv] = useState('');
    const [divisions, setDivisions] = useState([]);

    const role        = user?.role || 'gm';
    const divisionIds = user?.division_ids?.join(',') || '';
    const salesperson = user?.username;

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const params = new URLSearchParams({ role });
            if (divisionIds) params.set('division_ids', divisionIds);
            if (role === 'salesperson') params.set('salesperson_name', salesperson);
            const r = await fetch(`${API}/bids/?${params}`);
            const d = await r.json();
            const all = d.bids || [];
            setBids(all);
            // Build division list from division_label (covers both matched and unmatched)
            const divSet = new Set();
            all.forEach(b => { if (b.division_label) divSet.add(b.division_label); });
            setDivisions([...divSet].sort().map(label => ({ id: label, name: label })));
        } catch {}
        finally { setLoading(false); }
    }, [role, divisionIds, salesperson]);

    useEffect(() => { load(); }, [load]);

    // Auto-sync on mount: full sync if DB is empty, incremental if stale (>1h)
    useEffect(() => {
        const checkAndAutoSync = async () => {
            try {
                const [logRes, statusRes] = await Promise.all([
                    fetch(`${API}/zoho/sync/log?limit=1`),
                    fetch(`${API}/zoho/sync/status`),
                ]);
                const logD = await logRes.json();
                const statusD = await statusRes.json();
                if (statusD.running) return; // already syncing
                const last = logD.log?.[0]?.synced_at;
                const neverSynced = !last;
                const stale = last && (Date.now() - new Date(last).getTime()) > 60 * 60 * 1000;
                if (neverSynced || stale) runSync(neverSynced);
            } catch {}
        };
        checkAndAutoSync();
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

    const runSync = async (full = false) => {
        setSyncing(true); setSyncMsg('Syncing in background…');
        try {
            const res = await fetch(`${API}/zoho/sync${full ? '?full=true' : ''}`, { method: 'POST' });
            const d = await res.json();
            if (!res.ok) throw new Error(d.detail || 'Sync failed');
            if (d.status === 'already_running') {
                setSyncMsg('⏳ Sync already running…');
                return;
            }
            // Poll for completion
            const poll = setInterval(async () => {
                try {
                    const sr = await fetch(`${API}/zoho/sync/status`);
                    const sd = await sr.json();
                    if (!sd.running) {
                        clearInterval(poll);
                        setSyncing(false);
                        if (sd.error) {
                            setSyncMsg(`❌ ${sd.error}`);
                        } else if (sd.result) {
                            setSyncMsg(`✅ Synced — ${sd.result.total_in_db} bids in DB`);
                            load();
                        }
                        setTimeout(() => setSyncMsg(''), 8000);
                    }
                } catch {}
            }, 3000);
        } catch (e) {
            setSyncMsg(`❌ ${e.message}`);
            setSyncing(false);
            setTimeout(() => setSyncMsg(''), 7000);
        }
    };

    // Filter by division first (for counts), then also by bucket (for table)
    const divFiltered = filterDiv
        ? bids.filter(b => b.division_label === filterDiv || b.division_name === filterDiv)
        : bids;

    const displayed = divFiltered.filter(b =>
        bucket === 'all' || (STATUS_CFG[b.status]?.bucket === bucket) || b.status === bucket
    );

    // KPI cards reflect the active division filter
    const kpiBase  = divFiltered;
    const pending  = kpiBase.filter(b => STATUS_CFG[b.status]?.bucket === 'pending').length;
    const won      = kpiBase.filter(b => b.status === 'won').length;
    const lost     = kpiBase.filter(b => b.status === 'lost').length;
    const wonValue = kpiBase.filter(b => b.status === 'won').reduce((s, b) => s + (Number(b.order_value) || 0), 0);
    const winRate  = (won + lost) > 0 ? Math.round(won / (won + lost) * 100) : 0;

    // Tab counts reflect the active division filter
    const bucketCounts = {
        all:     divFiltered.length,
        pending: divFiltered.filter(b => STATUS_CFG[b.status]?.bucket === 'pending').length,
        won:     divFiltered.filter(b => b.status === 'won').length,
        lost:    divFiltered.filter(b => b.status === 'lost').length,
    };

    return (
        <div className="h-full flex flex-col bg-[#f8f9fc] overflow-hidden">

            {/* Header */}
            <div className="bg-white border-b border-gray-100 px-8 py-5 flex-shrink-0 flex items-center justify-between gap-4">
                <div>
                    <h1 className="text-xl font-bold text-gray-900">Bids Tracker</h1>
                    <p className="text-sm text-gray-400 mt-0.5">Track bid outcomes across all divisions</p>
                </div>
                <div className="flex items-center gap-3">
                    {syncMsg && (
                        <span className={`text-sm font-medium px-3 py-1.5 rounded-lg ${syncMsg.startsWith('✅') ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-600'}`}>
                            {syncMsg}
                        </span>
                    )}
                    <button onClick={() => runSync(true)} disabled={syncing}
                        className="flex items-center gap-2 px-4 py-2 text-sm bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white rounded-xl font-semibold transition shadow-sm">
                        {syncing
                            ? <><div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin"/><span>Syncing…</span></>
                            : <><span>🔄</span><span>Sync Zoho</span></>
                        }
                    </button>
                    <button onClick={load} className="px-3 py-2 text-sm bg-gray-50 hover:bg-gray-100 text-gray-600 border border-gray-200 rounded-xl font-semibold transition">
                        ↻
                    </button>
                </div>
            </div>

            <div className="flex-1 overflow-y-auto px-8 py-6 space-y-5">

                {/* KPI cards */}
                <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
                    <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
                        <p className="text-xs font-bold uppercase tracking-wider text-gray-400 mb-1">Total Bids</p>
                        <p className="text-3xl font-bold text-gray-800">{divFiltered.length}</p>
                        {filterDiv && <p className="text-xs text-gray-400 mt-1">{bids.length} across all divisions</p>}
                    </div>
                    <div className="bg-blue-50 rounded-2xl border border-blue-100 shadow-sm p-5">
                        <p className="text-xs font-bold uppercase tracking-wider text-blue-400 mb-1">Pending</p>
                        <p className="text-3xl font-bold text-blue-700">{pending}</p>
                        <p className="text-xs text-blue-400 mt-1">awaiting outcome</p>
                    </div>
                    <div className="bg-green-50 rounded-2xl border border-green-100 shadow-sm p-5">
                        <p className="text-xs font-bold uppercase tracking-wider text-green-500 mb-1">Won</p>
                        <p className="text-3xl font-bold text-green-700">{won}</p>
                        <p className="text-xs text-green-500 mt-1">AED {fmt(wonValue)}</p>
                    </div>
                    <div className="bg-red-50 rounded-2xl border border-red-100 shadow-sm p-5">
                        <p className="text-xs font-bold uppercase tracking-wider text-red-400 mb-1">Lost</p>
                        <p className="text-3xl font-bold text-red-600">{lost}</p>
                    </div>
                    <div className="bg-indigo-50 rounded-2xl border border-indigo-100 shadow-sm p-5">
                        <p className="text-xs font-bold uppercase tracking-wider text-indigo-400 mb-1">Win Rate</p>
                        <p className="text-3xl font-bold text-indigo-700">{winRate}%</p>
                        <p className="text-xs text-indigo-400 mt-1">won vs lost</p>
                    </div>
                </div>

                {/* Bucket tabs + division filter */}
                <div className="flex items-center gap-3 flex-wrap">
                    <div className="flex items-center bg-white border border-gray-100 rounded-xl p-1 shadow-sm gap-0.5">
                        {BUCKETS.map(b => (
                            <button key={b.id} onClick={() => setBucket(b.id)}
                                className={`flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-semibold transition ${
                                    bucket === b.id
                                        ? 'bg-indigo-600 text-white shadow-sm'
                                        : 'text-gray-500 hover:text-gray-800 hover:bg-gray-50'
                                }`}>
                                {b.label}
                                <span className={`text-xs px-1.5 py-0.5 rounded-full ${
                                    bucket === b.id ? 'bg-white/20 text-white' : 'bg-gray-100 text-gray-500'
                                }`}>
                                    {bucketCounts[b.id]}
                                </span>
                            </button>
                        ))}
                    </div>

                    {divisions.length > 1 && (
                        <select value={filterDiv} onChange={e => setFilterDiv(e.target.value)}
                            className="text-sm bg-white border border-gray-200 rounded-xl px-3 py-2.5 text-gray-700 focus:outline-none focus:ring-2 focus:ring-indigo-400 shadow-sm">
                            <option value="">All Divisions</option>
                            {divisions.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
                        </select>
                    )}

                    <span className="text-xs text-gray-400 ml-auto font-medium">{displayed.length} bids</span>
                </div>

                {/* Table */}
                {loading ? (
                    <div className="flex items-center justify-center py-28">
                        <div className="w-9 h-9 border-4 border-indigo-500 border-t-transparent rounded-full animate-spin"/>
                    </div>
                ) : displayed.length === 0 ? (
                    <div className="text-center py-28 text-gray-400">
                        <p className="text-5xl mb-4">
                            {bucket === 'won' ? '🏆' : bucket === 'lost' ? '📉' : '📋'}
                        </p>
                        <p className="font-semibold text-gray-500 text-lg">
                            No {bucket === 'all' ? '' : bucket} bids yet
                        </p>
                        <p className="text-sm mt-1 text-gray-400">
                            {bucket === 'pending'
                                ? 'Bids in progress will appear here.'
                                : bucket === 'won'
                                ? 'Won deals from Zoho or RFQ outcomes appear here.'
                                : bucket === 'lost'
                                ? 'Lost deals will appear here.'
                                : 'Record outcomes from the RFQ modal or sync Zoho CRM.'}
                        </p>
                    </div>
                ) : (
                    <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
                        <div className="overflow-x-auto">
                            <table className="w-full text-sm">
                                <thead className="border-b border-gray-100 bg-gray-50/70">
                                    <tr>
                                        {['RFQ / Deal', 'Client', 'Division', 'Salesperson', 'Status', 'Quoted AED', 'Won AED', 'Date'].map(h => (
                                            <th key={h} className="px-4 py-3.5 text-left text-[11px] font-bold text-gray-400 uppercase tracking-wider whitespace-nowrap">{h}</th>
                                        ))}
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-gray-50">
                                    {displayed.map(b => {
                                        const isBucketPending = STATUS_CFG[b.status]?.bucket === 'pending';
                                        return (
                                            <tr key={b.id} className={`hover:bg-gray-50/60 transition-colors ${b.status === 'won' ? 'bg-green-50/20' : b.status === 'lost' ? 'bg-red-50/10' : ''}`}>
                                                <td className="px-4 py-3.5">
                                                    <p className="font-mono text-xs font-bold text-gray-700">{b.bid_ref || b.inquiry_id || `BID-${b.id}`}</p>
                                                    {b.zoho_deal_id && <p className="text-[10px] text-indigo-400 mt-0.5">🔗 Zoho</p>}
                                                </td>
                                                <td className="px-4 py-3.5 font-semibold text-gray-800 max-w-[180px] truncate">{b.client || '—'}</td>
                                                <td className="px-4 py-3.5">
                                                    {(b.division_label || b.division_name)
                                                        ? <span className="bg-indigo-50 text-indigo-600 text-[11px] font-bold px-2 py-0.5 rounded-full">{b.division_label || b.division_name}</span>
                                                        : <span className="text-gray-300">—</span>}
                                                </td>
                                                <td className="px-4 py-3.5 text-gray-500 max-w-[130px] truncate">{b.salesperson_name || '—'}</td>
                                                <td className="px-4 py-3.5">
                                                    <StatusBadge status={b.status} />
                                                </td>
                                                <td className="px-4 py-3.5 font-mono text-xs text-gray-600">
                                                    {b.quotation_value != null ? fmt(b.quotation_value) : <span className="text-gray-300">—</span>}
                                                </td>
                                                <td className="px-4 py-3.5 font-mono text-xs">
                                                    {b.status === 'won' && b.order_value != null
                                                        ? <span className="text-green-600 font-bold">{fmt(b.order_value)}</span>
                                                        : <span className="text-gray-200">—</span>}
                                                </td>
                                                <td className="px-4 py-3.5 text-gray-400 text-xs whitespace-nowrap">
                                                    {fmtDate(b.outcome_date || b.bid_sent_date || b.created_at)}
                                                </td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                                {/* Footer totals */}
                                <tfoot className="border-t border-gray-100 bg-gray-50/70">
                                    <tr>
                                        <td colSpan={5} className="px-4 py-3 text-xs font-bold text-gray-400 uppercase tracking-wide">
                                            {displayed.length} bids shown
                                        </td>
                                        <td className="px-4 py-3 font-mono text-xs font-bold text-gray-600">
                                            {fmt(displayed.reduce((s, b) => s + (Number(b.quotation_value) || 0), 0))}
                                        </td>
                                        <td className="px-4 py-3 font-mono text-xs font-bold text-green-600">
                                            {fmt(displayed.filter(b => b.status === 'won').reduce((s, b) => s + (Number(b.order_value) || 0), 0))}
                                        </td>
                                        <td />
                                    </tr>
                                </tfoot>
                            </table>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
