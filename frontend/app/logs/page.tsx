"use client";
import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { Terminal } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export default function LogsPage() {
    const [logs, setLogs] = useState<string[]>([]);
    const bottomRef = useRef<HTMLDivElement>(null);

    const fetchLogs = async () => {
        try {
            const response = await axios.get(`${API_URL}/data`);
            setLogs(response.data.logs || []);
        } catch (err) {
            console.error(err);
        }
    };

    useEffect(() => {
        fetchLogs();
        const interval = setInterval(fetchLogs, 2000);
        return () => clearInterval(interval);
    }, []);

    useEffect(() => {
        bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [logs]);

    return (
        <div className="h-[calc(100vh-100px)] flex flex-col">
            <h1 className="text-3xl font-bold text-white flex items-center gap-3 mb-6">
                <Terminal className="text-green-400" /> System Logs
            </h1>

            <div className="flex-1 bg-black border border-gray-800 rounded-xl p-4 overflow-y-auto font-mono text-xs text-green-500 shadow-inner">
                {logs.length === 0 ? (
                    <div className="text-gray-600 italic">Waiting for logs...</div>
                ) : (
                    logs.map((log, i) => (
                        <div key={i} className="mb-1 break-words">
                            <span className="opacity-50 mr-2">[{i}]</span>
                            {log}
                        </div>
                    ))
                )}
                <div ref={bottomRef} />
            </div>
        </div>
    );
}
