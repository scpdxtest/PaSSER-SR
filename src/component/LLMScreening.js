/**
 * LLMScreening.js (v1.0)
 * ======================
 * React component for LLM-based automated screening
 * 
 * Features:
 *   - Model selection and loading
 *   - Strategy selection (S1-S5)
 *   - Data source selection (corpus/gold standard)
 *   - Zero-shot / Few-shot mode
 *   - Real-time progress via WebSocket
 *   - Results download
 * 
 * Author: PaSSER-SR Team
 * Date: January 2026
 * Version: 1.0
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';

// PrimeReact Components
import { Card } from 'primereact/card';
import { Button } from 'primereact/button';
import { Dropdown } from 'primereact/dropdown';
import { MultiSelect } from 'primereact/multiselect';
import { InputText } from 'primereact/inputtext';
import { ProgressBar } from 'primereact/progressbar';
import { Tag } from 'primereact/tag';
import { Panel } from 'primereact/panel';
import { DataTable } from 'primereact/datatable';
import { Column } from 'primereact/column';
import { Toast } from 'primereact/toast';
import { Divider } from 'primereact/divider';
import { Message } from 'primereact/message';
import { Checkbox } from 'primereact/checkbox';
import { SelectButton } from 'primereact/selectbutton';
import { Timeline } from 'primereact/timeline';
import { Dialog } from 'primereact/dialog';
import { Chip } from 'primereact/chip';
import { Badge } from 'primereact/badge';

import configuration from './configuration.json';

// Configuration - LLM Screening API runs locally on each user's Mac (Apple Silicon MLX)
const LLM_API_BASE = configuration.passer.LLMScreeningAPI || 'http://localhost:9902';
const LLM_WS_URL = LLM_API_BASE.replace(/^http/, 'ws') + '/ws/llm/progress';

// =============================================================================
// HELPERS
// =============================================================================

const formatDuration = (seconds) => {
    if (!seconds) return '-';
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}m ${secs}s`;
};

const estimateTimeRemaining = (processedThisSession, totalProcessed, totalPapers, elapsedSeconds) => {
    if (processedThisSession === 0) return 'Calculating...';
    const rate = processedThisSession / elapsedSeconds;
    const remaining = (totalPapers - totalProcessed) / rate;
    if (remaining < 60) return `~${Math.ceil(remaining)}s remaining`;
    if (remaining < 3600) return `~${Math.ceil(remaining / 60)}m remaining`;
    return `~${(remaining / 3600).toFixed(1)}h remaining`;
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

// =============================================================================
// MAIN COMPONENT
// =============================================================================

const LLMScreening = ({ selectedProject, userRoles, username, toast }) => {
    // Service status
    const [serviceStatus, setServiceStatus] = useState(null);
    const [models, setModels] = useState([]);
    const [strategies, setStrategies] = useState([]);
    
    // Configuration
    const [selectedModels, setSelectedModels] = useState([]);
    const [selectedStrategies, setSelectedStrategies] = useState([]);
    const [dataSource, setDataSource] = useState('corpus');
    const [promptMode, setPromptMode] = useState('zero_shot');
    const [outputFilename, setOutputFilename] = useState('');
    const [evaluationOnly, setEvaluationOnly] = useState(true);
    const [saveToMongoDB, setSaveToMongoDB] = useState(true);
    const [resumeJobId, setResumeJobId] = useState('');  // NEW: Resume from specific job
    const [s5FastFilter, setS5FastFilter] = useState('');
    const [s5DebateModels, setS5DebateModels] = useState([]);
    // UNCERTAIN treatment for metrics
    const [uncertainTreatment, setUncertainTreatment] = useState('INCLUDE');
    const [metricsLoading, setMetricsLoading] = useState(false);
    const [evaluationMetrics, setEvaluationMetrics] = useState(null);
    // Metrics dialog state
    const [metricsDialogVisible, setMetricsDialogVisible] = useState(false);
    const [selectedJobForMetrics, setSelectedJobForMetrics] = useState(null);
    const [comparisonResults, setComparisonResults] = useState(null);
    const [comparisonDialogVisible, setComparisonDialogVisible] = useState(false);
    const [legendVisible, setLegendVisible] = useState(false);
    // Error Analysis state
    const [errorAnalysis, setErrorAnalysis] = useState(null);
    const [errorAnalysisLoading, setErrorAnalysisLoading] = useState(false);
    const [errorAnalysisDialogVisible, setErrorAnalysisDialogVisible] = useState(false);
    // Job state
    const [activeJob, setActiveJob] = useState(null);
    const [jobProgress, setJobProgress] = useState(null);
    const [jobs, setJobs] = useState([]);
    const [resumableJobs, setResumableJobs] = useState([]);  // NEW: Jobs that can be resumed
    const [progressLog, setProgressLog] = useState([]);
    
    // WebSocket
    const wsRef = useRef(null);
    const [wsConnected, setWsConnected] = useState(false);
    
    // UI state
    const [loading, setLoading] = useState(false);
    const [loadingModel, setLoadingModel] = useState(null);
    const [jobDialogVisible, setJobDialogVisible] = useState(false);
    const [selectedJobDetails, setSelectedJobDetails] = useState(null);

    // Few-shot examples state
    const [fewShotExamples, setFewShotExamples] = useState([]);
    const [fewShotLoading, setFewShotLoading] = useState(false);
    const [fewShotReady, setFewShotReady] = useState(false);
    const [fewShotMissing, setFewShotMissing] = useState([]);
    const [fewShotDialogVisible, setFewShotDialogVisible] = useState(false);
    
    // Gold standard papers count
    const [goldStandardTotal, setGoldStandardTotal] = useState(null);

    // Job selection state
    const [selectedJobs, setSelectedJobs] = useState([]);
    const [selectAllJobs, setSelectAllJobs] = useState(false);

    // Job start time for ETA calculation
    const jobStartTimeRef = useRef(null);

    // Auto-fill form when resumable job is selected
    useEffect(() => {
        if (resumeJobId && resumableJobs.length > 0) {
            const selectedJob = resumableJobs.find(j => j.job_id === resumeJobId);
            if (selectedJob) {
                // Auto-populate form fields from selected job
                setSelectedModels(selectedJob.models || []);
                setSelectedStrategies(selectedJob.strategies || []);
                setPromptMode(selectedJob.prompt_mode || 'zero_shot');
                setDataSource(selectedJob.data_source || 'corpus');
                setEvaluationOnly(selectedJob.evaluation_only !== undefined ? selectedJob.evaluation_only : true);
            }
        }
    }, [resumeJobId, resumableJobs]);

    // ==========================================================================
    // API CALLS
    // ==========================================================================

    const fetchStatus = async () => {
        try {
            const response = await fetch(`${LLM_API_BASE}/api/llm/status`);
            const data = await response.json();
            setServiceStatus(data);
        } catch (error) {
            console.error('Failed to fetch status:', error);
            setServiceStatus({ status: 'offline', error: error.message });
        }
    };

    const fetchModels = async () => {
        try {
            const response = await fetch(`${LLM_API_BASE}/api/llm/models`);
            const data = await response.json();
            setModels(data.models);
        } catch (error) {
            console.error('Failed to fetch models:', error);
        }
    };

    const fetchStrategies = async () => {
        try {
            const response = await fetch(`${LLM_API_BASE}/api/llm/strategies`);
            const data = await response.json();
            setStrategies(data.strategies);
        } catch (error) {
            console.error('Failed to fetch strategies:', error);
        }
    };

    const fetchJobs = async () => {
        try {
            // Fetch jobs filtered by current project if one is selected
            const projectParam = selectedProject?.project_id ? `?project_id=${selectedProject.project_id}` : '';
            console.log(`Fetching LLM jobs for project:`, selectedProject?.project_id, `Project name:`, selectedProject?.project_name);
            const response = await fetch(`${LLM_API_BASE}/api/llm/jobs${projectParam}`);
            const data = await response.json();
            console.log('LLM jobs response:', data);
            setJobs(data.jobs || []);
            
            // Extract gold standard total from completed gold_standard jobs
            const goldStandardJobs = (data.jobs || []).filter(j => j.data_source === 'gold_standard' && j.total_papers);
            if (goldStandardJobs.length > 0) {
                // Use the most recent job's total_papers count
                setGoldStandardTotal(goldStandardJobs[0].total_papers);
            }
        } catch (error) {
            console.error('Failed to fetch jobs:', error);
        }
    };

    // ==========================================================================
    // ERROR ANALYSIS
    // ==========================================================================

    const fetchErrorAnalysis = async (config) => {
        /**
         * Fetch detailed error analysis from backend.
         *
         * @param {Object} config - Configuration with strategy, model, prompt_mode
         */
        if (!selectedProject?.project_id) {
            toast.current?.show({
                severity: 'warn',
                summary: 'Warning',
                detail: 'Please select a project first'
            });
            return;
        }
        
        setErrorAnalysisLoading(true);
        
        try {
            const response = await fetch(`${LLM_API_BASE}/api/llm/error-analysis`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    project_id: selectedProject.project_id,
                    strategy: config?.strategy || null,
                    model: config?.model || null,
                    prompt_mode: config?.prompt_mode || null,
                    uncertain_treatment: uncertainTreatment,
                    job_id: config?.job_id || null
                })
            });
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to fetch error analysis');
            }
            
            const data = await response.json();
            setErrorAnalysis(data);
            setErrorAnalysisDialogVisible(true);
            
        } catch (error) {
            console.error('Error analysis failed:', error);
            toast.current?.show({
                severity: 'error',
                summary: 'Error Analysis Failed',
                detail: error.message,
                life: 5000
            });
        } finally {
            setErrorAnalysisLoading(false);
        }
    };

    const exportErrorAnalysisJSON = () => {
        if (!errorAnalysis) return;
        
        const blob = new Blob(
            [JSON.stringify(errorAnalysis, null, 2)], 
            { type: 'application/json' }
        );
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `error_analysis_${selectedProject.project_id}_${new Date().toISOString().slice(0,10)}.json`;
        a.click();
        URL.revokeObjectURL(url);
    };

    const exportComparisonJSON = () => {
        if (!comparisonResults) return;
        
        const blob = new Blob(
            [JSON.stringify(comparisonResults, null, 2)], 
            { type: 'application/json' }
        );
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `strategy_comparison_${selectedProject.project_id}_${new Date().toISOString().slice(0,10)}.json`;
        a.click();
        URL.revokeObjectURL(url);
        
        toast.current?.show({
            severity: 'success',
            summary: 'Export Complete',
            detail: 'Comparison results exported to JSON',
            life: 3000
        });
    };

    const exportComparisonXLSX = () => {
        if (!comparisonResults) return;
        
        try {
            const XLSX = require('xlsx');
            
            // Prepare data for export - flatten the results
            const exportData = comparisonResults.results.map(row => {
                const baseData = {
                    'Rank': row.rank,
                    'Status': row.qualified ? 'Qualified' : 'Unqualified',
                    'Strategy': row.strategy,
                    'Model(s)': row.model,
                    'Prompt Mode': row.prompt_mode,
                    'Recall (%)': (row.recall * 100).toFixed(2),
                    'Precision (%)': (row.precision * 100).toFixed(2),
                    'F1 (%)': (row.f1 * 100).toFixed(2),
                    'WSS@95 (%)': (row.wss_95 * 100).toFixed(2),
                    'TP': row.confusion_matrix?.TP || 0,
                    'TN': row.confusion_matrix?.TN || 0,
                    'FP': row.confusion_matrix?.FP || 0,
                    'FN': row.confusion_matrix?.FN || 0,
                    'Papers Evaluated': row.confusion_matrix ? 
                        (row.confusion_matrix.TP + row.confusion_matrix.TN + row.confusion_matrix.FP + row.confusion_matrix.FN) : 0
                };
                
                // Add S5 metrics if available
                if (row.s5_stage_metrics) {
                    baseData['S5 Stage 1 Excluded'] = row.s5_stage_metrics.st1_excl || 0;
                    baseData['S5 Stage 1 Rate (%)'] = row.s5_stage_metrics.st1_rate || 0;
                    baseData['S5 Stage 2 Papers'] = row.s5_stage_metrics.st2_papers || 0;
                    baseData['S5 Time Savings (%)'] = row.s5_stage_metrics.time_savings_pct || 0;
                    baseData['S5 Avg Stage 1 Time (s)'] = row.s5_stage_metrics.avg_st1_time_sec || 0;
                    baseData['S5 Avg Stage 2 Time (s)'] = row.s5_stage_metrics.avg_st2_time_sec || 0;
                    baseData['S5 Total Time (s)'] = row.s5_stage_metrics.total_time_sec || 0;
                    baseData['S5 Debate Calls Saved'] = row.s5_stage_metrics.debate_calls_saved || 0;
                    baseData['S5 Fast Filter'] = row.s5_stage_metrics.model_roles?.fast_filter || '';
                    baseData['S5 Debate Models'] = Array.isArray(row.s5_stage_metrics.model_roles?.debate) 
                        ? row.s5_stage_metrics.model_roles.debate.join(', ') 
                        : (row.s5_stage_metrics.model_roles?.debate || '');
                }
                
                return baseData;
            });
            
            // Create workbook
            const wb = XLSX.utils.book_new();
            
            // Add results sheet
            const ws = XLSX.utils.json_to_sheet(exportData);
            
            // Set column widths (includes S5 columns if present)
            ws['!cols'] = [
                { wch: 6 },  // Rank
                { wch: 12 }, // Status
                { wch: 18 }, // Strategy
                { wch: 25 }, // Model(s)
                { wch: 12 }, // Prompt Mode
                { wch: 12 }, // Recall
                { wch: 12 }, // Precision
                { wch: 10 }, // F1
                { wch: 12 }, // WSS@95
                { wch: 6 },  // TP
                { wch: 6 },  // TN
                { wch: 6 },  // FP
                { wch: 6 },  // FN
                { wch: 18 }, // Papers Evaluated
                // S5 columns (if present)
                { wch: 18 }, // S5 Stage 1 Excluded
                { wch: 18 }, // S5 Stage 1 Rate
                { wch: 18 }, // S5 Stage 2 Papers
                { wch: 18 }, // S5 Time Savings
                { wch: 20 }, // S5 Avg Stage 1 Time
                { wch: 20 }, // S5 Avg Stage 2 Time
                { wch: 18 }, // S5 Total Time
                { wch: 20 }, // S5 Debate Calls Saved
                { wch: 15 }, // S5 Fast Filter
                { wch: 30 }  // S5 Debate Models
            ];
            
            XLSX.utils.book_append_sheet(wb, ws, 'Comparison Results');
            
            // Add summary sheet
            const summaryData = [
                { Metric: 'Total Combinations', Value: comparisonResults.summary.total_combinations },
                { Metric: 'Qualified (Recall ≥ 95%)', Value: comparisonResults.summary.qualified_count },
                { Metric: 'Unqualified (Recall < 95%)', Value: comparisonResults.summary.unqualified_count },
                { Metric: 'Ground Truth Papers', Value: comparisonResults.summary.ground_truth_papers },
                { Metric: '', Value: '' },
                { Metric: 'Best Strategy', Value: comparisonResults.summary.best_strategy?.strategy || 'N/A' },
                { Metric: 'Best Model', Value: comparisonResults.summary.best_strategy?.model || 'N/A' },
                { Metric: 'Best Prompt Mode', Value: comparisonResults.summary.best_strategy?.prompt_mode || 'N/A' },
                { Metric: 'Best Recall (%)', Value: comparisonResults.summary.best_strategy ? 
                    (comparisonResults.summary.best_strategy.recall * 100).toFixed(2) : 'N/A' },
                { Metric: 'Best WSS@95 (%)', Value: comparisonResults.summary.best_strategy ? 
                    (comparisonResults.summary.best_strategy.wss_95 * 100).toFixed(2) : 'N/A' }
            ];
            
            const wsSummary = XLSX.utils.json_to_sheet(summaryData);
            wsSummary['!cols'] = [{ wch: 25 }, { wch: 30 }];
            XLSX.utils.book_append_sheet(wb, wsSummary, 'Summary');
            
            // Write file
            const filename = `strategy_comparison_${selectedProject.project_id}_${new Date().toISOString().slice(0,10)}.xlsx`;
            XLSX.writeFile(wb, filename);
            
            toast.current?.show({
                severity: 'success',
                summary: 'Export Complete',
                detail: 'Comparison results exported to Excel',
                life: 3000
            });
        } catch (error) {
            console.error('Export to XLSX failed:', error);
            toast.current?.show({
                severity: 'error',
                summary: 'Export Failed',
                detail: error.message,
                life: 5000
            });
        }
    };

    // Export functions for single job metrics
    const exportJobMetricsJSON = () => {
        if (!evaluationMetrics) return;
        
        const exportData = {
            job_id: selectedJobForMetrics,
            evaluated_at: evaluationMetrics.evaluated_at,
            metrics:evaluationMetrics
        };
        
        const blob = new Blob(
            [JSON.stringify(exportData, null, 2)], 
            { type: 'application/json' }
        );
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `job_metrics_${selectedJobForMetrics}_${new Date().toISOString().slice(0,10)}.json`;
        a.click();
        URL.revokeObjectURL(url);
        
        toast.current?.show({
            severity: 'success',
            summary: 'Export Complete',
            detail: 'Job metrics exported to JSON',
            life: 3000
        });
    };

    const exportJobMetricsXLSX = () => {
        if (!evaluationMetrics) return;
        
        try {
            const XLSX = require('xlsx');
            
            // Main metrics sheet
            const metricsData = [
                { Metric: 'Job ID', Value: selectedJobForMetrics },
                { Metric: 'Strategy', Value: evaluationMetrics.strategy },
                { Metric: 'Model(s)', Value: evaluationMetrics.model },
                { Metric: 'Prompt Mode', Value: evaluationMetrics.prompt_mode },
                { Metric: '', Value: '' },
                { Metric: 'COVERAGE', Value: '' },
                { Metric: 'Papers Processed by Job', Value: evaluationMetrics.predictions_count || evaluationMetrics.total_papers },
                { Metric: 'Ground Truth Available', Value: evaluationMetrics.ground_truth_count || evaluationMetrics.total_papers },
                { Metric: 'Papers Evaluated', Value: evaluationMetrics.total_papers },
                { Metric: 'Includes Calibration Papers', Value: evaluationMetrics.includes_calibration ? 'YES' : 'NO' },
                { Metric: 'Coverage Warning', Value: evaluationMetrics.coverage_warning ? 'YES - Some papers lack ground truth' : 'NO - Full coverage' },
                { Metric: '', Value: '' },
                { Metric: 'Qualified', Value: evaluationMetrics.recall_threshold_met ? 'YES' : 'NO' },
                { Metric: 'Recall (%)', Value: (evaluationMetrics.recall * 100).toFixed(2) },
                { Metric: 'Precision (%)', Value: (evaluationMetrics.precision * 100).toFixed(2) },
                { Metric: 'F1 (%)', Value: (evaluationMetrics.f1 * 100).toFixed(2) },
                { Metric: 'WSS@95 (%)', Value: (evaluationMetrics.wss_95 * 100).toFixed(2) },
                { Metric: 'Specificity (%)', Value: (evaluationMetrics.specificity * 100).toFixed(2) },
                { Metric: 'Balanced Accuracy (%)', Value: (evaluationMetrics.balanced_accuracy * 100).toFixed(2) },
                { Metric: '', Value: '' },
                { Metric: 'True Positives (TP)', Value: evaluationMetrics.confusion_matrix?.TP || 0 },
                { Metric: 'True Negatives (TN)', Value: evaluationMetrics.confusion_matrix?.TN || 0 },
                { Metric: 'False Positives (FP)', Value: evaluationMetrics.confusion_matrix?.FP || 0 },
                { Metric: 'False Negatives (FN)', Value: evaluationMetrics.confusion_matrix?.FN || 0 },
                { Metric: '', Value: '' },
                { Metric: 'UNCERTAIN Treatment', Value: evaluationMetrics.uncertain_treatment }
            ];
            
            // Add S5 metrics if available
            if (evaluationMetrics.s5_stage_metrics) {
                metricsData.push({ Metric: '', Value: '' });
                metricsData.push({ Metric: 'S5 TWO-STAGE METRICS', Value: '' });
                metricsData.push({ Metric: '', Value: '' });
                metricsData.push({ Metric: 'Fast Filter Model', Value: evaluationMetrics.s5_stage_metrics.model_roles?.fast_filter || '' });
                metricsData.push({ 
                    Metric: 'Debate Models', 
                    Value: Array.isArray(evaluationMetrics.s5_stage_metrics.model_roles?.debate) 
                        ? evaluationMetrics.s5_stage_metrics.model_roles.debate.join(', ') 
                        : (evaluationMetrics.s5_stage_metrics.model_roles?.debate || '')
                });
                metricsData.push({ Metric: '', Value: '' });
                metricsData.push({ Metric: 'Stage 1 Excluded', Value: evaluationMetrics.s5_stage_metrics.st1_excl || 0 });
                metricsData.push({ Metric: 'Stage 1 Rate (%)', Value: evaluationMetrics.s5_stage_metrics.st1_rate || 0 });
                metricsData.push({ Metric: 'Stage 2 Papers', Value: evaluationMetrics.s5_stage_metrics.st2_papers || 0 });
                metricsData.push({ Metric: 'Time Savings (%)', Value: evaluationMetrics.s5_stage_metrics.time_savings_pct || 0 });
                metricsData.push({ Metric: 'Avg Stage 1 Time (s)', Value: evaluationMetrics.s5_stage_metrics.avg_st1_time_sec || 0 });
                metricsData.push({ Metric: 'Avg Stage 2 Time (s)', Value: evaluationMetrics.s5_stage_metrics.avg_st2_time_sec || 0 });
                metricsData.push({ Metric: 'Total Time (s)', Value: evaluationMetrics.s5_stage_metrics.total_time_sec || 0 });
                metricsData.push({ Metric: 'Debate Calls Saved', Value: evaluationMetrics.s5_stage_metrics.debate_calls_saved || 0 });
            }
            
            const wb = XLSX.utils.book_new();
            const ws = XLSX.utils.json_to_sheet(metricsData);
            ws['!cols'] = [{ wch: 30 }, { wch: 40 }];
            XLSX.utils.book_append_sheet(wb, ws, 'Metrics');
            
            // Error Analysis sheet
            if (evaluationMetrics.error_analysis) {
                const errorData = [
                    { Type: 'False Negatives (FN)', Count: evaluationMetrics.error_analysis.false_negatives_count || 0 },
                    { Type: 'False Positives (FP)', Count: evaluationMetrics.error_analysis.false_positives_count || 0 }
                ];
                const wsError = XLSX.utils.json_to_sheet(errorData);
                wsError['!cols'] = [{ wch: 25 }, { wch: 15 }];
                XLSX.utils.book_append_sheet(wb, wsError, 'Error Summary');
                
                // FN samples
                if (evaluationMetrics.error_analysis.false_negatives_sample?.length > 0) {
                    const fnData = evaluationMetrics.error_analysis.false_negatives_sample.map(id => ({ 'Paper ID': id }));
                    const wsFN = XLSX.utils.json_to_sheet(fnData);
                    wsFN['!cols'] = [{ wch: 20 }];
                    XLSX.utils.book_append_sheet(wb, wsFN, 'False Negatives');
                }
                
                // FP samples
                if (evaluationMetrics.error_analysis.false_positives_sample?.length > 0) {
                    const fpData = evaluationMetrics.error_analysis.false_positives_sample.map(id => ({ 'Paper ID': id }));
                    const wsFP = XLSX.utils.json_to_sheet(fpData);
                    wsFP['!cols'] = [{ wch: 20 }];
                    XLSX.utils.book_append_sheet(wb, wsFP, 'False Positives');
                }
            }
            
            const filename = `job_metrics_${selectedJobForMetrics}_${new Date().toISOString().slice(0,10)}.xlsx`;
            XLSX.writeFile(wb, filename);
            
            toast.current?.show({
                severity: 'success',
                summary: 'Export Complete',
                detail: 'Job metrics exported to Excel',
                life: 3000
            });
        } catch (error) {
            console.error('Export to XLSX failed:', error);
            toast.current?.show({
                severity: 'error',
                summary: 'Export Failed',
                detail: error.message,
                life: 5000
            });
        }
    };

    const exportErrorAnalysisTXT = () => {
        if (!errorAnalysis) return;
        
        const lines = [];
        lines.push('=' .repeat(70));
        lines.push('ERROR ANALYSIS REPORT');
        lines.push('=' .repeat(70));
        lines.push(`Generated: ${new Date().toISOString()}`);
        lines.push(`Project: ${errorAnalysis.metadata.project_id}`);
        lines.push(`Strategy: ${errorAnalysis.metadata.strategy || 'All'}`);
        lines.push(`Model: ${errorAnalysis.metadata.model || 'All'}`);
        lines.push(`UNCERTAIN treated as: ${errorAnalysis.metadata.uncertain_treatment}`);
        lines.push('');
        
        // False Positives
        lines.push('-'.repeat(70));
        lines.push(`FALSE POSITIVES (${errorAnalysis.false_positives.count} papers)`);
        lines.push(`(${errorAnalysis.false_positives.description})`);
        lines.push('-'.repeat(70));
        lines.push('');
        lines.push('Criteria causing FP:');
        Object.entries(errorAnalysis.false_positives.criteria_patterns).forEach(([c, n]) => {
            lines.push(`  ${c}: ${n}`);
        });
        lines.push('');
        lines.push('Examples:');
        errorAnalysis.false_positives.examples.slice(0, 10).forEach((ex, i) => {
            lines.push(`  ${i+1}. ${ex.corpus_id}: ${ex.title}`);
            lines.push(`     Criteria met: ${ex.criteria_met?.join(', ') || 'N/A'}`);
            lines.push(`     Reasoning: ${ex.reasoning?.slice(0, 150)}...`);
            lines.push('');
        });
        
        // False Negatives
        lines.push('-'.repeat(70));
        lines.push(`FALSE NEGATIVES (${errorAnalysis.false_negatives.count} papers)`);
        lines.push(`(${errorAnalysis.false_negatives.description})`);
        lines.push('-'.repeat(70));
        lines.push('');
        lines.push('Criteria causing FN:');
        Object.entries(errorAnalysis.false_negatives.criteria_patterns).forEach(([c, n]) => {
            lines.push(`  ${c}: ${n}`);
        });
        lines.push('');
        lines.push('Examples:');
        errorAnalysis.false_negatives.examples.slice(0, 10).forEach((ex, i) => {
            lines.push(`  ${i+1}. ${ex.corpus_id}: ${ex.title}`);
            lines.push(`     Criteria violated: ${ex.criteria_violated?.join(', ') || 'N/A'}`);
            lines.push(`     Reasoning: ${ex.reasoning?.slice(0, 150)}...`);
            lines.push('');
        });
        
        // Insights
        lines.push('-'.repeat(70));
        lines.push('INSIGHTS');
        lines.push('-'.repeat(70));
        errorAnalysis.insights?.forEach(insight => {
            lines.push(`• ${insight}`);
        });
        
        lines.push('');
        lines.push('='.repeat(70));
        lines.push('END OF REPORT');
        lines.push('='.repeat(70));
        
        const blob = new Blob([lines.join('\n')], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `error_analysis_${selectedProject.project_id}_${new Date().toISOString().slice(0,10)}.txt`;
        a.click();
        URL.revokeObjectURL(url);
    };

    const fetchResumableJobs = async () => {
        try {
            const projectParam = selectedProject?.project_id ? `?project_id=${selectedProject.project_id}` : '';
            const response = await fetch(`${LLM_API_BASE}/api/llm/jobs/resumable${projectParam}`);
            const data = await response.json();
            setResumableJobs(data.resumable_jobs || []);
        } catch (error) {
            console.error('Failed to fetch resumable jobs:', error);
        }
    };

    const loadModel = async (modelKey) => {
        setLoadingModel(modelKey);
        try {
            const response = await fetch(`${LLM_API_BASE}/api/llm/models/load`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ model_key: modelKey }),
            });
            const data = await response.json();
            
            if (response.ok) {
                toast.current?.show({
                    severity: 'success',
                    summary: 'Model Loaded',
                    detail: `${data.name || modelKey} loaded in ${data.load_time?.toFixed(1)}s`,
                });
                fetchModels();
            } else {
                throw new Error(data.detail);
            }
        } catch (error) {
            toast.current?.show({
                severity: 'error',
                summary: 'Load Failed',
                detail: error.message,
            });
        } finally {
            setLoadingModel(null);
        }
    };

    const unloadModel = async (modelKey) => {
        try {
            await fetch(`${LLM_API_BASE}/api/llm/models/unload`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ model_key: modelKey }),
            });
            fetchModels();
            toast.current?.show({
                severity: 'info',
                summary: 'Model Unloaded',
                detail: modelKey,
            });
        } catch (error) {
            console.error('Failed to unload model:', error);
        }
    };

        // Load few-shot examples from calibration set
    const loadFewShotExamples = async () => {
        if (!selectedProject) return;
        
        setFewShotLoading(true);
        try {
            const username = localStorage.getItem('user_name') || 
                           localStorage.getItem('wharf_user_name') || '';
            
            const response = await fetch(
                `${configuration.passer.ScreeningAPI}/api/fewshot/examples?project_id=${selectedProject.project_id}&antelope_account=${username}`
            );
            
            if (response.ok) {
                const data = await response.json();
                setFewShotExamples(data.examples || []);
                setFewShotReady(data.ready || false);
                setFewShotMissing(data.missing_decisions || []);
            } else {
                console.error('Failed to load few-shot examples');
                setFewShotReady(false);
            }
        } catch (error) {
            console.error('Error loading few-shot examples:', error);
            setFewShotReady(false);
        } finally {
            setFewShotLoading(false);
        }
    };

    useEffect(() => {
        // If fast filter is no longer among selected models, clear it
        if (s5FastFilter && !selectedModels.includes(s5FastFilter)) {
            setS5FastFilter('');
        }
        // Filter debate models to only available ones
        setS5DebateModels(prev => prev.filter(m => selectedModels.includes(m)));
    }, [selectedModels]);

    const startScreening = async () => {
        if (!selectedProject) {
            toast.current?.show({
                severity: 'warn',
                summary: 'No Project',
                detail: 'Please select a project first',
            });
            return;
        }

        if (selectedModels.length === 0) {
            toast.current?.show({
                severity: 'warn',
                summary: 'No Models',
                detail: 'Please select at least one model',
            });
            return;
        }

        if (selectedStrategies.length === 0) {
            toast.current?.show({
                severity: 'warn',
                summary: 'No Strategies',
                detail: 'Please select at least one strategy',
            });
            return;
        }

        // Validate S5 strategy configuration
        if (selectedStrategies.includes('S5_TWO_STAGE')) {
            if (!s5FastFilter) {
                toast.current?.show({
                    severity: 'warn',
                    summary: 'S5 Configuration Required',
                    detail: 'Please select a Fast Filter model for S5 Two-Stage strategy',
                });
                return;
            }
            
            // Ensure we have at least one debate model
            const debateModels = s5DebateModels.length > 0 
                ? s5DebateModels 
                : selectedModels.filter(m => m !== s5FastFilter);
            
            if (debateModels.length === 0) {
                toast.current?.show({
                    severity: 'warn',
                    summary: 'S5 Configuration Required',
                    detail: 'S5 requires at least one debate model. Please select more models.',
                });
                return;
            }
        }

        // Note: In memory-efficient mode, models don't need to be pre-loaded
        // The backend will lazy-load them on-demand during execution
        // This prevents GPU memory exhaustion on Apple Silicon

        setLoading(true);
        jobStartTimeRef.current = Date.now();
        setProgressLog([]);

        try {
            const requestBody = {
                project_id: selectedProject.project_id,
                data_source: dataSource,
                strategies: selectedStrategies,
                models: selectedModels,
                prompt_mode: promptMode,
                output_filename: outputFilename || undefined,
                evaluation_only: dataSource === 'corpus' ? true : evaluationOnly, //dataSource === 'gold_standard' ? evaluationOnly : false,
                save_to_mongodb: saveToMongoDB,
                antelope_account: username,  // Track user who initiated screening
                resume_job_id: resumeJobId || undefined,  // Resume from specific job if provided
                s5_model_roles: selectedStrategies.includes('S5_TWO_STAGE') && s5FastFilter
                    ? {
                        fast_filter: s5FastFilter,
                        debate: s5DebateModels.length > 0 
                            ? s5DebateModels 
                            : selectedModels.filter(m => m !== s5FastFilter)
                    }
                    : undefined,
            };

            console.log('Starting screening with request:', requestBody);

            const response = await fetch(`${LLM_API_BASE}/api/llm/screen/start`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(requestBody),
            });

            const data = await response.json();

            if (response.ok) {
                setActiveJob(data.job_id);
                toast.current?.show({
                    severity: 'success',
                    summary: 'Screening Started',
                    detail: `Job ${data.job_id} started`,
                });
            } else {
                console.error('Screening start failed:', data);
                throw new Error(data.detail || JSON.stringify(data));
            }
        } catch (error) {
            console.error('Start screening error:', error);
            toast.current?.show({
                severity: 'error',
                summary: 'Start Failed',
                detail: error.message,
            });
        } finally {
            setLoading(false);
        }
    };

    const stopScreening = async () => {
        if (!activeJob) return;

        try {
            await fetch(`${LLM_API_BASE}/api/llm/screen/stop`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ job_id: activeJob }),
            });
            toast.current?.show({
                severity: 'info',
                summary: 'Stop Requested',
                detail: 'Job will stop after current paper',
            });
        } catch (error) {
            console.error('Failed to stop job:', error);
        }
    };

    const downloadResults = async (jobId) => {
        window.open(`${LLM_API_BASE}/api/llm/results/${jobId}`, '_blank');
    };

    // ==========================================================================
    // WEBSOCKET
    // ==========================================================================

    const reconnectTimeoutRef = useRef(null);
    
    const connectWebSocket = useCallback(() => {
        // Clear any pending reconnect
        if (reconnectTimeoutRef.current) {
            clearTimeout(reconnectTimeoutRef.current);
            reconnectTimeoutRef.current = null;
        }
        
        // Don't connect if already open
        if (wsRef.current?.readyState === WebSocket.OPEN) return;
        
        // Close existing connection if in connecting/closing state
        if (wsRef.current && wsRef.current.readyState !== WebSocket.CLOSED) {
            try {
                wsRef.current.close();
            } catch (e) {
                console.error('Error closing WebSocket:', e);
            }
        }

        const ws = new WebSocket(LLM_WS_URL);

        ws.onopen = () => {
            setWsConnected(true);
            console.log('WebSocket connected');
        };

        ws.onmessage = (event) => {
            try {
                const message = JSON.parse(event.data);
                handleWsMessage(message);
            } catch (e) {
                // Handle ping/pong
                if (event.data === 'ping') {
                    ws.send('pong');
                }
            }
        };

        ws.onclose = () => {
            setWsConnected(false);
            console.log('WebSocket disconnected, reconnecting in 3s...');
            // Schedule reconnect
            reconnectTimeoutRef.current = setTimeout(connectWebSocket, 3000);
        };

        ws.onerror = (error) => {
            console.error('WebSocket error:', error);
        };

        wsRef.current = ws;
    }, []);

    const handleWsMessage = (message) => {
        switch (message.type) {
            case 'connected':
                if (message.active_job) {
                    setActiveJob(message.active_job);
                }
                break;

            case 'job_started':
                setActiveJob(message.job_id);
                jobStartTimeRef.current = Date.now();
                break;

            case 'job_info':
                setJobProgress({
                    total: message.total_papers,
                    processed: 0,
                    papersThisSession: 0,
                    percent: 0,
                });
                addProgressLog(`Job started: ${message.total_papers} papers, strategies: ${message.strategies.join(', ')}`);
                break;

            case 'progress':
                setJobProgress({
                    total: message.total,
                    processed: message.paper_index,
                    papersThisSession: message.papers_this_session || message.paper_index,
                    percent: message.percent,
                    currentPaper: message.paper_id,
                    currentStrategy: message.strategy,
                });
                break;

            case 'job_completed':
                setActiveJob(null);
                setJobProgress(null);
                addProgressLog(`✓ Job completed: ${message.total_processed} papers processed`);
                addProgressLog(`Results file: ${message.results_file}`);
                fetchJobs();
                toast.current?.show({
                    severity: 'success',
                    summary: 'Screening Complete',
                    detail: `Processed ${message.total_processed} papers`,
                    life: 10000,
                });
                break;

            case 'job_failed':
                setActiveJob(null);
                setJobProgress(null);
                addProgressLog(`✗ Job failed: ${message.error}`);
                fetchJobs();
                toast.current?.show({
                    severity: 'error',
                    summary: 'Screening Failed',
                    detail: message.error,
                    life: 10000,
                });
                break;

            case 'job_cancelled':
                setActiveJob(null);
                setJobProgress(null);
                addProgressLog(`⊗ Job cancelled`);
                fetchJobs();
                toast.current?.show({
                    severity: 'warn',
                    summary: 'Screening Cancelled',
                    detail: 'Job was stopped by user',
                    life: 5000,
                });
                break;

            default:
                console.log('Unknown message type:', message.type);
        }
    };

    const addProgressLog = (message) => {
        const timestamp = new Date().toLocaleTimeString();
        // Keep only last 30 entries to prevent memory buildup
        setProgressLog(prev => [...prev.slice(-29), { time: timestamp, message }]);
    };

    // ==========================================================================
    // EFFECTS
    // ==========================================================================

    useEffect(() => {
        fetchStatus();
        fetchModels();
        fetchStrategies();
        fetchJobs();
        connectWebSocket();

        const interval = setInterval(fetchStatus, 30000);

        return () => {
            // Cleanup on unmount
            clearInterval(interval);
            
            // Clear reconnect timeout
            if (reconnectTimeoutRef.current) {
                clearTimeout(reconnectTimeoutRef.current);
                reconnectTimeoutRef.current = null;
            }
            
            // Close WebSocket
            if (wsRef.current) {
                try {
                    wsRef.current.onclose = null; // Prevent reconnect on unmount
                    wsRef.current.close();
                } catch (e) {
                    console.error('Error closing WebSocket on unmount:', e);
                }
                wsRef.current = null;
            }
        };
    }, [connectWebSocket]);

    useEffect(() => {
        // Set default filename when project changes
        if (selectedProject) {
            const timestamp = new Date().toISOString().slice(0, 10).replace(/-/g, '');
            setOutputFilename(`screening_${selectedProject.project_id}_${timestamp}`);
        }
    }, [selectedProject]);

    // Load few-shot examples when project changes
    useEffect(() => {
        if (selectedProject) {
            loadFewShotExamples();
            fetchJobs(); // Refresh jobs for the selected project
            fetchResumableJobs(); // Refresh resumable jobs for the selected project
        }
    }, [selectedProject]);

    // ==========================================================================
    // RENDER HELPERS
    // ==========================================================================

    const renderServiceStatus = () => {
        if (!serviceStatus) {
            return <Message severity="info" text="Checking service status..." />;
        }

        if (serviceStatus.status === 'offline') {
            return (
                <Message 
                    severity="error" 
                    text={`LLM Screening Service is offline: ${serviceStatus.error || 'Unknown error'}`} 
                />
            );
        }

        return (
            <div className="flex align-items-center gap-3">
                <Tag severity="success" value="Service Online" />
                <Tag severity={serviceStatus.mlx_available ? 'success' : 'warning'} 
                     value={serviceStatus.mlx_available ? 'MLX Ready' : 'MLX Not Available'} />
                <Tag severity={wsConnected ? 'success' : 'warning'}
                     value={wsConnected ? 'WebSocket Connected' : 'WebSocket Disconnected'} />
                <span className="text-500" style={{marginLeft: '10px'}}>
                    Cache: {serviceStatus.cache_volume}
                </span>
            </div>
        );
    };

    const renderModelsPanel = () => (
        <Panel header="Models (Memory-Efficient Mode: Load on Demand)" className="mb-3" toggleable collapsed>
            <Message 
                severity="info" 
                text="💡 In memory-efficient mode, models are loaded automatically during execution. You don't need to pre-load them." 
                className="mb-3"
            />
            <div className="grid">
                {models.map(model => (
                    <div key={model.key} className="col-12 md:col-6 lg:col-3">
                        <Card className={`model-card ${model.loaded ? 'model-loaded' : ''}`}>
                            <div className="flex flex-column gap-2">
                                <div className="flex justify-content-between align-items-center">
                                    <span className="font-semibold">{model.name}</span>
                                    {model.loaded && <Badge value="Loaded" severity="success" />}
                                </div>
                                <small className="text-500">{model.description}</small>
                                <div className="flex gap-2 mt-2">
                                    {!model.loaded ? (
                                        <Button 
                                            label="Pre-Load (Optional)" 
                                            icon="pi pi-download"
                                            size="small"
                                            severity="secondary"
                                            loading={loadingModel === model.key}
                                            onClick={() => loadModel(model.key)}
                                        />
                                    ) : (
                                        <Button 
                                            label="Unload" 
                                            icon="pi pi-times"
                                            size="small"
                                            severity="secondary"
                                            onClick={() => unloadModel(model.key)}
                                            disabled={activeJob !== null}
                                        />
                                    )}
                                </div>
                            </div>
                        </Card>
                    </div>
                ))}
            </div>
        </Panel>
    );

    const renderConfigPanel = () => {
        const dataSourceOptions = [
            { label: 'Full Corpus', value: 'corpus' },
            { label: 'Gold Standard', value: 'gold_standard' },
        ];

        const promptModeOptions = [
            { label: 'Zero-Shot', value: 'zero_shot' },
            { label: 'Few-Shot', value: 'few_shot' },
        ];

        const strategyOptions = strategies.map(s => ({
            label: s.name,
            value: s.key,
            description: s.description,
        }));

        return (
            <Panel header="Configuration" className="mb-3">
                <div className="grid">
                    <div className="col-12 md:col-6">
                        <label className="block mb-2 font-semibold" >Data Source</label>
                        <SelectButton 
                            style={{marginBottom: '10px', marginTop: '10px'}}
                            value={dataSource} 
                            onChange={(e) => setDataSource(e.value)}
                            options={dataSourceOptions}
                            disabled={activeJob !== null}
                        />
                        {/* Evaluation Only - only for Gold Standard */}
                        {dataSource === 'gold_standard' && (
                            <div className="col-12 mt-2">
                                <div className="flex align-items-center">
                                    <Checkbox 
                                        inputId="evaluationOnly" 
                                        checked={evaluationOnly} 
                                        onChange={(e) => setEvaluationOnly(e.checked)} 
                                        disabled={activeJob !== null}
                                    />
                                    <label htmlFor="evaluationOnly" className="ml-2">
                                        Evaluation papers only (exclude 10 calibration papers)
                                    </label>
                                </div>
                                <small className="text-500 ml-4">
                                    {evaluationOnly 
                                        ? (goldStandardTotal ? `Will screen ${goldStandardTotal - 10} evaluation papers for metrics calculation` : "Will screen evaluation papers (excluding calibration) for metrics calculation")
                                        : (goldStandardTotal ? `Will screen all ${goldStandardTotal} gold standard papers` : "Will screen all gold standard papers")
                                    }
                                </small>
                            </div>
                        )}

                        {/* Save to MongoDB */}
                        <div className="col-12 mt-2">
                            <div className="flex align-items-center">
                                <Checkbox 
                                    inputId="saveToMongoDB" 
                                    checked={saveToMongoDB} 
                                    onChange={(e) => setSaveToMongoDB(e.checked)} 
                                    disabled={activeJob !== null}
                                />
                                <label htmlFor="saveToMongoDB" className="ml-2">
                                    Save results to MongoDB (required for evaluation metrics)
                                </label>
                            </div>
                            <small className="text-500 ml-4">
                                Results are always saved to JSONL. Enable this for Phase 7 metrics.
                            </small>
                        </div>
                    </div>

                    {/* Prompt Mode Selection */}
                    <div className="field mt-3" style={{marginTop: '10px'}}>
                        <label className="font-semibold">Prompt Mode</label>
                        <div className="mt-2">
                            <SelectButton 
                                value={promptMode}
                                options={[
                                    { label: 'Zero-Shot', value: 'zero_shot' },
                                    { label: `Few-Shot (${fewShotExamples.length} examples)`, value: 'few_shot', disabled: !fewShotReady }
                                ]}
                                onChange={(e) => setPromptMode(e.value)}
                                optionDisabled="disabled"
                            />
                        </div>
                        {promptMode === 'few_shot' && !fewShotReady && (
                            <small className="p-error block mt-1">
                                Complete calibration screening before using few-shot mode
                            </small>
                        )}
                        {promptMode === 'few_shot' && fewShotReady && (
                            <small className="text-secondary block mt-1">
                                Will use {fewShotExamples.length} calibration examples in prompt
                            </small>
                        )}
                    </div>

                    <div className="col-12 md:col-6" style={{marginTop: '10px'}}>
                        <label className="block mb-2 font-semibold" style={{marginBottom: '10px'}}>Models (select any available)</label>
                        <MultiSelect 
                            style={{marginBottom: '10px', marginRight: '10px', marginLeft: '10px'}}
                            value={selectedModels}
                            onChange={(e) => setSelectedModels(e.value)}
                            options={models.map(m => ({ label: m.name, value: m.key }))}
                            placeholder="Select models (will load on-demand)"
                            className="w-full"
                            disabled={activeJob !== null}
                            display="chip"
                        />
                        <small className="text-500">
                            Models will be loaded automatically during execution (memory-efficient)
                        </small>
                    </div>

                    <div className="col-12 md:col-6">
                        <label className="block mb-2 font-semibold" style={{marginBottom: '10px', marginRight: '10px'}}>Strategies</label>
                        <MultiSelect 
                            style={{marginBottom: '10px'}}
                            value={selectedStrategies}
                            onChange={(e) => setSelectedStrategies(e.value)}
                            options={strategyOptions}
                            placeholder="Select strategies"
                            className="w-full"
                            disabled={activeJob !== null}
                            display="chip"
                            itemTemplate={(option) => (
                                <div>
                                    <div>{option.label}</div>
                                    <small className="text-500">{option.description}</small>
                                </div>
                            )}
                        />
                    </div>

                    {/* S5 Role Assignment - shown only when S5 is selected */}
                    {selectedStrategies.includes('S5_TWO_STAGE') && selectedModels.length >= 2 && (
                        <div className="col-12">
                            <Panel 
                                header={
                                    <span>
                                        <i className="pi pi-sitemap mr-2"></i>
                                        S5 Role Assignment
                                        <Tag value="Optional" severity="info" className="ml-2" style={{fontSize: '0.7rem'}} />
                                    </span>
                                }
                                toggleable 
                                collapsed={false}
                                className="s5-role-panel"
                            >
                                <div className="grid">
                                    <div className="col-12">
                                        <Message 
                                            severity="info" 
                                            text="Assign models to S5 roles. The Fast Filter should have the highest recall (fewest false negatives). If left empty, the default order (first selected model) is used."
                                            className="mb-3 w-full"
                                        />
                                    </div>
                                    <div className="col-12 md:col-4">
                                        <label className="block mb-2 font-semibold">
                                            <i className="pi pi-filter mr-1"></i>
                                            Stage 1: Fast Filter
                                        </label>
                                        <Dropdown
                                            value={s5FastFilter}
                                            onChange={(e) => {
                                                setS5FastFilter(e.value);
                                                // Automatically remove from debate if present
                                                setS5DebateModels(prev => prev.filter(m => m !== e.value));
                                            }}
                                            options={selectedModels.map(key => {
                                                const model = models.find(m => m.key === key);
                                                return { label: model?.name || key, value: key };
                                            })}
                                            placeholder="Select fast filter model"
                                            className="w-full"
                                            disabled={activeJob !== null}
                                            showClear
                                        />
                                        <small className="text-500">
                                            Screens all papers first. HIGH-confidence EXCLUDE = final. 
                                            Choose model with highest recall.
                                        </small>
                                    </div>
                                    <div className="col-12 md:col-8">
                                        <label className="block mb-2 font-semibold">
                                            <i className="pi pi-comments mr-1"></i>
                                            Stage 2: Debate Models
                                        </label>
                                        <MultiSelect
                                            value={s5DebateModels}
                                            onChange={(e) => setS5DebateModels(e.value)}
                                            options={selectedModels
                                                .filter(key => key !== s5FastFilter)
                                                .map(key => {
                                                    const model = models.find(m => m.key === key);
                                                    return { label: model?.name || key, value: key };
                                                })}
                                            placeholder="Select debate models (remaining)"
                                            className="w-full"
                                            disabled={activeJob !== null}
                                            display="chip"
                                        />
                                        <small className="text-500">
                                            Review papers that pass Stage 1. Multiple models debate inclusion/exclusion.
                                        </small>
                                    </div>
                                </div>
                            </Panel>
                        </div>
                    )}

                    <div className="col-12">
                        <label className="block mb-2 font-semibold" >Output Filename</label>
                        <div className="p-inputgroup">
                            <InputText 
                                value={outputFilename}
                                onChange={(e) => setOutputFilename(e.target.value)}
                                placeholder="screening_results"
                                disabled={activeJob !== null}
                            />
                            <span className="p-inputgroup-addon">.jsonl</span>
                        </div>
                        <small className="text-500">
                            Results will be saved to: {serviceStatus?.results_dir}/{outputFilename || 'auto-generated'}.jsonl
                        </small>
                    </div>

                    <div className="col-12">
                        <div style={{ 
                            border: '1px solid #e5e7eb', 
                            backgroundColor: '#f9fafb', 
                            padding: '1rem', 
                            borderRadius: '6px' 
                        }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                                <label className="block font-semibold">Resume Job (Optional)</label>
                                <Button 
                                    icon="pi pi-refresh" 
                                    className="p-button-text p-button-sm"
                                    onClick={fetchResumableJobs}
                                    tooltip="Refresh resumable jobs list"
                                    disabled={activeJob !== null}
                                />
                            </div>
                            <Dropdown
                                value={resumeJobId}
                                options={[
                                    { label: '-- Start New Job --', value: '' },
                                    ...resumableJobs.map(job => ({
                                        label: `${job.job_id} - ${formatDateTime(job.start_time)} - ${job.strategies.join(',')}/${job.models.join(',')}/${job.prompt_mode} - ${job.unique_papers_completed}/${job.total_papers} papers`,
                                        value: job.job_id
                                    }))
                                ]}
                                onChange={(e) => setResumeJobId(e.value)}
                                placeholder="Select a job to resume or start new"
                                disabled={activeJob !== null}
                                className="w-full"
                                filter
                                showClear
                            />
                            <small className="text-500">
                                💡 Select a previous interrupted/failed job to resume, or leave as "Start New Job" for fresh screening.
                                {resumeJobId && resumableJobs.find(j => j.job_id === resumeJobId) && (
                                    <div style={{ marginTop: '0.5rem', padding: '0.5rem', background: '#f0f9ff', borderRadius: '4px' }}>
                                        <strong>Resuming:</strong> {resumableJobs.find(j => j.job_id === resumeJobId).unique_papers_completed} papers already completed
                                    </div>
                                )}
                            </small>
                        </div>
                    </div>
                </div>
            </Panel>
        );
    };

    const renderProgressPanel = () => {
        if (!activeJob && !jobProgress) return null;

        const elapsedSeconds = jobStartTimeRef.current 
            ? (Date.now() - jobStartTimeRef.current) / 1000 
            : 0;

        return (
            <Panel header="Screening Progress" className="mb-3" style={{marginBottom: '10px', marginTop: '10px'}}>
                <div className="flex flex-column gap-3">
                    <div className="flex justify-content-between align-items-center">
                        <div>
                            <Tag severity="info" value={`Job: ${activeJob}`} className="mr-2" />
                            <span style={{marginLeft: '5px'}}>
                                {jobProgress?.processed || 0} / {jobProgress?.total || '?'} papers
                            </span>
                        </div>
                        <div className="flex align-items-center gap-2">
                            <span className="text-500">
                                {jobProgress && estimateTimeRemaining(
                                    jobProgress.papersThisSession || 0,
                                    jobProgress.processed,
                                    jobProgress.total,
                                    elapsedSeconds
                                )}
                            </span>
                            <Button 
                                style={{marginBottom: '10px', marginLeft: '10px'}}
                                label="Stop" 
                                icon="pi pi-stop"
                                severity="danger"
                                size="small"
                                onClick={stopScreening}
                            />
                        </div>
                    </div>

                    <ProgressBar 
                        value={jobProgress?.percent || 0} 
                        showValue
                        style={{ height: '24px' }}
                    />

                    {jobProgress?.currentPaper && (
                        <div className="flex gap-3 text-500">
                            <span>Current: <strong>{jobProgress.currentPaper}</strong></span>
                            <span>Strategy: <strong>{jobProgress.currentStrategy}</strong></span>
                        </div>
                    )}

                    {progressLog.length > 0 && (
                        <div className="progress-log surface-ground border-round p-2" 
                             style={{ maxHeight: '150px', overflow: 'auto' }}>
                            {progressLog.map((log, i) => (
                                <div key={i} className="text-sm">
                                    <span className="text-500">{log.time}</span> {log.message}
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </Panel>
        );
    };

    const renderJobsHistory = () => {
        // Get completed gold standard jobs for selection
        const completedGoldStandardJobs = jobs.filter(j => j.status === 'completed');
        
        const handleSelectAllJobs = (e) => {
            const isChecked = e.checked;
            console.log('Select All clicked:', isChecked);
            setSelectAllJobs(isChecked);
            if (isChecked) {
                console.log('Selecting all jobs:', completedGoldStandardJobs);
                setSelectedJobs(completedGoldStandardJobs);
            } else {
                console.log('Deselecting all jobs');
                setSelectedJobs([]);
            }
        };
        
        const isRowSelectable = (rowData) => {
            return rowData.status === 'completed';
        };
        
        return (
            <Panel header="Job History" toggleable collapsed className="mb-3">
                {/* Controls Row - UNCERTAIN left, Compare button right */}
                <div style={{ 
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    marginBottom: '16px',
                    flexWrap: 'wrap',
                    gap: '12px'
                }}>
                    {/* Left side: UNCERTAIN treatment */}
                    <div className="flex align-items-center gap-2">
                        <label className="font-semibold">UNCERTAIN treatment:</label>
                        <Dropdown
                            value={uncertainTreatment}
                            options={[
                                { label: 'Treat as INCLUDE (conservative)', value: 'INCLUDE' },
                                { label: 'Treat as EXCLUDE', value: 'EXCLUDE' }
                            ]}
                            onChange={(e) => setUncertainTreatment(e.value)}
                            style={{ width: '280px', marginLeft: '10px' }}
                        />
                    </div>

                    {/* Right side: Compare button with selected count */}
                    <div className="flex align-items-center gap-2">
                        {selectedJobs.length > 0 && (
                            <Tag severity="info" value={`${selectedJobs.length} selected`} />
                        )}
                        <Button
                            label={`Compare Selected (${selectedJobs.length})`}
                            icon="pi pi-chart-line"
                            severity="help"
                            loading={metricsLoading && !selectedJobForMetrics}
                            onClick={calculateMetricsComparison}
                            disabled={selectedJobs.length === 0}
                            tooltip={selectedJobs.length === 0 ? "Select jobs to compare" : `Compare ${selectedJobs.length} selected job(s)`}
                        />
                    </div>
                </div>
                
                <DataTable 
                    value={jobs} 
                    size="small" 
                    emptyMessage="No jobs yet"
                    dataKey="job_id"
                    key={`jobs-table-${selectedJobs.map(j => j.job_id).join('-')}`}
                >
                    <Column 
                        header={
                            completedGoldStandardJobs.length > 0 ? (
                                <Checkbox
                                    inputId="selectAllHeader"
                                    checked={selectAllJobs}
                                    onChange={(e) => handleSelectAllJobs(e)}
                                    tooltip="Select/Deselect All"
                                />
                            ) : null
                        }
                        headerStyle={{width: '3rem', textAlign: 'center'}}
                        body={(rowData) => {
                            const isSelectable = isRowSelectable(rowData);
                            if (!isSelectable) return null;
                            
                            const isSelected = selectedJobs.some(job => job.job_id === rowData.job_id);
                            // console.log(`Rendering checkbox for job ${rowData.job_id}, isSelected:`, isSelected);
                            
                            return (
                                <Checkbox
                                    inputId={`checkbox-${rowData.job_id}`}
                                    checked={isSelected}
                                    onChange={(e) => {
                                        // console.log(`Checkbox clicked for ${rowData.job_id}, checked:`, e.checked);
                                        setSelectedJobs(prevSelected => {
                                            let newSelection;
                                            if (e.checked) {
                                                newSelection = [...prevSelected, rowData];
                                            } else {
                                                newSelection = prevSelected.filter(job => job.job_id !== rowData.job_id);
                                            }
                                            
                                            // console.log('New selection after click:', newSelection.map(j => j.job_id));
                                            
                                            // Update select all state
                                            const completedGoldStandardJobs = jobs.filter(j => j.status === 'completed');
                                            setSelectAllJobs(newSelection.length === completedGoldStandardJobs.length && completedGoldStandardJobs.length > 0);
                                            
                                            return newSelection;
                                        });
                                    }}
                                />
                            );
                        }}
                        style={{width: '3rem', textAlign: 'center'}}
                    />
                <Column field="job_id" header="Job ID" style={{ width: '100px' }} />
                <Column header="Created" body={(row) => {
                    const date = row.created_at || row.timestamp || row.start_time;
                    if (!date) return '-';
                    try {
                        // Ensure UTC timestamps are treated as UTC
                        let dateString = date;
                        if (typeof dateString === 'string' && !dateString.includes('Z') && !dateString.includes('+') && !dateString.includes('-', 10)) {
                            dateString = dateString.replace(' ', 'T') + 'Z';
                        }
                        return new Date(dateString).toLocaleString();
                    } catch {
                        return date;
                    }
                }} style={{ width: '150px' }} />
                <Column 
                    field="antelope_account" 
                    header="User" 
                    style={{ width: '120px', color: '#27498d' }} 
                />
                <Column field="status" header="Status" body={(row) => (
                    <Tag 
                        severity={
                            row.status === 'completed' ? 'success' :
                            row.status === 'running' ? 'info' :
                            row.status === 'failed' ? 'danger' : 'warning'
                        }
                        value={row.status}
                    />
                )} />
                <Column header="Blockchain" body={(row) => {
                    if (row.transaction_id) {
                        return (
                            <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                                <i className="pi pi-shield" style={{ color: '#10b981', fontSize: '0.9rem' }} 
                                   title="Recorded on blockchain" />
                                <code style={{ 
                                    fontSize: '0.75rem', 
                                    color: '#6b7280',
                                    maxWidth: '80px',
                                    overflow: 'hidden',
                                    textOverflow: 'ellipsis',
                                    whiteSpace: 'nowrap'
                                }} title={row.transaction_id}>
                                    {row.transaction_id.substring(0, 8)}...
                                </code>
                            </div>
                        );
                    }
                    return <span style={{ color: '#9ca3af', fontSize: '0.85rem' }}>-</span>;
                }} style={{ width: '110px' }} />
                <Column field="data_source" header="Source" />
                <Column field="processed_papers" header="Papers" body={(row) => 
                    `${row.processed_papers}/${row.total_papers}`
                } />
                <Column field="strategies" header="Strategies" body={(row) => 
                    row.strategies?.join(', ') || '-'
                } />
                <Column header="Actions" body={(row) => (
                    <div className="flex gap-1">
                        {row.results_file && (
                            <Button 
                                icon="pi pi-download" 
                                size="small"
                                tooltip="Download Results"
                                onClick={() => downloadResults(row.job_id)}
                            />
                        )}
                        {row.status === 'completed' && (
                            <Button 
                                icon="pi pi-chart-bar" 
                                size="small"
                                severity="info"
                                tooltip="Calculate Metrics"
                                loading={metricsLoading && selectedJobForMetrics === row.job_id}
                                data-job-id={row.job_id}
                                onClick={(e) => {
                                    e.stopPropagation();
                                    const jobId = e.currentTarget.getAttribute('data-job-id');
                                    console.log('Button clicked with data-job-id:', jobId);
                                    calculateMetricsForJob(jobId);
                                }}
                            />
                        )}
                    </div>
                )} />
                </DataTable>
            </Panel>
        );
    };

    // ==========================================================================
    // METRICS CALCULATION (Phase 7)
    // ==========================================================================

    /**
     * Variant 1: Calculate metrics for a specific job
     */
    const calculateMetricsForJob = async (jobId) => {
        console.log('calculateMetricsForJob called with jobId:', jobId, 'type:', typeof jobId);
        
        if (!jobId || typeof jobId !== 'string') {
            console.error('Invalid jobId - expected string, got:', jobId);
            toast.current?.show({
                severity: 'error',
                summary: 'Invalid Job ID',
                detail: 'Job ID must be a valid string',
                life: 3000
            });
            return;
        }
        
        setMetricsLoading(true);
        setSelectedJobForMetrics(jobId);
        
        try {
            const response = await fetch(`${LLM_API_BASE}/api/llm/evaluate/job/${jobId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    uncertain_treatment: uncertainTreatment,
                    save_to_db: true
                })
            });
            
            const data = await response.json();
            
            if (!response.ok) {
                throw new Error(data.detail || data.error || 'Evaluation failed');
            }
            
            if (data.error) {
                throw new Error(data.error);
            }
            
            setEvaluationMetrics(data);
            setMetricsDialogVisible(true);
            
            // Show notification
            const recallStatus = data.recall_threshold_met ? '✓' : '✗';
            toast.current?.show({
                severity: data.recall_threshold_met ? 'success' : 'warn',
                summary: `Metrics Calculated ${recallStatus}`,
                detail: `Recall: ${(data.recall * 100).toFixed(1)}%, WSS@95: ${(data.wss_95 * 100).toFixed(1)}%`,
                life: 5000
            });
            
        } catch (error) {
            console.error('Calculate metrics failed:', error);
            toast.current?.show({
                severity: 'error',
                summary: 'Evaluation Failed',
                detail: error.message,
                life: 5000
            });
        } finally {
            setMetricsLoading(false);
        }
    };

    /**
     * Variant 2: Comparative metrics for all combinations
     */
    const calculateMetricsComparison = async () => {
        if (selectedJobs.length === 0) {
            toast.current?.show({
                severity: 'warn',
                summary: 'No Jobs Selected',
                detail: 'Please select at least one job to compare',
                life: 3000
            });
            return;
        }
        
        // Check for jobs without decisions
        const jobsWithoutDecisions = selectedJobs.filter(job => 
            !job.decisions_count || job.decisions_count === 0
        );
        
        if (jobsWithoutDecisions.length > 0) {
            const jobIds = jobsWithoutDecisions.map(j => j.job_id).join(', ');
            toast.current?.show({
                severity: 'warn',
                summary: 'Jobs Without Decisions',
                detail: `${jobsWithoutDecisions.length} of ${selectedJobs.length} selected jobs have no decisions and will be excluded from comparison: ${jobIds}`,
                life: 8000
            });
        }
        
        // Extract job IDs from selected job objects
        const jobIds = selectedJobs.map(job => job.job_id);
        console.log('=== COMPARISON REQUEST ===');
        console.log('Selected jobs:', selectedJobs);
        console.log('Extracted job IDs:', jobIds);
        console.log('Number of selected jobs:', selectedJobs.length);
        console.log('Jobs without decisions:', jobsWithoutDecisions.length);
        
        setMetricsLoading(true);
        
        try {
            const requestBody = {
                project_id: selectedProject.project_id,
                uncertain_treatment: uncertainTreatment,
                filter_strategies: null,
                filter_models: null,
                filter_prompt_modes: null,
                job_ids: jobIds, // Pass extracted job IDs
                save_to_db: true
            };
            console.log('Request body:', JSON.stringify(requestBody, null, 2));
            
            const response = await fetch(`${LLM_API_BASE}/api/llm/evaluate/compare`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(requestBody)
            });
            
            const data = await response.json();
            console.log('=== COMPARISON RESPONSE ===');
            console.log('Response data:', data);
            console.log('Total combinations:', data.summary?.total_combinations);
            console.log('Results count:', data.results?.length);
            
            if (!response.ok) {
                throw new Error(data.detail || data.error || 'Comparison failed');
            }
            
            setComparisonResults(data);
            setComparisonDialogVisible(true);
            
            // Check if fewer results than selected jobs
            const resultsCount = data.summary?.total_combinations || data.results?.length || 0;
            const expectedJobs = selectedJobs.length - jobsWithoutDecisions.length;
            
            const message = resultsCount < expectedJobs 
                ? `${resultsCount} combinations evaluated from ${expectedJobs} jobs with decisions (${jobsWithoutDecisions.length} jobs excluded due to no decisions), ${data.summary.qualified_count} qualified (recall ≥ 95%)`
                : `${resultsCount} combinations from ${selectedJobs.length} jobs evaluated, ${data.summary.qualified_count} qualified (recall ≥ 95%)`;
            
            toast.current?.show({
                severity: 'success',
                summary: 'Comparison Complete',
                detail: message,
                life: 5000
            });
            
        } catch (error) {
            console.error('Compare metrics failed:', error);
            toast.current?.show({
                severity: 'error',
                summary: 'Comparison Failed',
                detail: error.message,
                life: 5000
            });
        } finally {
            setMetricsLoading(false);
        }
    };

    // ==========================================================================
    // MAIN RENDER
    // ==========================================================================

    if (!selectedProject) {
        return (
            <div className="p-4">
                <Message severity="info" text="Please select a project to use LLM Screening" />
            </div>
        );
    }

    return (
        <div className="llm-screening p-3">
            {/* Status Bar */}
            <div className="mb-3" style={{marginBottom: '10px'}}>
                {renderServiceStatus()}
            </div>

            {/* Models */}
            {renderModelsPanel()}

            {/* Configuration */}
            {renderConfigPanel()}

            {/* Few-Shot Examples Panel */}
            <Panel header="Few-Shot Calibration Status" toggleable collapsed className="fewshot-panel mt-3">
                <div className="fewshot-content">
                    <div className="fewshot-status">
                        <Tag 
                            severity={fewShotReady ? "success" : "warning"} 
                            value={fewShotReady ? `✓ Ready (${fewShotExamples.length}/10 examples)` : "⚠ Not Ready"} 
                            icon={fewShotReady ? "pi pi-check-circle" : "pi pi-exclamation-triangle"}
                        />
                        <Button 
                            icon="pi pi-refresh" 
                            className="p-button-text p-button-sm ml-2"
                            onClick={loadFewShotExamples}
                            loading={fewShotLoading}
                            tooltip="Refresh calibration status"
                        />
                        <Button 
                            icon="pi pi-eye" 
                            className="p-button-text p-button-sm"
                            onClick={() => setFewShotDialogVisible(true)}
                            disabled={fewShotExamples.length === 0}
                            tooltip="Preview examples"
                        />
                    </div>
                    
                    {!fewShotReady && fewShotMissing.length > 0 && (
                        <Message 
                            severity="warn" 
                            text={`Missing decisions for ${fewShotMissing.length} calibration paper(s): ${fewShotMissing.slice(0, 3).join(', ')}${fewShotMissing.length > 3 ? '...' : ''}. Please complete screening these papers first.`}
                            className="mt-2 w-full"
                        />
                    )}
                    
                    {!fewShotReady && fewShotMissing.length === 0 && fewShotExamples.length === 0 && (
                        <Message 
                            severity="info" 
                            className="mt-2 w-full"
                        >
                            <div>
                                <strong>No FEW-SHOT papers selected.</strong>
                                <p className="mt-2 mb-2">
                                    To use few-shot mode, an Admin must:
                                </p>
                                <ol style={{ paddingLeft: '1.5rem', margin: 0 }}>
                                    <li>Complete screening of all 100 Gold Standard papers</li>
                                    <li>Go to "Screen Papers" tab</li>
                                    <li>Click "Select FEW-SHOT (10)" button</li>
                                    <li>Select exactly 10 screened papers as calibration examples</li>
                                </ol>
                                {userRoles?.includes('admin') && (
                                    <p className="mt-2 mb-0" style={{ fontStyle: 'italic', color: '#666' }}>
                                        You have Admin permissions - use the "Screen Papers" tab to select FEW-SHOT papers.
                                    </p>
                                )}
                            </div>
                        </Message>
                    )}
                    
                    {fewShotReady && (
                        <div className="fewshot-summary mt-2">
                            <Message severity="success" className="mb-2">
                                <strong>Ready for Few-Shot screening!</strong> Using {fewShotExamples.length} calibration examples.
                            </Message>
                            <small className="text-secondary">
                                Distribution: {' '}
                                <Tag value={`${fewShotExamples.filter(e => e.decision === 'INCLUDE').length} INCLUDE`} severity="success" className="mr-1" />
                                <Tag value={`${fewShotExamples.filter(e => e.decision === 'EXCLUDE').length} EXCLUDE`} severity="danger" className="mr-1" />
                                <Tag value={`${fewShotExamples.filter(e => e.decision === 'UNCERTAIN').length} UNCERTAIN`} severity="warning" />
                            </small>
                        </div>
                    )}
                </div>
            </Panel>

            {/* Start LLM Screening Button */}
            <div className="mb-3">
                <Button 
                    style={{marginTop: '10px', marginBottom: '10px'}}
                    label={activeJob ? 'Screening in Progress...' : 'Start LLM Screening'}
                    icon={activeJob ? 'pi pi-spin pi-spinner' : 'pi pi-play'}
                    size="large"
                    severity="success"
                    disabled={activeJob !== null || loading}
                    loading={loading}
                    onClick={startScreening}
                    className="w-full"
                />
            </div>

            {/* Progress */}
            {renderProgressPanel()}

            {/* History */}
            {renderJobsHistory()}

            {/* Evaluation Metrics Panel */}
            {/* <Panel header="Evaluation Metrics" className="mt-3">
                <div className="flex align-items-center gap-3 mb-3">
                    <label className="font-bold">UNCERTAIN treatment:</label>
                    <SelectButton
                        value={uncertainTreatment}
                        onChange={(e) => setUncertainTreatment(e.value)}
                        options={[
                            { label: 'As INCLUDE', value: 'INCLUDE' },
                            { label: 'As EXCLUDE', value: 'EXCLUDE' }
                        ]}
                    />
                    <Button 
                        label="Calculate Metrics For Job" 
                        icon="pi pi-calculator"
                        onClick={calculateMetricsForJob}
                        loading={metricsLoading}
                    />
                    <Button 
                        label="Calculate Metrics For Comparison" 
                        icon="pi pi-calculator"
                        onClick={calculateMetricsComparison}
                        loading={metricsLoading}
                    />
                </div>
                
                {evaluationMetrics && (
                    <div className="metrics-grid">
                        <div>Recall: <strong>{(evaluationMetrics.recall * 100).toFixed(1)}%</strong></div>
                        <div>Precision: <strong>{(evaluationMetrics.precision * 100).toFixed(1)}%</strong></div>
                        <div>F1: <strong>{(evaluationMetrics.f1 * 100).toFixed(1)}%</strong></div>
                        <div>WSS@95: <strong>{(evaluationMetrics.wss_95 * 100).toFixed(1)}%</strong></div>
                    </div>
                )}
            </Panel> */}

            {/* Few-Shot Examples Preview Dialog */}
            <Dialog 
                header="Few-Shot Examples Preview" 
                visible={fewShotDialogVisible} 
                onHide={() => setFewShotDialogVisible(false)}
                style={{ width: '80vw', maxWidth: '1000px' }}
                maximizable
                modal
            >
                <div className="fewshot-examples-list">
                    {fewShotExamples.length === 0 ? (
                        <Message severity="info" text="No few-shot examples available" />
                    ) : (
                        fewShotExamples.map((example, index) => (
                            <Card key={example.gs_id} className="fewshot-example-card mb-3">
                                <div className="example-header flex justify-content-between align-items-center">
                                    <strong>Example {index + 1}: {example.gs_id}</strong>
                                    <div>
                                        <Tag 
                                            severity={
                                                example.decision === 'INCLUDE' ? 'success' : 
                                                example.decision === 'EXCLUDE' ? 'danger' : 'warning'
                                            } 
                                            value={example.decision}
                                            className="mr-2"
                                        />
                                        <Tag severity="info" value={example.confidence} />
                                    </div>
                                </div>
                                
                                <Divider />
                                
                                <div className="example-title">
                                    <strong>Title:</strong>
                                    <p className="mt-1 mb-2">{example.title}</p>
                                </div>
                                
                                <div className="example-abstract">
                                    <strong>Abstract:</strong>
                                    <p className="mt-1 mb-2 text-secondary" style={{ fontSize: '0.9rem' }}>
                                        {example.abstract?.length > 400 
                                            ? example.abstract.substring(0, 400) + '...' 
                                            : example.abstract}
                                    </p>
                                </div>
                                
                                <Divider />
                                
                                <div className="example-criteria">
                                    {example.criteria_met?.length > 0 && (
                                        <div className="criteria-met mb-2">
                                            <strong>Criteria Met: </strong>
                                            {example.criteria_met.map(c => (
                                                <Tag key={c} value={c} severity="success" className="mr-1" />
                                            ))}
                                        </div>
                                    )}
                                    {example.criteria_violated?.length > 0 && (
                                        <div className="criteria-violated mb-2">
                                            <strong>Criteria Violated: </strong>
                                            {example.criteria_violated.map(c => (
                                                <Tag key={c} value={c} severity="danger" className="mr-1" />
                                            ))}
                                        </div>
                                    )}
                                </div>
                                
                                {example.reasoning && (
                                    <div className="example-reasoning">
                                        <strong>Reasoning:</strong>
                                        <p className="mt-1" style={{ fontStyle: 'italic', fontSize: '0.9rem' }}>
                                            {example.reasoning}
                                        </p>
                                    </div>
                                )}
                            </Card>
                        ))
                    )}
                </div>
            </Dialog>

            {/* Single Job Metrics Dialog */}
            <Dialog
                header={`Evaluation Metrics — ${selectedJobForMetrics || ''}`}
                visible={metricsDialogVisible}
                onHide={() => {
                    setMetricsDialogVisible(false);
                    setEvaluationMetrics(null);
                }}
                style={{ width: '90vw', maxWidth: '900px' }}
                maximizable
                modal
            >
                {evaluationMetrics && (
                    <div>
                        {/* Compact Summary Bar */}
                        <div style={{ 
                            display: 'flex', 
                            gap: '20px', 
                            marginBottom: '16px', 
                            padding: '12px 16px',
                            background: '#f9fafb',
                            borderRadius: '8px',
                            alignItems: 'center',
                            flexWrap: 'wrap'
                        }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                <span style={{ color: '#6b7280', fontSize: '13px' }}>Strategy:</span>
                                <span style={{ fontWeight: '600', fontSize: '14px' }}>{evaluationMetrics.strategy}</span>
                            </div>
                            <div style={{ width: '1px', height: '20px', background: '#d1d5db' }} />
                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                <span style={{ color: '#6b7280', fontSize: '13px' }}>Model(s):</span>
                                <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                                    {(evaluationMetrics.model || '').split(',').map((m, i) => (
                                        <span key={i} style={{ 
                                            background: '#e0e7ff', 
                                            padding: '2px 8px', 
                                            borderRadius: '4px',
                                            fontSize: '12px',
                                            fontWeight: '500'
                                        }}>
                                            {m.trim()}
                                        </span>
                                    ))}
                                </div>
                            </div>
                            <div style={{ width: '1px', height: '20px', background: '#d1d5db' }} />
                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                <span style={{ color: '#6b7280', fontSize: '13px' }}>Mode:</span>
                                <span style={{ fontWeight: '500', fontSize: '13px' }}>{evaluationMetrics.prompt_mode}</span>
                            </div>
                            <div style={{ width: '1px', height: '20px', background: '#d1d5db' }} />
                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                <span style={{ color: '#6b7280', fontSize: '13px' }}>
                                    {evaluationMetrics.coverage_warning ? 'Evaluated:' : 'Papers:'}
                                </span>
                                <span style={{ 
                                    fontWeight: '600', 
                                    fontSize: '14px',
                                    color: evaluationMetrics.coverage_warning ? '#ca8a04' : 'inherit'
                                }}>
                                    {evaluationMetrics.total_papers}
                                    {evaluationMetrics.coverage_warning && 
                                        ` / ${evaluationMetrics.predictions_count}`
                                    }
                                </span>
                            </div>
                        </div>

                        {/* Qualification Status Banner */}
                        <div style={{
                            background: evaluationMetrics.recall_threshold_met ? '#f0fdf4' : '#fef2f2',
                            border: `1px solid ${evaluationMetrics.recall_threshold_met ? '#86efac' : '#fecaca'}`,
                            borderRadius: '8px',
                            padding: '12px 16px',
                            marginBottom: '16px',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '12px'
                        }}>
                            <span style={{ fontSize: '20px' }}>{evaluationMetrics.recall_threshold_met ? '✅' : '❌'}</span>
                            <div>
                                <strong style={{ color: evaluationMetrics.recall_threshold_met ? '#166534' : '#991b1b' }}>
                                    {evaluationMetrics.recall_threshold_met ? 'QUALIFIED' : 'NOT QUALIFIED'}
                                </strong>
                                <span style={{ marginLeft: '12px', color: '#6b7280', fontSize: '13px' }}>
                                    Recall: {(evaluationMetrics.recall * 100).toFixed(1)}% 
                                    {evaluationMetrics.recall_threshold_met ? ' ≥ 95% threshold' : ' < 95% threshold'}
                                </span>
                            </div>
                        </div>

                        {/* Coverage Warning (if some papers lack ground truth) */}
                        {evaluationMetrics.coverage_warning && (
                            <div style={{
                                background: '#fffbeb',
                                border: '1px solid #fde047',
                                borderRadius: '8px',
                                padding: '12px 16px',
                                marginBottom: '16px',
                                display: 'flex',
                                alignItems: 'flex-start',
                                gap: '12px'
                            }}>
                                <span style={{ fontSize: '18px', marginTop: '2px' }}>⚠️</span>
                                <div style={{ flex: 1 }}>
                                    <strong style={{ color: '#854d0e', display: 'block', marginBottom: '4px' }}>
                                        Partial Ground Truth Coverage
                                    </strong>
                                    <div style={{ fontSize: '13px', color: '#6b7280' }}>
                                        <div>Job processed: <strong>{evaluationMetrics.predictions_count}</strong> papers</div>
                                        <div>Ground truth available: <strong>{evaluationMetrics.ground_truth_count}</strong> papers 
                                            {evaluationMetrics.includes_calibration === false && ' (calibration papers excluded from evaluation)'}
                                        </div>
                                        <div>Evaluated: <strong>{evaluationMetrics.total_papers}</strong> papers (intersection)</div>
                                        <div style={{ marginTop: '6px', color: '#92400e' }}>
                                            ℹ️ {evaluationMetrics.predictions_count - evaluationMetrics.total_papers} papers were processed but lack human screening labels and are excluded from evaluation.
                                        </div>
                                        {evaluationMetrics.includes_calibration === false && (
                                            <div style={{ marginTop: '6px', color: '#92400e' }}>
                                                💡 This job was run with "Evaluation papers only" checked, excluding {evaluationMetrics.predictions_count - evaluationMetrics.ground_truth_count} calibration papers from ground truth.
                                            </div>
                                        )}
                                    </div>
                                </div>
                            </div>
                        )}

                        {/* Info Banner - No warning but job includes calibration */}
                        {!evaluationMetrics.coverage_warning && evaluationMetrics.includes_calibration === true && (
                            <div style={{
                                background: '#f0f9ff',
                                border: '1px solid #7dd3fc',
                                borderRadius: '8px',
                                padding: '12px 16px',
                                marginBottom: '16px',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '12px'
                            }}>
                                <span style={{ fontSize: '16px' }}>ℹ️</span>
                                <div style={{ fontSize: '13px', color: '#0c4a6e' }}>
                                    This job included calibration papers. All {evaluationMetrics.total_papers} papers (evaluation + calibration) are included in metrics.
                                </div>
                            </div>
                        )}

                        {/* Compact Metrics Row */}
                        <div style={{ 
                            display: 'grid', 
                            gridTemplateColumns: 'repeat(4, 1fr)', 
                            gap: '12px',
                            marginBottom: '16px'
                        }}>
                            {[
                                { label: 'Recall', value: evaluationMetrics.recall, critical: true, ci: evaluationMetrics.confidence_intervals },
                                { label: 'Precision', value: evaluationMetrics.precision, ci: evaluationMetrics.confidence_intervals },
                                { label: 'F1 Score', value: evaluationMetrics.f1 },
                                { label: 'WSS@95', value: evaluationMetrics.wss_95, highlight: true },
                            ].map((m, i) => (
                                <div key={i} style={{
                                    background: m.critical ? (evaluationMetrics.recall >= 0.95 ? '#f0fdf4' : '#fef2f2') : '#f9fafb',
                                    border: `1px solid ${m.critical ? (evaluationMetrics.recall >= 0.95 ? '#86efac' : '#fecaca') : '#e5e7eb'}`,
                                    borderRadius: '8px',
                                    padding: '12px',
                                    textAlign: 'center'
                                }}>
                                    <div style={{ 
                                        fontSize: '24px', 
                                        fontWeight: '700',
                                        color: m.critical ? (evaluationMetrics.recall >= 0.95 ? '#16a34a' : '#dc2626') : (m.highlight ? '#7c3aed' : '#1f2937')
                                    }}>
                                        {(m.value * 100).toFixed(1)}%
                                    </div>
                                    <div style={{ fontSize: '12px', color: '#6b7280', marginTop: '4px' }}>{m.label}</div>
                                    {m.ci && m.label === 'Recall' && m.ci.recall_ci_lower && (
                                        <div style={{ fontSize: '10px', color: '#9ca3af', marginTop: '2px' }}>
                                            95% CI: {(m.ci.recall_ci_lower * 100).toFixed(1)}%-{(m.ci.recall_ci_upper * 100).toFixed(1)}%
                                        </div>
                                    )}
                                </div>
                            ))}
                        </div>

                        {/* Legend Toggle */}
                        <Button
                            label="ℹ️ Metrics Legend"
                            icon={legendVisible ? "pi pi-chevron-down" : "pi pi-chevron-right"}
                            className="p-button-text p-button-sm mb-2"
                            onClick={() => setLegendVisible(!legendVisible)}
                        />

                        {/* Collapsible Legend - same as in Comparison Dialog */}
                        {legendVisible && (
                            <div style={{
                                background: '#fffbeb',
                                border: '1px solid #fde047',
                                borderRadius: '8px',
                                padding: '16px',
                                marginBottom: '16px',
                                fontSize: '13px'
                            }}>
                                {/* Same legend content as Comparison Dialog */}
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '24px' }}>
                                    <div>
                                        <strong style={{ fontSize: '14px', display: 'block', marginBottom: '10px' }}>Confusion Matrix</strong>
                                        <table style={{ borderCollapse: 'collapse', fontSize: '12px' }}>
                                            <tbody>
                                                <tr>
                                                    <td style={{ padding: '6px 10px' }}></td>
                                                    <td style={{ padding: '6px 10px', fontWeight: '600', color: '#4b5563', textAlign: 'center' }}>Human:<br/>INCLUDE</td>
                                                    <td style={{ padding: '6px 10px', fontWeight: '600', color: '#4b5563', textAlign: 'center' }}>Human:<br/>EXCLUDE</td>
                                                </tr>
                                                <tr>
                                                    <td style={{ padding: '6px 10px', fontWeight: '600', color: '#4b5563' }}>LLM: INCLUDE</td>
                                                    <td style={{ padding: '8px 12px', background: '#dcfce7', borderRadius: '4px', textAlign: 'center', fontWeight: '600' }}>TP</td>
                                                    <td style={{ padding: '8px 12px', background: '#fef9c3', borderRadius: '4px', textAlign: 'center', fontWeight: '600' }}>FP</td>
                                                </tr>
                                                <tr>
                                                    <td style={{ padding: '6px 10px', fontWeight: '600', color: '#4b5563' }}>LLM: EXCLUDE</td>
                                                    <td style={{ padding: '8px 12px', background: '#fecaca', borderRadius: '4px', textAlign: 'center', fontWeight: '700' }}>FN</td>
                                                    <td style={{ padding: '8px 12px', background: '#dcfce7', borderRadius: '4px', textAlign: 'center', fontWeight: '600' }}>TN</td>
                                                </tr>
                                            </tbody>
                                        </table>
                                    </div>
                                    <div style={{ minWidth: '320px' }}>
                                        <strong style={{ fontSize: '14px', display: 'block', marginBottom: '10px' }}>Metrics</strong>
                                        <table style={{ fontSize: '12px', borderCollapse: 'collapse' }}>
                                            <tbody>
                                                <tr>
                                                    <td style={{ padding: '4px 8px', fontWeight: '600' }}>Recall</td>
                                                    <td style={{ padding: '4px 8px', fontFamily: 'monospace', background: '#f3f4f6', borderRadius: '3px' }}>TP / (TP + FN)</td>
                                                    <td style={{ padding: '4px 8px', color: '#6b7280' }}>% of relevant papers found</td>
                                                </tr>
                                                <tr>
                                                    <td style={{ padding: '4px 8px', fontWeight: '600' }}>Precision</td>
                                                    <td style={{ padding: '4px 8px', fontFamily: 'monospace', background: '#f3f4f6', borderRadius: '3px' }}>TP / (TP + FP)</td>
                                                    <td style={{ padding: '4px 8px', color: '#6b7280' }}>% of includes that are relevant</td>
                                                </tr>
                                                <tr>
                                                    <td style={{ padding: '4px 8px', fontWeight: '600' }}>F1</td>
                                                    <td style={{ padding: '4px 8px', fontFamily: 'monospace', background: '#f3f4f6', borderRadius: '3px' }}>2·P·R / (P + R)</td>
                                                    <td style={{ padding: '4px 8px', color: '#6b7280' }}>harmonic mean</td>
                                                </tr>
                                                <tr>
                                                    <td style={{ padding: '4px 8px', fontWeight: '600' }}>WSS@95</td>
                                                    <td style={{ padding: '4px 8px', fontFamily: 'monospace', background: '#f3f4f6', borderRadius: '3px' }}>(TN+FN)/N − 0.05</td>
                                                    <td style={{ padding: '4px 8px', color: '#6b7280' }}>work saved</td>
                                                </tr>
                                            </tbody>
                                        </table>
                                    </div>
                                </div>
                            </div>
                        )}

                        {/* Confusion Matrix as 2x2 Table */}
                        <div style={{
                            background: '#f9fafb',
                            border: '1px solid #e5e7eb',
                            borderRadius: '8px',
                            padding: '16px',
                            marginBottom: '16px'
                        }}>
                            <strong style={{ fontSize: '14px', display: 'block', marginBottom: '12px' }}>Confusion Matrix Values</strong>
                            
                            <div style={{ display: 'flex', justifyContent: 'center' }}>
                                <table style={{ borderCollapse: 'collapse', fontSize: '13px' }}>
                                    <thead>
                                        <tr>
                                            <th style={{ padding: '10px 16px' }}></th>
                                            <th style={{ 
                                                padding: '10px 16px', 
                                                background: '#f3f4f6', 
                                                border: '1px solid #e5e7eb',
                                                fontWeight: '600',
                                                color: '#4b5563',
                                                textAlign: 'center'
                                            }}>
                                                Human: INCLUDE
                                            </th>
                                            <th style={{ 
                                                padding: '10px 16px', 
                                                background: '#f3f4f6', 
                                                border: '1px solid #e5e7eb',
                                                fontWeight: '600',
                                                color: '#4b5563',
                                                textAlign: 'center'
                                            }}>
                                                Human: EXCLUDE
                                            </th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        <tr>
                                            <td style={{ 
                                                padding: '10px 16px', 
                                                background: '#f3f4f6', 
                                                border: '1px solid #e5e7eb',
                                                fontWeight: '600',
                                                color: '#4b5563'
                                            }}>
                                                LLM: INCLUDE
                                            </td>
                                            <td style={{ 
                                                padding: '16px 24px', 
                                                background: '#dcfce7', 
                                                border: '1px solid #86efac',
                                                textAlign: 'center',
                                                minWidth: '100px'
                                            }}>
                                                <div style={{ fontSize: '28px', fontWeight: '700', color: '#166534' }}>
                                                    {evaluationMetrics.confusion_matrix?.TP}
                                                </div>
                                                <div style={{ fontSize: '11px', color: '#166534', marginTop: '4px' }}>TP</div>
                                            </td>
                                            <td style={{ 
                                                padding: '16px 24px', 
                                                background: '#fef9c3', 
                                                border: '1px solid #fde047',
                                                textAlign: 'center',
                                                minWidth: '100px'
                                            }}>
                                                <div style={{ fontSize: '28px', fontWeight: '700', color: '#854d0e' }}>
                                                    {evaluationMetrics.confusion_matrix?.FP}
                                                </div>
                                                <div style={{ fontSize: '11px', color: '#854d0e', marginTop: '4px' }}>FP</div>
                                            </td>
                                        </tr>
                                        <tr>
                                            <td style={{ 
                                                padding: '10px 16px', 
                                                background: '#f3f4f6', 
                                                border: '1px solid #e5e7eb',
                                                fontWeight: '600',
                                                color: '#4b5563'
                                            }}>
                                                LLM: EXCLUDE
                                            </td>
                                            <td style={{ 
                                                padding: '16px 24px', 
                                                background: evaluationMetrics.confusion_matrix?.FN > 0 ? '#fecaca' : '#dcfce7', 
                                                border: `1px solid ${evaluationMetrics.confusion_matrix?.FN > 0 ? '#fca5a5' : '#86efac'}`,
                                                textAlign: 'center',
                                                minWidth: '100px'
                                            }}>
                                                <div style={{ 
                                                    fontSize: '28px', 
                                                    fontWeight: '700', 
                                                    color: evaluationMetrics.confusion_matrix?.FN > 0 ? '#dc2626' : '#166534' 
                                                }}>
                                                    {evaluationMetrics.confusion_matrix?.FN}
                                                </div>
                                                <div style={{ 
                                                    fontSize: '11px', 
                                                    color: evaluationMetrics.confusion_matrix?.FN > 0 ? '#dc2626' : '#166534', 
                                                    marginTop: '4px',
                                                    fontWeight: evaluationMetrics.confusion_matrix?.FN > 0 ? '700' : '400'
                                                }}>
                                                    FN {evaluationMetrics.confusion_matrix?.FN > 0 && '⚠️'}
                                                </div>
                                            </td>
                                            <td style={{ 
                                                padding: '16px 24px', 
                                                background: '#dcfce7', 
                                                border: '1px solid #86efac',
                                                textAlign: 'center',
                                                minWidth: '100px'
                                            }}>
                                                <div style={{ fontSize: '28px', fontWeight: '700', color: '#166534' }}>
                                                    {evaluationMetrics.confusion_matrix?.TN}
                                                </div>
                                                <div style={{ fontSize: '11px', color: '#166534', marginTop: '4px' }}>TN</div>
                                            </td>
                                        </tr>
                                    </tbody>
                                </table>
                            </div>

                            {/* Summary below matrix */}
                            <div style={{ 
                                display: 'flex', 
                                justifyContent: 'center', 
                                gap: '24px', 
                                marginTop: '12px',
                                fontSize: '12px',
                                color: '#6b7280'
                            }}>
                                <span>Total: <strong>{evaluationMetrics.total_papers}</strong> papers</span>
                                <span>Correct: <strong>{(evaluationMetrics.confusion_matrix?.TP || 0) + (evaluationMetrics.confusion_matrix?.TN || 0)}</strong></span>
                                <span>Errors: <strong>{(evaluationMetrics.confusion_matrix?.FP || 0) + (evaluationMetrics.confusion_matrix?.FN || 0)}</strong></span>
                            </div>
                        </div>

                        {/* S5 Two-Stage Metrics */}
                        {evaluationMetrics.s5_stage_metrics && (
                            <div style={{
                                background: 'linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%)',
                                border: '1px solid #7dd3fc',
                                borderRadius: '8px',
                                padding: '16px',
                                marginBottom: '16px'
                            }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
                                    <i className="pi pi-sitemap" style={{ color: '#0284c7', fontSize: '18px' }}></i>
                                    <strong style={{ fontSize: '15px', color: '#0c4a6e' }}>S5 Two-Stage Performance</strong>
                                </div>
                                
                                {/* Model Roles */}
                                {evaluationMetrics.s5_stage_metrics.model_roles && (
                                    <div style={{
                                        background: 'white',
                                        border: '1px solid #bae6fd',
                                        borderRadius: '6px',
                                        padding: '10px',
                                        marginBottom: '12px',
                                        fontSize: '13px'
                                    }}>
                                        <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap' }}>
                                            <div>
                                                <span style={{ color: '#6b7280' }}>Fast Filter: </span>
                                                <span style={{ 
                                                    background: '#dbeafe', 
                                                    padding: '2px 8px', 
                                                    borderRadius: '4px',
                                                    fontWeight: '600',
                                                    color: '#0c4a6e'
                                                }}>
                                                    {evaluationMetrics.s5_stage_metrics.model_roles.fast_filter}
                                                </span>
                                            </div>
                                            <div>
                                                <span style={{ color: '#6b7280' }}>Debate: </span>
                                                {(() => {
                                                    const debateModels = evaluationMetrics.s5_stage_metrics.model_roles.debate;
                                                    // Handle both array and comma-separated string
                                                    const modelsArray = Array.isArray(debateModels) 
                                                        ? debateModels 
                                                        : (typeof debateModels === 'string' 
                                                            ? debateModels.split(',').map(m => m.trim()) 
                                                            : [debateModels]);
                                                    
                                                    return modelsArray.map((model, i) => (
                                                        <span key={i} style={{ 
                                                            background: '#dbeafe', 
                                                            padding: '2px 8px', 
                                                            borderRadius: '4px',
                                                            fontWeight: '600',
                                                            color: '#0c4a6e',
                                                            marginRight: '4px',
                                                            display: 'inline-block',
                                                            marginBottom: '4px'
                                                        }}>
                                                            {model}
                                                        </span>
                                                    ));
                                                })()}
                                            </div>
                                        </div>
                                    </div>
                                )}

                                {/* Stage Breakdown */}
                                <div style={{ 
                                    display: 'grid', 
                                    gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', 
                                    gap: '10px',
                                    marginBottom: '12px'
                                }}>
                                    <div style={{
                                        background: 'white',
                                        border: '1px solid #bae6fd',
                                        borderRadius: '6px',
                                        padding: '10px',
                                        textAlign: 'center'
                                    }}>
                                        <div style={{ fontSize: '24px', fontWeight: '700', color: '#0284c7' }}>
                                            {evaluationMetrics.s5_stage_metrics.st1_excl}
                                        </div>
                                        <div style={{ fontSize: '11px', color: '#6b7280', marginTop: '2px' }}>
                                            Stage 1 Excluded
                                        </div>
                                        <div style={{ fontSize: '13px', fontWeight: '600', color: '#0c4a6e', marginTop: '2px' }}>
                                            {evaluationMetrics.s5_stage_metrics.st1_rate}%
                                        </div>
                                    </div>
                                    
                                    <div style={{
                                        background: 'white',
                                        border: '1px solid #bae6fd',
                                        borderRadius: '6px',
                                        padding: '10px',
                                        textAlign: 'center'
                                    }}>
                                        <div style={{ fontSize: '24px', fontWeight: '700', color: '#0284c7' }}>
                                            {evaluationMetrics.s5_stage_metrics.st2_papers}
                                        </div>
                                        <div style={{ fontSize: '11px', color: '#6b7280', marginTop: '2px' }}>
                                            Stage 2 Debated
                                        </div>
                                    </div>
                                    
                                    <div style={{
                                        background: 'white',
                                        border: '1px solid #bae6fd',
                                        borderRadius: '6px',
                                        padding: '10px',
                                        textAlign: 'center'
                                    }}>
                                        <div style={{ fontSize: '24px', fontWeight: '700', color: '#16a34a' }}>
                                            {evaluationMetrics.s5_stage_metrics.time_savings_pct}%
                                        </div>
                                        <div style={{ fontSize: '11px', color: '#6b7280', marginTop: '2px' }}>
                                            Time Saved
                                        </div>
                                    </div>
                                    
                                    <div style={{
                                        background: 'white',
                                        border: '1px solid #bae6fd',
                                        borderRadius: '6px',
                                        padding: '10px',
                                        textAlign: 'center'
                                    }}>
                                        <div style={{ fontSize: '24px', fontWeight: '700', color: '#7c3aed' }}>
                                            {evaluationMetrics.s5_stage_metrics.debate_calls_saved}
                                        </div>
                                        <div style={{ fontSize: '11px', color: '#6b7280', marginTop: '2px' }}>
                                            LLM Calls Saved
                                        </div>
                                    </div>
                                </div>

                                {/* Time Details */}
                                <div style={{
                                    background: 'white',
                                    border: '1px solid #bae6fd',
                                    borderRadius: '6px',
                                    padding: '10px',
                                    fontSize: '12px'
                                }}>
                                    <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', justifyContent: 'center' }}>
                                        <div>
                                            <span style={{ color: '#6b7280' }}>Avg Stage 1: </span>
                                            <strong style={{ color: '#0c4a6e' }}>
                                                {evaluationMetrics.s5_stage_metrics.avg_st1_time_sec}s
                                            </strong>
                                        </div>
                                        <div style={{ width: '1px', background: '#bae6fd' }} />
                                        <div>
                                            <span style={{ color: '#6b7280' }}>Avg Stage 2: </span>
                                            <strong style={{ color: '#0c4a6e' }}>
                                                {evaluationMetrics.s5_stage_metrics.avg_st2_time_sec}s
                                            </strong>
                                        </div>
                                        <div style={{ width: '1px', background: '#bae6fd' }} />
                                        <div>
                                            <span style={{ color: '#6b7280' }}>Total Time: </span>
                                            <strong style={{ color: '#0c4a6e' }}>
                                                {evaluationMetrics.s5_stage_metrics.total_time_sec}s
                                            </strong>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        )}

                        {/* Error Analysis Summary */}
                        {(evaluationMetrics.error_analysis?.false_negatives_count > 0 || 
                        evaluationMetrics.error_analysis?.false_positives_count > 0) && (
                            <>
                                <Divider />
                                <h4>Error Analysis Summary</h4>
                                
                                {/* FN Summary */}
                                {evaluationMetrics.error_analysis?.false_negatives_count > 0 && (
                                    <div className="mb-3">
                                        <p className="text-sm text-500 mb-2">
                                            <i className="pi pi-exclamation-triangle text-red-500 mr-2"></i>
                                            <strong>False Negatives ({evaluationMetrics.error_analysis.false_negatives_count}):</strong> 
                                            {' '}Relevant papers incorrectly excluded
                                        </p>
                                        <div className="flex flex-wrap gap-2">
                                            {evaluationMetrics.error_analysis.false_negatives_sample?.slice(0, 5).map(id => (
                                                <Chip key={id} label={id} className="bg-red-100" />
                                            ))}
                                            {evaluationMetrics.error_analysis.false_negatives_count > 5 && (
                                                <Chip label={`+${evaluationMetrics.error_analysis.false_negatives_count - 5} more`} />
                                            )}
                                        </div>
                                    </div>
                                )}
                                
                                {/* FP Summary */}
                                {evaluationMetrics.error_analysis?.false_positives_count > 0 && (
                                    <div className="mb-3">
                                        <p className="text-sm text-500 mb-2">
                                            <i className="pi pi-info-circle text-orange-500 mr-2"></i>
                                            <strong>False Positives ({evaluationMetrics.error_analysis.false_positives_count}):</strong> 
                                            {' '}Non-relevant papers incorrectly included
                                        </p>
                                        <div className="flex flex-wrap gap-2">
                                            {evaluationMetrics.error_analysis.false_positives_sample?.slice(0, 5).map(id => (
                                                <Chip key={id} label={id} className="bg-orange-100" />
                                            ))}
                                            {evaluationMetrics.error_analysis.false_positives_count > 5 && (
                                                <Chip label={`+${evaluationMetrics.error_analysis.false_positives_count - 5} more`} />
                                            )}
                                        </div>
                                    </div>
                                )}
                                
                                {/* Detailed Analysis Button */}
                                <div className="flex justify-content-center mt-3">
                                    <Button
                                        style={{marginTop: '10px', marginBottom: '10px'}}
                                        label="🔍 Detailed Error Analysis"
                                        icon="pi pi-search-plus"
                                        className="p-button-outlined p-button-secondary"
                                        loading={errorAnalysisLoading}
                                        onClick={() => fetchErrorAnalysis({
                                            strategy: evaluationMetrics.strategy,
                                            model: evaluationMetrics.model,
                                            prompt_mode: evaluationMetrics.prompt_mode,
                                            job_id: evaluationMetrics.job_id
                                        })}
                                        tooltip="Analyze which criteria cause errors"
                                    />
                                </div>
                            </>
                        )}

                        {/* Export Buttons */}
                        <Divider />
                        <div style={{
                            display: 'flex',
                            gap: '10px',
                            justifyContent: 'center',
                            marginBottom: '16px'
                        }}>
                            <Button
                                label="Export JSON"
                                icon="pi pi-download"
                                className="export-json-btn"
                                onClick={exportJobMetricsJSON}
                                tooltip="Export metrics to JSON format"
                            />
                            <Button
                                label="Export XLSX"
                                icon="pi pi-file-excel"
                                className="export-txt-btn"
                                onClick={exportJobMetricsXLSX}
                                tooltip="Export metrics to Excel format"
                            />
                        </div>

                        {/* Footer Info */}
                        <div style={{
                            fontSize: '12px',
                            color: '#6b7280',
                            padding: '12px',
                            background: '#f9fafb',
                            borderRadius: '6px'
                        }}>
                            <strong>UNCERTAIN treated as:</strong> {evaluationMetrics.uncertain_treatment}
                        </div>
                    </div>
                )}
            </Dialog>

            {/* Comparison Results Dialog */}
            <Dialog
                header="Strategy Comparison Results"
                visible={comparisonDialogVisible}
                onHide={() => setComparisonDialogVisible(false)}
                style={{ width: '95vw', maxWidth: '1400px' }}
                maximizable
                modal
            >
                {comparisonResults && (
                    <div className="comparison-results">
                        {/* Compact Summary Bar */}
                        <div style={{ 
                            display: 'flex', 
                            gap: '24px', 
                            marginBottom: '16px', 
                            padding: '12px 16px',
                            background: '#f9fafb',
                            borderRadius: '8px',
                            alignItems: 'center',
                            flexWrap: 'wrap'
                        }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <span style={{ color: '#6b7280', fontSize: '13px' }}>Combinations:</span>
                                <span style={{ fontWeight: '600', fontSize: '15px' }}>{comparisonResults.summary.total_combinations}</span>
                            </div>
                            <div style={{ width: '1px', height: '20px', background: '#d1d5db' }} />
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <span style={{ color: '#16a34a', fontSize: '13px' }}>✓ Qualified:</span>
                                <span style={{ fontWeight: '600', fontSize: '15px', color: '#16a34a' }}>{comparisonResults.summary.qualified_count}</span>
                            </div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <span style={{ color: '#ca8a04', fontSize: '13px' }}>✗ Unqualified:</span>
                                <span style={{ fontWeight: '600', fontSize: '15px', color: '#ca8a04' }}>{comparisonResults.summary.unqualified_count}</span>
                            </div>
                            <div style={{ width: '1px', height: '20px', background: '#d1d5db' }} />
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <span style={{ color: '#6b7280', fontSize: '13px' }}>Ground Truth:</span>
                                <span style={{ fontWeight: '600', fontSize: '15px' }}>{comparisonResults.summary.ground_truth_papers} papers</span>
                            </div>
                        </div>
                        
                        {/* Best Strategy Highlight */}
                        {comparisonResults.summary.best_strategy && (
                            <div style={{
                                background: '#f0fdf4',
                                border: '1px solid #86efac',
                                borderRadius: '8px',
                                padding: '12px 16px',
                                marginBottom: '16px',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '12px'
                            }}>
                                <span style={{ fontSize: '20px' }}>🏆</span>
                                <div>
                                    <strong>Best:</strong> {comparisonResults.summary.best_strategy.strategy} | {comparisonResults.summary.best_strategy.model} | {comparisonResults.summary.best_strategy.prompt_mode}
                                    <span style={{ marginLeft: '16px', color: '#6b7280', fontSize: '13px' }}>
                                        Recall: {(comparisonResults.summary.best_strategy.recall * 100).toFixed(1)}% | 
                                        WSS@95: {(comparisonResults.summary.best_strategy.wss_95 * 100).toFixed(1)}%
                                    </span>
                                </div>
                            </div>
                        )}
                        
                        {/* Collapsible Legend */}
                        <Button
                            label="ℹ️ Metrics Legend"
                            icon={legendVisible ? "pi pi-chevron-down" : "pi pi-chevron-right"}
                            className="p-button-text p-button-sm mb-2"
                            onClick={() => setLegendVisible(!legendVisible)}
                        />
                        
                        {legendVisible && (
                            <div style={{
                                background: '#fffbeb',
                                border: '1px solid #fde047',
                                borderRadius: '8px',
                                padding: '16px',
                                marginBottom: '16px',
                                fontSize: '13px'
                            }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '24px' }}>
                                    {/* Confusion Matrix Visual */}
                                    <div>
                                        <strong style={{ fontSize: '14px', display: 'block', marginBottom: '10px' }}>Confusion Matrix</strong>
                                        <table style={{ borderCollapse: 'collapse', fontSize: '12px' }}>
                                            <tbody>
                                                <tr>
                                                    <td style={{ padding: '6px 10px' }}></td>
                                                    <td style={{ padding: '6px 10px', fontWeight: '600', color: '#4b5563', textAlign: 'center' }}>Human:<br/>INCLUDE</td>
                                                    <td style={{ padding: '6px 10px', fontWeight: '600', color: '#4b5563', textAlign: 'center' }}>Human:<br/>EXCLUDE</td>
                                                </tr>
                                                <tr>
                                                    <td style={{ padding: '6px 10px', fontWeight: '600', color: '#4b5563' }}>LLM: INCLUDE</td>
                                                    <td style={{ padding: '8px 12px', background: '#dcfce7', borderRadius: '4px', textAlign: 'center', fontWeight: '600' }}>TP</td>
                                                    <td style={{ padding: '8px 12px', background: '#fef9c3', borderRadius: '4px', textAlign: 'center', fontWeight: '600' }}>FP</td>
                                                </tr>
                                                <tr>
                                                    <td style={{ padding: '6px 10px', fontWeight: '600', color: '#4b5563' }}>LLM: EXCLUDE</td>
                                                    <td style={{ padding: '8px 12px', background: '#fecaca', borderRadius: '4px', textAlign: 'center', fontWeight: '700' }}>FN</td>
                                                    <td style={{ padding: '8px 12px', background: '#dcfce7', borderRadius: '4px', textAlign: 'center', fontWeight: '600' }}>TN</td>
                                                </tr>
                                            </tbody>
                                        </table>
                                    </div>

                                    {/* Terms */}
                                    <div style={{ minWidth: '280px' }}>
                                        <strong style={{ fontSize: '14px', display: 'block', marginBottom: '10px' }}>Terms</strong>
                                        <div style={{ display: 'grid', gap: '6px', fontSize: '12px' }}>
                                            <div><span style={{ background: '#dcfce7', padding: '2px 6px', borderRadius: '3px', fontWeight: '600' }}>TP</span> True Positive — correctly included relevant paper</div>
                                            <div><span style={{ background: '#dcfce7', padding: '2px 6px', borderRadius: '3px', fontWeight: '600' }}>TN</span> True Negative — correctly excluded irrelevant paper</div>
                                            <div><span style={{ background: '#fef9c3', padding: '2px 6px', borderRadius: '3px', fontWeight: '600' }}>FP</span> False Positive — incorrectly included (extra work)</div>
                                            <div><span style={{ background: '#fecaca', padding: '2px 6px', borderRadius: '3px', fontWeight: '700' }}>FN</span> False Negative — incorrectly excluded <strong style={{ color: '#dc2626' }}>(CRITICAL!)</strong></div>
                                        </div>
                                    </div>

                                    {/* Metrics Formulas */}
                                    <div style={{ minWidth: '320px' }}>
                                        <strong style={{ fontSize: '14px', display: 'block', marginBottom: '10px' }}>Metrics</strong>
                                        <table style={{ fontSize: '12px', borderCollapse: 'collapse' }}>
                                            <tbody>
                                                <tr>
                                                    <td style={{ padding: '4px 8px', fontWeight: '600' }}>Recall</td>
                                                    <td style={{ padding: '4px 8px', fontFamily: 'monospace', background: '#f3f4f6', borderRadius: '3px' }}>TP / (TP + FN)</td>
                                                    <td style={{ padding: '4px 8px', color: '#6b7280' }}>% of relevant papers found</td>
                                                </tr>
                                                <tr>
                                                    <td style={{ padding: '4px 8px', fontWeight: '600' }}>Precision</td>
                                                    <td style={{ padding: '4px 8px', fontFamily: 'monospace', background: '#f3f4f6', borderRadius: '3px' }}>TP / (TP + FP)</td>
                                                    <td style={{ padding: '4px 8px', color: '#6b7280' }}>% of includes that are relevant</td>
                                                </tr>
                                                <tr>
                                                    <td style={{ padding: '4px 8px', fontWeight: '600' }}>F1</td>
                                                    <td style={{ padding: '4px 8px', fontFamily: 'monospace', background: '#f3f4f6', borderRadius: '3px' }}>2·P·R / (P + R)</td>
                                                    <td style={{ padding: '4px 8px', color: '#6b7280' }}>harmonic mean of Precision & Recall</td>
                                                </tr>
                                                <tr>
                                                    <td style={{ padding: '4px 8px', fontWeight: '600' }}>WSS@95</td>
                                                    <td style={{ padding: '4px 8px', fontFamily: 'monospace', background: '#f3f4f6', borderRadius: '3px' }}>(TN+FN)/N − 0.05</td>
                                                    <td style={{ padding: '4px 8px', color: '#6b7280' }}>work saved vs random at 95% recall</td>
                                                </tr>
                                            </tbody>
                                        </table>
                                    </div>
                                </div>
                            </div>
                        )}
                        
                        {/* Export Buttons */}
                        <div className="flex justify-content-end gap-2 mb-3" style={{marginBottom: '10px'}}>
                            <Button 
                                label="Export JSON" 
                                icon="pi pi-download"
                                className="p-button-outlined p-button-secondary export-json-btn"
                                onClick={exportComparisonJSON}
                                tooltip="Download comparison data as JSON"
                            />
                            <Button 
                                label="Export Excel" 
                                icon="pi pi-file-excel"
                                className="p-button-outlined p-button-secondary export-txt-btn"
                                onClick={exportComparisonXLSX}
                                tooltip="Download comparison results as Excel spreadsheet"
                            />
                        </div>
                        
                        {/* Results Table */}
                        <DataTable 
                            value={comparisonResults.results} 
                            size="small"
                            sortField="rank"
                            sortOrder={1}
                            scrollable
                            scrollHeight="400px"
                            rowClassName={(data) => data.qualified ? 'bg-green-50' : ''}
                        >
                            <Column field="rank" header="#" style={{ width: '50px' }} sortable />
                            <Column 
                                field="qualified" 
                                header="Status" 
                                body={(row) => (
                                    <Tag 
                                        severity={row.qualified ? 'success' : 'warning'} 
                                        value={row.qualified ? '✓ Qual' : '✗ Unq'} 
                                    />
                                )}
                                style={{ width: '90px' }}
                            />
                            <Column field="strategy" header="Strategy" sortable />
                            <Column 
                                field="model" 
                                header="Model(s)" 
                                body={(row) => {
                                    const models = row.model ? row.model.split(',') : [];
                                    if (models.length <= 1) return row.model;
                                    return (
                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                                            {models.map((m, i) => (
                                                <span key={i} style={{ 
                                                    background: '#e0e7ff', 
                                                    padding: '1px 6px', 
                                                    borderRadius: '3px',
                                                    fontSize: '11px'
                                                }}>
                                                    {m.trim()}
                                                </span>
                                            ))}
                                        </div>
                                    );
                                }}
                                sortable 
                            />
                            <Column field="prompt_mode" header="Mode" sortable />
                            <Column 
                                field="recall" 
                                header="Recall" 
                                body={(row) => (
                                    <span style={{ 
                                        fontWeight: '700',
                                        color: row.recall >= 0.95 ? '#16a34a' : '#dc2626'
                                    }}>
                                        {(row.recall * 100).toFixed(1)}%
                                    </span>
                                )}
                                sortable
                            />
                            <Column 
                                field="precision" 
                                header="Precision" 
                                body={(row) => `${(row.precision * 100).toFixed(1)}%`}
                                sortable
                            />
                            <Column 
                                field="f1" 
                                header="F1" 
                                body={(row) => `${(row.f1 * 100).toFixed(1)}%`}
                                sortable
                            />
                            <Column 
                                field="wss_95" 
                                header="WSS@95" 
                                body={(row) => (
                                    <span style={{ fontWeight: '600' }}>{(row.wss_95 * 100).toFixed(1)}%</span>
                                )}
                                sortable
                            />
                            <Column 
                                header={<div style={{ textAlign: 'center' }}>Confusion<div style={{ fontSize: '10px', fontWeight: 'normal', color: '#9ca3af' }}>TP|TN|FP|FN</div></div>}
                                body={(row) => (
                                    <div style={{ 
                                        display: 'flex', 
                                        gap: '3px', 
                                        justifyContent: 'center',
                                        alignItems: 'center'
                                    }}>
                                        <span style={{ 
                                            background: '#dcfce7', 
                                            padding: '3px 6px', 
                                            borderRadius: '3px',
                                            minWidth: '32px',
                                            textAlign: 'center',
                                            fontSize: '12px',
                                            fontWeight: '500'
                                        }}>
                                            {row.confusion_matrix?.TP}
                                        </span>
                                        <span style={{ 
                                            background: '#e0e7ff', 
                                            padding: '3px 6px', 
                                            borderRadius: '3px',
                                            minWidth: '42px',
                                            textAlign: 'center',
                                            fontSize: '12px',
                                            fontWeight: '500'
                                        }}>
                                            {row.confusion_matrix?.TN}
                                        </span>
                                        <span style={{ 
                                            background: '#fef9c3', 
                                            padding: '3px 6px', 
                                            borderRadius: '3px',
                                            minWidth: '32px',
                                            textAlign: 'center',
                                            fontSize: '12px',
                                            fontWeight: '500'
                                        }}>
                                            {row.confusion_matrix?.FP}
                                        </span>
                                        <span style={{ 
                                            background: row.confusion_matrix?.FN > 0 ? '#fecaca' : '#dcfce7', 
                                            padding: '3px 6px', 
                                            borderRadius: '3px',
                                            minWidth: '28px',
                                            textAlign: 'center',
                                            fontSize: '12px',
                                            fontWeight: row.confusion_matrix?.FN > 0 ? '700' : '500',
                                            color: row.confusion_matrix?.FN > 0 ? '#dc2626' : 'inherit'
                                        }}>
                                            {row.confusion_matrix?.FN}
                                        </span>
                                    </div>
                                )}
                            />
                            <Column 
                                header="S5 Metrics"
                                body={(row) => {
                                    if (!row.s5_stage_metrics) return <span style={{ color: '#9ca3af' }}>—</span>;
                                    const s5 = row.s5_stage_metrics;
                                    return (
                                        <div style={{ fontSize: '11px', minWidth: '120px' }}>
                                            <div style={{ marginBottom: '2px' }}>
                                                <span style={{ color: '#6b7280' }}>St1: </span>
                                                <strong style={{ color: '#0284c7' }}>{s5.st1_excl}</strong>
                                                <span style={{ color: '#6b7280' }}> ({s5.st1_rate}%)</span>
                                            </div>
                                            <div style={{ marginBottom: '2px' }}>
                                                <span style={{ color: '#6b7280' }}>St2: </span>
                                                <strong style={{ color: '#0284c7' }}>{s5.st2_papers}</strong>
                                            </div>
                                            <div>
                                                <span style={{ color: '#6b7280' }}>Saved: </span>
                                                <strong style={{ color: '#16a34a' }}>{s5.time_savings_pct}%</strong>
                                            </div>
                                        </div>
                                    );
                                }}
                                style={{ width: '140px' }}
                            />
                        </DataTable>
                    </div>
                )}
            </Dialog>
            {/* ================================================================== */}
            {/* ERROR ANALYSIS DIALOG                                              */}
            {/* ================================================================== */}
            <Dialog
                header={
                    <div className="flex align-items-center gap-2">
                        <i className="pi pi-chart-bar text-primary"></i>
                        <span>Detailed Error Analysis</span>
                    </div>
                }
                visible={errorAnalysisDialogVisible}
                onHide={() => {
                    setErrorAnalysisDialogVisible(false);
                    // Don't clear errorAnalysis - user may want to export it
                }}
                style={{ width: '85vw', maxWidth: '1400px' }}
                maximizable
                modal
            >
                {errorAnalysis && (
                    <div className="error-analysis-content">
                        {/* Metadata */}
                        <div className="surface-100 p-3 border-round mb-3">
                            <div className="flex flex-wrap gap-3">
                                <span><strong>Project:</strong> {errorAnalysis.metadata.project_id}</span>
                                <span><strong>Strategy:</strong> {errorAnalysis.metadata.strategy || 'All'}</span>
                                <span><strong>Model:</strong> {errorAnalysis.metadata.model || 'All'}</span>
                                <span><strong>Mode:</strong> {errorAnalysis.metadata.prompt_mode || 'All'}</span>
                                <span><strong>Papers Compared:</strong> {errorAnalysis.metadata.total_compared}</span>
                            </div>
                        </div>

                        {/* Insights */}
                        {errorAnalysis.insights?.length > 0 && (
                            <Message 
                                severity="info" 
                                className="mb-3 w-full"
                                content={
                                    <div>
                                        <strong>💡 Insights for Paper 1:</strong>
                                        <ul className="mt-2 mb-0 pl-4">
                                            {errorAnalysis.insights.map((insight, i) => (
                                                <li key={i} className="mb-1">{insight}</li>
                                            ))}
                                        </ul>
                                    </div>
                                }
                            />
                        )}

                        {/* Criteria Usage Overview */}
                        <Panel header="📊 Criteria Usage Patterns" className="mb-3" toggleable>
                            <div className="grid">
                                <div className="col-12 md:col-6">
                                    <h5 className="text-green-600">
                                        <i className="pi pi-check-circle mr-2"></i>
                                        INCLUDE Criteria (criteria_met)
                                    </h5>
                                    {Object.keys(errorAnalysis.criteria_usage.criteria_met || {}).length > 0 ? (
                                        Object.entries(errorAnalysis.criteria_usage.criteria_met).map(([crit, count]) => (
                                            <div key={crit} className="flex align-items-center gap-2 mb-2">
                                                <Tag value={crit} severity="success" style={{ minWidth: '50px' }} />
                                                <div className="flex-grow-1">
                                                    <ProgressBar 
                                                        value={Math.min(count, 100)} 
                                                        showValue={false}
                                                        style={{ height: '10px' }}
                                                        color="#22c55e"
                                                    />
                                                </div>
                                                <span className="text-sm font-bold" style={{ minWidth: '40px' }}>{count}</span>
                                            </div>
                                        ))
                                    ) : (
                                        <p className="text-500">No INCLUDE decisions recorded</p>
                                    )}
                                </div>
                                <div className="col-12 md:col-6">
                                    <h5 className="text-red-600">
                                        <i className="pi pi-times-circle mr-2"></i>
                                        EXCLUDE Criteria (criteria_violated)
                                    </h5>
                                    {Object.keys(errorAnalysis.criteria_usage.criteria_violated || {}).length > 0 ? (
                                        Object.entries(errorAnalysis.criteria_usage.criteria_violated).map(([crit, count]) => (
                                            <div key={crit} className="flex align-items-center gap-2 mb-2">
                                                <Tag value={crit} severity="danger" style={{ minWidth: '50px' }} />
                                                <div className="flex-grow-1">
                                                    <ProgressBar 
                                                        value={Math.min(count, 100)} 
                                                        showValue={false}
                                                        style={{ height: '10px' }}
                                                        color="#ef4444"
                                                    />
                                                </div>
                                                <span className="text-sm font-bold" style={{ minWidth: '40px' }}>{count}</span>
                                            </div>
                                        ))
                                    ) : (
                                        <p className="text-500">No EXCLUDE decisions recorded</p>
                                    )}
                                </div>
                            </div>
                        </Panel>

                        {/* False Positives Panel */}
                        <Panel 
                            header={
                                <span className="text-orange-600">
                                    <i className="pi pi-exclamation-circle mr-2"></i>
                                    False Positives ({errorAnalysis.false_positives.count}) - {errorAnalysis.false_positives.description}
                                </span>
                            }
                            className="mb-3"
                            toggleable
                            collapsed={errorAnalysis.false_positives.count === 0}
                        >
                            {errorAnalysis.false_positives.count > 0 ? (
                                <>
                                    <div className="mb-3 p-2 surface-100 border-round">
                                        <strong>Criteria causing False Positives:</strong>{' '}
                                        {Object.entries(errorAnalysis.false_positives.criteria_patterns)
                                            .map(([c, n]) => (
                                                <Tag key={c} value={`${c}: ${n}`} severity="warning" className="mr-2 mb-1" />
                                            ))
                                        }
                                    </div>
                                    <DataTable 
                                        value={errorAnalysis.false_positives.examples} 
                                        size="small"
                                        paginator
                                        rows={5}
                                        rowsPerPageOptions={[5, 10, 20]}
                                        emptyMessage="No false positives"
                                        className="p-datatable-sm"
                                    >
                                        <Column 
                                            field="corpus_id" 
                                            header="ID" 
                                            style={{ width: '100px' }}
                                            body={(row) => <code>{row.corpus_id}</code>}
                                        />
                                        <Column 
                                            field="title" 
                                            header="Title" 
                                            style={{ maxWidth: '300px' }}
                                            body={(row) => (
                                                <span title={row.title}>
                                                    {row.title?.length > 80 ? row.title.slice(0, 80) + '...' : row.title}
                                                </span>
                                            )}
                                        />
                                        <Column 
                                            field="criteria_met" 
                                            header="Criteria Met" 
                                            style={{ width: '150px' }}
                                            body={(row) => (
                                                <div className="flex flex-wrap gap-1">
                                                    {row.criteria_met?.map(c => 
                                                        <Tag key={c} value={c} severity="warning" className="text-xs" />
                                                    )}
                                                </div>
                                            )}
                                        />
                                        <Column 
                                            field="reasoning" 
                                            header="LLM Reasoning" 
                                            body={(row) => (
                                                <span className="text-sm text-600" title={row.reasoning}>
                                                    {row.reasoning?.length > 150 ? row.reasoning.slice(0, 150) + '...' : row.reasoning}
                                                </span>
                                            )}
                                        />
                                    </DataTable>
                                </>
                            ) : (
                                <p className="text-500">🎉 No false positives - excellent precision!</p>
                            )}
                        </Panel>

                        {/* False Negatives Panel */}
                        <Panel 
                            header={
                                <span className="text-red-600">
                                    <i className="pi pi-exclamation-triangle mr-2"></i>
                                    False Negatives ({errorAnalysis.false_negatives.count}) - {errorAnalysis.false_negatives.description}
                                </span>
                            }
                            className="mb-3"
                            toggleable
                            collapsed={errorAnalysis.false_negatives.count === 0}
                        >
                            {errorAnalysis.false_negatives.count > 0 ? (
                                <>
                                    <Message 
                                        severity="error" 
                                        text="CRITICAL: These are relevant papers that the LLM missed. High FN count reduces recall."
                                        className="mb-3 w-full"
                                    />
                                    <div className="mb-3 p-2 surface-100 border-round">
                                        <strong>Criteria causing False Negatives:</strong>{' '}
                                        {Object.entries(errorAnalysis.false_negatives.criteria_patterns)
                                            .map(([c, n]) => (
                                                <Tag key={c} value={`${c}: ${n}`} severity="danger" className="mr-2 mb-1" />
                                            ))
                                        }
                                    </div>
                                    <DataTable 
                                        value={errorAnalysis.false_negatives.examples} 
                                        size="small"
                                        paginator
                                        rows={5}
                                        rowsPerPageOptions={[5, 10, 20]}
                                        emptyMessage="No false negatives"
                                        className="p-datatable-sm"
                                    >
                                        <Column 
                                            field="corpus_id" 
                                            header="ID" 
                                            style={{ width: '100px' }}
                                            body={(row) => <code>{row.corpus_id}</code>}
                                        />
                                        <Column 
                                            field="title" 
                                            header="Title" 
                                            style={{ maxWidth: '300px' }}
                                            body={(row) => (
                                                <span title={row.title}>
                                                    {row.title?.length > 80 ? row.title.slice(0, 80) + '...' : row.title}
                                                </span>
                                            )}
                                        />
                                        <Column 
                                            field="criteria_violated" 
                                            header="Criteria Violated" 
                                            style={{ width: '150px' }}
                                            body={(row) => (
                                                <div className="flex flex-wrap gap-1">
                                                    {row.criteria_violated?.map(c => 
                                                        <Tag key={c} value={c} severity="danger" className="text-xs" />
                                                    )}
                                                </div>
                                            )}
                                        />
                                        <Column 
                                            field="reasoning" 
                                            header="LLM Reasoning" 
                                            body={(row) => (
                                                <span className="text-sm text-600" title={row.reasoning}>
                                                    {row.reasoning?.length > 150 ? row.reasoning.slice(0, 150) + '...' : row.reasoning}
                                                </span>
                                            )}
                                        />
                                    </DataTable>
                                </>
                            ) : (
                                <p className="text-500">🎉 No false negatives - excellent recall!</p>
                            )}
                        </Panel>

                        {/* Export Buttons */}
                        <Divider />
                        <div className="flex justify-content-end gap-2">
                            <Button 
                                label="Export JSON" 
                                icon="pi pi-download"
                                className="p-button-outlined p-button-secondary export-json-btn"
                                onClick={exportErrorAnalysisJSON}
                                tooltip="Download detailed data for further analysis"
                            />
                            <Button 
                                label="Export TXT Report" 
                                icon="pi pi-file"
                                className="p-button-outlined p-button-secondary export-txt-btn"
                                onClick={exportErrorAnalysisTXT}
                                tooltip="Download human-readable report for Paper 1"
                            />
                        </div>
                    </div>
                )}
                
                {!errorAnalysis && errorAnalysisLoading && (
                    <div className="flex justify-content-center p-5">
                        <i className="pi pi-spin pi-spinner text-4xl"></i>
                    </div>
                )}
            </Dialog>                     
        </div>
    );
};

export default LLMScreening;
