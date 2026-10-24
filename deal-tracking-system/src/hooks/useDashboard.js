import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../context/AuthContext';
import { API } from '../config/api';

const REFRESH_INTERVAL_MS = 30_000; // poll every 30 s

export const useDashboard = () => {
    const { getBaseParams } = useAuth();
    const [rfqs, setRfqs] = useState([]);
    const [vendors, setVendors] = useState([]);
    const [stats, setStats] = useState({});
    const [divisions, setDivisions] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [lastRefresh, setLastRefresh] = useState(null);

    const fetchAll = useCallback((isInitial = false) => {
        const params = getBaseParams();
        if (isInitial) setLoading(true);

        Promise.all([
            fetch(`${API}/rfqs/?${params}`).then(r => r.json()),
            fetch(`${API}/rfqs/vendors?${params}`).then(r => r.json()),
            fetch(`${API}/rfqs/stats?${params}`).then(r => r.json()),
            fetch(`${API}/rfqs/my-divisions?${params}`).then(r => r.json()),
        ])
        .then(([rfqData, vendorData, statsData, divData]) => {
            setRfqs(rfqData.rfqs || []);
            setVendors(vendorData.vendors || []);
            setStats(statsData.stats || {});
            setDivisions(divData.divisions || []);
            setLastRefresh(new Date());
            setError(null);
            if (isInitial) setLoading(false);
        })
        .catch(() => {
            if (isInitial) {
                setError('Failed to load data. Is the backend running?');
                setLoading(false);
            }
        });
    }, [getBaseParams]);

    useEffect(() => {
        fetchAll(true);
        const timer = setInterval(() => fetchAll(false), REFRESH_INTERVAL_MS);
        const onSignal = () => fetchAll(false);
        window.addEventListener('dashboard:refresh', onSignal);
        return () => {
            clearInterval(timer);
            window.removeEventListener('dashboard:refresh', onSignal);
        };
    }, [fetchAll]);

    return { rfqs, vendors, stats, divisions, loading, error, lastRefresh, refresh: () => fetchAll(false) };
};
