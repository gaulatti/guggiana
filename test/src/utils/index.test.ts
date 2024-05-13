import { delay, excapeSSMLCharacters, extractPathWithTrailingSlash, lambdaHttpOutput, sanitizeGetInputs } from '../../../src/utils';

describe('excapeSSMLCharacters', () => {
  it('should escape SSML characters', () => {
    const input = 'Hello "world" & \'universe\' <planet> >moon<';
    const expectedOutput = 'Hello &amp;quot;world&amp;quot; &amp; &apos;universe&apos; &lt;planet&gt; &gt;moon&lt;';
    const result = excapeSSMLCharacters(input);
    expect(result).toEqual(expectedOutput);
  });

  it('should not modify text without SSML characters', () => {
    const input = 'Hello, world!';
    const result = excapeSSMLCharacters(input);
    expect(result).toEqual(input);
  });

  it('should handle empty string', () => {
    const input = '';
    const result = excapeSSMLCharacters(input);
    expect(result).toEqual(input);
  });

  it('should escape SSML characters', () => {
    const input = 'Hello "world" & \'universe\' <planet> >moon<';
    const expectedOutput = 'Hello &amp;quot;world&amp;quot; &amp; &apos;universe&apos; &lt;planet&gt; &gt;moon&lt;';
    const result = excapeSSMLCharacters(input);
    expect(result).toEqual(expectedOutput);
  });

  it('should not modify text without SSML characters', () => {
    const input = 'Hello, world!';
    const result = excapeSSMLCharacters(input);
    expect(result).toEqual(input);
  });

  it('should handle empty string', () => {
    const input = '';
    const result = excapeSSMLCharacters(input);
    expect(result).toEqual(input);
  });

  it('should escape double quotes', () => {
    const input = 'Hello "world"';
    const expectedOutput = 'Hello &amp;quot;world&amp;quot;';
    const result = excapeSSMLCharacters(input);
    expect(result).toEqual(expectedOutput);
  });

  it('should escape ampersands', () => {
    const input = 'Hello & universe';
    const expectedOutput = 'Hello &amp; universe';
    const result = excapeSSMLCharacters(input);
    expect(result).toEqual(expectedOutput);
  });

  it('should escape single quotes', () => {
    const input = "Hello 'world'";
    const expectedOutput = 'Hello &apos;world&apos;';
    const result = excapeSSMLCharacters(input);
    expect(result).toEqual(expectedOutput);
  });

  it('should escape less than sign', () => {
    const input = 'Hello <planet>';
    const expectedOutput = 'Hello &lt;planet&gt;';
    const result = excapeSSMLCharacters(input);
    expect(result).toEqual(expectedOutput);
  });

  it('should escape greater than sign', () => {
    const input = 'Hello >moon<';
    const expectedOutput = 'Hello &gt;moon&lt;';
    const result = excapeSSMLCharacters(input);
    expect(result).toEqual(expectedOutput);
  });
});

describe('delay', () => {
  it('should delay for the specified milliseconds', async () => {
    const milliseconds = 2000;
    const startTime = Date.now();
    await delay(milliseconds);
    const endTime = Date.now();
    const elapsedTime = endTime - startTime;
    expect(elapsedTime).toBeGreaterThanOrEqual(milliseconds);
  });

  it('should delay for the default 1000 milliseconds if no value is provided', async () => {
    const milliseconds = 1000;
    const startTime = Date.now();
    await delay();
    const endTime = Date.now();
    const elapsedTime = endTime - startTime;
    expect(elapsedTime).toBeGreaterThanOrEqual(milliseconds);
  });

  it('should delay for the specified milliseconds', async () => {
    const milliseconds = 2000;
    const startTime = Date.now();
    await delay(milliseconds);
    const endTime = Date.now();
    const elapsedTime = endTime - startTime;
    expect(elapsedTime).toBeGreaterThanOrEqual(milliseconds);
  });

  it('should delay for the default 1000 milliseconds if no value is provided', async () => {
    const milliseconds = 1000;
    const startTime = Date.now();
    await delay();
    const endTime = Date.now();
    const elapsedTime = endTime - startTime;
    expect(elapsedTime).toBeGreaterThanOrEqual(milliseconds);
  });
});

describe('sanitizeGetInputs', () => {
  it('should extract contentId from body for POST request', () => {
    const event = {
      httpMethod: 'POST',
      body: JSON.stringify({ contentId: '123' }),
    };
    const expectedOutput = { contentId: '123' };
    const result = sanitizeGetInputs(event);
    expect(result).toEqual(expectedOutput);
  });

  it('should extract contentId from pathParameters for non-POST request', () => {
    const event = {
      httpMethod: 'GET',
      pathParameters: { contentId: '123' },
    };
    const expectedOutput = { contentId: '123', href: null, language: null };
    const result = sanitizeGetInputs(event);
    expect(result).toEqual(expectedOutput);
  });

  it('should extract href and language from body for POST request', () => {
    const event = {
      httpMethod: 'POST',
      body: JSON.stringify({ url: 'https://example.com', language: 'en' }),
    };
    const expectedOutput = {
      href: 'https://example.com',
      language: 'en',
    };
    const result = sanitizeGetInputs(event);
    expect(result).toEqual(expectedOutput);
  });

  it('should return null for href and language for non-POST request', () => {
    const event = {
      httpMethod: 'GET',
      pathParameters: { contentId: '123' },
    };
    const expectedOutput = { contentId: '123', href: null, language: null };
    const result = sanitizeGetInputs(event);
    expect(result).toEqual(expectedOutput);
  });
});

describe('lambdaHttpOutput', () => {
  it('should return the correct response object with status code and body', () => {
    const statusCode = 200;
    const output = { message: 'Success' };
    const expectedOutput = {
      statusCode: statusCode,
      body: JSON.stringify(output),
    };
    const result = lambdaHttpOutput(statusCode, output);
    expect(result).toEqual(expectedOutput);
  });

  it('should return the correct response object with status code and empty body', () => {
    const statusCode = 404;
    const expectedOutput = {
      statusCode: statusCode,
      body: JSON.stringify(undefined),
    };
    const result = lambdaHttpOutput(statusCode);
    expect(result).toEqual(expectedOutput);
  });
});

describe('extractPathWithTrailingSlash', () => {
  it('should return the extracted path with a trailing slash', () => {
    const url = 'https://www.cnn.com/path/to/resource/';
    const expectedPath = '/path/to/resource/';

    const result = extractPathWithTrailingSlash(url);
    expect(result).toEqual(expectedPath);
  });

  it('should return null if the URL does not match the expected format', () => {
    const url = 'https://www.cnn.com';
    const result = extractPathWithTrailingSlash(url);
    expect(result).toBeNull();
  });

  it('should return null if the URL does not have a path', () => {
    const url = 'https://www.cnn.com/';
    const result = extractPathWithTrailingSlash(url);
    expect(result).toBeNull();
  });

  it('should return null if the URL is empty', () => {
    const url = '';
    const result = extractPathWithTrailingSlash(url);
    expect(result).toBeNull();
  });
});