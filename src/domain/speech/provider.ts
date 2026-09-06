import { ProviderCapabilities, SpeechDocument, SynthesisJob } from './contract';

/**
 * The contract a synthesis engine adapter implements. Step Functions task
 * tokens, S3 keys, and provider voice IDs are deliberately absent: they belong
 * to the wiring layer, not the provider API.
 */
export interface SpeechProvider {
  /** What this adapter supports. */
  capabilities(): ProviderCapabilities;
  /** Enqueue a synthesis job for a document. The job starts `queued`. */
  createJob(document: SpeechDocument): SynthesisJob;
  /** Move a non-terminal job forward one step. Terminal jobs are returned unchanged. */
  advance(job: SynthesisJob): SynthesisJob;
}

/** Whether a job state can still change. */
export function isTerminal(job: SynthesisJob): boolean {
  return job.state === 'succeeded' || job.state === 'failed';
}

/**
 * Drives a provider's job from `queued` to a terminal state. Intended for
 * contract tests and local evaluation, not the deployed workflow.
 */
export function runToCompletion(provider: SpeechProvider, document: SpeechDocument): SynthesisJob {
  let job = provider.createJob(document);
  while (!isTerminal(job)) {
    job = provider.advance(job);
  }
  return job;
}
