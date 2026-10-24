import React, { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { useAuth } from './context/AuthContext';
import Login from './pages/Login';

const ChairmanDashboard         = lazy(() => import('./pages/ChairmanDashboard'));
const GMDashboard               = lazy(() => import('./pages/GMDashboard'));
const ApoorvDashboard           = lazy(() => import('./pages/ApoorvDashboard'));
const ManagerDashboard          = lazy(() => import('./pages/ManagerDashboard'));
const SalespersonDashboard      = lazy(() => import('./pages/SalespersonDashboard'));
const ProcurementAgent          = lazy(() => import('./pages/ProcurementAgent'));
const ProcurementUserDashboard  = lazy(() => import('./pages/ProcurementUserDashboard'));
const SubhashProcurement        = lazy(() => import('./pages/SubhashProcurement'));

const DashboardRoute = () => {
    const { user } = useAuth();
    if (!user) return <Navigate to="/login" replace />;

    switch (user.role) {
        case 'chairman':
        case 'developer':   return <ChairmanDashboard />;
        case 'gm':
            if (user.username === 'apoorv_gm') return <ApoorvDashboard />;
            return <GMDashboard />;
        case 'manager':     return <ManagerDashboard />;
        case 'salesperson': return <SalespersonDashboard />;
        case 'procurement':
        case 'pq_cost':     return <ProcurementUserDashboard />;
        default:            return <Navigate to="/login" replace />;
    }
};

const PublicRoute = ({ children }) => {
    const { user } = useAuth();
    return user ? <Navigate to="/dashboard" replace /> : children;
};

const PageLoader = () => (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', background: '#f9fafb' }}>
        <div style={{ width: 32, height: 32, border: '3px solid #e5e7eb', borderTopColor: '#4f46e5', borderRadius: '50%', animation: 'spin 0.7s linear infinite' }} />
        <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
    </div>
);

function App() {
    return (
        <BrowserRouter>
            <Suspense fallback={<PageLoader />}>
                <Routes>
                    <Route path="/login"               element={<PublicRoute><Login /></PublicRoute>} />
                    <Route path="/dashboard"           element={<DashboardRoute />} />
                    <Route path="/procurement"         element={<ProcurementAgent />} />
                    <Route path="/procurement/subhash" element={<SubhashProcurement />} />
                    <Route path="*"                    element={<Navigate to="/login" replace />} />
                </Routes>
            </Suspense>
        </BrowserRouter>
    );
}

export default App;