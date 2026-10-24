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

const GM_DIVISIONS = {
    vinay_gm:  { range: 'Divisions 6–11',  color: 'blue' },
    madhav_gm: { range: 'Divisions 12–13', color: 'purple' },
    apoorv_gm: { range: 'Divisions 14–17', color: 'green' },
};

const BASE_COLS = [
    { key: 'enquiry_ref_no', label: 'Inquiry ID',  render: v => <span className="font-mono font-medium text-blue-600">{v || '—'}</span> },
    { key: 'client',         label: 'Client',       render: v => v || '—' },
    { key: 'description',    label: 'Description',  render: v => v ? <span className="text-gray-600 text-xs" title={v}>{v.length > 60 ? v.slice(0,60)+'…' : v}</span> : '—' },
    { key: 'division_name',  label: 'Team' },
    { key: 'total_items',    label: 'Items',        render: v => <span className="bg-blue-50 text-blue-700 px-2 py-0.5 rounded text-xs font-medium">{v ?? 0}</span> },
    { key: 'created_at',     label: 'Date',         render: v => v ? new Date(v).toLocaleDateString() : '—' },
];
const makeRfqColumnsOverview = (onView) => [...BASE_COLS, {
    key: '_actions', label: 'Actions', render: (_, row) => (
        <div className="flex gap-1.5" onClick={e => e.stopPropagation()}>
            <button onClick={() => onView(row.enquiry_ref_no)} className="px-2 py-1 text-xs bg-blue-50 text-blue-600 hover:bg-blue-100 rounded font-medium transition-colors">Edit</button>
        </div>
    ),
}];
const makeRfqColumnsFull = (onView, onDelete) => [...BASE_COLS, {
    key: '_actions', label: 'Actions', render: (_, row) => (
        <div className="flex gap-1.5" onClick={e => e.stopPropagation()}>
            <button onClick={() => onView(row.enquiry_ref_no)} className="px-2 py-1 text-xs bg-blue-50 text-blue-600 hover:bg-blue-100 rounded font-medium transition-colors">Edit</button>
            <button onClick={() => onDelete(row.enquiry_ref_no, row.client)} className="px-2 py-1 text-xs bg-red-50 text-red-500 hover:bg-red-100 rounded font-medium transition-colors">Delete</button>
            {row.enquiry_ref_no && (
                <a href={`${API}/vendors/export/${row.enquiry_ref_no}?mode=combined`} target="_blank" rel="noreferrer"
                    className="px-2 py-1 text-xs bg-green-50 text-green-600 hover:bg-green-100 rounded font-medium transition-colors">
                    Download
                </a>
            )}
        </div>
    ),
}];


const SearchSortBar = ({ query, setQuery, sort, setSort, onSearch, placeholder }) => (
    <div className="mb-3">
        <div className="flex gap-2 mb-2">
            <input
                value={query}
                onChange={e => setQuery(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && onSearch()}
                placeholder={placeholder}
                className="flex-1 border border-gray-300 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
            <button
                onClick={onSearch}
                className="bg-indigo-600 hover:bg-indigo-700 text-white px-5 py-2.5 rounded-lg text-sm font-semibold transition">
                Search
            </button>
        </div>
        <div className="flex items-center gap-2">
            <span className="text-gray-500 font-medium text-sm">Sort:</span>
            {['newest','oldest','az','za'].map(s => (
                <button key={s} onClick={() => setSort(s)}
                    className={`px-3 py-1 rounded-full text-xs font-medium border transition
                        ${sort === s ? 'bg-indigo-600 text-white border-indigo-600' : 'bg-white text-gray-600 border-gray-300 hover:border-indigo-400'}`}>
                    {s === 'newest' ? 'Newest first' : s === 'oldest' ? 'Oldest first' : s === 'az' ? 'A → Z' : 'Z → A'}
                </button>
            ))}
        </div>
    </div>
);

const ColumnFilters = ({ filters, setFilters, clients, teams, onClear }) => {
    const hasActive = filters.inquiryId || filters.client || filters.description || filters.team || filters.date;
    return (
        <div className="bg-gray-50 border border-gray-200 rounded-xl px-4 py-3 mb-4">
            <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Column Filters</span>
                {hasActive && (
                    <button onClick={onClear} className="text-xs text-indigo-600 hover:underline font-medium">✕ Clear all</button>
                )}
            </div>
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-2">
                <div>
                    <label className="text-xs text-gray-400 mb-1 block">Inquiry ID</label>
                    <input value={filters.inquiryId} onChange={e => setFilters(f => ({...f, inquiryId: e.target.value}))}
                        placeholder="e.g. INQ-2026"
                        className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-indigo-400"/>
                </div>
                <div>
                    <label className="text-xs text-gray-400 mb-1 block">Client</label>
                    <select value={filters.client} onChange={e => setFilters(f => ({...f, client: e.target.value}))}
                        className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-xs bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400">
                        <option value="">All</option>
                        {clients.map(c => <option key={c} value={c}>{c}</option>)}
                    </select>
                </div>
                <div>
                    <label className="text-xs text-gray-400 mb-1 block">Description</label>
                    <input value={filters.description} onChange={e => setFilters(f => ({...f, description: e.target.value}))}
                        placeholder="Keyword..."
                        className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-indigo-400"/>
                </div>
                <div>
                    <label className="text-xs text-gray-400 mb-1 block">Team</label>
                    <select value={filters.team} onChange={e => setFilters(f => ({...f, team: e.target.value}))}
                        className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-xs bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400">
                        <option value="">All</option>
                        {teams.map(t => <option key={t} value={t}>{t}</option>)}
                    </select>
                </div>
                <div>
                    <label className="text-xs text-gray-400 mb-1 block">Date</label>
                    <input type="date" value={filters.date} onChange={e => setFilters(f => ({...f, date: e.target.value}))}
                        className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-indigo-400"/>
                </div>
            </div>
            {hasActive && (
                <div className="flex flex-wrap gap-1.5 mt-2">
                    {filters.inquiryId   && <span className="bg-indigo-100 text-indigo-700 text-xs px-2 py-0.5 rounded-full">ID: {filters.inquiryId}</span>}
                    {filters.client      && <span className="bg-indigo-100 text-indigo-700 text-xs px-2 py-0.5 rounded-full">Client: {filters.client}</span>}
                    {filters.description && <span className="bg-indigo-100 text-indigo-700 text-xs px-2 py-0.5 rounded-full">Desc: {filters.description}</span>}
                    {filters.team        && <span className="bg-indigo-100 text-indigo-700 text-xs px-2 py-0.5 rounded-full">Team: {filters.team}</span>}
                    {filters.date        && <span className="bg-indigo-100 text-indigo-700 text-xs px-2 py-0.5 rounded-full">Date: {filters.date}</span>}
                </div>
            )}
        </div>
    );
};

const EMPTY_FILTERS = { inquiryId: '', client: '', description: '', team: '', date: '' };

const applyRfqFilter = (rows, query, sort, filters = {}) => {
    const q = query.trim().toLowerCase();
    let result = q
        ? rows.filter(r =>
            (r.enquiry_ref_no||'').toLowerCase().includes(q) ||
            (r.client||'').toLowerCase().includes(q) ||
            (r.description||'').toLowerCase().includes(q) ||
            (r.division_name||'').toLowerCase().includes(q))
        : [...rows];
    if (filters.inquiryId)   result = result.filter(r => (r.enquiry_ref_no||'').toLowerCase().includes(filters.inquiryId.toLowerCase()));
    if (filters.client)      result = result.filter(r => (r.client||'') === filters.client);
    if (filters.description) result = result.filter(r => (r.description||'').toLowerCase().includes(filters.description.toLowerCase()));
    if (filters.team)        result = result.filter(r => (r.division_name||'') === filters.team);
    if (filters.date)        result = result.filter(r => r.created_at && r.created_at.slice(0,10) === filters.date);
    if (sort === 'newest') result.sort((a,b) => new Date(b.created_at||0) - new Date(a.created_at||0));
    else if (sort === 'oldest') result.sort((a,b) => new Date(a.created_at||0) - new Date(b.created_at||0));
    else if (sort === 'az') result.sort((a,b) => (a.enquiry_ref_no||'').localeCompare(b.enquiry_ref_no||''));
    else if (sort === 'za') result.sort((a,b) => (b.enquiry_ref_no||'').localeCompare(a.enquiry_ref_no||''));
    return result;
};


const GMDashboard = () => {
    const { user } = useAuth();
    const { rfqs, stats, divisions, loading, error, lastRefresh, refresh } = useDashboard();
    const location = useLocation();
    const [activeTab,       setActiveTab]       = useState('overview');

    useEffect(() => {
        if (location.state?.tab) setActiveTab(location.state.tab);
    }, [location.state?.tab]);
    const [selectedInquiry, setSelectedInquiry] = useState(null);

    const [rfqSort,    setRfqSort]    = useState('newest');
    const [rfqFilters, setRfqFilters] = useState(EMPTY_FILTERS);

    const rfqClients = useMemo(() => [...new Set(rfqs.map(r => r.client).filter(Boolean))].sort(), [rfqs]);
    const rfqTeams   = useMemo(() => [...new Set(rfqs.map(r => r.division_name).filter(Boolean))].sort(), [rfqs]);

    const filteredRfqs = useMemo(() => applyRfqFilter(rfqs, '', rfqSort, rfqFilters), [rfqs, rfqSort, rfqFilters]);
    const recentRfqs      = useMemo(() => rfqs.slice(0, 5),  [rfqs]);
    const closeModal      = useCallback(() => setSelectedInquiry(null), []);

    const handleDeleteRfq = useCallback(async (inquiryId, client) => {
        const msg = `Delete RFQ "${inquiryId}"${client ? ` (${client})` : ''}?\n\nThis cannot be undone.`;
        // eslint-disable-next-line no-restricted-globals
        if (!window.confirm(msg)) return;
        try {
            const res = await fetch(`${API}/rfqs/${encodeURIComponent(inquiryId)}`, { method: 'DELETE' });
            const data = await res.json();
            if (data.success) {
                refresh();
            } else {
                alert(`Delete failed: ${data.detail || data.message || 'Unknown error'}`);
            }
        } catch (err) {
            alert(`Delete failed: ${err.message}`);
        }
    }, [refresh]);

    const rfqColumnsOverview = useMemo(() => makeRfqColumnsOverview(setSelectedInquiry), []);
    const rfqColumnsFull     = useMemo(() => makeRfqColumnsFull(setSelectedInquiry, handleDeleteRfq), [handleDeleteRfq]);

    const gmInfo = GM_DIVISIONS[user?.username] || { range: 'Assigned Divisions', color: 'blue' };

    return (
        <>
        <DashboardLayout
            title="Dashboard"
            welcomeSubtitle={<>Welcome, <span className="font-medium">{user?.name}</span> — {gmInfo.range}</>}
            loading={loading}
            loadingMessage="Loading Dashboard..."
            error={error}
            lastRefresh={lastRefresh}
            refresh={refresh}
            divisions={divisions}
            activeTab={activeTab}
            setActiveTab={setActiveTab}
        >
            <div style={{ display: activeTab === 'overview' ? undefined : 'none' }}>
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
                    <StatCard label="My RFQs"     value={stats.total_rfqs}    icon="📋" color="blue" />
                    <StatCard label="Vendors"      value={stats.total_vendors} icon="🏢" color="purple" />
                    <StatCard label="Items"        value={stats.total_items}   icon="📦" color="orange" />
                </div>
                <BidsConversionPanel role="gm" divisionIds={user?.division_ids?.join(',') || ''} />
                {divisions.length > 0 && (
                    <>
                        <h2 className="text-lg font-semibold text-gray-700 mb-4">My Divisions</h2>
                        <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mb-8">
                            {divisions.map(div => (
                                <div key={div.id} className="bg-white rounded-xl border border-gray-200 p-4 hover:shadow-md transition-shadow">
                                    <div className="flex items-start justify-between">
                                        <p className="font-medium text-sm text-gray-800">{div.name}</p>
                                        <span className="bg-blue-50 text-blue-600 text-xs font-semibold px-2 py-1 rounded-full">{div.rfq_count}</span>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </>
                )}
                <div className="flex items-center justify-between mb-4">
                    <h2 className="text-lg font-semibold text-gray-700">Recent RFQs</h2>
                    <button onClick={() => setActiveTab('rfqs')} className="text-sm text-indigo-600 hover:underline font-medium">View all →</button>
                </div>
                <DataTable columns={rfqColumnsOverview} rows={recentRfqs} emptyMessage="No RFQs in your divisions" onRowClick={r => setSelectedInquiry(r.enquiry_ref_no)} />
            </div>

            <div className="flex flex-col flex-1 min-h-0" style={{ display: activeTab === 'rfqs' ? 'flex' : 'none' }}>
                <div className="flex items-center justify-between mb-5">
                    <div>
                        <h2 className="text-lg font-semibold text-gray-800">RFQs in My Divisions</h2>
                        <p className="text-sm text-gray-500">{filteredRfqs.length} inquiries</p>
                    </div>
                </div>
                <ColumnFilters filters={rfqFilters} setFilters={setRfqFilters} clients={rfqClients} teams={rfqTeams} onClear={() => setRfqFilters(EMPTY_FILTERS)} />
                <div className="flex items-center gap-2 mb-4">
                    <span className="text-gray-500 font-medium text-sm">Sort:</span>
                    {['newest','oldest','az','za'].map(s => (
                        <button key={s} onClick={() => setRfqSort(s)}
                            className={`px-3 py-1 rounded-full text-xs font-medium border transition
                                ${rfqSort === s ? 'bg-indigo-600 text-white border-indigo-600' : 'bg-white text-gray-600 border-gray-300 hover:border-indigo-400'}`}>
                            {s === 'newest' ? 'Newest first' : s === 'oldest' ? 'Oldest first' : s === 'az' ? 'A → Z' : 'Z → A'}
                        </button>
                    ))}
                </div>
                <DataTable columns={rfqColumnsFull} rows={filteredRfqs} emptyMessage="No RFQs found" onRowClick={r => setSelectedInquiry(r.enquiry_ref_no)} fillHeight />
            </div>

            <div className="flex flex-col flex-1 min-h-0 -mx-8 -mb-8" style={{ display: activeTab === 'vendors' ? 'flex' : 'none' }}>
                <VendorDirectory />
            </div>

            <div className="flex flex-col flex-1 min-h-0 -mx-8 -mb-8" style={{ display: activeTab === 'zoho' ? 'flex' : 'none' }}>
                {activeTab === 'zoho' && <ZohoSync />}
            </div>

        </DashboardLayout>
        <InquiryModal inquiryId={selectedInquiry} onClose={closeModal} />
        </>
    );
};

export default GMDashboard;
