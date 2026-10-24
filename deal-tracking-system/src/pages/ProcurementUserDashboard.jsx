import React, { useState, useMemo, useCallback, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import { useLocation } from 'react-router-dom';
import DashboardLayout from '../components/DashboardLayout';
import { StatCard, DataTable, InquiryModal } from '../components/UI';
import { useDashboard } from '../hooks/useDashboard';
import { API } from '../config/api';
import { VendorDirectory } from './VendorImport';
import ZohoSync from './ZohoSync';
import BidsConversionPanel from '../components/BidsConversionPanel';

const BASE_COLS = [
    { key: 'enquiry_ref_no', label: 'Inquiry ID',  render: v => <span className="font-mono font-medium text-blue-600">{v || '—'}</span> },
    { key: 'client',         label: 'Client',       render: v => v || '—' },
    { key: 'description',    label: 'Description',  render: v => v ? <span className="text-gray-600 text-xs" title={v}>{v.length > 60 ? v.slice(0,60)+'…' : v}</span> : '—' },
    { key: 'division_name',  label: 'Division' },
    { key: 'total_items',    label: 'Items',        render: v => <span className="bg-blue-50 text-blue-700 px-2 py-0.5 rounded text-xs font-medium">{v ?? 0}</span> },
    { key: 'created_at',     label: 'Date',         render: v => v ? new Date(v).toLocaleDateString() : '—' },
];

const makeRfqCols = (onView) => [...BASE_COLS, {
    key: '_actions', label: '', render: (_, row) => (
        <button onClick={e => { e.stopPropagation(); onView(row.enquiry_ref_no); }}
            className="px-2 py-1 text-xs bg-blue-50 text-blue-600 hover:bg-blue-100 rounded font-medium transition-colors">
            View
        </button>
    ),
}];

const EMPTY_FILTERS = { inquiryId: '', client: '', team: '', date: '' };

const applyFilter = (rows, sort, filters) => {
    let result = [...rows];
    if (filters.inquiryId)  result = result.filter(r => (r.enquiry_ref_no||'').toLowerCase().includes(filters.inquiryId.toLowerCase()));
    if (filters.client)     result = result.filter(r => (r.client||'') === filters.client);
    if (filters.team)       result = result.filter(r => (r.division_name||'') === filters.team);
    if (filters.date)       result = result.filter(r => r.created_at && r.created_at.slice(0,10) === filters.date);
    if (sort === 'newest')  result.sort((a,b) => new Date(b.created_at||0) - new Date(a.created_at||0));
    else if (sort === 'oldest') result.sort((a,b) => new Date(a.created_at||0) - new Date(b.created_at||0));
    return result;
};

const ProcurementUserDashboard = () => {
    const { user } = useAuth();
    const { rfqs, stats, divisions, loading, error, lastRefresh, refresh } = useDashboard();
    const location = useLocation();
    const [activeTab, setActiveTab]     = useState('overview');
    const [selectedInquiry, setSelectedInquiry] = useState(null);
    const [rfqSort, setRfqSort]         = useState('newest');
    const [rfqFilters, setRfqFilters]   = useState(EMPTY_FILTERS);

    useEffect(() => {
        if (location.state?.tab) setActiveTab(location.state.tab);
    }, [location.state?.tab]);

    const rfqClients = useMemo(() => [...new Set(rfqs.map(r => r.client).filter(Boolean))].sort(), [rfqs]);
    const rfqTeams   = useMemo(() => [...new Set(rfqs.map(r => r.division_name).filter(Boolean))].sort(), [rfqs]);
    const filteredRfqs = useMemo(() => applyFilter(rfqs, rfqSort, rfqFilters), [rfqs, rfqSort, rfqFilters]);
    const recentRfqs   = useMemo(() => rfqs.slice(0, 5), [rfqs]);
    const closeModal   = useCallback(() => setSelectedInquiry(null), []);
    const rfqCols      = useMemo(() => makeRfqCols(setSelectedInquiry), []);

    const divisionNames = (user?.divisions || []).map(d => d.name).join(', ') || 'No divisions';

    return (
        <>
        <DashboardLayout
            title="My Dashboard"
            welcomeSubtitle={<>Welcome, <span className="font-medium">{user?.name}</span></>}
            loading={loading}
            loadingMessage="Loading your data…"
            error={error}
            lastRefresh={lastRefresh}
            refresh={refresh}
            divisions={divisions}
            activeTab={activeTab}
            setActiveTab={setActiveTab}
        >
            {/* ── Overview ── */}
            <div style={{ display: activeTab === 'overview' ? undefined : 'none' }}>
                {/* Division chips */}
                <div className="flex flex-wrap gap-2 mb-5">
                    {(user?.divisions || []).map(d => (
                        <span key={d.id} className="text-xs px-3 py-1 bg-indigo-50 text-indigo-700 border border-indigo-200 rounded-full font-medium">
                            {d.name}
                        </span>
                    ))}
                </div>

                {/* KPI cards */}
                <div className="grid grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
                    <StatCard label="My RFQs"    value={stats.total_rfqs}    icon="📋" color="blue" />
                    <StatCard label="Vendors"     value={stats.total_vendors} icon="🏢" color="purple" />
                    <StatCard label="Items"       value={stats.total_items}   icon="📦" color="orange" />
                </div>

                {/* Bids conversion */}
                <BidsConversionPanel role="procurement" divisionIds={user?.division_ids?.join(',') || ''} />

                {/* My divisions breakdown */}
                {divisions.length > 0 && (
                    <>
                        <h2 className="text-base font-semibold text-gray-700 mb-3 mt-6">My Divisions</h2>
                        <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mb-6">
                            {divisions.map(div => (
                                <div key={div.id} className="bg-white rounded-xl border border-gray-200 p-4 hover:shadow-md transition-shadow">
                                    <div className="flex items-center justify-between">
                                        <p className="font-medium text-sm text-gray-800">{div.name}</p>
                                        <span className="bg-indigo-50 text-indigo-600 text-xs font-semibold px-2 py-1 rounded-full">{div.rfq_count ?? 0} RFQs</span>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </>
                )}

                {/* Recent RFQs */}
                <div className="flex items-center justify-between mb-3">
                    <h2 className="text-base font-semibold text-gray-700">Recent RFQs</h2>
                    <button onClick={() => setActiveTab('rfqs')} className="text-sm text-indigo-600 hover:underline font-medium">View all →</button>
                </div>
                <DataTable columns={rfqCols} rows={recentRfqs} emptyMessage="No RFQs in your divisions yet" onRowClick={r => setSelectedInquiry(r.enquiry_ref_no)} />
            </div>

            {/* ── RFQs tab ── */}
            <div className="flex flex-col flex-1 min-h-0" style={{ display: activeTab === 'rfqs' ? 'flex' : 'none' }}>
                <div className="flex items-center justify-between mb-4">
                    <div>
                        <h2 className="text-lg font-semibold text-gray-800">RFQs — My Divisions</h2>
                        <p className="text-sm text-gray-500">{filteredRfqs.length} inquiries</p>
                    </div>
                </div>

                {/* Filters */}
                <div className="flex flex-wrap gap-3 mb-4">
                    <input value={rfqFilters.inquiryId} onChange={e => setRfqFilters(f => ({...f, inquiryId: e.target.value}))}
                        placeholder="Search inquiry ID…"
                        className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 w-44" />
                    <select value={rfqFilters.client} onChange={e => setRfqFilters(f => ({...f, client: e.target.value}))}
                        className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400">
                        <option value="">All clients</option>
                        {rfqClients.map(c => <option key={c} value={c}>{c}</option>)}
                    </select>
                    <select value={rfqFilters.team} onChange={e => setRfqFilters(f => ({...f, team: e.target.value}))}
                        className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400">
                        <option value="">All divisions</option>
                        {rfqTeams.map(t => <option key={t} value={t}>{t}</option>)}
                    </select>
                    <input type="date" value={rfqFilters.date} onChange={e => setRfqFilters(f => ({...f, date: e.target.value}))}
                        className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400" />
                    {Object.values(rfqFilters).some(Boolean) && (
                        <button onClick={() => setRfqFilters(EMPTY_FILTERS)}
                            className="text-xs text-blue-500 hover:underline px-2">✕ Clear</button>
                    )}
                </div>

                {/* Sort */}
                <div className="flex items-center gap-2 mb-4">
                    <span className="text-sm text-gray-500 font-medium">Sort:</span>
                    {['newest','oldest'].map(s => (
                        <button key={s} onClick={() => setRfqSort(s)}
                            className={`px-3 py-1 rounded-full text-xs font-medium border transition
                                ${rfqSort === s ? 'bg-indigo-600 text-white border-indigo-600' : 'bg-white text-gray-600 border-gray-300 hover:border-indigo-400'}`}>
                            {s === 'newest' ? 'Newest first' : 'Oldest first'}
                        </button>
                    ))}
                </div>

                <DataTable columns={rfqCols} rows={filteredRfqs} emptyMessage="No RFQs found" onRowClick={r => setSelectedInquiry(r.enquiry_ref_no)} fillHeight />
            </div>

            {/* ── Vendors tab ── */}
            <div className="flex flex-col flex-1 min-h-0 -mx-8 -mb-8" style={{ display: activeTab === 'vendors' ? 'flex' : 'none' }}>
                <VendorDirectory />
            </div>

            {/* ── Bids Tracker tab ── */}
            <div className="flex flex-col flex-1 min-h-0 -mx-8 -mb-8" style={{ display: activeTab === 'zoho' ? 'flex' : 'none' }}>
                {activeTab === 'zoho' && <ZohoSync />}
            </div>

        </DashboardLayout>
        <InquiryModal inquiryId={selectedInquiry} onClose={closeModal} />
        </>
    );
};

export default ProcurementUserDashboard;
