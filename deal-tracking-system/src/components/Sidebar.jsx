import React from 'react';
import { useAuth } from '../context/AuthContext';
import { useNavigate, useLocation } from 'react-router-dom';

const roleColors = {
    chairman:    { bg: 'bg-amber-500',   text: 'text-amber-950' },
    gm:          { bg: 'bg-blue-500',    text: 'text-white' },
    manager:     { bg: 'bg-emerald-500', text: 'text-white' },
    developer:   { bg: 'bg-violet-600',  text: 'text-white' },
    procurement: { bg: 'bg-sky-500',     text: 'text-white' },
    pq_cost:     { bg: 'bg-teal-500',    text: 'text-white' },
};
const roleLabels = {
    chairman:    'Chairman',
    gm:          'General Manager',
    manager:     'Manager',
    developer:   'Developer',
    procurement: 'Procurement',
    pq_cost:     'PQ & Cost Estimation',
};

const ICONS = {
    overview:    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg>,
    rfqs:        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>,
    vendors:     <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><path strokeLinecap="round" strokeLinejoin="round" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"/></svg>,
    procurement: <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-4.35-4.35M17 11A6 6 0 115 11a6 6 0 0112 0z"/></svg>,
    analytics:   <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><path strokeLinecap="round" strokeLinejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/></svg>,
    import:      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/></svg>,
    history:     <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>,
    zoho:        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>,
    users:       <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><path strokeLinecap="round" strokeLinejoin="round" d="M17 20h5v-2a4 4 0 00-5-3.87M9 20H4v-2a4 4 0 015-3.87m6-4.13a4 4 0 11-8 0 4 4 0 018 0zm6 0a3 3 0 11-6 0 3 3 0 016 0z"/></svg>,
    pipeline:    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>,
};

const PROC_TABS = new Set(['history', 'vendors', 'analytics', 'import']);

const TABS_MAIN = [
    { id: 'overview', label: 'Overview' },
    { id: 'rfqs',     label: 'RFQs' },
    { id: 'vendors',  label: 'Vendors' },
];

const TABS_TOOLS = [
    { id: 'procurement', label: 'Find New Suppliers' },
    { id: 'zoho',        label: 'Bids Tracker' },
    { id: 'analytics',   label: 'Analytics' },
    { id: 'pipeline',    label: 'Pipeline Insights' },
    { id: 'import',      label: 'Import' },
    { id: 'history',     label: 'History' },
];

// Procurement users see a trimmed set — only what's relevant to their work
const TABS_MAIN_PROCUREMENT = [
    { id: 'overview', label: 'Overview' },
    { id: 'rfqs',     label: 'RFQs' },
];

const TABS_TOOLS_PROCUREMENT = [
    { id: 'procurement', label: 'Find New Suppliers' },
    { id: 'zoho',        label: 'Bids Tracker' },
    { id: 'import',      label: 'Import' },
    { id: 'history',     label: 'History' },
];

const Sidebar = ({ activeTab, setActiveTab, divisions = [] }) => {
    const { user, logout } = useAuth();
    const navigate = useNavigate();
    const location = useLocation();

    const procTab = new URLSearchParams(location.search).get('tab');
    const effectiveTab = location.pathname.startsWith('/procurement')
        ? (PROC_TABS.has(procTab) ? procTab : 'procurement')
        : activeTab;

    const handleTabClick = (id) => {
        if (id === 'procurement') {
            navigate(user?.username === 'subhash_mgr' ? '/procurement/subhash' : '/procurement');
        } else if (PROC_TABS.has(id)) {
            navigate(`/procurement?tab=${id}`);
        } else {
            if (location.pathname.startsWith('/procurement')) {
                navigate('/dashboard', { state: { tab: id } });
            } else {
                setActiveTab(id);
            }
        }
    };

    const rc = roleColors[user?.role] || { bg: 'bg-gray-600', text: 'text-white' };
    const initials = (user?.name || user?.username || '?').split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase();

    const NavBtn = ({ id, label }) => {
        const active = effectiveTab === id;
        return (
            <button
                onClick={() => handleTabClick(id)}
                className={`w-full text-left px-3 py-2.5 rounded-xl mb-0.5 text-sm flex items-center gap-3 transition-all duration-100 group
                    ${active
                        ? 'bg-indigo-600 text-white font-semibold shadow-md shadow-indigo-900/40'
                        : 'text-gray-400 hover:text-white hover:bg-white/5'
                    }`}
            >
                <span className={`flex-shrink-0 transition-colors ${active ? 'text-white' : 'text-gray-500 group-hover:text-gray-300'}`}>
                    {ICONS[id]}
                </span>
                <span className="flex-1 truncate">{label}</span>
                {active && (
                    <span className="flex-shrink-0 w-1.5 h-1.5 rounded-full bg-white/70" />
                )}
            </button>
        );
    };

    return (
        <div className="w-60 h-full bg-[#0f1117] text-white flex flex-col flex-shrink-0 border-r border-white/5">

            {/* Logo */}
            <div className="px-4 py-4 border-b border-white/5 flex-shrink-0">
                <div className="flex items-center gap-3">
                    <div className="bg-white rounded-xl p-1.5 flex-shrink-0 shadow-lg">
                        <img src="/bb-logo.png" alt="Bhatia Brothers" className="h-7 w-7 object-contain" />
                    </div>
                    <div>
                        <h1 className="text-sm font-bold text-white leading-tight tracking-tight">Bhatia Brothers</h1>
                        <p className="text-[11px] text-gray-500 mt-0.5 font-medium">Bids Agent</p>
                    </div>
                </div>
            </div>

            {/* User chip */}
            <div className="px-4 py-3 border-b border-white/5 flex-shrink-0">
                <div className="flex items-center gap-3 bg-white/5 rounded-xl px-3 py-2.5">
                    <div className={`w-8 h-8 rounded-lg ${rc.bg} flex items-center justify-center flex-shrink-0 shadow-sm`}>
                        <span className={`text-xs font-bold ${rc.text}`}>{initials}</span>
                    </div>
                    <div className="min-w-0 flex-1">
                        <p className="text-sm font-semibold text-white truncate leading-tight">{user?.name}</p>
                        <p className="text-[11px] text-gray-500 truncate mt-0.5">{roleLabels[user?.role] || user?.role}</p>
                    </div>
                </div>
            </div>

            {/* Nav */}
            <nav className="flex-1 overflow-y-auto px-3 py-4 flex flex-col gap-5">
                <div>
                    <p className="text-[10px] text-gray-600 uppercase tracking-[0.12em] font-bold mb-2 px-2">Main</p>
                    {(['procurement', 'pq_cost'].includes(user?.role)
                        ? TABS_MAIN_PROCUREMENT
                        : TABS_MAIN
                    ).map(t => <NavBtn key={t.id} {...t} />)}
                </div>

                <div className="border-t border-white/5 pt-1">
                    <p className="text-[10px] text-gray-600 uppercase tracking-[0.12em] font-bold mb-2 px-2 mt-1">Tools</p>
                    {(['procurement', 'pq_cost'].includes(user?.role)
                        ? TABS_TOOLS_PROCUREMENT
                        : TABS_TOOLS
                    ).map(t => <NavBtn key={t.id} {...t} />)}
                </div>

                {(user?.role === 'chairman' || user?.role === 'developer') && (
                    <div className="border-t border-white/5 pt-1">
                        <p className="text-[10px] text-gray-600 uppercase tracking-[0.12em] font-bold mb-2 px-2 mt-1">Admin</p>
                        <NavBtn id="users" label="Manage Users" />
                    </div>
                )}
            </nav>

            {/* Sign Out */}
            <div className="px-3 pb-4 pt-2 border-t border-white/5 flex-shrink-0">
                <button
                    onClick={() => { logout(); navigate('/login'); }}
                    className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm text-gray-500 hover:text-red-400 hover:bg-red-500/10 transition-all duration-100 group"
                >
                    <svg className="w-4 h-4 group-hover:text-red-400 transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"/>
                    </svg>
                    Sign Out
                </button>
            </div>
        </div>
    );
};

export default Sidebar;
