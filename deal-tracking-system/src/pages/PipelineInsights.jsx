import React, { useState, useEffect } from 'react';
import { API } from '../config/api';

const CHANNEL_NAMES = {
    LAD: 'Local Authorized Distributors',
    GM:  'Grey Market / Parallel Import',
    OCD: 'Other Country Distributors',
    OEM: 'OEM Direct Factory',
    ISD: 'Industrial Surplus Dealers',
    IGS: 'Independent Global Stockists',
    PSE: 'Project Subcontractor Excess',
    LMR: 'Local Mfg / Reverse Engineering',
    FZT: 'Free Zone Trading Houses',
    B2B: 'Industrial B2B Marketplaces',
    HOA: 'Hidden Regional OEM Agents',
    SRC: 'Service & Repair Companies',
    BGA: 'Buying Groups / Procurement Alliances',
    CIS: 'Cross-Industry Suppliers',
    MRO: 'Online Retail / MRO E-commerce',
    CBN: 'Category-Based Supplier Networks',
    ESP: 'Emergency Supplier Panel',
    OHF: 'Obsolete / Hard-to-Find Network',
    MCR: 'Multi-Channel RFQ Strategy',
    SBP: 'Strategic Brand Partnerships',
    PSS: 'Partial Stocking Strategy',
    RRP: 'Repair + Replacement Proposals',
    ABP: 'Alternative Brand Proposal',
    PTA: 'Payment-Term Arbitrage',
    SPS: 'Supplier Performance Segmentation',
};

const WinRateBadge = ({ rate }) => {
    if (rate === null || rate === undefined) return <span className="text-gray-400 text-xs">—</span>;
    const color = rate >= 60 ? 'text-green-700 bg-green-50' : rate >= 30 ? 'text-yellow-700 bg-yellow-50' : 'text-red-700 bg-red-50';
    return <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${color}`}>{rate}%</span>;
};

const Bar = ({ value, max, color = 'bg-indigo-500' }) => (
    <div className="w-full bg-gray-100 rounded-full h-1.5">
        <div className={`${color} h-1.5 rounded-full transition-all`} style={{ width: `${Math.min(100, max ? (value / max) * 100 : 0)}%` }} />
    </div>
);

export default function PipelineInsights() {
    const [data, setData]     = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError]   = useState(null);
    const [sortBy, setSortBy] = useState('selected');
    const [tab, setTab]       = useState('channels');

    useEffect(() => {
        setLoading(true);
        fetch(`${API}/vendors/pipeline/analytics`)
            .then(r => r.json())
            .then(d => { setData(d); setLoading(false); })
            .catch(e => { setError(e.message); setLoading(false); });
    }, []);

    if (loading) return (
        <div className="flex items-center justify-center h-64 text-gray-400 text-sm">Loading pipeline data…</div>
    );
    if (error) return (
        <div className="flex items-center justify-center h-64 text-red-400 text-sm">Error: {error}</div>
    );
    if (!data?.channels?.length) return (
        <div className="flex flex-col items-center justify-center h-64 gap-3">
            <div className="text-4xl">📊</div>
            <p className="text-gray-500 font-medium">No pipeline data yet</p>
            <p className="text-gray-400 text-sm text-center max-w-xs">
                Pipeline decisions are logged when your team saves vendor selections in the Procurement Agent.
                Data will appear here once searches are performed.
            </p>
        </div>
    );

    const { channels = [], totals = {}, top_vendors = [] } = data;

    const sorted = [...channels].sort((a, b) => {
        if (sortBy === 'selected')  return b.total_selected - a.total_selected;
        if (sortBy === 'win_rate')  return (b.win_rate ?? -1) - (a.win_rate ?? -1);
        if (sortBy === 'shown')     return b.total_shown - a.total_shown;
        return 0;
    });

    const maxSelected = Math.max(...channels.map(c => c.total_selected), 1);

    return (
        <div className="p-6 max-w-5xl mx-auto">
            {/* Header */}
            <div className="mb-6">
                <h2 className="text-xl font-bold text-gray-800">Pipeline Insights</h2>
                <p className="text-gray-500 text-sm mt-1">
                    Track which sourcing channels and vendors are most effective across all RFQs
                </p>
            </div>

            {/* Summary KPIs */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                {[
                    { label: 'RFQs Tracked',      value: totals.total_inquiries ?? 0,  color: 'text-indigo-600', bg: 'bg-indigo-50' },
                    { label: 'Vendors Evaluated',  value: totals.total_decisions ?? 0,  color: 'text-blue-600',   bg: 'bg-blue-50'   },
                    { label: 'Vendors Selected',   value: totals.total_selected ?? 0,   color: 'text-purple-600', bg: 'bg-purple-50' },
                    { label: 'Won',                value: totals.total_won ?? 0,        color: 'text-green-600',  bg: 'bg-green-50'  },
                ].map(k => (
                    <div key={k.label} className={`${k.bg} rounded-xl p-4`}>
                        <p className="text-xs text-gray-500 font-medium mb-1">{k.label}</p>
                        <p className={`text-2xl font-bold ${k.color}`}>{k.value.toLocaleString()}</p>
                    </div>
                ))}
            </div>

            {/* Tabs */}
            <div className="flex gap-1 mb-5 bg-gray-100 p-1 rounded-lg w-fit">
                {[['channels', 'Channels'], ['vendors', 'Top Vendors']].map(([id, label]) => (
                    <button key={id} onClick={() => setTab(id)}
                        className={`px-4 py-1.5 rounded-md text-sm font-medium transition
                            ${tab === id ? 'bg-white text-indigo-700 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}>
                        {label}
                    </button>
                ))}
            </div>

            {tab === 'channels' && (
                <>
                    {/* Sort controls */}
                    <div className="flex items-center gap-2 mb-4">
                        <span className="text-xs text-gray-500 font-medium">Sort by:</span>
                        {[['selected','Most Selected'], ['win_rate','Best Win Rate'], ['shown','Most Shown']].map(([k, l]) => (
                            <button key={k} onClick={() => setSortBy(k)}
                                className={`px-3 py-1 rounded-full text-xs font-medium border transition
                                    ${sortBy === k ? 'bg-indigo-600 text-white border-indigo-600' : 'bg-white text-gray-600 border-gray-200 hover:border-indigo-400'}`}>
                                {l}
                            </button>
                        ))}
                    </div>

                    {/* Channel table */}
                    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
                        <table className="w-full text-sm">
                            <thead className="bg-gray-50 border-b border-gray-200">
                                <tr>
                                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Channel</th>
                                    <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Shown</th>
                                    <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Selected</th>
                                    <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Won</th>
                                    <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Lost</th>
                                    <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Win Rate</th>
                                    <th className="px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide w-28">Selection</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-100">
                                {sorted.map(ch => (
                                    <tr key={ch.channel} className="hover:bg-gray-50 transition-colors">
                                        <td className="px-4 py-3">
                                            <div className="font-semibold text-gray-800 text-xs">{ch.channel}</div>
                                            <div className="text-gray-400 text-xs mt-0.5">{CHANNEL_NAMES[ch.channel] || ch.channel}</div>
                                        </td>
                                        <td className="px-4 py-3 text-right text-gray-600 font-mono text-xs">{ch.total_shown}</td>
                                        <td className="px-4 py-3 text-right font-semibold text-indigo-600 font-mono text-xs">{ch.total_selected}</td>
                                        <td className="px-4 py-3 text-right text-green-600 font-mono text-xs">{ch.total_won}</td>
                                        <td className="px-4 py-3 text-right text-red-500 font-mono text-xs">{ch.total_lost}</td>
                                        <td className="px-4 py-3 text-right"><WinRateBadge rate={ch.win_rate} /></td>
                                        <td className="px-4 py-3">
                                            <div className="flex items-center gap-2">
                                                <Bar value={ch.total_selected} max={maxSelected} />
                                                <span className="text-xs text-gray-400 w-9 text-right">{ch.selection_rate}%</span>
                                            </div>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                    <p className="text-xs text-gray-400 mt-3">
                        Win Rate = wins ÷ (wins + losses). Pending outcomes are excluded from rate calculation.
                    </p>
                </>
            )}

            {tab === 'vendors' && (
                <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
                    {top_vendors.length === 0 ? (
                        <div className="flex items-center justify-center h-40 text-gray-400 text-sm">
                            No vendor selection data yet
                        </div>
                    ) : (
                        <table className="w-full text-sm">
                            <thead className="bg-gray-50 border-b border-gray-200">
                                <tr>
                                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">#</th>
                                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Vendor</th>
                                    <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Times Selected</th>
                                    <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Won</th>
                                    <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Lost</th>
                                    <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Avg Score</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-100">
                                {top_vendors.map((v, i) => {
                                    const wr = (v.wins + v.losses) > 0 ? Math.round(v.wins / (v.wins + v.losses) * 100) : null;
                                    return (
                                        <tr key={v.vendor_name} className="hover:bg-gray-50 transition-colors">
                                            <td className="px-4 py-3 text-gray-400 text-xs font-mono">{i + 1}</td>
                                            <td className="px-4 py-3 font-medium text-gray-800">{v.vendor_name}</td>
                                            <td className="px-4 py-3 text-right font-semibold text-indigo-600 font-mono text-xs">{v.times_selected}</td>
                                            <td className="px-4 py-3 text-right text-green-600 font-mono text-xs">{v.wins}</td>
                                            <td className="px-4 py-3 text-right text-red-500 font-mono text-xs">{v.losses}</td>
                                            <td className="px-4 py-3 text-right">
                                                {v.avg_score != null
                                                    ? <span className="text-xs font-mono text-gray-600">{v.avg_score}</span>
                                                    : <span className="text-gray-400 text-xs">—</span>}
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    )}
                </div>
            )}
        </div>
    );
}
