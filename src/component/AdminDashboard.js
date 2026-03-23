/**
 * AdminDashboard.js
 * =================
 * Admin panel for managing projects, viewing execution status, and clearing results
 * 
 * Features:
 *   - View all projects with detailed execution status
 *   - Clear project results (human/LLM/evaluation/audit)
 *   - View project action history
 *   - View screening results
 *   - View evaluation results
 * 
 * Author: PaSSER-SR Team
 * Date: January 2026
 */

import React, { useState, useEffect, useRef } from 'react';
import { Card } from 'primereact/card';
import { DataTable } from 'primereact/datatable';
import { Column } from 'primereact/column';
import { Button } from 'primereact/button';
import { Dialog } from 'primereact/dialog';
import { Tag } from 'primereact/tag';
import { Panel } from 'primereact/panel';
import { Dropdown } from 'primereact/dropdown';
import { ProgressBar } from 'primereact/progressbar';
import { ProgressSpinner } from 'primereact/progressspinner';
import { Divider } from 'primereact/divider';
import { Badge } from 'primereact/badge';
import { Timeline } from 'primereact/timeline';
import { confirmDialog } from 'primereact/confirmdialog';
import { TabView, TabPanel } from 'primereact/tabview';

import configuration from './configuration.json';
import './AdminDashboard.css';

const API_BASE_URL = configuration.passer.ScreeningAPI + '/api' || 'http://localhost:9901/api';

const AdminDashboard = ({ toast, currentUser }) => {
    const [projects, setProjects] = useState([]);
    const [loading, setLoading] = useState(false);
    const [selectedProject, setSelectedProject] = useState(null);
    
    // Dialogs
    const [actionsDialogVisible, setActionsDialogVisible] = useState(false);
    const [resultsDialogVisible, setResultsDialogVisible] = useState(false);
    const [evaluationDialogVisible, setEvaluationDialogVisible] = useState(false);
    const [llmJobsDialogVisible, setLlmJobsDialogVisible] = useState(false);
    const [llmDecisionsDialogVisible, setLlmDecisionsDialogVisible] = useState(false);
    const [txDialogVisible, setTxDialogVisible] = useState(false);
    
    // Data
    const [projectActions, setProjectActions] = useState([]);
    const [screeningResults, setScreeningResults] = useState(null);
    const [evaluationResults, setEvaluationResults] = useState(null);
    const [llmJobs, setLlmJobs] = useState([]);
    const [llmDecisions, setLlmDecisions] = useState(null);
    const [selectedJob, setSelectedJob] = useState(null);
    const [selectedJobs, setSelectedJobs] = useState([]);  // NEW: For multi-select delete
    const [actionsLoading, setActionsLoading] = useState(false);
    
    // Transaction dialog state
    const [txData, setTxData] = useState(null);
    const [txLoading, setTxLoading] = useState(false);

    useEffect(() => {
        loadAllProjects();
    }, []);

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

    const loadAllProjects = async () => {
        setLoading(true);
        try {
            const data = await apiRequest('/admin/projects/all');
            setProjects(data.projects || []);
        } catch (error) {
            toast.current?.show({ severity: 'error', summary: 'Error', detail: error.message, life: 3000 });
        } finally {
            setLoading(false);
        }
    };

    const clearProjectResults = async (project, clearType) => {
        confirmDialog({
            message: `Are you sure you want to clear ${clearType} results for project "${project.name}"? This action cannot be undone.`,
            header: 'Confirm Clear',
            icon: 'pi pi-exclamation-triangle',
            accept: async () => {
                try {
                    const data = await apiRequest(
                        `/admin/projects/${project.project_id}/clear?clear_type=${clearType}`,
                        { method: 'POST' }
                    );
                    toast.current?.show({ 
                        severity: 'success', 
                        summary: 'Success', 
                        detail: `Cleared ${clearType} results. Deleted: ${JSON.stringify(data.counts)}`,
                        life: 5000 
                    });
                    loadAllProjects();
                } catch (error) {
                    toast.current?.show({ severity: 'error', summary: 'Error', detail: error.message, life: 3000 });
                }
            }
        });
    };

    const viewProjectActions = async (project) => {
        setSelectedProject(project);
        setActionsDialogVisible(true);
        setActionsLoading(true);
        try {
            const data = await apiRequest(`/admin/projects/${project.project_id}/actions`);
            setProjectActions(data.actions || []);
        } catch (error) {
            toast.current?.show({ severity: 'error', summary: 'Error', detail: error.message, life: 3000 });
        } finally {
            setActionsLoading(false);
        }
    };

    const viewScreeningResults = async (project) => {
        setSelectedProject(project);
        setResultsDialogVisible(true);
        setActionsLoading(true);
        try {
            const data = await apiRequest(`/admin/results/screening?project_id=${project.project_id}&result_type=all`);
            setScreeningResults(data);
        } catch (error) {
            toast.current?.show({ severity: 'error', summary: 'Error', detail: error.message, life: 3000 });
        } finally {
            setActionsLoading(false);
        }
    };

    const viewEvaluationResults = async (project) => {
        setSelectedProject(project);
        setEvaluationDialogVisible(true);
        setActionsLoading(true);
        try {
            const data = await apiRequest(`/admin/results/evaluation?project_id=${project.project_id}`);
            setEvaluationResults(data);
        } catch (error) {
            toast.current?.show({ severity: 'error', summary: 'Error', detail: error.message, life: 3000 });
        } finally {
            setActionsLoading(false);
        }
    };

    const viewLlmJobs = async (project) => {
        setSelectedProject(project);
        setLlmJobsDialogVisible(true);
        setActionsLoading(true);
        setSelectedJobs([]);  // Clear selection
        console.log('Fetching LLM jobs for project:', project.project_id, 'Project name:', project.name);
        try {
            const data = await apiRequest(`/admin/results/llm-jobs?project_id=${project.project_id}`);
            console.log('LLM jobs response:', data);
            setLlmJobs(data.jobs || []);
        } catch (error) {
            console.error('Error fetching LLM jobs:', error);
            toast.current?.show({ severity: 'error', summary: 'Error', detail: error.message, life: 3000 });
        } finally {
            setActionsLoading(false);
        }
    };

    const deleteSelectedJobs = async () => {
        if (selectedJobs.length === 0) {
            toast.current?.show({ severity: 'warn', summary: 'No Selection', detail: 'Please select jobs to delete', life: 3000 });
            return;
        }

        const runningJobs = selectedJobs.filter(job => job.status === 'running');
        const hasRunning = runningJobs.length > 0;

        confirmDialog({
            message: `Are you sure you want to delete ${selectedJobs.length} selected job(s)? ${hasRunning ? `\n\n⚠️ WARNING: ${runningJobs.length} job(s) are marked as "running". This will force-delete them.` : ''} This will also delete all associated decisions. This action cannot be undone.`,
            header: hasRunning ? 'Confirm Force Delete' : 'Confirm Delete',
            icon: 'pi pi-exclamation-triangle',
            acceptClassName: hasRunning ? 'p-button-danger' : '',
            accept: async () => {
                const LLM_API_BASE = configuration.passer.LLMScreeningAPI || 'http://127.0.0.1:9902';
                let successCount = 0;
                let failCount = 0;

                for (const job of selectedJobs) {
                    try {
                        // Add force=true for running jobs
                        const forceParam = job.status === 'running' ? '?force=true' : '';
                        const response = await fetch(`${LLM_API_BASE}/api/llm/jobs/${job.job_id}${forceParam}`, {
                            method: 'DELETE'
                        });

                        if (!response.ok) {
                            const error = await response.json().catch(() => ({ detail: 'Delete failed' }));
                            throw new Error(error.detail || 'Delete failed');
                        }

                        successCount++;
                    } catch (error) {
                        console.error(`Failed to delete job ${job.job_id}:`, error);
                        failCount++;
                    }
                }

                if (successCount > 0) {
                    toast.current?.show({
                        severity: 'success',
                        summary: 'Jobs Deleted',
                        detail: `Successfully deleted ${successCount} job(s)${failCount > 0 ? `, ${failCount} failed` : ''}`,
                        life: 3000
                    });
                    // Reload jobs list
                    viewLlmJobs(selectedProject);
                } else {
                    toast.current?.show({
                        severity: 'error',
                        summary: 'Delete Failed',
                        detail: `Failed to delete ${failCount} job(s)`,
                        life: 3000
                    });
                }

                setSelectedJobs([]);
            }
        });
    };

    const viewLlmDecisions = async (project, jobId = null) => {
        setSelectedProject(project);
        setSelectedJob(jobId);
        setLlmDecisionsDialogVisible(true);
        setActionsLoading(true);
        try {
            const jobParam = jobId ? `&job_id=${jobId}` : '';
            const data = await apiRequest(`/admin/results/llm-decisions?project_id=${project.project_id}${jobParam}&limit=200`);
            setLlmDecisions(data);
        } catch (error) {
            toast.current?.show({ severity: 'error', summary: 'Error', detail: error.message, life: 3000 });
        } finally {
            setActionsLoading(false);
        }
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
            toast.current?.show({ severity: 'error', summary: 'Error', detail: 'Failed to load transaction', life: 3000 });
            setTxDialogVisible(false);
        } finally {
            setTxLoading(false);
        }
    };

    // Render helpers
    const phaseTag = (phase) => {
        const phaseMap = {
            '1_data_loaded': { label: 'Data Loaded', severity: 'info' },
            '2_human_screening': { label: 'Human Screening', severity: 'warning' },
            '3_llm_screening': { label: 'LLM Screening', severity: 'success' },
            '4_evaluation_complete': { label: 'Evaluation Complete', severity: 'success' }
        };
        const config = phaseMap[phase] || { label: phase, severity: 'secondary' };
        return <Tag value={config.label} severity={config.severity} />;
    };

    const actionsBodyTemplate = (project) => (
        <div className="admin-actions-buttons">
            <Button 
                icon="pi pi-history" 
                className="p-button-rounded p-button-text p-button-info"
                tooltip="View Actions"
                onClick={() => viewProjectActions(project)}
            />
            <Button 
                icon="pi pi-eye" 
                className="p-button-rounded p-button-text p-button-success"
                tooltip="View Results"
                onClick={() => viewScreeningResults(project)}
            />
            {project.execution_status?.evaluation?.results_count > 0 && (
                <Button 
                    icon="pi pi-chart-bar" 
                    className="p-button-rounded p-button-text p-button-warning"
                    tooltip="View Evaluation"
                    onClick={() => viewEvaluationResults(project)}
                />
            )}
            <Button 
                icon="pi pi-bolt" 
                className="p-button-rounded p-button-help"
                tooltip="View LLM Jobs"
                onClick={() => viewLlmJobs(project)}
            />
            <Dropdown 
                placeholder="Clear..."
                options={[
                    { label: 'Clear All Results', value: 'all' },
                    { label: 'Clear Human Screening', value: 'human' },
                    { label: 'Clear LLM Screening', value: 'llm' },
                    { label: 'Clear Evaluation', value: 'evaluation' },
                    { label: 'Clear Audit Exports', value: 'audit' },
                    { label: 'Clear FEW-SHOT Markers', value: 'fewshot' }
                ]}
                onChange={(e) => clearProjectResults(project, e.value)}
                className="p-button-sm"
                style={{ marginLeft: '0.5rem' }}
            />
        </div>
    );

    const executionStatusTemplate = (project) => {
        const status = project.execution_status || {};
        return (
            <div className="execution-status-cell">
                <div className="status-grid">
                    <span>📚 Corpus: <strong>{status.corpus_count || 0}</strong></span>
                    <span>⭐ GS: <strong>{status.gold_standard?.total || 0}</strong> ({status.gold_standard?.calibration || 0} cal / {status.gold_standard?.evaluation || 0} eval)</span>
                    <span>👤 Human: <strong>{status.human_screening?.papers_screened || 0}/{status.gold_standard?.total || 0}</strong> ({status.human_screening?.progress || 0}%)</span>
                    <span>🤖 LLM: <strong>{status.llm_screening?.decisions_count || 0}</strong> decisions</span>
                    <span>📊 Eval: <strong>{status.evaluation?.results_count || 0}</strong> results</span>
                </div>
                {status.human_screening?.progress > 0 && (
                    <ProgressBar value={status.human_screening.progress} showValue={false} style={{ height: '4px', marginTop: '0.5rem' }} />
                )}
            </div>
        );
    };

    const actionTypeTemplate = (action) => {
        const typeMap = {
            'human_decision': { icon: 'pi-user', color: '#3b82f6' },
            'resolution': { icon: 'pi-check-circle', color: '#10b981' },
            'llm_decision': { icon: 'pi-microchip', color: '#8b5cf6' },
            'audit_export': { icon: 'pi-shield', color: '#f59e0b' }
        };
        const config = typeMap[action.type] || { icon: 'pi-circle', color: '#6b7280' };
        return (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <i className={`pi ${config.icon}`} style={{ color: config.color }}></i>
                <span>{action.type}</span>
            </div>
        );
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

    return (
        <div className="admin-dashboard">
            <Card className="admin-header-card">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                        <h2>Admin Dashboard</h2>
                        <p>Manage projects, view execution status, and clear results</p>
                    </div>
                    <Button 
                        label="Refresh" 
                        icon="pi pi-refresh" 
                        onClick={loadAllProjects}
                        loading={loading}
                        className="p-button-outlined"
                    />
                </div>
            </Card>

            <Card>
                <DataTable 
                    value={projects}
                    loading={loading}
                    paginator
                    rows={10}
                    emptyMessage="No projects found"
                    className="admin-projects-table"
                >
                    <Column field="project_id" header="Project ID" sortable style={{ width: '150px' }} />
                    <Column field="name" header="Name" sortable style={{ minWidth: '200px' }} />
                    <Column 
                        header="Phase" 
                        body={(row) => phaseTag(row.execution_status?.phase)}
                        style={{ width: '180px' }}
                        sortable
                        sortField="execution_status.phase"
                    />
                    <Column 
                        header="Execution Status" 
                        body={executionStatusTemplate}
                        style={{ minWidth: '400px' }}
                    />
                    <Column 
                        header="Actions" 
                        body={actionsBodyTemplate}
                        style={{ width: '300px' }}
                    />
                </DataTable>
            </Card>

            {/* Actions Dialog */}
            <Dialog
                header={`Actions History: ${selectedProject?.name}`}
                visible={actionsDialogVisible}
                style={{ width: '80vw' }}
                onHide={() => setActionsDialogVisible(false)}
            >
                {actionsLoading ? (
                    <div className="loading-container">
                        <i className="pi pi-spin pi-spinner" style={{ fontSize: '2rem' }}></i>
                    </div>
                ) : (
                    <DataTable
                        value={projectActions}
                        paginator
                        rows={20}
                        emptyMessage="No actions found"
                    >
                        <Column header="Type" body={actionTypeTemplate} style={{ width: '180px' }} />
                        <Column field="timestamp" header="Timestamp" body={(row) => formatDateTime(row.timestamp)} sortable style={{ width: '180px' }} />
                        <Column 
                            field="user" 
                            header="User" 
                            body={(row) => row.user || <span style={{ color: '#9ca3af' }}>-</span>}
                            style={{ width: '120px' }}
                        />
                        <Column 
                            field="gs_id" 
                            header="Paper ID" 
                            body={(row) => row.gs_id || <span style={{ color: '#9ca3af' }}>-</span>}
                            style={{ width: '100px' }}
                        />
                        <Column 
                            field="decision" 
                            header="Decision" 
                            body={(row) => {
                                if (row.decision) {
                                    return (
                                        <Tag 
                                            value={row.decision} 
                                            severity={
                                                row.decision === 'INCLUDE' ? 'success' : 
                                                row.decision === 'EXCLUDE' ? 'danger' : 
                                                'warning'
                                            }
                                        />
                                    );
                                }
                                return <span style={{ color: '#9ca3af' }}>-</span>;
                            }}
                            style={{ width: '120px' }}
                        />
                        <Column field="strategy" header="Strategy" style={{ width: '140px' }} />
                        <Column field="model" header="Model" style={{ minWidth: '200px' }} />
                        <Column 
                            header="Blockchain TX" 
                            body={(row) => {
                                const txId = row.transaction_id;
                                if (txId) {
                                    return (
                                        <Button
                                            label={txId.substring(0, 12) + '...'}
                                            className="p-button-link p-button-sm"
                                            style={{ fontSize: '0.75rem', color: '#6366f1', padding: '0' }}
                                            onClick={() => viewTransaction(txId)}
                                            tooltip="View transaction details"
                                            icon="pi pi-shield"
                                        />
                                    );
                                }
                                return <span style={{ color: '#9ca3af', fontSize: '0.85rem' }}>-</span>;
                            }}
                            style={{ width: '160px' }}
                        />
                    </DataTable>
                )}
            </Dialog>

            {/* Screening Results Dialog */}
            <Dialog
                header={`Screening Results: ${selectedProject?.name}`}
                visible={resultsDialogVisible}
                style={{ width: '90vw', height: '80vh' }}
                onHide={() => setResultsDialogVisible(false)}
            >
                {actionsLoading ? (
                    <div className="loading-container">
                        <i className="pi pi-spin pi-spinner" style={{ fontSize: '2rem' }}></i>
                    </div>
                ) : screeningResults && (
                    <div className="screening-results-content">
                        {screeningResults.papers?.map((paper, idx) => (
                            <Panel key={idx} header={`${paper.gs_id}: ${paper.title}`} toggleable collapsed={idx > 2}>
                                <div className="paper-result-grid">
                                    <div className="paper-meta">
                                        <span><strong>Year:</strong> {paper.year}</span>
                                        <span><strong>Type:</strong> {paper.is_calibration ? 'Calibration' : 'Evaluation'}</span>
                                    </div>

                                    {paper.human_decisions?.length > 0 && (
                                        <div className="human-decisions-section">
                                            <h4>Human Decisions ({paper.human_decisions.length})</h4>
                                            {paper.human_decisions.map((d, i) => (
                                                <div key={i} className="decision-item">
                                                    <strong>{d.antelope_account}:</strong> <Tag value={d.decision} severity={d.decision === 'INCLUDE' ? 'success' : d.decision === 'EXCLUDE' ? 'danger' : 'warning'} /> ({d.confidence})
                                                    <p style={{ fontSize: '0.9rem', color: '#666', marginTop: '0.25rem' }}>{d.reason}</p>
                                                </div>
                                            ))}
                                        </div>
                                    )}

                                    {paper.resolution && (
                                        <div className="resolution-section">
                                            <h4>Resolution</h4>
                                            <div className="decision-item">
                                                <strong>{paper.resolution.resolver}:</strong> <Tag value={paper.resolution.final_decision} severity="success" />
                                                <p style={{ fontSize: '0.9rem', color: '#666', marginTop: '0.25rem' }}>{paper.resolution.resolution_reason}</p>
                                            </div>
                                        </div>
                                    )}

                                    {paper.llm_decisions?.length > 0 && (
                                        <div className="llm-decisions-section">
                                            <h4>LLM Decisions ({paper.llm_decisions.length})</h4>
                                            <DataTable value={paper.llm_decisions} size="small">
                                                <Column field="strategy" header="Strategy" />
                                                <Column field="model" header="Model" />
                                                <Column field="prompt_mode" header="Mode" />
                                                <Column field="final_decision" header="Decision" body={(row) => <Tag value={row.final_decision} />} />
                                                <Column field="final_confidence" header="Confidence" />
                                            </DataTable>
                                        </div>
                                    )}
                                </div>
                            </Panel>
                        ))}
                    </div>
                )}
            </Dialog>

            {/* Evaluation Results Dialog */}
            <Dialog
                header={`Evaluation Results: ${selectedProject?.name}`}
                visible={evaluationDialogVisible}
                style={{ width: '90vw' }}
                onHide={() => setEvaluationDialogVisible(false)}
            >
                {actionsLoading ? (
                    <div className="loading-container">
                        <i className="pi pi-spin pi-spinner" style={{ fontSize: '2rem' }}></i>
                    </div>
                ) : evaluationResults && (
                    <DataTable
                        value={evaluationResults.results}
                        paginator
                        rows={20}
                        emptyMessage="No evaluation results found"
                    >
                        <Column field="strategy" header="Strategy" sortable />
                        <Column field="model" header="Model" sortable />
                        <Column field="prompt_mode" header="Mode" sortable />
                        <Column 
                            field="recall" 
                            header="Recall" 
                            body={(row) => (row.recall * 100).toFixed(1) + '%'}
                            sortable
                        />
                        <Column 
                            field="precision" 
                            header="Precision" 
                            body={(row) => (row.precision * 100).toFixed(1) + '%'}
                            sortable
                        />
                        <Column 
                            field="f1" 
                            header="F1" 
                            body={(row) => (row.f1 * 100).toFixed(1) + '%'}
                            sortable
                        />
                        <Column 
                            field="wss_95" 
                            header="WSS@95" 
                            body={(row) => (row.wss_95 * 100).toFixed(1) + '%'}
                            sortable
                        />
                        <Column 
                            field="recall_threshold_met" 
                            header="Qualified" 
                            body={(row) => row.recall_threshold_met ? <Tag value="✓" severity="success" /> : <Tag value="✗" severity="danger" />}
                        />
                    </DataTable>
                )}
            </Dialog>

            {/* LLM Jobs Dialog */}
            <Dialog
                header={`LLM Screening Jobs - ${selectedProject?.project_name || ''}`}
                visible={llmJobsDialogVisible}
                style={{ width: '90vw' }}
                onHide={() => setLlmJobsDialogVisible(false)}
            >
                {actionsLoading ? (
                    <div className="loading-container">
                        <ProgressSpinner />
                    </div>
                ) : (
                    <>
                        {selectedJobs.length > 0 && (
                            <div className="mb-3">
                                <Button
                                    label={`Delete Selected (${selectedJobs.length})`}
                                    icon="pi pi-trash"
                                    className="p-button-danger"
                                    onClick={deleteSelectedJobs}
                                />
                            </div>
                        )}
                        <DataTable
                            value={llmJobs}
                            selection={selectedJobs}
                            onSelectionChange={(e) => setSelectedJobs(e.value)}
                            dataKey="job_id"
                            paginator
                            rows={10}
                            emptyMessage="No LLM jobs found"
                            responsiveLayout="scroll"
                        >
                            <Column selectionMode="multiple" headerStyle={{ width: '3rem' }} />
                            <Column field="job_id" header="Job ID" sortable style={{ width: '120px' }} />
                            <Column 
                                field="antelope_account" 
                                header="User" 
                                sortable 
                                style={{ width: '120px' }}
                            />
                            <Column 
                                field="created_at" 
                                header="Created" 
                                body={(row) => formatDateTime(row.created_at)}
                                sortable 
                                style={{ width: '180px' }}
                            />
                            <Column field="model" header="Model" sortable />
                            <Column field="strategy" header="Strategy" sortable />
                            <Column 
                                field="status" 
                                header="Status" 
                                body={(row) => <Tag value={row.status} severity={row.status === 'completed' ? 'success' : row.status === 'running' ? 'info' : 'warning'} />}
                                sortable 
                            />
                            <Column 
                                field="decisions_count" 
                                header="Total Decisions" 
                                sortable 
                            />
                            <Column 
                                field="decision_breakdown.INCLUDE" 
                                header="Include" 
                                body={(row) => <Tag value={row.decision_breakdown?.INCLUDE || 0} severity="success" />}
                            />
                            <Column 
                                field="decision_breakdown.EXCLUDE" 
                                header="Exclude" 
                                body={(row) => <Tag value={row.decision_breakdown?.EXCLUDE || 0} severity="danger" />}
                            />
                            <Column 
                                field="decision_breakdown.UNCERTAIN" 
                                header="Uncertain" 
                                body={(row) => <Tag value={row.decision_breakdown?.UNCERTAIN || 0} severity="warning" />}
                            />
                            <Column 
                                header="Actions"
                                body={(row) => (
                                    <Button
                                        label="View Decisions"
                                        icon="pi pi-search"
                                        className="p-button-sm"
                                        onClick={() => {
                                            setLlmJobsDialogVisible(false);
                                            viewLlmDecisions(selectedProject, row.job_id);
                                        }}
                                    />
                                )}
                            />
                        </DataTable>
                    </>
                )}
            </Dialog>

            {/* LLM Decisions Dialog */}
            <Dialog
                header={`LLM Decisions - ${selectedProject?.project_name || ''} ${selectedJob ? `(Job: ${selectedJob})` : ''}`}
                visible={llmDecisionsDialogVisible}
                style={{ width: '95vw', height: '90vh' }}
                onHide={() => setLlmDecisionsDialogVisible(false)}
            >
                {actionsLoading ? (
                    <div className="loading-container">
                        <ProgressSpinner />
                    </div>
                ) : (
                    <>
                        <div style={{ marginBottom: '1rem' }}>
                            <strong>Summary:</strong> Total {llmDecisions?.total_decisions || 0} decisions |
                            <Tag value={`INCLUDE: ${llmDecisions?.decision_breakdown?.INCLUDE || 0}`} severity="success" style={{ marginLeft: '0.5rem' }} />
                            <Tag value={`EXCLUDE: ${llmDecisions?.decision_breakdown?.EXCLUDE || 0}`} severity="danger" style={{ marginLeft: '0.5rem' }} />
                            <Tag value={`UNCERTAIN: ${llmDecisions?.decision_breakdown?.UNCERTAIN || 0}`} severity="warning" style={{ marginLeft: '0.5rem' }} />
                        </div>
                        <DataTable
                            value={llmDecisions?.decisions || []}
                            paginator
                            rows={20}
                            emptyMessage="No LLM decisions found"
                            responsiveLayout="scroll"
                        >
                            <Column field="paper_id" header="Paper ID" sortable />
                            <Column field="title" header="Title" sortable style={{ maxWidth: '300px' }} />
                            <Column 
                                field="final_decision" 
                                header="Decision" 
                                body={(row) => <Tag 
                                    value={row.final_decision} 
                                    severity={row.final_decision === 'INCLUDE' ? 'success' : row.final_decision === 'EXCLUDE' ? 'danger' : 'warning'} 
                                />}
                                sortable 
                            />
                            <Column 
                                field="confidence_score" 
                                header="Confidence" 
                                body={(row) => row.confidence_score ? (row.confidence_score * 100).toFixed(0) + '%' : 'N/A'}
                                sortable 
                            />
                            <Column field="model" header="Model" sortable />
                            <Column field="strategy" header="Strategy" sortable />
                            <Column 
                                field="created_at" 
                                header="Timestamp" 
                                body={(row) => formatDateTime(row.created_at)}
                                sortable 
                            />
                            <Column 
                                field="reasoning" 
                                header="Reasoning" 
                                style={{ maxWidth: '400px' }}
                                body={(row) => <div style={{ maxHeight: '100px', overflow: 'auto' }}>{row.reasoning || 'N/A'}</div>}
                            />
                        </DataTable>
                    </>
                )}
            </Dialog>

            {/* Blockchain Transaction Dialog */}
            <Dialog 
                header="Blockchain Transaction Details"
                visible={txDialogVisible}
                className="tx-dialog"
                style={{ width: '800px' }}
                onHide={() => { setTxDialogVisible(false); setTxData(null); }}
            >
                {txLoading ? (
                    <div className="tx-loading" style={{ textAlign: 'center', padding: '2rem' }}>
                        <i className="pi pi-spin pi-spinner" style={{ fontSize: '2rem' }}></i>
                        <p>Loading transaction data...</p>
                    </div>
                ) : txData && (
                    <div className="tx-details">
                        {/* Transaction Status */}
                        <div className="tx-status-section" style={{ marginBottom: '1rem' }}>
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
                            <div className="tx-info-grid" style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '0.75rem' }}>
                                <div className="tx-info-item">
                                    <strong>Transaction ID:</strong>
                                    <div><code style={{ fontSize: '0.85rem' }}>{txData.data?.trace?.id}</code></div>
                                </div>
                                <div className="tx-info-item">
                                    <strong>Block Number:</strong>
                                    <span> {txData.data?.block_num}</span>
                                </div>
                                <div className="tx-info-item">
                                    <strong>Block Timestamp:</strong>
                                    <span> {formatDateTime(txData.data?.block_timestamp)}</span>
                                </div>
                                <div className="tx-info-item">
                                    <strong>CPU Usage:</strong>
                                    <span> {txData.data?.trace?.cpu_usage_us} μs</span>
                                </div>
                                <div className="tx-info-item">
                                    <strong>NET Usage:</strong>
                                    <span> {txData.data?.trace?.net_usage} bytes</span>
                                </div>
                            </div>
                        </Panel>

                        {/* Action Details */}
                        {txData.data?.trace?.action_traces && txData.data.trace.action_traces[0] && (
                            <Panel header="Action Details" className="tx-panel" style={{ marginTop: '1rem' }}>
                                <div className="tx-info-grid" style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '0.75rem' }}>
                                    <div className="tx-info-item">
                                        <strong>Contract:</strong>
                                        <code> {txData.data.trace.action_traces[0].act?.account}</code>
                                    </div>
                                    <div className="tx-info-item">
                                        <strong>Action:</strong>
                                        <code> {txData.data.trace.action_traces[0].act?.name}</code>
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
                                        <div className="tx-data-grid" style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '0.5rem' }}>
                                            {Object.entries(txData.data.trace.action_traces[0].act.data).map(([key, value]) => (
                                                <div key={key} className="tx-data-item">
                                                    <strong>{key}:</strong>
                                                    <span> {typeof value === 'object' ? JSON.stringify(value) : String(value)}</span>
                                                </div>
                                            ))}
                                        </div>
                                    </>
                                )}
                            </Panel>
                        )}

                        {/* Raw JSON */}
                        <Panel header="Raw JSON" toggleable collapsed className="tx-panel" style={{ marginTop: '1rem' }}>
                            <pre className="tx-json" style={{ fontSize: '0.75rem', overflow: 'auto', maxHeight: '400px' }}>{JSON.stringify(txData, null, 2)}</pre>
                        </Panel>
                    </div>
                )}
            </Dialog>
        </div>
    );
};

export default AdminDashboard;
