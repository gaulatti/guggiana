import {
  instrumentHandler,
  observeDependency,
  recordRetry,
  recordWorkflowBacklog,
  recordWorkflowBatch,
  recordWorkflowOutcome,
} from '../../../src/utils/metrics';

describe('Guggiana embedded metrics collector', () => {
  const originalVersion = process.env.GUGGIANA_BUILD_VERSION;
  let output: string[];
  let logSpy: jest.SpyInstance;

  beforeEach(() => {
    output = [];
    process.env.GUGGIANA_BUILD_VERSION = 'build-test';
    logSpy = jest.spyOn(console, 'log').mockImplementation((line: string) => {
      output.push(line);
    });
  });

  afterEach(() => {
    logSpy.mockRestore();
    if (originalVersion === undefined) {
      delete process.env.GUGGIANA_BUILD_VERSION;
    } else {
      process.env.GUGGIANA_BUILD_VERSION = originalVersion;
    }
  });

  it('parses real success collector output and keeps every dimension bounded', async () => {
    const handler = instrumentHandler('pre_translate', async () => 'ok');

    await expect(handler()).resolves.toBe('ok');
    await expect(
      observeDependency('trigger', 'http', 'fetch', async () => 'response')
    ).resolves.toBe('response');
    recordRetry('get', 'content_poll', 'waiting');
    recordWorkflowBatch('trigger', 3);
    recordWorkflowBacklog('polly_listener', 2);
    recordWorkflowOutcome('merge_files', 'skipped');

    const events = output.map((line) => JSON.parse(line));
    const allowedDimensionKeys = new Set([
      'service',
      'stage',
      'version',
      'result',
      'dependency',
      'operation',
    ]);
    const metricNames = new Set<string>();
    const dimensionValues: string[] = [];

    events.forEach((event) => {
      expect(event._aws.Timestamp).toEqual(expect.any(Number));
      expect(event._aws.CloudWatchMetrics).toHaveLength(1);
      const directive = event._aws.CloudWatchMetrics[0];
      expect(directive.Namespace).toBe('Gaulatti/Guggiana');
      directive.Dimensions[0].forEach((key: string) => {
        expect(allowedDimensionKeys).toContain(key);
        expect(event[key]).toEqual(expect.any(String));
        dimensionValues.push(event[key]);
      });
      directive.Metrics.forEach(({ Name }: { Name: string }) => {
        metricNames.add(Name);
        expect(event[Name]).toEqual(expect.any(Number));
      });
    });

    expect(metricNames).toEqual(
      new Set([
        'guggiana_build_identity',
        'guggiana_dependency_duration_seconds',
        'guggiana_dependency_requests_total',
        'guggiana_lambda_duration_seconds',
        'guggiana_lambda_invocations_total',
        'guggiana_retries_total',
        'guggiana_workflow_backlog',
        'guggiana_workflow_batch_size',
        'guggiana_workflow_outcomes_total',
        'guggiana_workflow_stage_events_total',
      ])
    );
    expect(dimensionValues.join('\n')).not.toMatch(
      /:\/\/|private-|document-|object-|device-|token-|error message/
    );
  });

  it('emits failure outcomes without serializing thrown errors or payload values', async () => {
    const privateValue = 'private-object-key-and-document-id';
    const handler = instrumentHandler('get', async (_event: any) => {
      throw new Error(privateValue);
    });

    await expect(handler({ documentId: privateValue })).rejects.toThrow(
      privateValue
    );
    await expect(
      observeDependency('merge_files', 's3', 'put', async () => {
        throw new Error(privateValue);
      })
    ).rejects.toThrow(privateValue);

    const serialized = output.join('\n');
    expect(serialized).toContain('"result":"failure"');
    expect(serialized).not.toContain(privateValue);
  });
});
