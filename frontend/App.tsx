import React, { useState, useEffect } from 'react';
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Code2,
  Cpu,
  FileCode,
  FolderGit2,
  Key,
  Layers,
  Play,
  RefreshCw,
  Search,
  Sparkles,
  Terminal,
  Wrench,
  XCircle,
  Zap,
} from 'lucide-react';
import {
  analyzeRepository,
  diagnoseFailure,
  executeTests,
  generateTests,
  getHealth,
  getPresets,
  runBenchmark,
  runRepair,
} from './api';
import {
  BenchmarkResult,
  ExecutionReport,
  FailureDiagnosis,
  GenerationReport,
  HealthStatus,
  Preset,
  RepairReport,
  RepositoryAnalysis,
  TestCaseResultItem,
} from './types';

export function App() {
  // Global & Environment State
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [selectedRepo, setSelectedRepo] = useState<string>('benchmarks/repositories/python_simple');
  const [apiKey, setApiKey] = useState<string>('');
  const [showKeyModal, setShowKeyModal] = useState<boolean>(false);
  const [activeTab, setActiveTab] = useState<'overview' | 'analysis' | 'execution' | 'ai_generation' | 'repair' | 'benchmark'>('overview');

  // Loading States
  const [loadingAction, setLoadingAction] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Results State
  const [analysis, setAnalysis] = useState<RepositoryAnalysis | null>(null);
  const [execution, setExecution] = useState<ExecutionReport | null>(null);
  const [generation, setGeneration] = useState<GenerationReport | null>(null);
  const [diagnosis, setDiagnosis] = useState<FailureDiagnosis | null>(null);
  const [repair, setRepair] = useState<RepairReport | null>(null);
  const [benchmark, setBenchmark] = useState<BenchmarkResult | null>(null);

  // UI Filters
  const [testFilter, setTestFilter] = useState<'all' | 'passed' | 'failed'>('all');
  const [symbolSearch, setSymbolSearch] = useState<string>('');
  const [selectedTargetFile, setSelectedTargetFile] = useState<string>('');

  // Initial Load
  useEffect(() => {
    checkHealth();
    loadPresets();
  }, []);

  const checkHealth = async () => {
    try {
      const data = await getHealth();
      setHealth(data);
    } catch (err: any) {
      console.warn('Health check note:', err.message);
    }
  };

  const loadPresets = async () => {
    try {
      const data = await getPresets();
      setPresets(data.presets);
      if (data.presets.length > 0) {
        setSelectedRepo(data.presets[0].path);
      }
    } catch (err: any) {
      console.warn('Presets note:', err.message);
    }
  };

  // Actions
  const handleAnalyze = async () => {
    setLoadingAction('Analyzing repository structure and symbols...');
    setErrorMessage(null);
    try {
      const res = await analyzeRepository(selectedRepo);
      setAnalysis(res.analysis);
      if (res.analysis.source_files.length > 0 && !selectedTargetFile) {
        setSelectedTargetFile(res.analysis.source_files[0]);
      }
      setActiveTab('analysis');
    } catch (err: any) {
      setErrorMessage(err.message || 'Analysis failed');
    } finally {
      setLoadingAction(null);
    }
  };

  const handleRunTests = async () => {
    setLoadingAction('Executing test suite via TestPilot runner...');
    setErrorMessage(null);
    try {
      const res = await executeTests(selectedRepo);
      setExecution(res.execution);
      setActiveTab('execution');
    } catch (err: any) {
      setErrorMessage(err.message || 'Test execution failed');
    } finally {
      setLoadingAction(null);
    }
  };

  const handleGenerateTests = async () => {
    setLoadingAction('Generating AST-validated pytest tests with TestPilot Generator...');
    setErrorMessage(null);
    try {
      const res = await generateTests(selectedRepo, selectedTargetFile || undefined, apiKey || undefined);
      setGeneration(res.generation);
      setActiveTab('ai_generation');
    } catch (err: any) {
      setErrorMessage(err.message || 'Test generation failed');
    } finally {
      setLoadingAction(null);
    }
  };

  const handleDiagnoseTest = async (testItem: TestCaseResultItem) => {
    setLoadingAction(`Diagnosing failure for ${testItem.name}...`);
    try {
      const res = await diagnoseFailure(
        testItem.failure_type || 'AssertionError',
        testItem.failure_message || '',
        testItem.traceback || ''
      );
      setDiagnosis(res);
      setActiveTab('repair');
    } catch (err: any) {
      setErrorMessage(err.message || 'Diagnosis failed');
    } finally {
      setLoadingAction(null);
    }
  };

  const handleRunRepair = async () => {
    setLoadingAction('Executing automated iterative repair loop...');
    setErrorMessage(null);
    try {
      const res = await runRepair(selectedRepo, undefined, 2, apiKey || undefined);
      setRepair(res.repair);
      setActiveTab('repair');
    } catch (err: any) {
      setErrorMessage(err.message || 'Repair loop failed');
    } finally {
      setLoadingAction(null);
    }
  };

  const handleRunBenchmark = async () => {
    setLoadingAction('Running end-to-end benchmark in isolated workspace...');
    setErrorMessage(null);
    try {
      const res = await runBenchmark(selectedRepo, selectedTargetFile || undefined, apiKey || undefined);
      setBenchmark(res.benchmark);
      setActiveTab('benchmark');
    } catch (err: any) {
      setErrorMessage(err.message || 'Benchmark run failed');
    } finally {
      setLoadingAction(null);
    }
  };

  // Filtered lists
  const filteredTests = execution?.tests.filter((t) => {
    if (testFilter === 'passed') return t.status === 'passed';
    if (testFilter === 'failed') return t.status === 'failed' || t.status === 'error';
    return true;
  }) || [];

  const filteredSymbols = analysis?.symbols.filter((s) => {
    if (!symbolSearch) return true;
    const q = symbolSearch.toLowerCase();
    return s.name.toLowerCase().includes(q) || s.qualified_name.toLowerCase().includes(q) || s.file.toLowerCase().includes(q);
  }) || [];

  return (
    <div className="min-h-screen flex flex-col">
      {/* Top Navigation Bar */}
      <header style={{ borderBottom: '1px solid var(--border-subtle)', background: 'rgba(15, 23, 42, 0.8)', backdropFilter: 'blur(12px)', position: 'sticky', top: 0, zIndex: 40 }}>
        <div className="container" style={{ padding: '16px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '20px' }}>
          {/* Logo & Branding */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
            <div style={{ width: '40px', height: '40px', borderRadius: '10px', background: 'linear-gradient(135deg, #0284c7, #38bdf8)', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: 'var(--shadow-glow-cyan)' }}>
              <Zap size={22} color="#080d1a" strokeWidth={2.5} />
            </div>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ fontSize: '20px', fontWeight: 800, letterSpacing: '-0.03em', color: '#f8fafc' }}>TestPilot</span>
                <span className="badge badge-cyan" style={{ fontSize: '10px', padding: '2px 8px' }}>AI Platform</span>
              </div>
              <p style={{ fontSize: '11px', color: 'var(--text-dim)', fontWeight: 500 }}>Agentic Software Testing & Validation</p>
            </div>
          </div>

          {/* System Status Indicators & API Key Button */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '6px 12px', background: 'var(--bg-card-subtle)', border: '1px solid var(--border-subtle)', borderRadius: '8px', fontSize: '12px' }}>
              <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: health?.status === 'online' ? '#10b981' : '#f59e0b', boxShadow: health?.status === 'online' ? '0 0 8px #10b981' : 'none' }}></div>
              <span style={{ color: 'var(--text-muted)' }}>Python:</span>
              <span style={{ fontWeight: 600, color: '#f8fafc' }}>{health?.python_version || '3.11'}</span>
            </div>

            <button
              onClick={() => setShowKeyModal(true)}
              className="btn btn-secondary"
              style={{ fontSize: '12px', padding: '6px 12px' }}
              title="Configure Optional OpenAI API Key"
            >
              <Key size={14} color={apiKey ? '#34d399' : 'var(--text-muted)'} />
              <span>{apiKey ? 'API Key Configured' : 'LLM Settings'}</span>
            </button>
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="container">
        {/* Repository Input & Actions Bar */}
        <section className="card" style={{ marginBottom: '24px', background: 'linear-gradient(180deg, #10192e 0%, #0d1424 100%)', border: '1px solid rgba(56, 189, 248, 0.2)' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
              <div>
                <h2 style={{ fontSize: '16px', fontWeight: 700, color: '#f8fafc', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <FolderGit2 size={18} color="#38bdf8" />
                  Target Repository
                </h2>
                <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px' }}>
                  Select a bundled benchmark or input a local repository path
                </p>
              </div>

              {/* Preset Chips */}
              <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                {presets.map((p) => (
                  <button
                    key={p.id}
                    onClick={() => setSelectedRepo(p.path)}
                    style={{
                      background: selectedRepo === p.path ? 'rgba(56, 189, 248, 0.15)' : 'var(--bg-card-subtle)',
                      border: `1px solid ${selectedRepo === p.path ? '#38bdf8' : 'var(--border-subtle)'}`,
                      color: selectedRepo === p.path ? '#38bdf8' : 'var(--text-muted)',
                      padding: '6px 12px',
                      borderRadius: '8px',
                      fontSize: '12px',
                      fontWeight: 600,
                      cursor: 'pointer',
                      transition: 'all 0.15s ease',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px',
                    }}
                  >
                    <span>{p.name.split('(')[0].trim()}</span>
                    {p.recommended && <span style={{ fontSize: '9px', background: '#0284c7', color: '#fff', padding: '1px 5px', borderRadius: '4px' }}>DEMO</span>}
                  </button>
                ))}
              </div>
            </div>

            {/* Path Input Box & Action Buttons */}
            <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
              <div style={{ flex: '1 1 340px', position: 'relative' }}>
                <input
                  type="text"
                  value={selectedRepo}
                  onChange={(e) => setSelectedRepo(e.target.value)}
                  placeholder="Enter local repository path or select a preset..."
                  style={{
                    width: '100%',
                    background: 'var(--bg-input)',
                    border: '1px solid var(--border-strong)',
                    borderRadius: 'var(--radius-md)',
                    padding: '12px 16px',
                    color: '#f8fafc',
                    fontSize: '14px',
                    fontFamily: 'JetBrains Mono, monospace',
                    outline: 'none',
                    boxShadow: 'inset 0 2px 4px rgba(0,0,0,0.3)',
                  }}
                />
              </div>

              <button
                onClick={handleAnalyze}
                disabled={!!loadingAction}
                className="btn btn-primary"
                style={{ padding: '10px 20px' }}
              >
                <Search size={16} />
                <span>Analyze Repository</span>
              </button>

              <button
                onClick={handleRunTests}
                disabled={!!loadingAction}
                className="btn btn-emerald"
                style={{ padding: '10px 20px' }}
              >
                <Play size={16} fill="white" />
                <span>Run Tests</span>
              </button>

              <button
                onClick={handleRunBenchmark}
                disabled={!!loadingAction}
                className="btn btn-purple"
                style={{ padding: '10px 20px' }}
              >
                <Sparkles size={16} />
                <span>AI Pipeline Benchmark</span>
              </button>
            </div>
          </div>
        </section>

        {/* Global Loading Spinner / Progress Notice */}
        {loadingAction && (
          <div className="card" style={{ marginBottom: '24px', background: 'rgba(2, 132, 199, 0.1)', border: '1px solid rgba(56, 189, 248, 0.3)', display: 'flex', alignItems: 'center', gap: '16px', padding: '18px 24px' }}>
            <RefreshCw size={22} className="animate-spin" color="#38bdf8" />
            <div>
              <p style={{ fontWeight: 600, color: '#38bdf8', fontSize: '14px' }}>Executing Real TestPilot Agent</p>
              <p style={{ fontSize: '13px', color: 'var(--text-muted)' }}>{loadingAction}</p>
            </div>
          </div>
        )}

        {/* Global Error Banner */}
        {errorMessage && (
          <div className="card" style={{ marginBottom: '24px', background: 'rgba(244, 63, 94, 0.1)', border: '1px solid rgba(244, 63, 94, 0.3)', display: 'flex', alignItems: 'flex-start', gap: '14px', padding: '18px 24px' }}>
            <AlertCircle size={22} color="#fb7185" style={{ flexShrink: 0, marginTop: '2px' }} />
            <div style={{ flex: 1 }}>
              <p style={{ fontWeight: 700, color: '#fb7185', fontSize: '14px' }}>Operation Notice</p>
              <p style={{ fontSize: '13px', color: '#f8fafc', marginTop: '2px', wordBreak: 'break-word' }}>{errorMessage}</p>
            </div>
            <button onClick={() => setErrorMessage(null)} style={{ background: 'none', border: 'none', color: '#fb7185', cursor: 'pointer', fontWeight: 700 }}>✕</button>
          </div>
        )}

        {/* Navigation Tabs */}
        <div className="tabs-nav">
          <button
            onClick={() => setActiveTab('overview')}
            className={`tab-btn ${activeTab === 'overview' ? 'active' : ''}`}
          >
            <Activity size={16} />
            <span>Dashboard Overview</span>
          </button>

          <button
            onClick={() => setActiveTab('analysis')}
            className={`tab-btn ${activeTab === 'analysis' ? 'active' : ''}`}
          >
            <FileCode size={16} />
            <span>1. Repository Analysis {analysis && `(${analysis.source_file_count} files)`}</span>
          </button>

          <button
            onClick={() => setActiveTab('execution')}
            className={`tab-btn ${activeTab === 'execution' ? 'active' : ''}`}
          >
            <CheckCircle2 size={16} />
            <span>2. Test Execution {execution && `(${execution.summary.passed}/${execution.summary.total} passed)`}</span>
          </button>

          <button
            onClick={() => setActiveTab('ai_generation')}
            className={`tab-btn ${activeTab === 'ai_generation' ? 'active' : ''}`}
          >
            <Sparkles size={16} />
            <span>3. AI Test Generator</span>
          </button>

          <button
            onClick={() => setActiveTab('repair')}
            className={`tab-btn ${activeTab === 'repair' ? 'active' : ''}`}
          >
            <Wrench size={16} />
            <span>4. Failure Diagnosis & Repair</span>
          </button>

          <button
            onClick={() => setActiveTab('benchmark')}
            className={`tab-btn ${activeTab === 'benchmark' ? 'active' : ''}`}
          >
            <Layers size={16} />
            <span>5. End-to-End Pipeline</span>
          </button>
        </div>

        {/* TAB 1: OVERVIEW */}
        {activeTab === 'overview' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            {/* Quick Hero / Flow Walkthrough */}
            <div className="card" style={{ background: 'linear-gradient(135deg, #0d1527 0%, #111e38 100%)', border: '1px solid #1e293b' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px' }}>
                <div>
                  <span className="badge badge-purple" style={{ marginBottom: '8px' }}>TestPilot Agentic Architecture</span>
                  <h3 style={{ fontSize: '20px', fontWeight: 800, color: '#f8fafc', letterSpacing: '-0.02em' }}>
                    Automated Test Generation, Execution & Iterative Repair
                  </h3>
                  <p style={{ color: 'var(--text-muted)', fontSize: '14px', maxWidth: '680px', marginTop: '6px', lineHeight: '1.6' }}>
                    TestPilot inspects Python repositories using AST parsing, runs pytest test suites with bounded output capture, analyzes coverage gaps, and deploys iterative AI agents to repair broken assertions safely.
                  </p>
                </div>
                <div style={{ display: 'flex', gap: '12px' }}>
                  <button onClick={handleAnalyze} className="btn btn-primary">
                    <Search size={16} />
                    <span>Start Analysis</span>
                  </button>
                  <button onClick={handleRunTests} className="btn btn-emerald">
                    <Play size={16} fill="white" />
                    <span>Run Test Suite</span>
                  </button>
                </div>
              </div>

              {/* Workflow Pipeline Graphic */}
              <div style={{ marginTop: '24px', paddingTop: '20px', borderTop: '1px solid var(--border-subtle)', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '12px' }}>
                {[
                  { step: '01', title: 'Repository Discovery', desc: 'AST parsing & symbols', icon: FileCode, done: !!analysis },
                  { step: '02', title: 'Test Execution', desc: 'Pytest + Coverage.py', icon: Play, done: !!execution },
                  { step: '03', title: 'AI Generation', desc: 'Context-aware test synthesis', icon: Sparkles, done: !!generation },
                  { step: '04', title: 'Failure Diagnosis', desc: 'Safety-gate AST triage', icon: AlertTriangle, done: !!diagnosis },
                  { step: '05', title: 'Bounded Repair', desc: 'Targeted diff validation', icon: Wrench, done: !!repair },
                ].map((item, idx) => {
                  const Icon = item.icon;
                  return (
                    <div
                      key={idx}
                      style={{
                        background: item.done ? 'rgba(56, 189, 248, 0.08)' : 'rgba(15, 23, 42, 0.6)',
                        border: `1px solid ${item.done ? 'rgba(56, 189, 248, 0.3)' : 'var(--border-subtle)'}`,
                        borderRadius: 'var(--radius-md)',
                        padding: '14px',
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                        <span style={{ fontSize: '11px', fontWeight: 700, color: item.done ? '#38bdf8' : 'var(--text-dim)' }}>STEP {item.step}</span>
                        <Icon size={16} color={item.done ? '#38bdf8' : 'var(--text-dim)'} />
                      </div>
                      <h4 style={{ fontSize: '13px', fontWeight: 700, color: '#f8fafc' }}>{item.title}</h4>
                      <p style={{ fontSize: '11px', color: 'var(--text-dim)', marginTop: '2px' }}>{item.desc}</p>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Quick KPI Overview (if data available) */}
            <div className="card">
              <h3 style={{ fontSize: '15px', fontWeight: 700, color: '#f8fafc', marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Activity size={18} color="#38bdf8" />
                Live Session Telemetry
              </h3>

              <div className="kpi-grid">
                <div className="kpi-card">
                  <span className="kpi-title">Repository</span>
                  <span className="kpi-value" style={{ fontSize: '16px', wordBreak: 'break-all' }}>
                    {selectedRepo.split('/').pop() || selectedRepo}
                  </span>
                  <span className="kpi-sub">{selectedRepo}</span>
                </div>

                <div className="kpi-card">
                  <span className="kpi-title">Source Files</span>
                  <span className="kpi-value">{analysis?.source_file_count ?? '—'}</span>
                  <span className="kpi-sub">{analysis ? `${analysis.symbol_count} AST symbols` : 'Run analysis'}</span>
                </div>

                <div className="kpi-card">
                  <span className="kpi-title">Test Results</span>
                  <span className="kpi-value" style={{ color: execution?.summary.failed ? '#fb7185' : execution ? '#34d399' : '#f8fafc' }}>
                    {execution ? `${execution.summary.passed} / ${execution.summary.total}` : '—'}
                  </span>
                  <span className="kpi-sub">{execution ? `${execution.duration_seconds.toFixed(2)}s runtime` : 'Run tests'}</span>
                </div>

                <div className="kpi-card">
                  <span className="kpi-title">Measured Coverage</span>
                  <span className="kpi-value" style={{ color: '#38bdf8' }}>
                    {execution?.coverage?.coverage_pct ? `${execution.coverage.coverage_pct}%` : analysis?.coverage_summary?.line_coverage_pct ? `${analysis.coverage_summary.line_coverage_pct}%` : '—'}
                  </span>
                  <span className="kpi-sub">Pytest-cov integration</span>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* TAB 2: REPOSITORY ANALYSIS */}
        {activeTab === 'analysis' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            {!analysis ? (
              <div className="card" style={{ textAlign: 'center', padding: '60px 20px' }}>
                <FileCode size={48} color="#38bdf8" style={{ margin: '0 auto 16px', opacity: 0.8 }} />
                <h3 style={{ fontSize: '18px', fontWeight: 700 }}>No Repository Analysis Data Yet</h3>
                <p style={{ color: 'var(--text-muted)', fontSize: '14px', maxWidth: '440px', margin: '8px auto 20px' }}>
                  Run the TestPilot Repository Analyzer to extract AST symbols, detect test frameworks, and calculate coverage.
                </p>
                <button onClick={handleAnalyze} className="btn btn-primary">
                  <Search size={16} />
                  <span>Analyze Repository Now</span>
                </button>
              </div>
            ) : (
              <>
                {/* Analysis KPI Summary */}
                <div className="card">
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px', marginBottom: '16px' }}>
                    <div>
                      <span className="badge badge-cyan">AST Structural Analysis</span>
                      <h3 style={{ fontSize: '18px', fontWeight: 700, marginTop: '4px' }}>{analysis.repository_path.split(/[\\/]/).pop()}</h3>
                    </div>
                    <span style={{ fontSize: '12px', color: 'var(--text-dim)' }}>
                      Completed in <strong style={{ color: '#38bdf8' }}>{analysis.duration_seconds.toFixed(2)}s</strong>
                    </span>
                  </div>

                  <div className="kpi-grid">
                    <div className="kpi-card">
                      <span className="kpi-title">Language</span>
                      <span className="kpi-value">{analysis.language}</span>
                      <span className="kpi-sub">Python {analysis.python_version || '3.11'}</span>
                    </div>

                    <div className="kpi-card">
                      <span className="kpi-title">Test Framework</span>
                      <span className="kpi-value">{analysis.test_framework || 'pytest'}</span>
                      <span className="kpi-sub">from {analysis.test_framework_config_source || 'detected'}</span>
                    </div>

                    <div className="kpi-card">
                      <span className="kpi-title">Source Files</span>
                      <span className="kpi-value">{analysis.source_file_count}</span>
                      <span className="kpi-sub">{analysis.all_python_files.length} total Python files</span>
                    </div>

                    <div className="kpi-card">
                      <span className="kpi-title">Test Files</span>
                      <span className="kpi-value">{analysis.test_file_count}</span>
                      <span className="kpi-sub">{analysis.has_tests ? 'Tests found' : 'No tests'}</span>
                    </div>

                    <div className="kpi-card">
                      <span className="kpi-title">Extracted Symbols</span>
                      <span className="kpi-value">{analysis.symbol_count}</span>
                      <span className="kpi-sub">{analysis.public_symbol_count} public APIs</span>
                    </div>

                    <div className="kpi-card">
                      <span className="kpi-title">Parse Errors</span>
                      <span className="kpi-value" style={{ color: analysis.parse_errors.length > 0 ? '#fb7185' : '#34d399' }}>
                        {analysis.parse_errors.length}
                      </span>
                      <span className="kpi-sub">AST syntax validity</span>
                    </div>

                    <div className="kpi-card">
                      <span className="kpi-title">Line Coverage</span>
                      <span className="kpi-value" style={{ color: '#38bdf8' }}>
                        {analysis.coverage_summary.line_coverage_pct !== null && analysis.coverage_summary.line_coverage_pct !== undefined
                          ? `${analysis.coverage_summary.line_coverage_pct.toFixed(1)}%`
                          : analysis.coverage_summary.status}
                      </span>
                      <span className="kpi-sub">Baseline measurement</span>
                    </div>

                    <div className="kpi-card">
                      <span className="kpi-title">Duration</span>
                      <span className="kpi-value">{analysis.duration_seconds.toFixed(2)}s</span>
                      <span className="kpi-sub">AST engine wall-clock</span>
                    </div>
                  </div>
                </div>

                {/* Symbols Inventory Table */}
                <div className="card">
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', flexWrap: 'wrap', gap: '12px' }}>
                    <h4 style={{ fontSize: '15px', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <Code2 size={18} color="#38bdf8" />
                      Extracted Python AST Symbols ({filteredSymbols.length})
                    </h4>
                    <input
                      type="text"
                      placeholder="Filter symbols or files..."
                      value={symbolSearch}
                      onChange={(e) => setSymbolSearch(e.target.value)}
                      style={{
                        background: 'var(--bg-input)',
                        border: '1px solid var(--border-subtle)',
                        borderRadius: '6px',
                        padding: '6px 12px',
                        color: '#f8fafc',
                        fontSize: '12px',
                        minWidth: '220px',
                      }}
                    />
                  </div>

                  <div style={{ maxHeight: '380px', overflowY: 'auto', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)' }}>
                    <table className="custom-table font-mono">
                      <thead>
                        <tr>
                          <th>Symbol Name</th>
                          <th>Kind</th>
                          <th>Scope</th>
                          <th>Source File</th>
                          <th>Line</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredSymbols.length === 0 ? (
                          <tr>
                            <td colSpan={5} style={{ textAlign: 'center', padding: '24px', color: 'var(--text-dim)' }}>
                              No symbols match the current search.
                            </td>
                          </tr>
                        ) : (
                          filteredSymbols.map((s, idx) => (
                            <tr key={idx}>
                              <td style={{ fontWeight: 600, color: '#38bdf8' }}>{s.qualified_name}</td>
                              <td>
                                <span className={`badge ${s.kind === 'class' ? 'badge-purple' : 'badge-neutral'}`} style={{ fontSize: '10px' }}>
                                  {s.kind}
                                </span>
                              </td>
                              <td>{s.is_private ? 'Private' : s.is_dunder ? 'Dunder' : 'Public'}</td>
                              <td style={{ color: 'var(--text-muted)' }}>{s.file}</td>
                              <td>{s.line}</td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* File Inventory Accordion */}
                <div className="card">
                  <h4 style={{ fontSize: '15px', fontWeight: 700, marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <Layers size={18} color="#38bdf8" />
                    Source & Test Inventory
                  </h4>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '16px' }}>
                    <div>
                      <span className="badge badge-cyan" style={{ marginBottom: '8px' }}>Source Files ({analysis.source_files.length})</span>
                      <ul style={{ listStyle: 'none', background: 'var(--bg-card-subtle)', border: '1px solid var(--border-subtle)', borderRadius: '8px', padding: '12px', maxHeight: '200px', overflowY: 'auto' }}>
                        {analysis.source_files.map((f, i) => (
                          <li key={i} style={{ padding: '6px 0', borderBottom: '1px solid rgba(255,255,255,0.05)', fontSize: '13px', fontFamily: 'JetBrains Mono', color: '#e2e8f0' }}>
                            {f}
                          </li>
                        ))}
                      </ul>
                    </div>

                    <div>
                      <span className="badge badge-emerald" style={{ marginBottom: '8px' }}>Test Files ({analysis.test_files.length})</span>
                      <ul style={{ listStyle: 'none', background: 'var(--bg-card-subtle)', border: '1px solid var(--border-subtle)', borderRadius: '8px', padding: '12px', maxHeight: '200px', overflowY: 'auto' }}>
                        {analysis.test_files.map((f, i) => (
                          <li key={i} style={{ padding: '6px 0', borderBottom: '1px solid rgba(255,255,255,0.05)', fontSize: '13px', fontFamily: 'JetBrains Mono', color: '#e2e8f0' }}>
                            {f}
                          </li>
                        ))}
                      </ul>
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        {/* TAB 3: TEST EXECUTION */}
        {activeTab === 'execution' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            {!execution ? (
              <div className="card" style={{ textAlign: 'center', padding: '60px 20px' }}>
                <CheckCircle2 size={48} color="#34d399" style={{ margin: '0 auto 16px', opacity: 0.8 }} />
                <h3 style={{ fontSize: '18px', fontWeight: 700 }}>No Test Execution Results Yet</h3>
                <p style={{ color: 'var(--text-muted)', fontSize: '14px', maxWidth: '440px', margin: '8px auto 20px' }}>
                  Execute the test suite using TestPilot's real pytest runner to capture pass/fail telemetry and coverage.
                </p>
                <button onClick={handleRunTests} className="btn btn-emerald">
                  <Play size={16} fill="white" />
                  <span>Execute Tests Now</span>
                </button>
              </div>
            ) : (
              <>
                {/* Execution Banner */}
                <div
                  className="card"
                  style={{
                    background: execution.has_failures
                      ? 'linear-gradient(135deg, rgba(244, 63, 94, 0.15) 0%, rgba(15, 23, 42, 1) 100%)'
                      : 'linear-gradient(135deg, rgba(16, 185, 129, 0.15) 0%, rgba(15, 23, 42, 1) 100%)',
                    border: `1px solid ${execution.has_failures ? 'rgba(244, 63, 94, 0.4)' : 'rgba(16, 185, 129, 0.4)'}`,
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
                      {execution.has_failures ? (
                        <div style={{ width: '48px', height: '48px', borderRadius: '12px', background: 'rgba(244, 63, 94, 0.2)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                          <XCircle size={28} color="#fb7185" />
                        </div>
                      ) : (
                        <div style={{ width: '48px', height: '48px', borderRadius: '12px', background: 'rgba(16, 185, 129, 0.2)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                          <CheckCircle2 size={28} color="#34d399" />
                        </div>
                      )}
                      <div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <span className={`badge ${execution.has_failures ? 'badge-rose' : 'badge-emerald'}`}>
                            {execution.status.toUpperCase()}
                          </span>
                          <span style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
                            in <strong style={{ color: '#f8fafc' }}>{execution.duration_seconds.toFixed(2)}s</strong>
                          </span>
                        </div>
                        <h3 style={{ fontSize: '20px', fontWeight: 800, marginTop: '4px' }}>
                          {execution.has_failures ? `${execution.summary.failed} Failing Tests Detected` : `All ${execution.summary.passed} Tests Passed Successfully`}
                        </h3>
                      </div>
                    </div>

                    <button onClick={handleRunTests} className="btn btn-secondary">
                      <RefreshCw size={14} />
                      <span>Re-run Tests</span>
                    </button>
                  </div>

                  {/* Execution Metrics Grid */}
                  <div className="kpi-grid">
                    <div className="kpi-card">
                      <span className="kpi-title">Total Tests</span>
                      <span className="kpi-value">{execution.summary.total}</span>
                      <span className="kpi-sub">Discovered & executed</span>
                    </div>

                    <div className="kpi-card">
                      <span className="kpi-title">Passed</span>
                      <span className="kpi-value" style={{ color: '#34d399' }}>{execution.summary.passed}</span>
                      <span className="kpi-sub">Assertions verified</span>
                    </div>

                    <div className="kpi-card">
                      <span className="kpi-title">Failed</span>
                      <span className="kpi-value" style={{ color: execution.summary.failed ? '#fb7185' : 'var(--text-main)' }}>
                        {execution.summary.failed}
                      </span>
                      <span className="kpi-sub">{execution.summary.errors} pytest errors</span>
                    </div>

                    <div className="kpi-card">
                      <span className="kpi-title">Skipped</span>
                      <span className="kpi-value">{execution.summary.skipped}</span>
                      <span className="kpi-sub">{execution.summary.xfailed} expected fails</span>
                    </div>

                    <div className="kpi-card">
                      <span className="kpi-title">Coverage</span>
                      <span className="kpi-value" style={{ color: '#38bdf8' }}>
                        {execution.coverage.coverage_pct !== null && execution.coverage.coverage_pct !== undefined
                          ? `${execution.coverage.coverage_pct}%`
                          : 'Unavailable'}
                      </span>
                      <span className="kpi-sub">{execution.coverage.status}</span>
                    </div>
                  </div>
                </div>

                {/* Individual Test Cases Table */}
                <div className="card">
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', flexWrap: 'wrap', gap: '12px' }}>
                    <h4 style={{ fontSize: '15px', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <Terminal size={18} color="#38bdf8" />
                      Individual Test Cases ({filteredTests.length})
                    </h4>

                    {/* Filter buttons */}
                    <div style={{ display: 'flex', gap: '6px' }}>
                      <button
                        onClick={() => setTestFilter('all')}
                        className="btn btn-secondary"
                        style={{ fontSize: '11px', padding: '4px 10px', background: testFilter === 'all' ? 'rgba(56, 189, 248, 0.15)' : undefined }}
                      >
                        All ({execution.tests.length})
                      </button>
                      <button
                        onClick={() => setTestFilter('passed')}
                        className="btn btn-secondary"
                        style={{ fontSize: '11px', padding: '4px 10px', background: testFilter === 'passed' ? 'rgba(16, 185, 129, 0.15)' : undefined }}
                      >
                        Passed ({execution.summary.passed})
                      </button>
                      <button
                        onClick={() => setTestFilter('failed')}
                        className="btn btn-secondary"
                        style={{ fontSize: '11px', padding: '4px 10px', background: testFilter === 'failed' ? 'rgba(244, 63, 94, 0.15)' : undefined }}
                      >
                        Failed ({execution.summary.failed})
                      </button>
                    </div>
                  </div>

                  <div style={{ maxHeight: '450px', overflowY: 'auto', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)' }}>
                    <table className="custom-table font-mono">
                      <thead>
                        <tr>
                          <th>Status</th>
                          <th>Test Node ID</th>
                          <th>Duration</th>
                          <th>Action / Details</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredTests.length === 0 ? (
                          <tr>
                            <td colSpan={4} style={{ textAlign: 'center', padding: '24px', color: 'var(--text-dim)' }}>
                              No test cases match filter.
                            </td>
                          </tr>
                        ) : (
                          filteredTests.map((t, idx) => (
                            <React.Fragment key={idx}>
                              <tr>
                                <td>
                                  <span className={`badge ${t.status === 'passed' ? 'badge-emerald' : t.status === 'failed' ? 'badge-rose' : 'badge-amber'}`} style={{ fontSize: '10px' }}>
                                    {t.status}
                                  </span>
                                </td>
                                <td style={{ color: '#f8fafc', fontWeight: 600 }}>{t.nodeid}</td>
                                <td>{t.duration_seconds !== null && t.duration_seconds !== undefined ? `${t.duration_seconds.toFixed(3)}s` : '—'}</td>
                                <td>
                                  {t.status === 'failed' || t.status === 'error' ? (
                                    <button
                                      onClick={() => handleDiagnoseTest(t)}
                                      className="btn btn-purple"
                                      style={{ fontSize: '11px', padding: '4px 8px' }}
                                    >
                                      <Wrench size={12} />
                                      <span>Diagnose Failure</span>
                                    </button>
                                  ) : (
                                    <span style={{ color: 'var(--text-dim)', fontSize: '11px' }}>OK</span>
                                  )}
                                </td>
                              </tr>
                              {/* Inline error display for failing tests */}
                              {(t.status === 'failed' || t.status === 'error') && t.failure_message && (
                                <tr>
                                  <td colSpan={4} style={{ background: 'rgba(244, 63, 94, 0.05)', padding: '10px 16px', borderBottom: '1px solid rgba(244, 63, 94, 0.2)' }}>
                                    <div style={{ color: '#fb7185', fontSize: '12px', fontWeight: 600 }}>
                                      {t.failure_type ? `${t.failure_type}: ` : ''}{t.failure_message}
                                    </div>
                                    {t.traceback && (
                                      <pre style={{ marginTop: '6px', fontSize: '11px', color: '#94a3b8', maxHeight: '120px', overflowY: 'auto' }}>
                                        {t.traceback}
                                      </pre>
                                    )}
                                  </td>
                                </tr>
                              )}
                            </React.Fragment>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        {/* TAB 4: AI TEST GENERATOR */}
        {activeTab === 'ai_generation' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            <div className="card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px', marginBottom: '18px' }}>
                <div>
                  <span className="badge badge-purple">TestPilot AI Generator</span>
                  <h3 style={{ fontSize: '18px', fontWeight: 700, marginTop: '4px' }}>AST-Verified Pytest Test Generation</h3>
                  <p style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
                    Analyzes Python modules, extracts priority AST symbols, prompts the LLM client, and validates Python syntax via AST parser before reporting.
                  </p>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Target File:</span>
                    <input
                      type="text"
                      placeholder="e.g. src/calculator/converter.py"
                      value={selectedTargetFile}
                      onChange={(e) => setSelectedTargetFile(e.target.value)}
                      style={{
                        background: 'var(--bg-input)',
                        border: '1px solid var(--border-subtle)',
                        borderRadius: '6px',
                        padding: '6px 12px',
                        color: '#f8fafc',
                        fontSize: '12px',
                        fontFamily: 'JetBrains Mono',
                        width: '260px',
                      }}
                    />
                  </div>

                  <button onClick={handleGenerateTests} disabled={!!loadingAction} className="btn btn-purple">
                    <Sparkles size={16} />
                    <span>Generate Tests</span>
                  </button>
                </div>
              </div>

              {!generation ? (
                <div style={{ textAlign: 'center', padding: '40px 20px', background: 'var(--bg-card-subtle)', borderRadius: 'var(--radius-md)' }}>
                  <Sparkles size={40} color="#a78bfa" style={{ margin: '0 auto 12px', opacity: 0.7 }} />
                  <p style={{ fontSize: '14px', color: 'var(--text-muted)' }}>
                    Click "Generate Tests" to produce syntactically valid pytest tests for the selected module.
                  </p>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                  {/* Generation Meta KPIs */}
                  <div className="kpi-grid">
                    <div className="kpi-card">
                      <span className="kpi-title">Status</span>
                      <span className="kpi-value" style={{ color: generation.has_valid_tests ? '#34d399' : '#fb7185' }}>
                        {generation.status}
                      </span>
                      <span className="kpi-sub">AST verification</span>
                    </div>

                    <div className="kpi-card">
                      <span className="kpi-title">Tests Generated</span>
                      <span className="kpi-value">{generation.total_tests_generated}</span>
                      <span className="kpi-sub">Discovered test functions</span>
                    </div>

                    <div className="kpi-card">
                      <span className="kpi-title">Model Used</span>
                      <span className="kpi-value" style={{ fontSize: '16px' }}>{generation.model}</span>
                      <span className="kpi-sub">LLM provider engine</span>
                    </div>

                    <div className="kpi-card">
                      <span className="kpi-title">Duration</span>
                      <span className="kpi-value">{generation.duration_seconds.toFixed(2)}s</span>
                      <span className="kpi-sub">Inference + AST parse</span>
                    </div>
                  </div>

                  {/* Generated Code Display */}
                  {generation.generated_files.map((gf, i) => (
                    <div key={i} style={{ marginTop: '8px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                        <span style={{ fontSize: '13px', fontWeight: 600, color: '#f8fafc', fontFamily: 'JetBrains Mono' }}>
                          Output Target: {gf.file_path}
                        </span>
                        <span className={`badge ${gf.is_valid ? 'badge-emerald' : 'badge-rose'}`} style={{ fontSize: '10px' }}>
                          {gf.is_valid ? 'Valid AST Syntax' : `AST Error: ${gf.validation_error}`}
                        </span>
                      </div>
                      <pre className="code-box" style={{ maxHeight: '340px' }}>
                        {gf.code || '// No code output returned.'}
                      </pre>
                    </div>
                  ))}

                  {generation.explanation && (
                    <div style={{ padding: '14px', background: 'var(--bg-card-subtle)', borderRadius: '8px', border: '1px solid var(--border-subtle)' }}>
                      <span style={{ fontSize: '11px', fontWeight: 700, color: '#a78bfa', textTransform: 'uppercase' }}>Model Reasoning:</span>
                      <p style={{ fontSize: '13px', color: 'var(--text-muted)', marginTop: '4px', whiteSpace: 'pre-wrap' }}>{generation.explanation}</p>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        {/* TAB 5: FAILURE DIAGNOSIS & REPAIR */}
        {activeTab === 'repair' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            <div className="card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px', marginBottom: '18px' }}>
                <div>
                  <span className="badge badge-amber">Failure Analysis & Bounded Repair</span>
                  <h3 style={{ fontSize: '18px', fontWeight: 700, marginTop: '4px' }}>Automated Failure Diagnosis & AST Safety-Gate</h3>
                  <p style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
                    Differentiates genuine application bugs from test defects, applying targeted diffs and re-validating in a bounded iteration loop.
                  </p>
                </div>

                <button onClick={handleRunRepair} disabled={!!loadingAction} className="btn btn-purple">
                  <Wrench size={16} />
                  <span>Run Bounded Repair Loop</span>
                </button>
              </div>

              {/* Diagnosis Card if triggered from failed test */}
              {diagnosis && (
                <div style={{ marginBottom: '20px', padding: '18px', background: 'rgba(245, 158, 11, 0.08)', border: '1px solid rgba(245, 158, 11, 0.3)', borderRadius: 'var(--radius-md)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                    <AlertTriangle size={18} color="#fbbf24" />
                    <h4 style={{ fontSize: '15px', fontWeight: 700, color: '#fbbf24' }}>Automated Failure Classification</h4>
                    <span className="badge badge-amber" style={{ fontSize: '10px' }}>{diagnosis.category}</span>
                  </div>
                  <p style={{ fontSize: '13px', color: '#f8fafc', lineHeight: '1.6' }}>{diagnosis.explanation}</p>
                  <div style={{ marginTop: '10px', fontSize: '12px', color: diagnosis.is_repairable ? '#34d399' : '#fb7185', fontWeight: 600 }}>
                    {diagnosis.is_repairable
                      ? '✓ Categorized as repairable at test level (Incorrect assertion or missing fixture).'
                      : '⚠️ Categorized as Genuine Source Code Defect. TestPilot Safety Gate will protect tests from being mutilated to mask real application bugs.'}
                  </div>
                </div>
              )}

              {/* Repair Loop Report */}
              {!repair ? (
                <div style={{ textAlign: 'center', padding: '40px 20px', background: 'var(--bg-card-subtle)', borderRadius: 'var(--radius-md)' }}>
                  <Wrench size={40} color="#fbbf24" style={{ margin: '0 auto 12px', opacity: 0.7 }} />
                  <p style={{ fontSize: '14px', color: 'var(--text-muted)' }}>
                    Click "Run Bounded Repair Loop" to attempt iterative automated test repair and re-execution.
                  </p>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                  <div className="kpi-grid">
                    <div className="kpi-card">
                      <span className="kpi-title">Repair Status</span>
                      <span className="kpi-value" style={{ color: repair.resolved ? '#34d399' : '#fb7185' }}>
                        {repair.status}
                      </span>
                      <span className="kpi-sub">{repair.resolved ? 'Failures resolved' : 'Unresolved / Defect'}</span>
                    </div>

                    <div className="kpi-card">
                      <span className="kpi-title">Iterations Run</span>
                      <span className="kpi-value">{repair.iterations_run} / {repair.max_iterations}</span>
                      <span className="kpi-sub">Bounded loop limit</span>
                    </div>

                    <div className="kpi-card">
                      <span className="kpi-title">Failures Fixed</span>
                      <span className="kpi-value" style={{ color: '#34d399' }}>{repair.failures_fixed_count}</span>
                      <span className="kpi-sub">{repair.initial_failures.length} initial failing tests</span>
                    </div>

                    <div className="kpi-card">
                      <span className="kpi-title">Duration</span>
                      <span className="kpi-value">{repair.duration_seconds.toFixed(2)}s</span>
                      <span className="kpi-sub">Total loop execution</span>
                    </div>
                  </div>

                  {repair.attempts.length > 0 && (
                    <div style={{ marginTop: '12px' }}>
                      <h4 style={{ fontSize: '14px', fontWeight: 700, marginBottom: '8px' }}>Repair Iteration History</h4>
                      {repair.attempts.map((att, idx) => (
                        <div key={idx} style={{ padding: '12px', background: 'var(--bg-card-subtle)', border: '1px solid var(--border-subtle)', borderRadius: '8px', marginBottom: '8px' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px' }}>
                            <span style={{ fontWeight: 600, color: '#f8fafc' }}>Iteration {att.iteration} — {att.test_file}</span>
                            <span style={{ color: att.re_execution_passed ? '#34d399' : '#fb7185' }}>
                              Re-execution: {att.re_execution_passed ? 'PASSED' : 'FAILED'} (AST Valid: {att.is_ast_valid ? 'Yes' : 'No'})
                            </span>
                          </div>
                          {att.diff && (
                            <pre className="code-box" style={{ marginTop: '8px', fontSize: '11px', maxHeight: '150px' }}>
                              {att.diff}
                            </pre>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        {/* TAB 6: END-TO-END PIPELINE BENCHMARK */}
        {activeTab === 'benchmark' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            <div className="card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px', marginBottom: '18px' }}>
                <div>
                  <span className="badge badge-purple">Full Benchmark Suite</span>
                  <h3 style={{ fontSize: '18px', fontWeight: 700, marginTop: '4px' }}>Analyze &rarr; Generate &rarr; Execute &rarr; Repair &rarr; Metrics</h3>
                  <p style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
                    Executes the complete TestPilot pipeline inside an isolated temporary workspace, gathering empirical metrics and coverage deltas without mutating original repository code.
                  </p>
                </div>

                <button onClick={handleRunBenchmark} disabled={!!loadingAction} className="btn btn-purple">
                  <Play size={16} fill="white" />
                  <span>Execute Full Benchmark</span>
                </button>
              </div>

              {!benchmark ? (
                <div style={{ textAlign: 'center', padding: '40px 20px', background: 'var(--bg-card-subtle)', borderRadius: 'var(--radius-md)' }}>
                  <Layers size={40} color="#a78bfa" style={{ margin: '0 auto 12px', opacity: 0.7 }} />
                  <p style={{ fontSize: '14px', color: 'var(--text-muted)' }}>
                    Click "Execute Full Benchmark" to run all 5 pipeline phases on an isolated workspace copy.
                  </p>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                  <div className="kpi-grid">
                    <div className="kpi-card">
                      <span className="kpi-title">Benchmark Name</span>
                      <span className="kpi-value" style={{ fontSize: '18px' }}>{benchmark.benchmark_name}</span>
                      <span className="kpi-sub">{benchmark.run_id}</span>
                    </div>

                    <div className="kpi-card">
                      <span className="kpi-title">Overall Status</span>
                      <span className="kpi-value" style={{ color: benchmark.status === 'passed' ? '#34d399' : '#38bdf8' }}>
                        {benchmark.status}
                      </span>
                      <span className="kpi-sub">{benchmark.total_duration_seconds.toFixed(2)}s runtime</span>
                    </div>

                    <div className="kpi-card">
                      <span className="kpi-title">Generated Tests</span>
                      <span className="kpi-value">{benchmark.tests_generated}</span>
                      <span className="kpi-sub">{benchmark.valid_generated_tests} AST valid</span>
                    </div>

                    <div className="kpi-card">
                      <span className="kpi-title">Initial Execution</span>
                      <span className="kpi-value" style={{ fontSize: '16px' }}>
                        {benchmark.initial_passed} pass, {benchmark.initial_failed} fail
                      </span>
                      <span className="kpi-sub">Baseline test run</span>
                    </div>

                    <div className="kpi-card">
                      <span className="kpi-title">Baseline Coverage</span>
                      <span className="kpi-value" style={{ color: '#38bdf8' }}>
                        {benchmark.coverage_before !== null && benchmark.coverage_before !== undefined ? `${benchmark.coverage_before.toFixed(1)}%` : '—'}
                      </span>
                      <span className="kpi-sub">Before generation</span>
                    </div>

                    <div className="kpi-card">
                      <span className="kpi-title">Final Coverage</span>
                      <span className="kpi-value" style={{ color: '#34d399' }}>
                        {benchmark.coverage_after !== null && benchmark.coverage_after !== undefined ? `${benchmark.coverage_after.toFixed(1)}%` : '—'}
                      </span>
                      <span className="kpi-sub">
                        Delta: {benchmark.coverage_delta !== null && benchmark.coverage_delta !== undefined ? `${benchmark.coverage_delta >= 0 ? '+' : ''}${benchmark.coverage_delta.toFixed(1)}%` : '0.0%'}
                      </span>
                    </div>
                  </div>

                  {benchmark.has_source_code_defects && (
                    <div style={{ padding: '14px', background: 'rgba(245, 158, 11, 0.1)', border: '1px solid rgba(245, 158, 11, 0.3)', borderRadius: '8px' }}>
                      <p style={{ color: '#fbbf24', fontSize: '13px', fontWeight: 600 }}>
                        Safety Gate Triggered: Real source code defect detected. Repair Agent refused to alter tests to conceal genuine application bugs.
                      </p>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </main>

      {/* API Key Modal */}
      {showKeyModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>
          <div className="card" style={{ maxWidth: '480px', width: '90%', background: '#0f172a', border: '1px solid var(--border-strong)', boxShadow: '0 25px 50px -12px rgba(0,0,0,0.7)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Key size={18} color="#38bdf8" />
                <h3 style={{ fontSize: '16px', fontWeight: 700 }}>LLM Provider Settings</h3>
              </div>
              <button onClick={() => setShowKeyModal(false)} style={{ background: 'none', border: 'none', color: 'var(--text-dim)', cursor: 'pointer', fontSize: '16px' }}>✕</button>
            </div>

            <p style={{ fontSize: '13px', color: 'var(--text-muted)', marginBottom: '14px', lineHeight: '1.5' }}>
              TestPilot operates with deterministic AST verification & heuristic classification by default. If you provide an OpenAI API key, live GPT-4o test generation and deep reasoning will be used.
            </p>

            <div style={{ marginBottom: '16px' }}>
              <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: '#f8fafc', marginBottom: '6px' }}>
                OpenAI API Key (Optional):
              </label>
              <input
                type="password"
                placeholder="sk-..."
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                style={{
                  width: '100%',
                  background: 'var(--bg-input)',
                  border: '1px solid var(--border-strong)',
                  borderRadius: '6px',
                  padding: '10px 14px',
                  color: '#f8fafc',
                  fontSize: '13px',
                  fontFamily: 'JetBrains Mono',
                  outline: 'none',
                }}
              />
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
              <button onClick={() => setShowKeyModal(false)} className="btn btn-secondary">
                Close
              </button>
              <button onClick={() => setShowKeyModal(false)} className="btn btn-primary">
                Save & Apply
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Footer */}
      <footer style={{ borderTop: '1px solid var(--border-subtle)', background: 'var(--bg-card)', padding: '20px', marginTop: 'auto', textAlign: 'center', fontSize: '12px', color: 'var(--text-dim)' }}>
        <p>TestPilot AI v0.1.0 — Agentic Software Testing & Validation Platform</p>
        <p style={{ marginTop: '4px' }}>Ready for live hackathon demonstration &amp; Vercel deployment.</p>
      </footer>
    </div>
  );
}
export default App;
