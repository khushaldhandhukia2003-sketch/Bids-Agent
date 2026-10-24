import React, { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import { useNavigate } from 'react-router-dom';
import { API } from '../config/api';

const StatusBadge = ({ status }) => {
    const styles = {
        received: 'bg-green-100 text-green-700',
        lost:     'bg-red-100 text-red-700',
        pending:  'bg-yellow-100 text-yellow-700',
    };
    return (
        <span className={`px-2.5 py-1 rounded-full text-xs font-medium capitalize ${styles[status] || 'bg-gray-100 text-gray-500'}`}>
            {status || 'pending'}
        </span>
    );
};

const ApoorvDashboard = () => {
    const { user, logout, getBaseParams } = useAuth();
    const navigate = useNavigate();
    const [activeTab, setActiveTab]             = useState('overview');
    const [rfqs, setRfqs]                       = useState([]);
    const [stats, setStats]                     = useState({});
    const [byPerson, setByPerson]               = useState([]);
    const [selectedSP, setSelectedSP]           = useState(null);
    const [loading, setLoading]                 = useState(true);

    const params = getBaseParams();

    useEffect(() => {
        Promise.all([
            fetch(`${API}/rfqs/?${params}`).then(r => r.json()),
            fetch(`${API}/rfqs/stats?${params}`).then(r => r.json()),
            fetch(`${API}/rfqs/by-salesperson?${params}`).then(r => r.json()),
        ]).then(([rfqData, statsData, byPersonData]) => {
            setRfqs(rfqData.rfqs || []);
            setStats(statsData.stats || {});
            setByPerson(byPersonData.data || []);
            setLoading(false);
        });
    }, []);

    const handleLogout = () => { logout(); navigate('/login'); };

    const filteredRfqs = selectedSP
        ? rfqs.filter(r => r.salesperson_name === selectedSP)
        : rfqs;

    if (loading) return (
        <div className="min-h-screen flex items-center justify-center bg-gray-50">
            <div className="text-center">
                <div className="w-10 h-10 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-3"></div>
                <p className="text-gray-500">Loading RFQ Dashboard...</p>
            </div>
        </div>
    );

    return (
        <div className="flex min-h-screen bg-gray-50">
            {/* Sidebar */}
            <div className="w-64 bg-gray-900 text-white flex flex-col">
                <div className="p-6 border-b border-gray-700">
                    <h1 className="text-lg font-bold">🏗️ Bhatia Group</h1>
                    <p className="text-xs text-gray-400 mt-1">RFQ Division Portal</p>
                </div>
                <div className="p-4 border-b border-gray-700">
                    <div className="bg-blue-600 inline-block px-2 py-1 rounded text-xs mb-2">General Manager</div>
                    <p className="font-semibold text-sm">{user?.name}</p>
                    <p className="text-xs text-gray-400">Export · TPE · MRO · Petrogulf</p>
                </div>
                <nav className="flex-1 p-4">
                    {[
                        { id: 'overview',      label: 'Overview',       icon: '📊' },
                        { id: 'rfqs',          label: 'All RFQs',       icon: '📋' },
                        { id: 'by_person',     label: 'By Salesperson', icon: '👥' },
                    ].map(tab => (
                        <button key={tab.id} onClick={() => setActiveTab(tab.id)}
                            className={`w-full text-left px-3 py-2.5 rounded-lg mb-1 text-sm flex items-center gap-3 transition
                                ${activeTab === tab.id ? 'bg-blue-600 text-white' : 'text-gray-300 hover:bg-gray-800'}`}>
                            <span>{tab.icon}</span>{tab.label}
                        </button>
                    ))}

                    {/* Salesperson quick filter */}
                    <div className="mt-4">
                        <p className="text-xs text-gray-500 uppercase mb-2">Salespersons</p>
                        <button onClick={() => setSelectedSP(null)}
                            className={`w-full text-left px-3 py-1.5 rounded text-xs mb-1 ${!selectedSP ? 'bg-blue-600 text-white' : 'text-gray-400 hover:bg-gray-800'}`}>
                            All ({rfqs.length})
                        </button>
                        {byPerson.map(sp => (
                            <button key={sp.salesperson_name}
                                onClick={() => { setSelectedSP(sp.salesperson_name); setActiveTab('rfqs'); }}
                                className={`w-full text-left px-3 py-1.5 rounded text-xs mb-1 flex justify-between
                                    ${selectedSP === sp.salesperson_name ? 'bg-blue-600 text-white' : 'text-gray-400 hover:bg-gray-800'}`}>
                                <span>{sp.salesperson_name}</span>
                                <span className="bg-gray-700 px-1.5 rounded">{sp.total}</span>
                            </button>
                        ))}
                    </div>
                </nav>
                <div className="p-4 border-t border-gray-700">
                    <button onClick={handleLogout} className="w-full bg-red-600 hover:bg-red-700 text-white py-2 rounded-lg text-sm">
                        Logout
                    </button>
                </div>
            </div>

            {/* Main Content */}
            <div className="flex-1 overflow-auto">
                <div className="bg-white border-b px-8 py-5 flex justify-between items-center">
                    <div>
                        <h1 className="text-2xl font-bold text-gray-800">RFQ Dashboard</h1>
                        <p className="text-sm text-gray-500">GM {user?.name} — Export, TPE, MRO, Petrogulf</p>
                    </div>
                    <div className="bg-blue-100 text-blue-700 px-4 py-2 rounded-lg text-sm font-medium">
                        RFQ Workflow · 4 Divisions
                    </div>
                </div>

                <div className="p-8">
                    {/* Overview */}
                    {activeTab === 'overview' && (
                        <>
                            {/* Stats */}
                            <div className="grid grid-cols-2 lg:grid-cols-5 gap-4 mb-8">
                                {[
                                    { label: 'Total RFQs',   value: stats.total_rfqs,  color: 'bg-blue-50 text-blue-600',   icon: '📋' },
                                    { label: 'Received',      value: stats.received,    color: 'bg-green-50 text-green-600', icon: '✅' },
                                    { label: 'Lost',          value: stats.lost,        color: 'bg-red-50 text-red-600',     icon: '❌' },
                                    { label: 'Pending',       value: stats.pending,     color: 'bg-yellow-50 text-yellow-600',icon: '⏳' },
                                    { label: 'Total Value',   value: stats.total_value ? `$${Number(stats.total_value).toLocaleString()}` : '—',
                                      color: 'bg-purple-50 text-purple-600', icon: '💰' },
                                ].map(s => (
                                    <div key={s.label} className={`rounded-xl border p-4 ${s.color}`}>
                                        <div className="flex justify-between items-center mb-1">
                                            <p className="text-xs font-medium opacity-75">{s.label}</p>
                                            <span>{s.icon}</span>
                                        </div>
                                        <p className="text-2xl font-bold">{s.value ?? '—'}</p>
                                    </div>
                                ))}
                            </div>

                            {/* Salesperson breakdown */}
                            <h2 className="text-lg font-semibold text-gray-700 mb-4">Salesperson Breakdown</h2>
                            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-8">
                                {byPerson.map(sp => (
                                    <div key={sp.salesperson_name}
                                        onClick={() => { setSelectedSP(sp.salesperson_name); setActiveTab('rfqs'); }}
                                        className="bg-white rounded-xl border border-gray-200 p-5 hover:shadow-md hover:border-blue-300 transition cursor-pointer">
                                        <div className="flex justify-between items-start mb-3">
                                            <div>
                                                <p className="font-semibold text-gray-800">{sp.salesperson_name}</p>
                                                <p className="text-xs text-gray-400">{sp.division_name}</p>
                                            </div>
                                            <span className="bg-blue-50 text-blue-600 font-bold text-lg px-3 py-1 rounded-lg">{sp.total}</span>
                                        </div>
                                        <div className="flex gap-3 text-xs">
                                            <span className="text-green-600">✅ {sp.received} received</span>
                                            <span className="text-red-500">❌ {sp.lost} lost</span>
                                        </div>
                                        <p className="text-xs text-gray-400 mt-2">
                                            Value: ${Number(sp.total_value || 0).toLocaleString()}
                                        </p>
                                    </div>
                                ))}
                            </div>

                            {/* Recent RFQs */}
                            <h2 className="text-lg font-semibold text-gray-700 mb-4">Recent RFQs</h2>
                            <RFQTable rfqs={rfqs.slice(0, 10)} />
                        </>
                    )}

                    {/* All RFQs */}
                    {activeTab === 'rfqs' && (
                        <>
                            <div className="flex items-center justify-between mb-5">
                                <div className="flex items-center gap-3">
                                    <h2 className="text-lg font-semibold text-gray-700">
                                        {selectedSP ? `${selectedSP}'s RFQs` : 'All RFQs'}
                                        <span className="text-gray-400 font-normal ml-2">({filteredRfqs.length})</span>
                                    </h2>
                                    {selectedSP && (
                                        <button onClick={() => setSelectedSP(null)} className="text-xs text-blue-500 hover:underline">
                                            ✕ Clear
                                        </button>
                                    )}
                                </div>
                                <select onChange={e => setSelectedSP(e.target.value || null)} value={selectedSP || ''}
                                    className="border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                                    <option value="">All Salespersons</option>
                                    {byPerson.map(sp => (
                                        <option key={sp.salesperson_name} value={sp.salesperson_name}>
                                            {sp.salesperson_name} ({sp.total})
                                        </option>
                                    ))}
                                </select>
                            </div>
                            <RFQTable rfqs={filteredRfqs} />
                        </>
                    )}

                    {/* By Salesperson */}
                    {activeTab === 'by_person' && (
                        <>
                            <h2 className="text-lg font-semibold text-gray-700 mb-5">Performance by Salesperson</h2>
                            <div className="bg-white rounded-xl shadow overflow-hidden">
                                <table className="w-full text-sm">
                                    <thead className="bg-gray-50 text-xs text-gray-500 uppercase">
                                        <tr>
                                            {['Salesperson','Division','Total RFQs','Received','Lost','Pending','Total Value'].map(h => (
                                                <th key={h} className="px-4 py-3 text-left">{h}</th>
                                            ))}
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-gray-100">
                                        {byPerson.map(sp => (
                                            <tr key={sp.salesperson_name} className="hover:bg-gray-50">
                                                <td className="px-4 py-3 font-medium">{sp.salesperson_name}</td>
                                                <td className="px-4 py-3 text-gray-500">{sp.division_name}</td>
                                                <td className="px-4 py-3 font-bold text-blue-600">{sp.total}</td>
                                                <td className="px-4 py-3 text-green-600">{sp.received}</td>
                                                <td className="px-4 py-3 text-red-500">{sp.lost}</td>
                                                <td className="px-4 py-3 text-yellow-600">{sp.total - sp.received - sp.lost}</td>
                                                <td className="px-4 py-3">${Number(sp.total_value||0).toLocaleString()}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </>
                    )}
                </div>
            </div>
        </div>
    );
};

// ── Shared RFQ Table ──────────────────────────────────────────
const RFQTable = ({ rfqs }) => (
    <div className="bg-white rounded-xl shadow overflow-hidden">
        <div className="overflow-x-auto">
            <table className="w-full text-sm">
                <thead className="bg-gray-50 text-xs text-gray-500 uppercase">
                    <tr>
                        {['Ref No','Client','Salesperson','Division','Description','Closing Date','Value','Status'].map(h => (
                            <th key={h} className="px-4 py-3 text-left whitespace-nowrap">{h}</th>
                        ))}
                    </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                    {rfqs.length === 0 ? (
                        <tr><td colSpan={8} className="text-center py-10 text-gray-400">No RFQs found</td></tr>
                    ) : rfqs.map(rfq => (
                        <tr key={rfq.id} className="hover:bg-gray-50">
                            <td className="px-4 py-3 font-mono text-xs text-blue-600">{rfq.enquiry_ref_no || '—'}</td>
                            <td className="px-4 py-3 font-medium">{rfq.client || '—'}</td>
                            <td className="px-4 py-3">{rfq.salesperson_name || '—'}</td>
                            <td className="px-4 py-3 text-gray-500">{rfq.division_name || '—'}</td>
                            <td className="px-4 py-3 text-gray-500 max-w-xs truncate">{rfq.package_description || '—'}</td>
                            <td className="px-4 py-3 text-gray-500 whitespace-nowrap">
                                {rfq.closing_date ? new Date(rfq.closing_date).toLocaleDateString() : '—'}
                            </td>
                            <td className="px-4 py-3">
                                {rfq.quotation_value ? `$${Number(rfq.quotation_value).toLocaleString()}` : '—'}
                            </td>
                            <td className="px-4 py-3">
                                <span className={`px-2.5 py-1 rounded-full text-xs font-medium
                                    ${rfq.status === 'received' ? 'bg-green-100 text-green-700' :
                                      rfq.status === 'lost'     ? 'bg-red-100 text-red-700' :
                                                                   'bg-yellow-100 text-yellow-700'}`}>
                                    {rfq.status || 'pending'}
                                </span>
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    </div>
);

export default ApoorvDashboard;