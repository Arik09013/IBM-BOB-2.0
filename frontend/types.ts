export interface Preset {
  id: string;
  name: string;
  path: string;
  description: string;
  type: string;
  tests_expected: number;
  recommended: boolean;
}

export interface SymbolInfo {
  name: string;
  qualified_name: string;
  kind: string;
  file: string;
  line: number;
  is_private: boolean;
  is_dunder: boolean;
  parent_class?: string | null;
}

export interface FileSummary {
  path: string;
  is_test_file: boolean;
  parse_error?: string | null;
  symbol_count: number;
}

export interface CoverageSummary {
  status: string;
  line_coverage_pct?: number | null;
  lines_covered?: number | null;
  lines_total?: number | null;
  tests_ran?: number | null;
  tests_passed?: number | null;
  tests_failed?: number | null;
  raw_output?: string;
  error_detail?: string;
}

export interface CoverageGap {
  file: string;
  symbol_name?: string | null;
  uncovered_lines: number[];
  gap_type: 'file' | 'symbol' | 'lines';
}

export interface RepositoryAnalysis {
  repository_path: string;
  analysed_at: string;
  language: string;
  python_version: string;
  test_framework: string;
  test_framework_detected: boolean;
  test_framework_config_source: string;
  source_files: string[];
  test_files: string[];
  all_python_files: string[];
  file_summaries: FileSummary[];
  symbols: SymbolInfo[];
  coverage_summary: CoverageSummary;
  coverage_gaps: CoverageGap[];
  warnings: string[];
  errors: string[];
  parse_errors: string[];
  duration_seconds: number;
  source_file_count: number;
  test_file_count: number;
  symbol_count: number;
  public_symbol_count: number;
  has_tests: boolean;
}

export interface TestCaseResultItem {
  nodeid: string;
  name: string;
  file: string;
  classname: string;
  status: 'passed' | 'failed' | 'error' | 'skipped' | 'xfailed' | 'xpassed';
  duration_seconds?: number | null;
  failure_type?: string;
  failure_message?: string;
  traceback?: string;
}

export interface ExecutionSummary {
  total: number;
  passed: number;
  failed: number;
  errors: number;
  skipped: number;
  xfailed: number;
  xpassed: number;
  pass_rate?: number | null;
}

export interface ExecutionCoverage {
  status: string;
  coverage_pct?: number | null;
  lines_covered?: number | null;
  lines_total?: number | null;
  missing_lines_by_file: Record<string, number[]>;
  raw_output?: string;
  error_detail?: string;
}

export interface ExecutionReport {
  repository_path: string;
  status: string;
  duration_seconds: number;
  tests: TestCaseResultItem[];
  summary: ExecutionSummary;
  coverage: ExecutionCoverage;
  failed_tests: string[];
  passed_tests: string[];
  warnings: string[];
  errors: string[];
  stdout?: string;
  stderr?: string;
  exit_code: number;
  has_failures: boolean;
  is_successful: boolean;
  failed_tests_count: number;
  passed_tests_count: number;
}

export interface GeneratedTestCase {
  name: string;
  code: string;
  line_start?: number;
  line_end?: number;
}

export interface GeneratedTestFile {
  file_path: string;
  code: string;
  is_valid: boolean;
  validation_error: string;
  test_cases: GeneratedTestCase[];
  test_names: string[];
  written_to_disk: boolean;
}

export interface GenerationReport {
  repository_path: string;
  status: string;
  model: string;
  target_files: string[];
  duration_seconds: number;
  total_tests_generated: number;
  has_valid_tests: boolean;
  explanation: string;
  warnings: string[];
  errors: string[];
  generated_files: GeneratedTestFile[];
}

export interface FailureDiagnosis {
  category: string;
  explanation: string;
  is_repairable: boolean;
}

export interface RepairAttemptRecord {
  iteration: number;
  test_file: string;
  tests_repaired_count: number;
  is_ast_valid: boolean;
  re_execution_passed: boolean;
  failures_remaining: number;
  diff: string;
  duration_seconds: number;
}

export interface FailureAnalysisItem {
  test_nodeid: string;
  category: string;
  explanation: string;
  suggested_fix?: string;
  is_repairable_at_test_level: boolean;
}

export interface RepairReport {
  repository_path: string;
  status: string;
  test_file: string;
  resolved: boolean;
  iterations_run: number;
  max_iterations: number;
  initial_failures: string[];
  final_failures: string[];
  failures_fixed_count: number;
  duration_seconds: number;
  analyses: FailureAnalysisItem[];
  attempts: RepairAttemptRecord[];
  warnings: string[];
  errors: string[];
}

export interface BenchmarkResult {
  run_id: string;
  benchmark_name: string;
  status: string;
  total_duration_seconds: number;
  tests_generated: number;
  valid_generated_tests: number;
  generation_duration_seconds: number;
  initial_passed: number;
  initial_failed: number;
  final_passed: number;
  final_failed: number;
  repair_required: boolean;
  repair_attempts: number;
  repair_status: string;
  failures_resolved: number;
  has_source_code_defects: boolean;
  coverage_before?: number | null;
  coverage_after?: number | null;
  coverage_delta?: number | null;
  warnings: string[];
  errors: string[];
}

export interface HealthStatus {
  status: string;
  app: string;
  version: string;
  platform: string;
  python_version: string;
  llm_provider: string;
  llm_model: string;
  openai_configured: boolean;
}
