import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import Sidebar from './Sidebar';
import { LoadingScreen } from './UI';

/**
 * Shared chrome for GM, Manager, and Chairman dashboards.
 * Handles loading/error states, the outer flex shell, sidebar, and header.
 * Each dashboard renders its own tab content as children.
 */
const DashboardLayout = ({
    title,
    welcomeSubtitle,
    loading,
    loadingMessage = 'Loading Dashboard...',
    error,
    lastRefresh,
    refresh,
    divisions,
    activeTab,
    setActiveTab,
    children,
}) => {
    const { logout } = useAuth();
    const navigate = useNavigate();

    if (loading) return <LoadingScreen message={loadingMessage} />;

    if (error) return (
        <div className="min-h-screen flex items-center justify-center bg-gray-50">
            <div className="text-center text-red-500">
                <p className="text-xl mb-2">⚠️</p>
                <p>{error}</p>
            </div>
        </div>
    );

    return (
        <div className="flex h-screen bg-gray-50">
            <Sidebar activeTab={activeTab} setActiveTab={setActiveTab} divisions={divisions} />

            <div className="flex-1 min-h-0 overflow-auto flex flex-col">
                {/* Header — only shown on Overview tab */}
                {activeTab === 'overview' && (
                    <div className="bg-white border-b px-8 py-5 flex-shrink-0">
                        <div className="flex items-center justify-between">
                            <div>
                                <h1 className="text-2xl font-bold text-gray-800">{title}</h1>
                                <p className="text-sm text-gray-500 mt-0.5">{welcomeSubtitle}</p>
                            </div>
                        </div>
                    </div>
                )}

                <div className="p-8 flex-1 min-h-0 flex flex-col">
                    {children}
                </div>
            </div>
        </div>
    );
};

export default DashboardLayout;
