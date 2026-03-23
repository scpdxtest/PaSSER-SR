/**
 * Screening.js (v5.0 with Criteria Checkboxes)
 * =============================================
 * Main component for Human Screening Module in PaSSER-SR
 * 
 * Features:
 *   - Project selection with corpus & gold standard info
 *   - View full corpus papers (read-only)
 *   - Screen Gold Standard papers with structured criteria selection
 *   - Disagreement resolution
 *   - Statistics dashboard
 *   - Blockchain Audit Trail with Merkle export & OpenTimestamps
 * 
 * v5.0 Changes:
 *   - Added IC1-IC5 and EC1-EC6 checkboxes for structured criteria selection
 *   - Criteria text is stored in reason field for unified format with LLM screening
 *   - Conditional display: INCLUDE shows IC, EXCLUDE shows EC, UNCERTAIN shows both
 * 
 * Author: PaSSER-SR Team
 * Date: January 2026
 * Version: 5.0
 */

import React, { useState, useEffect, useRef } from 'react';

// PrimeReact Components
import { Card } from 'primereact/card';
import { DataTable } from 'primereact/datatable';
import { Column } from 'primereact/column';
import { Button } from 'primereact/button';
import { Dialog } from 'primereact/dialog';
import { RadioButton } from 'primereact/radiobutton';
import { Checkbox } from 'primereact/checkbox';
import { InputTextarea } from 'primereact/inputtextarea';
import { InputText } from 'primereact/inputtext';
import { ProgressBar } from 'primereact/progressbar';
import { Tag } from 'primereact/tag';
import { TabView, TabPanel } from 'primereact/tabview';
import { Toast } from 'primereact/toast';
import { Toolbar } from 'primereact/toolbar';
import { Dropdown } from 'primereact/dropdown';
import { Panel } from 'primereact/panel';
import { Divider } from 'primereact/divider';
import { Message } from 'primereact/message';
import { Skeleton } from 'primereact/skeleton';
import { Sidebar } from 'primereact/sidebar';
import { Paginator } from 'primereact/paginator';
import { ConfirmDialog, confirmDialog } from 'primereact/confirmdialog';
import { Timeline } from 'primereact/timeline';
import { FileUpload } from 'primereact/fileupload';
import { Tooltip } from 'primereact/tooltip';
import configuration from './configuration.json';
import LLMScreening from './LLMScreening';
import AdminDashboard from './AdminDashboard';
import UserActionLog from './UserActionLog';
import './LLMScreening.css';

// Styles
import './Screening.css';

// Screening Criteria Constants
import { INCLUSION_CRITERIA, EXCLUSION_CRITERIA, formatReasonFromCriteria } from '../constants/screeningCriteria';

// Configuration
const API_BASE_URL = configuration.passer.ScreeningAPI + '/api' || 'http://localhost:9901/api';

// =============================================================================
// HELPERS
// =============================================================================

const getCurrentUser = () => {
    return localStorage.getItem('user_name') || localStorage.getItem('wharf_user_name') || null;
};

const apiRequest = async (endpoint, options = {}, extraParams = {}) => {
    const username = getCurrentUser();
    if (!username) throw new Error('Not logged in');

    const url = new URL(`${API_BASE_URL}${endpoint}`);
    url.searchParams.append('antelope_account', username);
    Object.entries(extraParams).forEach(([key, value]) => {
        if (value !== null && value !== undefined) url.searchParams.append(key, value);
    });

    const response = await fetch(url.toString(), {
        ...options,
        headers: { 'Content-Type': 'application/json', ...options.headers },
    });

    if (!response.ok) {
        let errorMessage = `API request failed (${response.status})`;
        try {
            const error = await response.json();
            // Handle FastAPI validation errors
            if (error.detail) {
                if (Array.isArray(error.detail)) {
                    // Validation errors array from FastAPI
                    errorMessage = error.detail.map(e => `${e.loc?.join('.')}: ${e.msg}`).join('; ');
                } else if (typeof error.detail === 'string') {
                    errorMessage = error.detail;
                } else {
                    errorMessage = JSON.stringify(error.detail);
                }
            }
        } catch (parseError) {
            // If JSON parsing fails, use status text
            errorMessage = response.statusText || errorMessage;
        }
        throw new Error(errorMessage);
    }
    return response.json();
};

const hasRole = (userRoles, role) => userRoles && userRoles.includes(role);

const formatDateTime = (dateStr) => {
    if (!dateStr) return '-';
    const date = new Date(dateStr);
    return date.toLocaleString('en-GB', {
        day: '2-digit',
        month: 'short',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
};

const formatFileSize = (bytes) => {
    if (!bytes) return '-';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
};

// =============================================================================
// MAIN COMPONENT
// =============================================================================

const Screening = () => {
    // User state
    const [user, setUser] = useState(null);
    const [userRoles, setUserRoles] = useState([]);
    
    // Project state
    const [projects, setProjects] = useState([]);
    const [selectedProject, setSelectedProject] = useState(null);
    const [projectDetails, setProjectDetails] = useState(null);
    const [projectSidebarVisible, setProjectSidebarVisible] = useState(false);
    
    // Corpus state
    const [corpusPapers, setCorpusPapers] = useState([]);
    const [corpusTotal, setCorpusTotal] = useState(0);
    const [corpusPage, setCorpusPage] = useState(1);
    const [corpusSearch, setCorpusSearch] = useState('');
    const [corpusLoading, setCorpusLoading] = useState(false);
    
    // Gold Standard state
    const [papers, setPapers] = useState([]);
    const [stats, setStats] = useState(null);
    const [selectedPaper, setSelectedPaper] = useState(null);
    const [loading, setLoading] = useState(true);
    const [submitting, setSubmitting] = useState(false);
    const [dialogVisible, setDialogVisible] = useState(false);
    const [filter, setFilter] = useState('all');
    const [activeTab, setActiveTab] = useState(0);
    
    // Form state - Decision
    const [decision, setDecision] = useState(null);
    const [confidence, setConfidence] = useState(null);
    const [reason, setReason] = useState('');
    const [screeningInstructions, setScreeningInstructions] = useState(null);
    
    // Form state - Criteria (NEW)
    const [criteriaMet, setCriteriaMet] = useState([]);
    const [criteriaViolated, setCriteriaViolated] = useState([]);
    const [additionalNotes, setAdditionalNotes] = useState('');
    
    // Disagreements
    const [disagreements, setDisagreements] = useState([]);
    const [selectedDisagreement, setSelectedDisagreement] = useState(null);
    const [resolutionDialogVisible, setResolutionDialogVisible] = useState(false);
    const [finalDecision, setFinalDecision] = useState(null);
    const [finalConfidence, setFinalConfidence] = useState(null);
    const [resolutionCriteriaMet, setResolutionCriteriaMet] = useState([]);
    const [resolutionCriteriaViolated, setResolutionCriteriaViolated] = useState([]);
    const [resolutionNotes, setResolutionNotes] = useState('');
    const [resolutionReason, setResolutionReason] = useState('');
    
    // Statistics
    const [statistics, setStatistics] = useState(null);
    
    // Blockchain transaction viewer
    const [txDialogVisible, setTxDialogVisible] = useState(false);
    const [txData, setTxData] = useState(null);
    const [txLoading, setTxLoading] = useState(false);

    // Blockchain Audit state
    const [auditStatus, setAuditStatus] = useState(null);
    const [auditLoading, setAuditLoading] = useState(false);
    const [auditActionLoading, setAuditActionLoading] = useState(null);
    const [verifyDialogVisible, setVerifyDialogVisible] = useState(false);
    const [verifyFile, setVerifyFile] = useState(null);
    const [verifyResult, setVerifyResult] = useState(null);
    const [llmJobs, setLlmJobs] = useState([]);
    const [selectedInclusionJobId, setSelectedInclusionJobId] = useState(null);
    
    const toast = useRef(null);

    // Paper type filter
    const [paperTypeFilter, setPaperTypeFilter] = useState('all');

    // ==========================================================================
    // EFFECTS
    // ==========================================================================

    useEffect(() => {
        const username = getCurrentUser();
        if (username) {
            setUser(username);
            loadProjects();
        } else {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        if (selectedProject) {
            loadProjectDetails();
            loadPapers();
            if (hasRole(userRoles, 'resolver') || hasRole(userRoles, 'admin')) {
                loadDisagreements();
            }
            if (hasRole(userRoles, 'admin')) {
                loadStatistics();
                loadAuditStatus();
                loadLlmJobs();
            }
        }
    }, [selectedProject]);

    // Auto-refresh audit status every 5 minutes if there are pending timestamps
    useEffect(() => {
        if (!selectedProject || !hasRole(userRoles, 'admin')) return;
        
        const hasPendingTimestamps = auditStatus?.exports?.some(e => e.ots_status === 'pending');
        if (!hasPendingTimestamps) return;
        
        const intervalId = setInterval(() => {
            console.log('Auto-refreshing audit status to check pending timestamps...');
            loadAuditStatus();
        }, 5 * 60 * 1000); // 5 minutes
        
        return () => clearInterval(intervalId);
    }, [selectedProject, auditStatus, userRoles]);

    // Reset criteria when decision changes
    useEffect(() => {
        if (decision === 'INCLUDE') {
            setCriteriaViolated([]);
        } else if (decision === 'EXCLUDE') {
            setCriteriaMet([]);
        }
        // UNCERTAIN keeps both
    }, [decision]);

    // Auto-generate reason from criteria
    useEffect(() => {
        const generatedReason = formatReasonFromCriteria(criteriaMet, criteriaViolated, additionalNotes);
        setReason(generatedReason);
    }, [criteriaMet, criteriaViolated, additionalNotes]);

    // ==========================================================================
    // LOADING FUNCTIONS
    // ==========================================================================

    const loadProjects = async () => {
        try {
            const data = await apiRequest('/projects');
            setProjects(data.projects || []);
            
            // Get user roles from first project (simplified)
            if (data.projects?.length > 0) {
                const projectData = await apiRequest(`/projects/${data.projects[0].project_id}`);
                setUserRoles(projectData.user_roles || []);
            }
        } catch (error) {
            console.error('Failed to load projects:', error);
        } finally {
            setLoading(false);
        }
    };

    const loadProjectDetails = async () => {
        if (!selectedProject) return;
        try {
            const data = await apiRequest(`/projects/${selectedProject.project_id}`);
            setProjectDetails(data);
            setUserRoles(data.user_roles || []);
            setScreeningInstructions(data.screening_instructions || null);
        } catch (error) {
            console.error('Failed to load project details:', error);
        }
    };

    const loadPapers = async () => {
        if (!selectedProject) return;
        try {
            const data = await apiRequest('/papers', {}, { 
                project_id: selectedProject.project_id,
                filter: filter !== 'all' ? filter : undefined
            });
            setPapers(data.papers || []);
            setStats(data.stats || null);
        } catch (error) {
            console.error('Failed to load papers:', error);
        }
    };

    const loadPaperDetails = async (gsId) => {
        try {
            const data = await apiRequest(`/papers/${gsId}`, {}, { project_id: selectedProject.project_id });
            console.log('------------>>>> Loaded paper details:', data);
            setSelectedPaper(data);
            setScreeningInstructions(data.screening_instructions);
            
            if (data.my_decision) {
                setDecision(data.my_decision.decision);
                setConfidence(data.my_decision.confidence);
                setReason(data.my_decision.reason || '');
            } else {
                setDecision(null);
                setConfidence(null);
                setReason('');
                setCriteriaMet([]);
                setCriteriaViolated([]);
                setAdditionalNotes('');
            }
            setDialogVisible(true);
        } catch (error) {
            toast.current?.show({ severity: 'error', summary: 'Error', detail: error.message });
        }
    };

    const loadDisagreements = async () => {
        if (!selectedProject) return;
        try {
            const data = await apiRequest('/disagreements', {}, { project_id: selectedProject.project_id });
            setDisagreements(data.disagreements || []);
        } catch (error) {
            console.error('Failed to load disagreements:', error);
        }
    };

    const loadStatistics = async () => {
        if (!selectedProject) return;
        try {
            const data = await apiRequest('/stats', {}, { project_id: selectedProject.project_id });
            setStatistics(data);
        } catch (error) {
            console.error('Failed to load statistics:', error);
        }
    };

    const loadAuditStatus = async () => {
        if (!selectedProject) return;
        setAuditLoading(true);
        try {
            const data = await apiRequest('/audit/status', {}, { project_id: selectedProject.project_id });
            // console.log('Audit status response:', data);
            setAuditStatus(data);
        } catch (error) {
            console.error('Failed to load audit status:', error);
        } finally {
            setAuditLoading(false);
        }
    };

    const loadLlmJobs = async () => {
        if (!selectedProject) return;
        try {
            const data = await apiRequest('/admin/results/llm-jobs', {}, { project_id: selectedProject.project_id });
            setLlmJobs(data.jobs || []);
        } catch (error) {
            console.error('Failed to load LLM jobs:', error);
        }
    };

    const loadCorpusPapers = async (page = 1, search = '') => {
        if (!selectedProject) return;
        setCorpusLoading(true);
        try {
            const data = await apiRequest('/corpus', {}, { 
                project_id: selectedProject.project_id,
                page: page,
                limit: 20,
                search: search || undefined
            });
            setCorpusPapers(data.papers || []);
            setCorpusTotal(data.total || 0);
            setCorpusPage(page);
        } catch (error) {
            console.error('Failed to load corpus:', error);
        } finally {
            setCorpusLoading(false);
        }
    };

    // ==========================================================================
    // DIALOG HANDLERS
    // ==========================================================================

    const openScreeningDialog = (paper) => {
        setSelectedPaper(paper);
        setDecision(null);
        setConfidence(null);
        setReason('');
        setCriteriaMet([]);
        setCriteriaViolated([]);
        setAdditionalNotes('');
        setDialogVisible(true);
    };

    const openResolutionDialog = (disagreement) => {
        setSelectedDisagreement(disagreement);
        setFinalDecision(null);
        setFinalConfidence(null);
        setResolutionCriteriaMet([]);
        setResolutionCriteriaViolated([]);
        setResolutionNotes('');
        setResolutionReason('');
        setResolutionDialogVisible(true);
    };

    // ==========================================================================
    // CRITERIA CHECKBOX HANDLERS
    // ==========================================================================

    const onCriteriaMetChange = (e) => {
        let selected = [...criteriaMet];
        if (e.checked) {
            selected.push(e.value);
        } else {
            selected = selected.filter(code => code !== e.value);
        }
        setCriteriaMet(selected);
    };

    const onCriteriaViolatedChange = (e) => {
        let selected = [...criteriaViolated];
        if (e.checked) {
            selected.push(e.value);
        } else {
            selected = selected.filter(code => code !== e.value);
        }
        setCriteriaViolated(selected);
    };

    // Validation: at least one criterion must be selected
    const isCriteriaValid = () => {
        if (decision === 'INCLUDE') {
            return criteriaMet.length > 0;
        } else if (decision === 'EXCLUDE') {
            return criteriaViolated.length > 0;
        } else if (decision === 'UNCERTAIN') {
            return criteriaMet.length > 0 || criteriaViolated.length > 0;
        }
        return false;
    };

    // ==========================================================================
    // SUBMIT HANDLERS
    // ==========================================================================

    const submitDecision = async () => {
        if (!decision || !confidence) {
            toast.current?.show({ severity: 'warn', summary: 'Validation', detail: 'Please select decision and confidence' });
            return;
        }

        if (!isCriteriaValid()) {
            toast.current?.show({ severity: 'warn', summary: 'Validation', detail: 'Please select at least one criterion' });
            return;
        }

        // Generate final reason from criteria
        const finalReason = formatReasonFromCriteria(criteriaMet, criteriaViolated, additionalNotes);
        
        if (finalReason.length < 5) {
            toast.current?.show({ severity: 'warn', summary: 'Validation', detail: 'Reason too short' });
            return;
        }

        // Validate reason length (backend limit is 3000 characters)
        if (finalReason.length > 3000) {
            toast.current?.show({ 
                severity: 'warn', 
                summary: 'Validation', 
                detail: `Reason too long (${finalReason.length} chars). Please shorten your additional notes. Max: 3000 chars.` 
            });
            return;
        }

        try {
            setSubmitting(true);
            
            // Log request data for debugging
            console.log('Submitting decision:', {
                gs_id: selectedPaper.gs_id,
                project_id: selectedProject.project_id,
                decision,
                confidence,
                reason_length: finalReason.length,
                criteria_met: criteriaMet,
                criteria_violated: criteriaViolated
            });
            
            await apiRequest(`/papers/${selectedPaper.gs_id}/decision`, {
                method: 'POST',
                body: JSON.stringify({ decision, confidence, reason: finalReason })
            }, { project_id: selectedProject.project_id });

            toast.current?.show({ severity: 'success', summary: 'Success', detail: 'Decision saved' });
            setDialogVisible(false);
            loadPapers();
        } catch (error) {
            console.error('Submit decision error:', error);
            
            // Show detailed error message
            const errorDetail = error.message || 'Failed to save decision';
            toast.current?.show({ 
                severity: 'error', 
                summary: 'Error', 
                detail: errorDetail,
                life: 5000 
            });
        } finally {
            setSubmitting(false);
        }
    };

    const submitResolution = async () => {
        if (!finalDecision || !finalConfidence) {
            toast.current?.show({ severity: 'warn', summary: 'Validation', detail: 'Please select decision and confidence' });
            return;
        }

        // Validate criteria selection
        if (finalDecision === 'INCLUDE' && resolutionCriteriaMet.length === 0) {
            toast.current?.show({ severity: 'warn', summary: 'Validation', detail: 'Please select at least one inclusion criterion' });
            return;
        }
        if (finalDecision === 'EXCLUDE' && resolutionCriteriaViolated.length === 0) {
            toast.current?.show({ severity: 'warn', summary: 'Validation', detail: 'Please select at least one exclusion criterion' });
            return;
        }
        if (finalDecision === 'UNCERTAIN' && (resolutionCriteriaMet.length === 0 && resolutionCriteriaViolated.length === 0)) {
            toast.current?.show({ severity: 'warn', summary: 'Validation', detail: 'Please select at least one criterion' });
            return;
        }

        // Generate final reason from criteria
        const finalReason = formatReasonFromCriteria(resolutionCriteriaMet, resolutionCriteriaViolated, resolutionNotes);

        try {
            setSubmitting(true);
            await apiRequest(`/papers/${selectedDisagreement.gs_id}/resolve`, {
                method: 'POST',
                body: JSON.stringify({ 
                    final_decision: finalDecision, 
                    confidence: finalConfidence,
                    resolution_reason: finalReason 
                })
            }, { project_id: selectedProject.project_id });

            toast.current?.show({ severity: 'success', summary: 'Success', detail: 'Resolution saved' });
            setResolutionDialogVisible(false);
            loadDisagreements();
        } catch (error) {
            toast.current?.show({ severity: 'error', summary: 'Error', detail: error.message });
        } finally {
            setSubmitting(false);
        }
    };

    const exportResults = async () => {
        try {
            const data = await apiRequest('/export', {}, { project_id: selectedProject.project_id });
            const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${selectedProject.project_id}_results_${new Date().toISOString().split('T')[0]}.json`;
            a.click();
            URL.revokeObjectURL(url);
            toast.current?.show({ severity: 'success', summary: 'Export', detail: 'Results exported' });
        } catch (error) {
            toast.current?.show({ severity: 'error', summary: 'Error', detail: error.message });
        }
    };

    // ==========================================================================
    // FEW-SHOT HANDLERS
    // ==========================================================================

    const clearFewShotMarkers = async () => {
        confirmDialog({
            message: 'Are you sure you want to clear all FEW-SHOT markers? This will remove the calibration flag from all papers.',
            header: 'Clear FEW-SHOT Markers',
            icon: 'pi pi-exclamation-triangle',
            accept: async () => {
                try {
                    const data = await apiRequest('/fewshot/clear', {
                        method: 'POST'
                    }, { project_id: selectedProject.project_id });
                    
                    toast.current?.show({ 
                        severity: 'success', 
                        summary: 'Success', 
                        detail: data.message 
                    });
                    loadPapers();
                } catch (error) {
                    toast.current?.show({ 
                        severity: 'error', 
                        summary: 'Error', 
                        detail: error.message 
                    });
                }
            }
        });
    };

    const togglePaperFewShot = async (paper) => {
        try {
            const newStatus = !paper.is_calibration;
            
            // Update in database
            const response = await fetch(
                `${API_BASE_URL}/papers/${paper.gs_id}/fewshot?project_id=${selectedProject.project_id}&antelope_account=${user}`,
                {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ is_calibration: newStatus })
                }
            );

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to update FEW-SHOT status');
            }

            toast.current?.show({ 
                severity: 'success', 
                summary: 'Updated', 
                detail: `Paper ${newStatus ? 'marked as' : 'removed from'} FEW-SHOT` 
            });
            loadPapers();
        } catch (error) {
            toast.current?.show({ 
                severity: 'error', 
                summary: 'Error', 
                detail: error.message 
            });
        }
    };

    // ==========================================================================
    // AUDIT HANDLERS
    // ==========================================================================

    const createAuditExport = async (milestone) => {
        setAuditActionLoading('export');
        try {
            const body = {
                milestone: milestone || undefined,
                include_llm_decisions: true,
                inclusion_list_job_id: selectedInclusionJobId || undefined
            };
            const data = await apiRequest('/audit/export', {
                method: 'POST',
                body: JSON.stringify(body)
            }, { project_id: selectedProject.project_id });

            // Auto-download the export JSON file
            if (data.export_data) {
                const jsonStr = JSON.stringify(data.export_data, null, 2);
                const blob = new Blob([jsonStr], { type: 'application/json' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = data.filename || `audit_export_${Date.now()}.json`;
                a.click();
                URL.revokeObjectURL(url);
            }

            toast.current?.show({ severity: 'success', summary: 'Export Created', detail: `Merkle root: ${data.merkle_root?.substring(0, 16)}... — JSON downloaded.` });
            loadAuditStatus();
        } catch (error) {
            toast.current?.show({ severity: 'error', summary: 'Error', detail: error.message });
        } finally {
            setAuditActionLoading(null);
        }
    };

    const submitToTimestamp = async (exportId) => {
        setAuditActionLoading(`timestamp-${exportId}`);
        try {
            await apiRequest('/audit/timestamp', {
                method: 'POST',
                body: JSON.stringify({ export_id: exportId })
            }, { project_id: selectedProject.project_id });
            
            toast.current?.show({ severity: 'success', summary: 'Submitted', detail: 'Timestamp pending confirmation (2-4 hours)' });
            loadAuditStatus();
        } catch (error) {
            toast.current?.show({ severity: 'error', summary: 'Error', detail: error.message });
        } finally {
            setAuditActionLoading(null);
        }
    };

    const downloadProof = async (exportId) => {
        try {
            const data = await apiRequest(`/audit/proof/${exportId}`, {}, { project_id: selectedProject.project_id });
            
            // Decode base64 and download
            const byteCharacters = atob(data.ots_proof_base64);
            const byteNumbers = new Array(byteCharacters.length);
            for (let i = 0; i < byteCharacters.length; i++) {
                byteNumbers[i] = byteCharacters.charCodeAt(i);
            }
            const byteArray = new Uint8Array(byteNumbers);
            const blob = new Blob([byteArray], { type: 'application/octet-stream' });
            
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = data.filename;
            a.click();
            URL.revokeObjectURL(url);
        } catch (error) {
            toast.current?.show({ severity: 'error', summary: 'Error', detail: error.message });
        }
    };

    const handleVerifyFile = async () => {
        if (!verifyFile) return;
        
        setAuditActionLoading('verify');
        try {
            const content = await verifyFile.text();
            const data = await apiRequest('/audit/verify', {
                method: 'POST',
                body: JSON.stringify({ file_content: content, filename: verifyFile.name })
            }, { project_id: selectedProject.project_id });
            
            setVerifyResult(data);
        } catch (error) {
            toast.current?.show({ severity: 'error', summary: 'Error', detail: error.message });
        } finally {
            setAuditActionLoading(null);
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
            toast.current?.show({ severity: 'error', summary: 'Error', detail: 'Failed to load transaction' });
            setTxDialogVisible(false);
        } finally {
            setTxLoading(false);
        }
    };

    // ==========================================================================
    // RENDER HELPERS
    // ==========================================================================

    const renderRoleTags = () => userRoles.map((role, i) => (
        <Tag key={i} value={role} 
             severity={role === 'admin' ? 'danger' : role === 'resolver' ? 'warning' : 'info'}
             className="role-tag" />
    ));

    const projectStatusTag = (status) => {
        return <Tag value={status} severity={status === 'active' ? 'success' : 'warning'} />;
    };

    const renderAuditStatusBadge = (status) => {
        switch (status) {
            case 'confirmed':
                return <Tag severity="success" value="✓ Confirmed on Bitcoin" icon="pi pi-check" />;
            case 'pending':
                return <Tag severity="warning" value="⏳ Pending (2-4 hours)" icon="pi pi-clock" />;
            case 'not_timestamped':
                return <Tag severity="info" value="○ Not Timestamped" />;
            default:
                return <Tag severity="secondary" value="Unknown" />;
        }
    };

    const renderMilestoneIcon = (milestone) => {
        const icons = {
            'protocol_registered': 'pi-bookmark',
            'gold_standard_complete': 'pi-star',
            'llm_screening_complete': 'pi-microchip',
            'final_corpus': 'pi-flag'
        };
        return <i className={`pi ${icons[milestone] || 'pi-circle'} milestone-icon`}></i>;
    };

    const decisionSeverity = (decision) => {
        switch (decision) {
            case 'INCLUDE': return 'success';
            case 'EXCLUDE': return 'danger';
            case 'UNCERTAIN': return 'warning';
            default: return 'info';
        }
    };

    const statusBodyTemplate = (rowData) => (
        rowData.status === 'completed' 
            ? <Tag severity="success" value="✓ Done" />
            : <Tag severity="warning" value="○ Pending" />
    );

    const decisionBodyTemplate = (rowData) => {
        if (!rowData.my_decision) return '-';
        const severityMap = { 'INCLUDE': 'success', 'EXCLUDE': 'danger', 'UNCERTAIN': 'warning' };
        return <Tag severity={severityMap[rowData.my_decision]} value={rowData.my_decision} />;
    };

    const actionsBodyTemplate = (rowData) => (
        <Button 
            icon="pi pi-pencil" 
            className="p-button-rounded p-button-text"
            tooltip="Screen this paper"
            onClick={() => loadPaperDetails(rowData.gs_id)}
        />
    );

    // ==========================================================================
    // CRITERIA CHECKBOXES RENDER
    // ==========================================================================

    const renderCriteriaCheckboxes = () => {
        if (!decision) return null;

        const showInclusion = decision === 'INCLUDE' || decision === 'UNCERTAIN';
        const showExclusion = decision === 'EXCLUDE' || decision === 'UNCERTAIN';

        return (
            <div className="criteria-selection">
                {showInclusion && (
                    <div className="criteria-group inclusion-group">
                        <h5 className="criteria-header include-header">
                            <i className="pi pi-check-circle"></i> Inclusion Criteria (IC)
                            {decision === 'INCLUDE' && <span className="required-badge">* Select at least one</span>}
                        </h5>
                        <div className="criteria-checkboxes">
                            {INCLUSION_CRITERIA.map(criterion => (
                                <div key={criterion.code} className="criteria-checkbox-item">
                                    <Checkbox 
                                        inputId={criterion.code}
                                        value={criterion.code}
                                        onChange={onCriteriaMetChange}
                                        checked={criteriaMet.includes(criterion.code)}
                                    />
                                    <label htmlFor={criterion.code} className="criteria-label">
                                        <strong>{criterion.code}:</strong> {criterion.text}
                                    </label>
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                {showExclusion && (
                    <div className="criteria-group exclusion-group">
                        <h5 className="criteria-header exclude-header">
                            <i className="pi pi-times-circle"></i> Exclusion Criteria (EC)
                            {decision === 'EXCLUDE' && <span className="required-badge">* Select at least one</span>}
                        </h5>
                        <div className="criteria-checkboxes">
                            {EXCLUSION_CRITERIA.map(criterion => (
                                <div key={criterion.code} className="criteria-checkbox-item">
                                    <Checkbox 
                                        inputId={criterion.code}
                                        value={criterion.code}
                                        onChange={onCriteriaViolatedChange}
                                        checked={criteriaViolated.includes(criterion.code)}
                                    />
                                    <label htmlFor={criterion.code} className="criteria-label">
                                        <strong>{criterion.code}:</strong> {criterion.text}
                                    </label>
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                <div className="form-field additional-notes">
                    <label>Additional Notes (optional)</label>
                    <InputTextarea 
                        value={additionalNotes} 
                        onChange={(e) => setAdditionalNotes(e.target.value)}
                        rows={2} 
                        className="notes-textarea" 
                        placeholder="Any additional observations or justification..."
                    />
                </div>

                {/* Preview of generated reason */}
                {reason && (
                    <Panel header="Generated Reason (Preview)" toggleable collapsed className="reason-preview-panel">
                        <pre className="reason-preview">{reason}</pre>
                    </Panel>
                )}
            </div>
        );
    };

    // ==========================================================================
    // MAIN RENDER
    // ==========================================================================

    if (!user) {
        return (
            <div className="screening-container">
                <Card className="login-prompt">
                    <i className="pi pi-lock" style={{ fontSize: '3rem', color: '#6366f1' }}></i>
                    <h2>Authentication Required</h2>
                    <p>Please log in with your Antelope wallet to access screening.</p>
                </Card>
            </div>
        );
    }

    return (
        <div className="screening-container">
            <Toast ref={toast} />
            <ConfirmDialog />

            {/* Header */}
            <Card className="screening-header">
                <div className="header-content">
                    <div className="header-info">
                        <h2>Human Screening Module</h2>
                        <p className="user-info">Logged in as: <strong>{user}</strong> | Roles: {renderRoleTags()}</p>
                    </div>
                    <div className="header-project">
                        <div className="project-selector" onClick={() => setProjectSidebarVisible(true)}>
                            <span className="project-label">Project:</span>
                            <span className="project-name">{selectedProject?.name}</span>
                            <i className="pi pi-chevron-down"></i>
                        </div>
                        <div className="project-counts">
                            <span className="count-item">
                                <i className="pi pi-database"></i>
                                {projectDetails?.statistics?.corpus_count || selectedProject?.corpus_count || 0} corpus
                            </span>
                            <span className="count-item">
                                <i className="pi pi-star"></i>
                                {projectDetails?.statistics?.gold_standard_count || selectedProject?.gold_standard_count || 0} gold standard
                            </span>
                        </div>
                        {stats && (
                            <div className="header-stats">
                                <div className="stats-number">{stats.screened}/{stats.total}</div>
                                <div className="stats-label">My Progress</div>
                            </div>
                        )}
                    </div>
                </div>
                
                {stats && (
                    <ProgressBar value={stats.total > 0 ? (stats.screened / stats.total) * 100 : 0} showValue={false} className="progress-bar" />
                )}
            </Card>

            {!selectedProject ? (
                <Card className="select-project-prompt">
                    <i className="pi pi-folder-open" style={{ fontSize: '3rem', color: '#6366f1' }}></i>
                    <h3>Select a Project</h3>
                    <p>Choose a project from the dropdown above to start screening.</p>
                </Card>
            ) : (
                <TabView activeIndex={activeTab} onTabChange={(e) => {
                    setActiveTab(e.index);
                    if (e.index === 1 && corpusPapers.length === 0) {
                        loadCorpusPapers();
                    }
                }}>
                    {/* Screening Tab */}
                    <TabPanel header="Screen Papers" leftIcon="pi pi-pencil">
                        <div className="screening-content">
                            {/* Stats Summary */}
                            {stats && (
                                <div className="stats-summary">
                                    <div className="stat-item">
                                        <span className="stat-value">{stats.total}</span>
                                        <span className="stat-label">Total</span>
                                    </div>
                                    <div className="stat-item completed">
                                        <span className="stat-value">{stats.screened}</span>
                                        <span className="stat-label">Screened</span>
                                    </div>
                                    <div className="stat-item pending">
                                        <span className="stat-value">{stats.pending}</span>
                                        <span className="stat-label">Pending</span>
                                    </div>
                                    <ProgressBar 
                                        value={stats.total > 0 ? Math.round((stats.screened / stats.total) * 100) : 0} 
                                        className="progress-bar"
                                    />
                                </div>
                            )}

                            {/* Filter */}
                            <div className="filter-bar">
                                <Dropdown 
                                    value={filter}
                                    options={[
                                        { label: 'All Papers', value: 'all' },
                                        { label: 'Pending', value: 'pending' },
                                        { label: 'Completed', value: 'completed' }
                                    ]}
                                    onChange={(e) => { setFilter(e.value); }}
                                    className="filter-dropdown"
                                />
                                {/* NEW ADD for Calibration */}
                                <Dropdown 
                                    value={paperTypeFilter}
                                    options={[
                                        { label: `All Types (${papers.length})`, value: 'all' },
                                        { label: `Calibration (${papers.filter(p => p.is_calibration).length})`, value: 'calibration' },
                                        { label: `Evaluation (${papers.length - 10})`, value: 'evaluation' }
                                    ]}
                                    onChange={(e) => setPaperTypeFilter(e.value)}
                                    className="filter-dropdown"
                                    placeholder="Paper Type"
                                />
                                <Button label="Refresh" icon="pi pi-refresh" className="p-button-outlined" onClick={loadPapers} style={{marginLeft: '10px'}}/>
                                
                                {/* FEW-SHOT Management (Admin only) */}
                                {hasRole(userRoles, 'admin') && papers.length > 0 && (
                                    <>
                                        {papers.filter(p => p.is_calibration).length > 0 && (
                                            <>
                                                <Tag 
                                                    value={`${papers.filter(p => p.is_calibration).length} FEW-SHOT selected`}
                                                    severity="warning"
                                                    icon="pi pi-star"
                                                    style={{marginLeft: '10px'}}
                                                />
                                                <Button 
                                                    label="Clear All FEW-SHOT" 
                                                    icon="pi pi-times" 
                                                    className="p-button-danger p-button-outlined"
                                                    onClick={clearFewShotMarkers}
                                                    style={{marginLeft: '10px'}}
                                                    tooltip="Remove all FEW-SHOT markers"
                                                />
                                            </>
                                        )}
                                        {papers.filter(p => p.is_calibration).length === 0 && (
                                            <Message 
                                                severity="info" 
                                                text="Use checkboxes in table to select FEW-SHOT papers (10 required)"
                                                style={{marginLeft: '10px', padding: '0.5rem 1rem'}}
                                            />
                                        )}
                                    </>
                                )}
                            </div>                          

                            {/* Papers Table */}
                            <DataTable 
                                value={papers.filter(p => {
                                    // Status filter
                                    const statusMatch = filter === 'all' || 
                                        (filter === 'pending' && p.status === 'pending') ||
                                        (filter === 'completed' && p.status === 'completed');
                                    
                                    // Paper type filter
                                    const typeMatch = paperTypeFilter === 'all' ||
                                        (paperTypeFilter === 'calibration' && p.is_calibration === true) ||
                                        (paperTypeFilter === 'evaluation' && p.is_calibration === false);
                                    
                                    return statusMatch && typeMatch;
                                })} 
                                loading={loading}
                                paginator rows={10}
                                emptyMessage="No papers found"
                                className="papers-table"
                            >
                                {/* FEW-SHOT Checkbox Column (Admin only) */}
                                {hasRole(userRoles, 'admin') && (
                                    <Column 
                                        header="FEW-SHOT" 
                                        style={{ width: '90px', textAlign: 'center' }}
                                        body={(row) => (
                                            <Checkbox 
                                                checked={row.is_calibration === true}
                                                onChange={() => togglePaperFewShot(row)}
                                                disabled={row.status !== 'completed'}
                                                tooltip={row.status !== 'completed' ? 'Complete screening first' : (row.is_calibration ? 'Remove from FEW-SHOT' : 'Mark as FEW-SHOT')}
                                                tooltipOptions={{ position: 'top' }}
                                            />
                                        )}
                                    />
                                )}
                                <Column field="gs_id" header="ID" style={{ width: '80px' }} sortable />
                                <Column field="title" header="Title" style={{ maxWidth: '400px' }} 
                                        body={(row) => <span className="title-cell" title={row.title}>{row.title}</span>} />
                                <Column field="year" header="Year" style={{ width: '70px' }} sortable />
                                <Column header="Decision" body={decisionBodyTemplate} style={{ width: '120px' }} />
                                <Column field="pool" header="Pool" style={{ width: '60px' }} 
                                        body={(row) => row.pool ? <Tag value={row.pool} /> : '-'} />
                                <Column 
                                    field="is_calibration" 
                                    header="Type" 
                                    style={{ width: '100px' }}
                                    body={(row) => (
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                                            <Tag 
                                                value={row.is_calibration ? "FEW-SHOT" : "Evaluation"} 
                                                severity={row.is_calibration ? "warning" : "info"}
                                                style={{ fontSize: '0.75rem' }}
                                                icon={row.is_calibration ? "pi pi-star" : undefined}
                                            />
                                        </div>
                                    )}
                                />
                                <Column header="Status" body={statusBodyTemplate} style={{ width: '100px' }} />
                                <Column header="Actions" body={actionsBodyTemplate} style={{ width: '80px' }} />
                            </DataTable>
                        </div>
                    </TabPanel>

                    {/* Corpus Tab */}
                    <TabPanel header="Browse Corpus" leftIcon="pi pi-database">
                        <div className="corpus-content">
                            <div className="corpus-search">
                                <span className="p-input-icon-left">
                                    <i className="pi pi-search" />
                                    <InputText 
                                        value={corpusSearch}
                                        onChange={(e) => setCorpusSearch(e.target.value)}
                                        placeholder="Search corpus..."
                                        onKeyPress={(e) => e.key === 'Enter' && loadCorpusPapers(1, corpusSearch)}
                                    />
                                </span>
                                <Button label="Search" onClick={() => loadCorpusPapers(1, corpusSearch)} style={{marginLeft: '10px', marginRight: '10px'}}/>
                                <span className="corpus-total">Total: {corpusTotal} papers</span>
                            </div>

                            <DataTable 
                                value={corpusPapers}
                                loading={corpusLoading}
                                emptyMessage="No papers found"
                                className="corpus-table"
                            >
                                <Column field="corpus_id" header="ID" style={{ width: '100px' }} />
                                <Column field="title" header="Title" />
                                <Column field="year" header="Year" style={{ width: '70px' }} />
                                <Column field="venue" header="Venue" style={{ width: '150px' }} />
                            </DataTable>

                            <Paginator 
                                first={(corpusPage - 1) * 20}
                                rows={20}
                                totalRecords={corpusTotal}
                                onPageChange={(e) => loadCorpusPapers(e.page + 1, corpusSearch)}
                            />
                        </div>
                    </TabPanel>

                    {/* Disagreements Tab */}
                    {(hasRole(userRoles, 'resolver') || hasRole(userRoles, 'admin')) && (
                        <TabPanel header="Disagreements" leftIcon="pi pi-exclamation-triangle">
                            <div style={{ marginBottom: '1rem', display: 'flex', justifyContent: 'flex-end' }}>
                                <Button 
                                    label="Refresh" 
                                    icon="pi pi-refresh" 
                                    onClick={loadDisagreements}
                                    className="p-button-outlined"
                                    tooltip="Reload disagreements"
                                />
                            </div>
                            <div className="disagreements-content">
                                <DataTable 
                                    value={disagreements}
                                    emptyMessage="No disagreements found"
                                    className="disagreements-table"
                                    paginator
                                    rows={20}
                                    sortField="gs_id"
                                    sortOrder={1} 
                                >
                                    <Column field="gs_id" header="ID" style={{ width: '80px' }} />
                                    <Column field="title" header="Title" />
                                    <Column header="Decisions" body={(row) => (
                                        <div className="decision-badges">
                                            {row.decisions?.map((d, i) => (
                                                <Tag key={i} severity={decisionSeverity(d.decision)} value={`${d.user}: ${d.decision}`} />
                                            ))}
                                        </div>
                                    )} />
                                    <Column header="Status" body={(row) => (
                                        row.resolved 
                                            ? <Tag severity="success" value="Resolved" />
                                            : <Tag severity="warning" value="Pending" />
                                    )} style={{ width: '100px' }} />
                                    <Column header="Actions" body={(row) => (
                                        row.resolved ? null : (
                                            <Button 
                                                icon="pi pi-check" 
                                                className="p-button-rounded p-button-success p-button-text"
                                                onClick={() => openResolutionDialog(row)}
                                                tooltip="Resolve"
                                            />
                                        )
                                    )} style={{ width: '80px' }} />
                                </DataTable>
                            </div>
                        </TabPanel>
                    )}

                    {/* Statistics Tab */}
                    {hasRole(userRoles, 'admin') && (
                        <TabPanel header="Statistics" leftIcon="pi pi-chart-bar">
                            <div style={{ marginBottom: '1rem', display: 'flex', justifyContent: 'flex-end' }}>
                                <Button 
                                    label="Refresh" 
                                    icon="pi pi-refresh" 
                                    onClick={loadStatistics}
                                    className="p-button-outlined"
                                    tooltip="Reload project statistics"
                                />
                            </div>
                            {statistics ? (
                                <div className="statistics-grid">
                                    <div className="stats-panel">
                                        <Panel header="Project Overview">
                                            <div className="stats-list">
                                                <div className="stats-row"><span>Corpus:</span><strong>{statistics.corpus_count}</strong></div>
                                                <div className="stats-row"><span>Gold Standard:</span><strong>{statistics.gold_standard_count}</strong></div>
                                                <Divider />
                                                <div className="stats-row"><span>Cohen's Kappa:</span><strong>{statistics.agreement?.cohens_kappa ?? 'N/A'}</strong></div>
                                                <div className="stats-row"><span>Interpretation:</span><Tag value={statistics.agreement?.interpretation || 'N/A'} /></div>
                                                <div className="stats-row"><span>PABAK:</span><strong>{statistics.agreement?.pabak ?? 'N/A'}</strong></div>
                                                <div className="stats-row"><span>PABAK Interpretation:</span><Tag value={statistics.agreement?.pabak_interpretation || 'N/A'} /></div>
                                                <div className="stats-row"><span>Agreements:</span><strong>{statistics.agreement?.agreements ?? 0}/{statistics.agreement?.n ?? 0}</strong></div>
                                            </div>
                                        </Panel>
                                    </div>
                                    
                                    <div className="stats-panel">
                                        <Panel header="Screeners">
                                            {Object.entries(statistics.screeners || {}).map(([name, data]) => (
                                                <div key={name} className="screener-stats">
                                                    <strong>{name}</strong>
                                                    <div className="screener-details">
                                                        Total: {data.total} | Inc: {data.include} | Exc: {data.exclude} | Unc: {data.uncertain}
                                                    </div>
                                                </div>
                                            ))}
                                        </Panel>
                                    </div>

                                    <div className="stats-panel">
                                        <Panel header="FEW-SHOT Calibration Set">
                                            {statistics.fewshot && statistics.fewshot.total > 0 ? (
                                                <div className="screener-stats">
                                                    <div className="screener-details" style={{ fontSize: '1.1rem' }}>
                                                        <div style={{ marginBottom: '0.5rem' }}>
                                                            <strong>Total:</strong> {statistics.fewshot.total} papers
                                                        </div>
                                                        <div>
                                                            Inc: {statistics.fewshot.include} | Exc: {statistics.fewshot.exclude} | Unc: {statistics.fewshot.uncertain}
                                                        </div>
                                                    </div>
                                                </div>
                                            ) : (
                                                <div style={{ padding: '1rem', textAlign: 'center', color: '#888' }}>
                                                    <i className="pi pi-info-circle" style={{ fontSize: '2rem', marginBottom: '0.5rem' }}></i>
                                                    <p>No FEW-SHOT papers selected yet.</p>
                                                    <p style={{ fontSize: '0.9rem' }}>Go to "Screen Papers" tab to select calibration papers.</p>
                                                </div>
                                            )}
                                        </Panel>
                                    </div>

                                    <div className="stats-panel full-width">
                                        <Button label="Export Results" icon="pi pi-download" onClick={exportResults} className="p-button-success" />
                                    </div>
                                </div>
                            ) : <Skeleton height="200px" />}
                        </TabPanel>
                    )}

                    {/* Blockchain Audit Tab */}
                    {hasRole(userRoles, 'admin') && (
                        <TabPanel header="Blockchain Audit" leftIcon="pi pi-shield mr-2">
                            {auditLoading ? (
                                <Skeleton height="400px" />
                            ) : (
                                <div className="audit-container">
                                    {/* Audit Header */}
                                    <div className="audit-header-section">
                                        <div className="audit-title-row">
                                            <div className="audit-title">
                                                <i className="pi pi-shield"></i>
                                                <h3>Blockchain Audit Trail</h3>
                                            </div>
                                            <div className="audit-actions">
                                                <Dropdown
                                                    placeholder="Export Milestone..."
                                                    options={[
                                                        { label: 'Protocol Registered', value: 'protocol_registered' },
                                                        { label: 'Gold Standard Complete', value: 'gold_standard_complete' },
                                                        { label: 'LLM Screening Complete', value: 'llm_screening_complete' },
                                                        { label: 'Final Corpus', value: 'final_corpus' }
                                                    ]}
                                                    onChange={(e) => createAuditExport(e.value)}
                                                    className="milestone-dropdown"
                                                />
                                                <Dropdown
                                                    placeholder="Inclusion List Job..."
                                                    options={llmJobs.map(j => ({
                                                        label: `${(j.strategies && j.strategies[0]) || 'N/A'} / ${j.models || j.model || 'N/A'} / ${j.prompt_mode || 'N/A'} (${j.data_source || '?'}) [${j.decisions_count || 0} dec]`,
                                                        value: j.job_id
                                                    }))}
                                                    value={selectedInclusionJobId}
                                                    onChange={(e) => setSelectedInclusionJobId(e.value)}
                                                    showClear
                                                    className="milestone-dropdown"
                                                    tooltip="Select LLM job for final inclusion list (Section F)"
                                                    tooltipOptions={{ position: 'bottom' }}
                                                />
                                                <Button
                                                    label="Quick Export"
                                                    icon="pi pi-file-export"
                                                    onClick={() => createAuditExport('quick_export')}
                                                    loading={auditActionLoading === 'export'}
                                                    className="p-button-outlined"
                                                />
                                                <Button 
                                                    label="Refresh Status" 
                                                    icon="pi pi-refresh" 
                                                    onClick={() => loadAuditStatus()}
                                                    loading={auditLoading}
                                                    className="p-button-outlined p-button-secondary"
                                                    tooltip="Check for timestamp confirmations"
                                                />
                                                <Button 
                                                    label="Verify File" 
                                                    icon="pi pi-verified" 
                                                    onClick={() => setVerifyDialogVisible(true)}
                                                    className="p-button-outlined p-button-secondary"
                                                />
                                            </div>
                                        </div>

                                        <Message 
                                            severity="info" 
                                            className="audit-info-message"
                                            text="Exports are anchored to Bitcoin via OpenTimestamps for independent verification. Download packages include JSON + OTS proof files for Zenodo submission." 
                                        />
                                    </div>

                                    {/* Current Status */}
                                    {auditStatus && (
                                        <div className="audit-status-section">
                                            <Panel header="Current Audit Status">
                                                <div className="audit-stats-grid">
                                                    <div className="audit-stat-item">
                                                        <span className="audit-stat-label">Total Decisions</span>
                                                        <span className="audit-stat-value">{auditStatus.stats?.total_decisions || 0}</span>
                                                    </div>
                                                    <div className="audit-stat-item">
                                                        <span className="audit-stat-label">Blockchain Logged</span>
                                                        <span className="audit-stat-value">{auditStatus.stats?.blockchain_logged || 0}</span>
                                                    </div>
                                                    <div className="audit-stat-item">
                                                        <span className="audit-stat-label">Audit Exports</span>
                                                        <span className="audit-stat-value">{auditStatus.exports?.length || 0}</span>
                                                    </div>
                                                    <div className="audit-stat-item">
                                                        <span className="audit-stat-label">Merkle Leaves</span>
                                                        <span className="audit-stat-value">
                                                            {auditStatus.exports?.reduce((sum, e) => sum + (e.merkle_leaf_count || 0), 0).toLocaleString()}
                                                        </span>
                                                    </div>
                                                    <div className="audit-stat-item">
                                                        <span className="audit-stat-label">Timestamped</span>
                                                        <span className="audit-stat-value">
                                                            {auditStatus.exports?.filter(e => e.ots_status === 'confirmed').length || 0}
                                                        </span>
                                                    </div>
                                                </div>
                                            </Panel>
                                        </div>
                                    )}

                                    {/* Exports Table */}
                                    <Panel header="Audit Exports" className="audit-exports-panel">
                                        {auditStatus?.exports?.length > 0 ? (
                                            <DataTable 
                                                value={auditStatus.exports} 
                                                size="small" 
                                                className="audit-table"
                                                emptyMessage="No audit exports yet"
                                                sortField="created_at"
                                                sortOrder={-1}
                                            >
                                                <Column 
                                                    header="Milestone" 
                                                    body={(row) => (
                                                        <div className="milestone-cell">
                                                            {renderMilestoneIcon(row.milestone)}
                                                            <span>{row.milestone_label || row.milestone}</span>
                                                        </div>
                                                    )} 
                                                    style={{ width: '200px' }} 
                                                />
                                                <Column 
                                                    header="File" 
                                                    body={(row) => (
                                                        <div className="filename-cell">
                                                            <code>{row.filename}</code>
                                                            <small>{formatFileSize(row.file_size)}</small>
                                                        </div>
                                                    )} 
                                                    style={{ minWidth: '250px' }} 
                                                />
                                                <Column 
                                                    header="Merkle Root" 
                                                    body={(row) => (
                                                        <>
                                                            <Tooltip target={`.merkle-${row.export_id}`} content={row.merkle_root} />
                                                            <code className={`merkle-root merkle-${row.export_id}`}>
                                                                {row.merkle_root?.substring(0, 16)}...
                                                            </code>
                                                        </>
                                                    )} 
                                                    style={{ width: '180px' }} 
                                                />
                                                <Column
                                                    header="Created"
                                                    body={(row) => formatDateTime(row.created_at)}
                                                    style={{ width: '160px' }}
                                                />
                                                <Column
                                                    header="Blockchain TX"
                                                    body={(row) => (
                                                        row.blockchain_tx_id && !row.blockchain_tx_id.startsWith('ERROR') && row.blockchain_tx_id !== 'unknown' ? (
                                                            <div className="tx-cell">
                                                                <Tooltip target={`.tx-${row.export_id}`} content={row.blockchain_tx_id} />
                                                                <code className={`tx-hash tx-${row.export_id}`}>
                                                                    {row.blockchain_tx_id.substring(0, 12)}...
                                                                </code>
                                                                <i className="pi pi-check-circle" style={{ color: 'green', marginLeft: '4px' }} />
                                                            </div>
                                                        ) : (
                                                            <span className="tx-missing">
                                                                <i className="pi pi-exclamation-triangle" style={{ color: 'orange' }} />
                                                                {' '}Not logged
                                                            </span>
                                                        )
                                                    )}
                                                    style={{ width: '180px' }}
                                                />
                                                <Column
                                                    header="Bitcoin Status"
                                                    body={(row) => renderAuditStatusBadge(row.ots_status)} 
                                                    style={{ width: '180px' }} 
                                                />
                                                <Column 
                                                    header="Actions" 
                                                    body={(row) => (
                                                        <div className="audit-action-buttons">
                                                            {row.ots_status === 'not_timestamped' && (
                                                                <Button 
                                                                    icon="pi pi-clock" 
                                                                    className="p-button-rounded p-button-warning p-button-text"
                                                                    tooltip="Submit to OpenTimestamps"
                                                                    onClick={() => submitToTimestamp(row.export_id)}
                                                                    loading={auditActionLoading === `timestamp-${row.export_id}`}
                                                                />
                                                            )}
                                                            {row.ots_status === 'confirmed' && (
                                                                <Button 
                                                                    icon="pi pi-download" 
                                                                    className="p-button-rounded p-button-success p-button-text"
                                                                    tooltip="Download OTS Proof"
                                                                    onClick={() => downloadProof(row.export_id)}
                                                                    loading={auditActionLoading === `download-${row.export_id}`}
                                                                />
                                                            )}
                                                            {row.blockchain_tx_id && (
                                                                <Button 
                                                                    icon="pi pi-info-circle" 
                                                                    className="p-button-rounded p-button-info p-button-text"
                                                                    tooltip="View Transaction Details"
                                                                    onClick={() => viewTransaction(row.blockchain_tx_id)}
                                                                />
                                                            )}
                                                        </div>
                                                    )} 
                                                    style={{ width: '140px' }} 
                                                />
                                            </DataTable>
                                        ) : (
                                            <div className="audit-empty">
                                                <i className="pi pi-inbox"></i>
                                                <p>No audit exports yet. Create your first export using the buttons above.</p>
                                            </div>
                                        )}
                                    </Panel>

                                    {/* Instructions Panel */}
                                    <Panel header="Verification Instructions" toggleable collapsed className="audit-instructions-panel">
                                        <div className="instructions-content">
                                            <h4>Three-Tier Verification Model</h4>
                                            <ol>
                                                <li>
                                                    <strong>Operational Layer (Antelope Blockchain)</strong>
                                                    <p>Every screening decision is logged to the private Antelope blockchain with transaction ID for detailed audit trail.</p>
                                                </li>
                                                <li>
                                                    <strong>Temporal Anchor (OpenTimestamps + Bitcoin)</strong>
                                                    <p>Merkle root of export files is timestamped on Bitcoin blockchain for independent verification of "when" data existed.</p>
                                                </li>
                                                <li>
                                                    <strong>Archival Layer (Zenodo)</strong>
                                                    <p>Final export files with OTS proofs are published to Zenodo with DOI for permanent archival and citation.</p>
                                                </li>
                                            </ol>

                                            <h4>How to Verify</h4>
                                            <ol>
                                                <li>Download the JSON export file and the .ots proof file</li>
                                                <li>Install OpenTimestamps client: <code>pip install opentimestamps-client</code></li>
                                                <li>Run verification: <code>ots verify export_file.json.ots</code></li>
                                                <li>The tool will confirm the Bitcoin block and timestamp</li>
                                            </ol>
                                        </div>
                                    </Panel>
                                </div>
                            )}
                        </TabPanel>
                    )}
                    
                    {/* LLM Screening Tab */}
                    {hasRole(userRoles, 'admin') && (
                        <TabPanel header="LLM Screening" leftIcon="pi pi-microchip">
                            <LLMScreening 
                                selectedProject={selectedProject}
                                userRoles={userRoles}
                                username={user}
                                toast={toast}
                            />
                        </TabPanel>
                    )}
                    
                    {/* Admin Dashboard Tab */}
                    {hasRole(userRoles, 'admin') && (
                        <TabPanel header="Admin Dashboard" leftIcon="pi pi-cog">
                            <AdminDashboard 
                                toast={toast}
                                currentUser={user}
                            />
                        </TabPanel>
                    )}
                    
                    {/* User Action Log Tab */}
                    <TabPanel header="My Actions" leftIcon="pi pi-history">
                        <UserActionLog 
                            currentUser={user}
                            selectedProject={selectedProject}
                            toast={toast}
                        />
                    </TabPanel>
                </TabView>
            )}

            {/* Project Sidebar */}
            <Sidebar visible={projectSidebarVisible} onHide={() => setProjectSidebarVisible(false)} className="project-sidebar">
                <h3>Select Project</h3>
                <div className="project-list">
                    {projects.map(project => (
                        <div key={project.project_id}
                             className={`project-item ${selectedProject?.project_id === project.project_id ? 'selected' : ''}`}
                             onClick={() => { setSelectedProject(project); setProjectSidebarVisible(false); }}>
                            <div className="project-item-header">
                                <strong>{project.name}</strong>
                                {projectStatusTag(project.status)}
                            </div>
                            <div className="project-item-id">{project.project_id}</div>
                            <div className="project-item-counts">
                                <span>📚 {project.stats?.corpus_count || project.corpus_count || 0} papers</span>
                                <span>⭐ {project.stats?.gold_standard_count || project.gold_standard_count || 0} GS</span>
                                <span>✓ {project.stats?.my_completed || 0} done</span>
                            </div>
                        </div>
                    ))}
                </div>
            </Sidebar>

            {/* Screening Dialog with Criteria Checkboxes */}
            <Dialog header={selectedPaper ? `${selectedPaper.gs_id}: ${selectedPaper.title}` : 'Paper'}
                    visible={dialogVisible} className="screening-dialog" onHide={() => setDialogVisible(false)}
                    style={{ width: '800px' }}
                    footer={
                        <div className="dialog-footer">
                            <Button label="Cancel" icon="pi pi-times" className="p-button-text" onClick={() => setDialogVisible(false)} />
                            <Button label="Save Decision" icon="pi pi-check" onClick={submitDecision} loading={submitting}
                                    disabled={!decision || !confidence || !isCriteriaValid()} />
                        </div>
                    }>
                {selectedPaper && (
                    <div className="paper-details">
                        <div className="paper-metadata">
                            <span><i className="pi pi-calendar"></i>{selectedPaper.year || 'N/A'}</span>
                            <span title="Publication venue">
                                <i className="pi pi-building"></i>
                                {selectedPaper.venue || selectedPaper.source_name || 
                                 (selectedPaper.type && selectedPaper.type !== 'unknown' ? selectedPaper.type : '') ||
                                 (selectedPaper.data_sources && selectedPaper.data_sources.length > 0 
                                  ? `Source: ${selectedPaper.data_sources.join(', ')}` 
                                  : 'N/A')}
                            </span>
                            {selectedPaper.pool && <span><i className="pi pi-tag"></i>Pool {selectedPaper.pool}</span>}
                            {selectedPaper.doi && (
                                <span><i className="pi pi-link"></i>
                                    <a href={`https://doi.org/${selectedPaper.doi}`} target="_blank" rel="noreferrer">{selectedPaper.doi}</a>
                                </span>
                            )}
                        </div>

                        <div className="paper-authors"><strong>Authors:</strong> {selectedPaper.authors?.join(', ') || 'N/A'}</div>

                        {selectedPaper.all_keywords && selectedPaper.all_keywords.length > 0 && (
                            <div className="paper-keywords" style={{ marginTop: '1rem', marginBottom: '1rem' }}>
                                <strong>Keywords:</strong>
                                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginTop: '0.5rem' }}>
                                    {selectedPaper.all_keywords.map((keyword, idx) => (
                                        <Tag key={idx} value={keyword} severity="info" style={{ fontSize: '0.9rem' }} />
                                    ))}
                                </div>
                            </div>
                        )}

                        <Panel header="Abstract" className="abstract-panel">
                            <p className="abstract-text">{selectedPaper.abstract || 'No abstract available.'}</p>
                        </Panel>

                        <Divider />

                        <h4>Your Decision</h4>
                        
                        <div className="form-field">
                            <label>Decision *</label>
                            <div className="radio-group">
                                {['INCLUDE', 'EXCLUDE', 'UNCERTAIN'].map(opt => (
                                    <div key={opt} className="radio-item">
                                        <RadioButton inputId={opt} name="decision" value={opt}
                                                     onChange={(e) => setDecision(e.value)} checked={decision === opt} />
                                        <label htmlFor={opt}>{opt}</label>
                                    </div>
                                ))}
                            </div>
                        </div>

                        <div className="form-field">
                            <label>Confidence *</label>
                            <div className="radio-group">
                                {['HIGH', 'MEDIUM', 'LOW'].map(opt => (
                                    <div key={opt} className="radio-item">
                                        <RadioButton inputId={`conf-${opt}`} name="confidence" value={opt}
                                                     onChange={(e) => setConfidence(e.value)} checked={confidence === opt} />
                                        <label htmlFor={`conf-${opt}`}>{opt}</label>
                                    </div>
                                ))}
                            </div>
                        </div>

                        {/* Criteria Checkboxes */}
                        {renderCriteriaCheckboxes()}
                    </div>
                )}
            </Dialog>

            {/* Resolution Dialog */}
            <Dialog header={`Resolve: ${selectedDisagreement?.gs_id}`}
                    visible={resolutionDialogVisible} className="resolution-dialog" 
                    style={{ width: '800px' }}
                    onHide={() => setResolutionDialogVisible(false)}
                    footer={
                        <div className="dialog-footer">
                            <Button label="Cancel" icon="pi pi-times" className="p-button-text" onClick={() => setResolutionDialogVisible(false)} />
                            <Button label="Save Resolution" icon="pi pi-check" onClick={submitResolution} loading={submitting}
                                    disabled={!finalDecision || !finalConfidence} className="p-button-success" />
                        </div>
                    }>
                {selectedDisagreement && (
                    <div className="resolution-content">
                        <h4>{selectedDisagreement.title}</h4>
                        
                        <Panel header="Abstract" className="abstract-panel">
                            <p className="abstract-text">{selectedDisagreement.abstract}</p>
                        </Panel>

                        <Panel header="Screener Decisions" className="decisions-panel">
                            {selectedDisagreement.decisions.map((d, i) => (
                                <div key={i} className="screener-decision">
                                    <strong>{d.user}:</strong>{' '}
                                    <Tag severity={d.decision === 'INCLUDE' ? 'success' : d.decision === 'EXCLUDE' ? 'danger' : 'warning'} value={d.decision} />
                                    <span className="confidence">({d.confidence})</span>
                                    <p className="decision-reason">{d.reason}</p>
                                </div>
                            ))}
                        </Panel>

                        <Divider />

                        <h4>Your Resolution</h4>

                        <div className="form-field">
                            <label>Final Decision *</label>
                            <div className="radio-group">
                                {['INCLUDE', 'EXCLUDE', 'UNCERTAIN'].map(opt => (
                                    <div key={opt} className="radio-item">
                                        <RadioButton inputId={`final-${opt}`} name="finalDecision" value={opt}
                                                     onChange={(e) => setFinalDecision(e.value)} checked={finalDecision === opt} />
                                        <label htmlFor={`final-${opt}`}>{opt}</label>
                                    </div>
                                ))}
                            </div>
                        </div>

                        <div className="form-field">
                            <label>Confidence *</label>
                            <div className="radio-group">
                                {['HIGH', 'MEDIUM', 'LOW'].map(opt => (
                                    <div key={opt} className="radio-item">
                                        <RadioButton inputId={`res-conf-${opt}`} name="finalConfidence" value={opt}
                                                     onChange={(e) => setFinalConfidence(e.value)} checked={finalConfidence === opt} />
                                        <label htmlFor={`res-conf-${opt}`}>{opt}</label>
                                    </div>
                                ))}
                            </div>
                        </div>

                        {/* Resolution Criteria */}
                        <div className="criteria-selection">
                            {(finalDecision === 'INCLUDE' || finalDecision === 'UNCERTAIN') && (
                                <div className="criteria-group inclusion-group">
                                    <h5 className="criteria-header include-header">
                                        <i className="pi pi-check-circle"></i> Inclusion Criteria (IC)
                                        {finalDecision === 'INCLUDE' && <span className="required-badge">* Select at least one</span>}
                                    </h5>
                                    <div className="criteria-checkboxes">
                                        {INCLUSION_CRITERIA.map(criterion => (
                                            <div key={criterion.code} className="criteria-checkbox-item">
                                                <Checkbox 
                                                    inputId={`res-ic-${criterion.code}`}
                                                    checked={resolutionCriteriaMet.includes(criterion.code)}
                                                    onChange={(e) => {
                                                        if (e.checked) {
                                                            setResolutionCriteriaMet([...resolutionCriteriaMet, criterion.code]);
                                                        } else {
                                                            setResolutionCriteriaMet(resolutionCriteriaMet.filter(c => c !== criterion.code));
                                                        }
                                                    }}
                                                />
                                                <label htmlFor={`res-ic-${criterion.code}`} className="criteria-label">
                                                    <strong>{criterion.code}:</strong> {criterion.text}
                                                </label>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {(finalDecision === 'EXCLUDE' || finalDecision === 'UNCERTAIN') && (
                                <div className="criteria-group exclusion-group">
                                    <h5 className="criteria-header exclude-header">
                                        <i className="pi pi-times-circle"></i> Exclusion Criteria (EC)
                                        {finalDecision === 'EXCLUDE' && <span className="required-badge">* Select at least one</span>}
                                    </h5>
                                    <div className="criteria-checkboxes">
                                        {EXCLUSION_CRITERIA.map(criterion => (
                                            <div key={criterion.code} className="criteria-checkbox-item">
                                                <Checkbox 
                                                    inputId={`res-ec-${criterion.code}`}
                                                    checked={resolutionCriteriaViolated.includes(criterion.code)}
                                                    onChange={(e) => {
                                                        if (e.checked) {
                                                            setResolutionCriteriaViolated([...resolutionCriteriaViolated, criterion.code]);
                                                        } else {
                                                            setResolutionCriteriaViolated(resolutionCriteriaViolated.filter(c => c !== criterion.code));
                                                        }
                                                    }}
                                                />
                                                <label htmlFor={`res-ec-${criterion.code}`} className="criteria-label">
                                                    <strong>{criterion.code}:</strong> {criterion.text}
                                                </label>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}

                            <div className="form-field additional-notes">
                                <label>Additional Notes (optional)</label>
                                <InputTextarea 
                                    value={resolutionNotes} 
                                    onChange={(e) => setResolutionNotes(e.target.value)}
                                    rows={2} 
                                    className="notes-textarea" 
                                    placeholder="Optional additional notes or explanation..." 
                                />
                            </div>
                        </div>
                    </div>
                )}
            </Dialog>

            {/* Verify File Dialog */}
            <Dialog 
                header="Verify Export File" 
                visible={verifyDialogVisible} 
                className="verify-dialog"
                onHide={() => { setVerifyDialogVisible(false); setVerifyFile(null); setVerifyResult(null); }}
                footer={
                    <div className="dialog-footer">
                        <Button label="Close" icon="pi pi-times" className="p-button-text" 
                                onClick={() => { setVerifyDialogVisible(false); setVerifyFile(null); setVerifyResult(null); }} />
                        <Button label="Verify" icon="pi pi-check" onClick={handleVerifyFile} 
                                loading={auditActionLoading === 'verify'}
                                disabled={!verifyFile} />
                    </div>
                }
            >
                <div className="verify-content">
                    <p>Upload an export JSON file to verify its integrity against stored audit records.</p>
                    
                    <input
                        type="file"
                        accept=".json"
                        onChange={(e) => { setVerifyFile(e.target.files[0] || null); }}
                        style={{ marginBottom: '1rem' }}
                    />

                    {verifyFile && (
                        <div className="selected-file">
                            <i className="pi pi-file"></i>
                            <span>{verifyFile.name}</span>
                        </div>
                    )}

                    {verifyResult && (
                        <div className={`verify-result ${verifyResult.valid ? 'valid' : 'invalid'}`}>
                            <i className={`pi ${verifyResult.valid ? 'pi-check-circle' : 'pi-times-circle'}`}></i>
                            <div className="verify-result-content">
                                <strong>{verifyResult.valid ? 'Verification Successful' : 'Verification Failed'}</strong>
                                <p>{verifyResult.message}</p>
                                {verifyResult.matched_export && (
                                    <small>Matched export: {verifyResult.matched_export.filename} ({formatDateTime(verifyResult.matched_export.created_at)})</small>
                                )}
                            </div>
                        </div>
                    )}
                </div>
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
                    <div className="tx-loading">
                        <i className="pi pi-spin pi-spinner" style={{ fontSize: '2rem' }}></i>
                        <p>Loading transaction data...</p>
                    </div>
                ) : txData && (
                    <div className="tx-details">
                        {/* Status Badge */}
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

                        {/* Transaction Info */}
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

export default Screening;
