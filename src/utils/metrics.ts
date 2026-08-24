type Stage =
  | 'pre_translate'
  | 'pre_polly'
  | 'polly_listener'
  | 'polly_wait'
  | 'merge_files'
  | 'get'
  | 'trigger';

type Result = 'success' | 'failure' | 'skipped' | 'waiting';
type Dependency = 'dynamodb' | 'http' | 's3' | 'step_functions';
type Operation =
  | 'create'
  | 'fetch'
  | 'get'
  | 'list'
  | 'presign'
  | 'put'
  | 'query'
  | 'send_task'
  | 'start_execution'
  | 'update';
type RetryOperation = 'content_poll' | 'workflow_task';
type Unit = 'Count' | 'None' | 'Seconds';

interface Measurement {
  name: string;
  unit: Unit;
  value: number;
}

const NAMESPACE = 'Gaulatti/Guggiana';
const SERVICE = 'guggiana';

const emit = (
  stage: Stage,
  dimensions: Record<string, string>,
  measurements: Measurement[]
) => {
  const values = Object.fromEntries(
    measurements.map(({ name, value }) => [name, value])
  );
  console.log(
    JSON.stringify({
      _aws: {
        Timestamp: Date.now(),
        CloudWatchMetrics: [
          {
            Namespace: NAMESPACE,
            Dimensions: [['service', 'stage', ...Object.keys(dimensions)]],
            Metrics: measurements.map(({ name: Name, unit: Unit }) => ({
              Name,
              Unit,
            })),
          },
        ],
      },
      service: SERVICE,
      stage,
      ...dimensions,
      ...values,
    })
  );
};

const recordInvocation = (
  stage: Stage,
  result: Extract<Result, 'success' | 'failure'>,
  durationSeconds: number
) => {
  emit(stage, { result }, [
    { name: 'guggiana_lambda_invocations_total', unit: 'Count', value: 1 },
    {
      name: 'guggiana_lambda_duration_seconds',
      unit: 'Seconds',
      value: durationSeconds,
    },
    {
      name: 'guggiana_workflow_stage_events_total',
      unit: 'Count',
      value: 1,
    },
  ]);
};

const recordBuild = (stage: Stage) => {
  emit(
    stage,
    { version: process.env.GUGGIANA_BUILD_VERSION ?? 'development' },
    [{ name: 'guggiana_build_identity', unit: 'None', value: 1 }]
  );
};

const recordDependency = (
  stage: Stage,
  dependency: Dependency,
  operation: Operation,
  result: Extract<Result, 'success' | 'failure'>,
  durationSeconds: number
) => {
  emit(stage, { dependency, operation, result }, [
    { name: 'guggiana_dependency_requests_total', unit: 'Count', value: 1 },
    {
      name: 'guggiana_dependency_duration_seconds',
      unit: 'Seconds',
      value: durationSeconds,
    },
  ]);
};

const observeDependency = async <T>(
  stage: Stage,
  dependency: Dependency,
  operation: Operation,
  operationCall: () => Promise<T>
): Promise<T> => {
  const startedAt = Date.now();
  try {
    const value = await operationCall();
    recordDependency(
      stage,
      dependency,
      operation,
      'success',
      (Date.now() - startedAt) / 1000
    );
    return value;
  } catch (error) {
    recordDependency(
      stage,
      dependency,
      operation,
      'failure',
      (Date.now() - startedAt) / 1000
    );
    throw error;
  }
};

const recordRetry = (
  stage: Stage,
  operation: RetryOperation,
  result: Extract<Result, 'success' | 'failure' | 'waiting'>
) => {
  emit(stage, { operation, result }, [
    { name: 'guggiana_retries_total', unit: 'Count', value: 1 },
  ]);
};

const recordWorkflowBatch = (stage: Stage, batchSize: number) => {
  emit(stage, {}, [
    { name: 'guggiana_workflow_batch_size', unit: 'None', value: batchSize },
  ]);
};

const recordWorkflowBacklog = (stage: Stage, backlog: number) => {
  emit(stage, {}, [
    { name: 'guggiana_workflow_backlog', unit: 'None', value: backlog },
  ]);
};

const recordWorkflowOutcome = (
  stage: Stage,
  result: Extract<Result, 'success' | 'failure' | 'skipped'>
) => {
  emit(stage, { result }, [
    { name: 'guggiana_workflow_outcomes_total', unit: 'Count', value: 1 },
  ]);
};

const instrumentHandler = <T extends (...args: any[]) => Promise<any>>(
  stage: Stage,
  handler: T
): T => {
  const instrumented = async (...args: Parameters<T>): Promise<ReturnType<T>> => {
    const startedAt = Date.now();
    recordBuild(stage);
    try {
      const value = await handler(...args);
      recordInvocation(stage, 'success', (Date.now() - startedAt) / 1000);
      return value;
    } catch (error) {
      recordInvocation(stage, 'failure', (Date.now() - startedAt) / 1000);
      throw error;
    }
  };
  return instrumented as T;
};

export {
  instrumentHandler,
  observeDependency,
  recordRetry,
  recordWorkflowBacklog,
  recordWorkflowBatch,
  recordWorkflowOutcome,
};
export type { Dependency, Operation, Result, Stage };
