import React, { useEffect, useState } from 'react';
import { API } from '../config/api';

const fmt = n => n == null ? '—' : Number(n).toLocaleString('en-AE', { minimumFractionDigits: 0 });

export default function BidsConversionPanel({ role = 'gm', divisionIds = '' }) {
    const [stats, setStats]     = useState(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const params = new URLSearchParams({ role });
        if (divisionIds) params.set('division_ids', divisionIds);
        fetch(`${API}/bids/stats?${params}`)
            .then(r => r.json())
            .then(d => { if (d.success) setStats(d.stats); })
            .catch(() => {})
            .finally(() => setLoading(false));
    }, [role, divisionIds]);

    if (loading) return (
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-5 mb-6 animate-pulse h-28" />
    );
    if (!stats) return null;

    const total   = stats.total      || 0;
    const pending = (stats.bid_sent  || 0) + (stats.quoted || 0) + (stats.no_response || 0);
    const won     = stats.won        || 0;
    const lost    = stats.lost       || 0;
    const wonVal  = stats.total_won_value  || 0;
    const winRate = stats.win_vs_lost_rate || 0;

    // Funnel bar widths (relative to total)
    const pct = v => total > 0 ? Math.round(v / total * 100) : 0;

    return (
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-5 mb-6">
            <div className="flex items-center justify-between mb-4">
                <h2 className="text-sm font-bold text-gray-700 uppercase tracking-wider">Bid Conversion</h2>
                <span className="text-xs text-gray-400">{fmt(total)} total bids · from Zoho CRM</span>
            </div>

            {/* KPI row */}
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-5">
                <div className="bg-gray-50 rounded-xl p-3 text-center">
                    <p className="text-xs text-gray-400 font-semibold uppercase tracking-wide mb-1">Total</p>
                    <p className="text-2xl font-bold text-gray-800">{fmt(total)}</p>
                </div>
                <div className="bg-blue-50 rounded-xl p-3 text-center">
                    <p className="text-xs text-blue-400 font-semibold uppercase tracking-wide mb-1">Pending</p>
                    <p className="text-2xl font-bold text-blue-700">{fmt(pending)}</p>
                </div>
                <div className="bg-green-50 rounded-xl p-3 text-center">
                    <p className="text-xs text-green-500 font-semibold uppercase tracking-wide mb-1">Won</p>
                    <p className="text-2xl font-bold text-green-700">{fmt(won)}</p>
                    <p className="text-[10px] text-green-400 mt-0.5">AED {fmt(wonVal)}</p>
                </div>
                <div className="bg-red-50 rounded-xl p-3 text-center">
                    <p className="text-xs text-red-400 font-semibold uppercase tracking-wide mb-1">Lost</p>
                    <p className="text-2xl font-bold text-red-600">{fmt(lost)}</p>
                </div>
                <div className="bg-indigo-50 rounded-xl p-3 text-center">
                    <p className="text-xs text-indigo-400 font-semibold uppercase tracking-wide mb-1">Win Rate</p>
                    <p className="text-2xl font-bold text-indigo-700">{winRate}%</p>
                    <p className="text-[10px] text-indigo-400 mt-0.5">won vs lost</p>
                </div>
            </div>

            {/* Funnel bar */}
            <div>
                <p className="text-xs text-gray-400 font-semibold uppercase tracking-wide mb-2">Pipeline Funnel</p>
                <div className="flex rounded-full overflow-hidden h-5 bg-gray-100 gap-px">
                    {pending > 0 && (
                        <div style={{ width: `${pct(pending)}%` }}
                            className="bg-blue-400 flex items-center justify-center text-[10px] text-white font-bold transition-all"
                            title={`Pending: ${pending}`}>
                            {pct(pending) > 8 ? `${pct(pending)}%` : ''}
                        </div>
                    )}
                    {won > 0 && (
                        <div style={{ width: `${pct(won)}%` }}
                            className="bg-green-500 flex items-center justify-center text-[10px] text-white font-bold transition-all"
                            title={`Won: ${won}`}>
                            {pct(won) > 8 ? `${pct(won)}%` : ''}
                        </div>
                    )}
                    {lost > 0 && (
                        <div style={{ width: `${pct(lost)}%` }}
                            className="bg-red-400 flex items-center justify-center text-[10px] text-white font-bold transition-all"
                            title={`Lost: ${lost}`}>
                            {pct(lost) > 8 ? `${pct(lost)}%` : ''}
                        </div>
                    )}
                </div>
                <div className="flex gap-4 mt-2">
                    <span className="flex items-center gap-1 text-xs text-gray-500"><span className="w-2 h-2 rounded-full bg-blue-400 inline-block"/>Pending</span>
                    <span className="flex items-center gap-1 text-xs text-gray-500"><span className="w-2 h-2 rounded-full bg-green-500 inline-block"/>Won</span>
                    <span className="flex items-center gap-1 text-xs text-gray-500"><span className="w-2 h-2 rounded-full bg-red-400 inline-block"/>Lost</span>
                </div>
            </div>
        </div>
    );
}
