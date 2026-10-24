import React, { createContext, useState, useContext } from 'react';

const AuthContext = createContext();

export const AuthProvider = ({ children }) => {
    const [user, setUser] = useState(() => {
        try {
            const saved = localStorage.getItem('deal_user');
            return saved ? JSON.parse(saved) : null;
        } catch {
            return null;
        }
    });

    const login = (userData) => {
        localStorage.setItem('deal_user', JSON.stringify(userData));
        setUser(userData);
    };

    const logout = () => {
        localStorage.removeItem('deal_user');
        setUser(null);
    };

    // Build query param string from user's division_ids
    // Chairman has empty array → no filter → sees all
    const getDivisionParams = () => {
        if (!user) return '';
        const ids = user.division_ids || [];
        return ids.length > 0 ? `&division_ids=${ids.join(',')}` : '';
    };

    const getBaseParams = () => {
        if (!user) return '';
        return `role=${user.role}${getDivisionParams()}`;
    };

    return (
        <AuthContext.Provider value={{ user, login, logout, getBaseParams }}>
            {children}
        </AuthContext.Provider>
    );
};

export const useAuth = () => useContext(AuthContext);