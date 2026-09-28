import {
  BenchmarkResult,
  ExecutionReport,
  FailureDiagnosis,
  GenerationReport,
  HealthStatus,
  Preset,
  RepairReport,
  RepositoryAnalysis,
} from './types';

// Relative API base - works seamlessly both locally (via Vite proxy or direct) and on Vercel!
// NO hardcoded localhost URLs.
const API_BASE = '/api';

async function handleResponse<T>(res: Response): Promise<T> {
  const data = await res.json();
  if (!res.ok || data.success === false) {
    const errorMsg = data.error || data.details || `Request failed with status ${res.status}`;
    throw new Error(errorMsg);
  }
  return data;
}

export async function getHealth(): Promise<HealthStatus> {
  const res = await fetch(`${API_BASE}/health`);
  return handleResponse<HealthStatus>(res);
}

export async function getPresets(): Promise<{ presets: Preset[] }> {
  const res = await fetch(`${API_BASE}/presets`);
  return handleResponse<{ presets: Preset[] }>(res);
}

export async function analyzeRepository(
  repoPath: string,
  noCoverage = false
): Promise<{ analysis: RepositoryAnalysis }> {
  const res = await fetch(`${API_BASE}/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ repo_path: repoPath, no_coverage: noCoverage }),
  });
  return handleResponse<{ analysis: RepositoryAnalysis }>(res);
}

export async function executeTests(
  repoPath: string,
  noCoverage = false,
  timeout = 60
): Promise<{ execution: ExecutionReport }> {
  const res = await fetch(`${API_BASE}/execute`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ repo_path: repoPath, no_coverage: noCoverage, timeout }),
  });
  return handleResponse<{ execution: ExecutionReport }>(res);
}

export async function generateTests(
  repoPath: string,
  targetFile?: string,
  openaiApiKey?: string
): Promise<{ generation: GenerationReport }> {
  const res = await fetch(`${API_BASE}/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      repo_path: repoPath,
      target_file: targetFile,
      openai_api_key: openaiApiKey,
    }),
  });
  return handleResponse<{ generation: GenerationReport }>(res);
}

export async function diagnoseFailure(
  failureType: string,
  failureMessage: string,
  traceback: string
): Promise<FailureDiagnosis> {
  const res = await fetch(`${API_BASE}/diagnose`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      failure_type: failureType,
      failure_message: failureMessage,
      traceback,
    }),
  });
  return handleResponse<FailureDiagnosis>(res);
}

export async function runRepair(
  repoPath: string,
  testFile?: string,
  maxAttempts = 2,
  openaiApiKey?: string
): Promise<{ repair: RepairReport }> {
  const res = await fetch(`${API_BASE}/repair`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      repo_path: repoPath,
      test_file: testFile,
      max_attempts: maxAttempts,
      openai_api_key: openaiApiKey,
    }),
  });
  return handleResponse<{ repair: RepairReport }>(res);
}

export async function runBenchmark(
  repoPath: string,
  targetModule?: string,
  openaiApiKey?: string
): Promise<{ benchmark: BenchmarkResult }> {
  const res = await fetch(`${API_BASE}/benchmark`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      repo_path: repoPath,
      target_module: targetModule,
      openai_api_key: openaiApiKey,
    }),
  });
  return handleResponse<{ benchmark: BenchmarkResult }>(res);
}
