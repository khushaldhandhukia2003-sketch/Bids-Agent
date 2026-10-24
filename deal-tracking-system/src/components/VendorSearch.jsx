import React, { useState, useRef } from 'react';
import { useAuth } from '../context/AuthContext';
import { API } from '../config/api';

const SourceBadge = ({ source }) => {
    const colors = {
        'yellowpages.ae':   'bg-yellow-100 text-yellow-700',
        'dubizzle.com':     'bg-blue-100 text-blue-700',
        'tradearabia.com':  'bg-green-100 text-green-700',
        'gulf-directory.com': 'bg-purple-100 text-purple-700',
        'google.ae':        'bg-red-100 text-red-700',
    };
    return (
        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${colors[source] || 'bg-gray-100 text-gray-600'}`}>
            {source}
        </span>
    );
};

const ScoreBar = ({ score }) => {
    const color = score >= 7 ? 'bg-green-500' : score >= 4 ? 'bg-yellow-500' : 'bg-red-400';
    return (
        <div className="flex items-center gap-2">
            <div className="w-20 bg-gray-200 rounded-full h-1.5">
                <div className={`h-1.5 rounded-full ${color}`} style={{ width: `${score * 10}%` }} />
            </div>
            <span className="text-xs text-gray-500">{score}/10</span>
        </div>
    );
};

const VendorSearch = () => {
    const { user } = useAuth();
    const fileRef  = useRef();

    // Manual trigger state
    const [manualQuery, setManualQuery] = useState('');

    // Auto trigger state
    const [file, setFile]         = useState(null);
    const [dragOver, setDragOver] = useState(false);

    // Results state
    const [results, setResults]   = useState(null);
    const [loading, setLoading]   = useState(false);
    const [error, setError]       = useState('');
    const [activeTab, setActiveTab] = useState('manual');

    // ── Manual Search ────────────────────────────────────────
    const handleManualSearch = async (e) => {
        e.preventDefault();
        if (!manualQuery.trim()) return;
        setLoading(true);
        setError('');
        setResults(null);

        try {
            const res = await fetch(`${API}/vendor-search/manual`, {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({
                    product_query:    manualQuery,
                    salesperson_name: user?.salesperson_name,
                    division_id:      user?.division_id,
                }),
            });
            const data = await res.json();
            if (data.success) setResults(data);
            else setError(data.detail || 'Search failed');
        } catch {
            setError('Cannot connect to backend. Is FastAPI running?');
        } finally {
            setLoading(false);
        }
    };

    // ── Auto from Document ───────────────────────────────────
    const handleFileUpload = async () => {
        if (!file) return;
        setLoading(true);
        setError('');
        setResults(null);

        const formData = new FormData();
        formData.append('file',             file);
        formData.append('salesperson_name', user?.salesperson_name || '');
        formData.append('division_id',      user?.division_id || '');

        try {
            const res = await fetch(`${API}/vendor-search/from-rfq`, {
                method: 'POST',
                body:   formData,
            });
            const data = await res.json();
            if (data.success) setResults(data);
            else setError(data.detail || 'Upload failed');
        } catch {
            setError('Cannot connect to backend. Is FastAPI running?');
        } finally {
            setLoading(false);
        }
    };

    const handleDrop = (e) => {
        e.preventDefault();
        setDragOver(false);
        const dropped = e.dataTransfer.files[0];
        if (dropped) setFile(dropped);
    };

    return (
        <div className="p-6">
            <div className="max-w-5xl mx-auto">
                {/* Header */}
                <div className="mb-6">
                    <h2 className="text-2xl font-bold text-gray-800">🔍 UAE Vendor Search</h2>
                    <p className="text-gray-500 text-sm mt-1">
                        Search across yellowpages.ae · dubizzle · tradearabia · gulf-directory · google.ae
                    </p>
                </div>

                {/* Tabs */}
                <div className="flex gap-2 mb-6">
                    <button onClick={() => setActiveTab('manual')}
                        className={`px-5 py-2.5 rounded-lg text-sm font-medium transition
                            ${activeTab === 'manual' ? 'bg-blue-600 text-white' : 'bg-white text-gray-600 border hover:bg-gray-50'}`}>
                        ✏️ Manual Search
                    </button>
                    <button onClick={() => setActiveTab('upload')}
                        className={`px-5 py-2.5 rounded-lg text-sm font-medium transition
                            ${activeTab === 'upload' ? 'bg-blue-600 text-white' : 'bg-white text-gray-600 border hover:bg-gray-50'}`}>
                        📄 Upload RFQ Document
                    </button>
                </div>

                {/* Manual Search */}
                {activeTab === 'manual' && (
                    <div className="bg-white rounded-xl border border-gray-200 p-6 mb-6">
                        <h3 className="font-semibold text-gray-700 mb-4">Search by Product Name</h3>
                        <form onSubmit={handleManualSearch} className="flex gap-3">
                            <input
                                type="text"
                                value={manualQuery}
                                onChange={e => setManualQuery(e.target.value)}
                                placeholder="e.g. ADNOC filters RC9, Battery E34, Signal Board..."
                                className="flex-1 border border-gray-300 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                            />
                            <button type="submit" disabled={loading || !manualQuery.trim()}
                                className="bg-blue-600 text-white px-6 py-2.5 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition whitespace-nowrap">
                                {loading ? '🔍 Searching...' : '🔍 Search UAE Vendors'}
                            </button>
                        </form>
                        <p className="text-xs text-gray-400 mt-2">
                            💡 Tip: Use specific product names for better results (e.g. "Retro-jet pipe cleaning nozzle")
                        </p>
                    </div>
                )}

                {/* Upload Document */}
                {activeTab === 'upload' && (
                    <div className="bg-white rounded-xl border border-gray-200 p-6 mb-6">
                        <h3 className="font-semibold text-gray-700 mb-4">Upload RFQ Document</h3>
                        <p className="text-sm text-gray-500 mb-4">
                            Claude AI will read the document, extract the product details automatically, then search UAE vendors.
                        </p>

                        {/* Drop Zone */}
                        <div
                            onDragOver={e => { e.preventDefault(); setDragOver(true); }}
                            onDragLeave={() => setDragOver(false)}
                            onDrop={handleDrop}
                            onClick={() => fileRef.current?.click()}
                            className={`border-2 border-dashed rounded-xl p-10 text-center cursor-pointer transition
                                ${dragOver ? 'border-blue-500 bg-blue-50' : 'border-gray-300 hover:border-blue-400 hover:bg-gray-50'}`}
                        >
                            <div className="text-4xl mb-3">📄</div>
                            {file ? (
                                <div>
                                    <p className="font-medium text-blue-600">{file.name}</p>
                                    <p className="text-xs text-gray-400 mt-1">{(file.size / 1024).toFixed(1)} KB</p>
                                </div>
                            ) : (
                                <div>
                                    <p className="text-gray-600 font-medium">Drag & drop or click to upload</p>
                                    <p className="text-xs text-gray-400 mt-1">PDF, DOCX, DOC, TXT supported</p>
                                </div>
                            )}
                            <input ref={fileRef} type="file" accept=".pdf,.docx,.doc,.txt"
                                className="hidden" onChange={e => setFile(e.target.files[0])} />
                        </div>

                        {file && (
                            <button onClick={handleFileUpload} disabled={loading}
                                className="mt-4 w-full bg-blue-600 text-white py-3 rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50 transition">
                                {loading ? '🤖 Claude is reading document & searching...' : '🤖 Extract & Search UAE Vendors'}
                            </button>
                        )}
                    </div>
                )}

                {/* Error */}
                {error && (
                    <div className="bg-red-50 border border-red-200 text-red-600 px-4 py-3 rounded-lg mb-6 text-sm">
                        ⚠️ {error}
                    </div>
                )}

                {/* Loading */}
                {loading && (
                    <div className="bg-blue-50 border border-blue-200 rounded-xl p-6 mb-6 text-center">
                        <div className="w-10 h-10 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-3"></div>
                        <p className="text-blue-700 font-medium">Searching UAE vendor databases...</p>
                        <p className="text-blue-500 text-sm mt-1">Checking yellowpages · dubizzle · tradearabia · gulf-directory · google</p>
                    </div>
                )}

                {/* Results */}
                {results && !loading && (
                    <div>
                        {/* Product Info (auto trigger) */}
                        {results.product_info?.product_name && (
                            <div className="bg-green-50 border border-green-200 rounded-xl p-4 mb-5">
                                <p className="text-sm font-semibold text-green-700 mb-2">🤖 Claude Extracted:</p>
                                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                                    {[
                                        { label: 'Product',  val: results.product_info.product_name },
                                        { label: 'Brand',    val: results.product_info.brand },
                                        { label: 'Quantity', val: results.product_info.quantity },
                                        { label: 'Specs',    val: results.product_info.specs },
                                    ].map(item => item.val && (
                                        <div key={item.label}>
                                            <p className="text-xs text-green-500 uppercase">{item.label}</p>
                                            <p className="font-medium text-green-800">{item.val}</p>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}

                        {/* Summary */}
                        <div className="flex items-center justify-between mb-4">
                            <h3 className="text-lg font-semibold text-gray-700">
                                Found {results.total_found} UAE Vendors
                                {results.saved_to_db > 0 && (
                                    <span className="ml-2 text-sm text-green-600 font-normal">
                                        ✅ {results.saved_to_db} saved to database
                                    </span>
                                )}
                            </h3>
                            <div className="flex gap-2 flex-wrap">
                                {results.sources_used?.map(s => <SourceBadge key={s} source={s} />)}
                            </div>
                        </div>

                        {/* Vendor Cards */}
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            {results.vendors?.map((vendor, i) => (
                                <div key={i} className="bg-white rounded-xl border border-gray-200 p-5 hover:shadow-md transition">
                                    <div className="flex items-start justify-between mb-3">
                                        <div className="flex-1">
                                            <div className="flex items-center gap-2 mb-1">
                                                <h4 className="font-semibold text-gray-800">{vendor.name}</h4>
                                                {vendor.verified && (
                                                    <span className="text-xs bg-green-100 text-green-600 px-1.5 py-0.5 rounded">✓ Verified</span>
                                                )}
                                            </div>
                                            <SourceBadge source={vendor.source} />
                                        </div>
                                        {vendor.relevance_score && (
                                            <ScoreBar score={vendor.relevance_score} />
                                        )}
                                    </div>

                                    <div className="space-y-1.5 text-sm">
                                        {vendor.phone && (
                                            <p className="flex items-center gap-2 text-gray-600">
                                                <span>📞</span>
                                                <a href={`tel:${vendor.phone}`} className="hover:text-blue-600">{vendor.phone}</a>
                                            </p>
                                        )}
                                        {vendor.email && (
                                            <p className="flex items-center gap-2 text-gray-600">
                                                <span>✉️</span>
                                                <a href={`mailto:${vendor.email}`} className="hover:text-blue-600">{vendor.email}</a>
                                            </p>
                                        )}
                                        {vendor.address && (
                                            <p className="flex items-center gap-2 text-gray-600">
                                                <span>📍</span>{vendor.address}
                                            </p>
                                        )}
                                        {vendor.website && (
                                            <p className="flex items-center gap-2">
                                                <span>🌐</span>
                                                <a href={vendor.website} target="_blank" rel="noopener noreferrer"
                                                    className="text-blue-500 hover:underline truncate">
                                                    {vendor.website}
                                                </a>
                                            </p>
                                        )}
                                        {vendor.categories && (
                                            <p className="text-xs text-gray-400 mt-2 italic">{vendor.categories}</p>
                                        )}
                                        {vendor.notes && (
                                            <p className="text-xs text-blue-600 mt-2 bg-blue-50 px-2 py-1 rounded">
                                                🤖 {vendor.notes}
                                            </p>
                                        )}
                                    </div>
                                </div>
                            ))}
                        </div>

                        {!results.vendors?.length && (
                            <div className="text-center py-12 text-gray-400">
                                <p className="text-4xl mb-3">🔍</p>
                                <p className="font-medium text-gray-500">No vendors found</p>
                                <p className="text-sm mt-1">Try a more specific product name or a different search term.</p>
                            </div>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
};

export default VendorSearch;