/**
 * UserActionLog.js
 * ================
 * Component for viewing user's screening action history
 * 
 * Features:
 *   - View all screening decisions made by the user
 *   - Filter by project
 *   - View blockchain transaction details
 *   - Export action log
 * 
 * Author: PaSSER-SR Team
 * Date: January 2026
 */

import React, { useState, useEffect } from 'react';
import { Card } from 'primereact/card';
import { DataTable } from 'primereact/datatable';
import { Column } from 'primereact/column';
import { Button } from 'primereact/button';
import { Dropdown } from 'primereact/dropdown';
import { Tag } from 'primereact/tag';
import { Panel } from 'primereact/panel';
import { Dialog } from 'primereact/dialog';
import { Divider } from 'primereact/divider';

import configuration from './configuration.json';
import './AdminDashboard.css';

const API_BASE_URL = configuration.passer.ScreeningAPI + '/api' || 'http://localhost:9901/api';

const UserActionLog = ({ currentUser, selectedProject, toast }) => {
    const [actions, setActions] = useState([]);
    const [loading, setLoading] = useState(false);
    const [filterProject, setFilterProject] = useState(selectedProject?.project_id || null);
    const [projects, setProjects] = useState([]);
    
    // Transaction dialog state
    const [txDialogVisible, setTxDialogVisible] = useState(false);
    const [txData, setTxData] = useState(null);
    const [txLoading, setTxLoading] = useState(false);

    useEffect(() => {
        loadProjects();
    }, []);

    useEffect(() => {
        if (currentUser) {
            loadActions();
        }
    }, [currentUser, filterProject]);

    const apiRequest = async (endpoint, options = {}) => {
        const url = new URL(`${API_BASE_URL}${endpoint}`);
        url.searchParams.append('antelope_account', currentUser);

        const response = await fetch(url.toString(), {
            ...options,
            headers: { 'Content-Type': 'application/json', ...options.headers },
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: 'Request failed' }));
            throw new Error(error.detail || 'Request failed');
        }
        return response.json();
    };

    const loadProjects = async () => {
        try {
            const data = await apiRequest('/projects');
            setProjects([
                { label: 'All Projects', value: null },
                ...data.projects.map(p => ({ label: p.name, value: p.project_id }))
            ]);
        } catch (error) {
            console.error('Failed to load projects:', error);
        }
    };

    const loadActions = async () => {
        setLoading(true);
        try {
            const projectParam = filterProject ? `&project_id=${filterProject}` : '';
            const data = await apiRequest(`/users/${currentUser}/actions?limit=200${projectParam}`);
            setActions(data.actions || []);
        } catch (error) {
            toast.current?.show({ severity: 'error', summary: 'Error', detail: error.message, life: 3000 });
        } finally {
            setLoading(false);
        }
    };

    const exportActions = () => {
        const dataStr = JSON.stringify(actions, null, 2);
        const dataUri = 'data:application/json;charset=utf-8,' + encodeURIComponent(dataStr);
        const exportFileDefaultName = `actions_${currentUser}_${new Date().toISOString().split('T')[0]}.json`;
        
        const linkElement = document.createElement('a');
        linkElement.setAttribute('href', dataUri);
        linkElement.setAttribute('download', exportFileDefaultName);
        linkElement.click();
    };

    const viewTransaction = async (txId) => {
        if (!txId) return;
        
        setTxLoading(true);
        setTxDialogVisible(true);
        
        try {
            const mementoUrl = configuration.passer.MementoAPI || 'http://localhost:9909/wax/get_transaction';
            const response = await fetch(`${mementoUrl}?trx_id=${txId}`);
            const data = await response.json();
            setTxData(data);
        } catch (error) {
            toast.current?.show({ severity: 'error', summary: 'Error', detail: 'Failed to load transaction' });
            setTxDialogVisible(false);
        } finally {
            setTxLoading(false);
        }
    };

    const formatDateTime = (dateStr) => {
        if (!dateStr) return 'N/A';
        // Ensure UTC timestamps are treated as UTC (add 'Z' if missing)
        let dateString = dateStr;
        if (typeof dateString === 'string' && !dateString.includes('Z') && !dateString.includes('+') && !dateString.includes('-', 10)) {
            dateString = dateString.replace(' ', 'T') + 'Z';
        }
        const date = new Date(dateString);
        return date.toLocaleString('en-GB', {
            day: '2-digit',
            month: 'short',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    };

    const typeBodyTemplate = (action) => {
        const typeMap = {
            'screening_decision': { label: 'Manual Screening', severity: 'info', icon: 'pi-user' },
            'llm_screening': { label: 'LLM Screening', severity: 'primary', icon: 'pi-bolt' },
            'resolution': { label: 'Resolution', severity: 'success', icon: 'pi-check-circle' }
        };
        const config = typeMap[action.type] || { label: action.type, severity: 'secondary', icon: 'pi-circle' };
        return (
            <Tag value={config.label} severity={config.severity} icon={`pi ${config.icon}`} />
        );
    };

    const decisionBodyTemplate = (action) => {
        if (!action.decision) return '-';
        const severity = action.decision === 'INCLUDE' ? 'success' : 
                        action.decision === 'EXCLUDE' ? 'danger' : 'warning';
        return <Tag value={action.decision} severity={severity} />;
    };

    const blockchainBodyTemplate = (action) => {
        if (!action.blockchain_tx) return '-';
        return (
            <Button
                label={action.blockchain_tx.substring(0, 12) + '...'}
                className="p-button-link p-button-sm"
                style={{ fontSize: '0.75rem', color: '#6366f1', padding: '0' }}
                onClick={() => viewTransaction(action.blockchain_tx)}
                tooltip="View transaction details"
            />
        );
    };

    return (
        <div className="user-action-log">
            <Card>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                    <div>
                        <h3>My Action Log</h3>
                        <p style={{ color: '#666', marginTop: '0.25rem' }}>
                            Total actions: {actions.length}
                        </p>
                    </div>
                    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                        <Dropdown 
                            value={filterProject}
                            options={projects}
                            onChange={(e) => setFilterProject(e.value)}
                            placeholder="Filter by project"
                            style={{ minWidth: '200px' }}
                        />
                        <Button 
                            label="Refresh" 
                            icon="pi pi-refresh" 
                            onClick={loadActions}
                            loading={loading}
                            className="p-button-outlined"
                        />
                        <Button 
                            label="Export JSON" 
                            icon="pi pi-download" 
                            onClick={exportActions}
                            className="p-button-outlined p-button-success"
                            disabled={actions.length === 0}
                        />
                    </div>
                </div>

                <DataTable 
                    value={actions}
                    loading={loading}
                    paginator
                    rows={20}
                    emptyMessage="No actions found"
                    className="action-log-table"
                    sortField="timestamp"
                    sortOrder={-1}
                >
                    <Column 
                        field="timestamp" 
                        header="Timestamp" 
                        body={(row) => formatDateTime(row.timestamp)}
                        sortable
                        style={{ width: '180px' }}
                    />
                    <Column 
                        field="type" 
                        header="Type" 
                        body={typeBodyTemplate}
                        style={{ width: '150px' }}
                    />
                    <Column 
                        field="project_id" 
                        header="Project" 
                        sortable
                        style={{ width: '150px' }}
                    />
                    <Column 
                        field="gs_id" 
                        header="Paper ID" 
                        style={{ width: '120px' }}
                    />
                    <Column 
                        field="decision" 
                        header="Decision" 
                        body={decisionBodyTemplate}
                        style={{ width: '120px' }}
                    />
                    <Column 
                        field="confidence" 
                        header="Confidence" 
                        style={{ width: '120px' }}
                    />
                    <Column 
                        field="blockchain_tx" 
                        header="Blockchain TX" 
                        body={blockchainBodyTemplate}
                        style={{ width: '150px' }}
                    />
                </DataTable>
            </Card>

            {/* Blockchain Transaction Dialog */}
            <Dialog 
                header="Blockchain Transaction Details"
                visible={txDialogVisible}
                className="tx-dialog"
                style={{ width: '800px' }}
                onHide={() => { setTxDialogVisible(false); setTxData(null); }}
            >
                {txLoading ? (
                    <div className="tx-loading">
                        <i className="pi pi-spin pi-spinner" style={{ fontSize: '2rem' }}></i>
                        <p>Loading transaction data...</p>
                    </div>
                ) : txData && (
                    <div className="tx-details">
                        {/* Transaction Status */}
                        <div className="tx-status-section">
                            <Tag 
                                severity={txData.irreversible ? 'success' : 'warning'} 
                                value={txData.irreversible ? '✓ Irreversible' : '○ Pending'}
                                style={{ fontSize: '1rem', padding: '0.5rem 1rem' }}
                            />
                            <Tag 
                                severity="info" 
                                value={txData.data?.trace?.status === 'executed' ? '✔ Executed' : txData.data?.trace?.status}
                                style={{ fontSize: '1rem', padding: '0.5rem 1rem', marginLeft: '0.5rem' }}
                            />
                        </div>

                        <Divider />

                        {/* Transaction Information */}
                        <Panel header="Transaction Information" className="tx-panel">
                            <div className="tx-info-grid">
                                <div className="tx-info-item">
                                    <strong>Transaction ID:</strong>
                                    <code className="tx-id">{txData.data?.trace?.id}</code>
                                </div>
                                <div className="tx-info-item">
                                    <strong>Block Number:</strong>
                                    <span>{txData.data?.block_num}</span>
                                </div>
                                <div className="tx-info-item">
                                    <strong>Block Timestamp:</strong>
                                    <span>{formatDateTime(txData.data?.block_timestamp)}</span>
                                </div>
                                <div className="tx-info-item">
                                    <strong>CPU Usage:</strong>
                                    <span>{txData.data?.trace?.cpu_usage_us} μs</span>
                                </div>
                                <div className="tx-info-item">
                                    <strong>NET Usage:</strong>
                                    <span>{txData.data?.trace?.net_usage} bytes</span>
                                </div>
                            </div>
                        </Panel>

                        {/* Action Details */}
                        {txData.data?.trace?.action_traces && txData.data.trace.action_traces[0] && (
                            <Panel header="Action Details" className="tx-panel" style={{ marginTop: '1rem' }}>
                                <div className="tx-info-grid">
                                    <div className="tx-info-item">
                                        <strong>Contract:</strong>
                                        <code>{txData.data.trace.action_traces[0].act?.account}</code>
                                    </div>
                                    <div className="tx-info-item">
                                        <strong>Action:</strong>
                                        <code>{txData.data.trace.action_traces[0].act?.name}</code>
                                    </div>
                                    <div className="tx-info-item">
                                        <strong>Authorization:</strong>
                                        <span>
                                            {txData.data.trace.action_traces[0].act?.authorization?.map(auth => 
                                                `${auth.actor}@${auth.permission}`
                                            ).join(', ')}
                                        </span>
                                    </div>
                                </div>

                                {/* Action Data */}
                                {txData.data.trace.action_traces[0].act?.data && (
                                    <>
                                        <Divider />
                                        <h4>Action Data</h4>
                                        <div className="tx-data-grid">
                                            {Object.entries(txData.data.trace.action_traces[0].act.data).map(([key, value]) => (
                                                <div key={key} className="tx-data-item">
                                                    <strong>{key}:</strong>
                                                    <span>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</span>
                                                </div>
                                            ))}
                                        </div>
                                    </>
                                )}
                            </Panel>
                        )}

                        {/* Raw JSON */}
                        <Panel header="Raw JSON" toggleable collapsed className="tx-panel" style={{ marginTop: '1rem' }}>
                            <pre className="tx-json">{JSON.stringify(txData, null, 2)}</pre>
                        </Panel>
                    </div>
                )}
            </Dialog>
        </div>
    );
};

export default UserActionLog;
