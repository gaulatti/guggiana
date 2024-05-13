import { main, prepareTitle, groupParagraphs } from '../../../../src/functions/tts/pre_polly';

describe('main', () => {
  it('should return the converted text-to-speech data', async () => {
    const event = {
      uuid: '123',
      url: 'https://example.com',
      language: {
        items: [{ name: 'voice1' }, { name: 'voice2' }, { name: 'voice3' }],
      },
      text: 'Lorem ipsum dolor sit amet, consectetur adipiscing elit.',
      title: 'Sample Title',
      byline: 'Sample Byline',
    };

    const result = await main(event, null, null);

    expect(result.uuid).toBe('123');
    expect(result.url).toBe('https://example.com');
    expect(result.title).toBe('<speak>Sample Title<p>Sample Byline</p></speak>');
    expect(result.selectedVoice).toBeDefined();
    expect(result.language).toBeDefined();
    expect(result.text).toHaveLength(1);
  });
});

describe('prepareTitle', () => {
  it('should return the prepared text in SSML format', () => {
    const title = 'Sample Title';
    const byline = 'Sample Byline';

    const result = prepareTitle(title, byline);

    expect(result).toBe('<speak>Sample Title<p>Sample Byline</p></speak>');
  });
});

describe('groupParagraphs', () => {
  it('should group paragraphs based on a maximum character limit', () => {
    const text = 'Paragraph 1\nParagraph 2\nParagraph 3';
    const maxCharacterLimit = 20;

    const result = groupParagraphs(text, maxCharacterLimit);

    expect(result).toHaveLength(3);
    expect(result[0]).toBe('<speak><p>Paragraph 1</p></speak>');
    expect(result[1]).toBe('<speak><p>Paragraph 2</p></speak>');
    expect(result[2]).toBe('<speak><p>Paragraph 3</p></speak>');
  });
});
