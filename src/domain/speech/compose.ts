import { SpeechDocument, SpeechSegment, SpeechLocale, VoiceRole } from './contract';

/**
 * The article shape Guggiana already synthesizes today: a title, a byline, and
 * a newline-separated body. {@link composeArticleSpeechDocument} proves every
 * such shape is representable in the neutral contract without SSML or Polly
 * names.
 */
export interface ArticleForSpeech {
  readonly locale: SpeechLocale;
  readonly voice?: VoiceRole;
  readonly title: string;
  readonly byline: string;
  readonly body: string;
}

/** Pause after the title/byline block, before the body. */
export const TITLE_PAUSE_MS = 900;
/** Pause between adjacent spoken units. */
export const PARAGRAPH_PAUSE_MS = 450;

export function composeArticleSpeechDocument(article: ArticleForSpeech): SpeechDocument {
  const segments: SpeechSegment[] = [];
  const title = article.title.trim();
  const byline = article.byline.trim();
  const paragraphs = article.body
    .split('\n')
    .map((paragraph) => paragraph.trim())
    .filter((paragraph) => paragraph.length > 0);

  if (title.length > 0) {
    segments.push({ kind: 'text', text: title });
  }
  if (byline.length > 0) {
    if (segments.length > 0) {
      segments.push({ kind: 'pause', durationMs: PARAGRAPH_PAUSE_MS });
    }
    segments.push({ kind: 'text', text: byline });
  }
  if (segments.length > 0 && paragraphs.length > 0) {
    segments.push({ kind: 'pause', durationMs: TITLE_PAUSE_MS });
  }
  paragraphs.forEach((paragraph, index) => {
    if (index > 0) {
      segments.push({ kind: 'pause', durationMs: PARAGRAPH_PAUSE_MS });
    }
    segments.push({ kind: 'text', text: paragraph });
  });

  return {
    locale: article.locale,
    voice: article.voice ?? 'narrator',
    segments,
  };
}
