import { checkLanguagesPresent } from '../../../src/utils';
import { pollyLanguages } from '../../../src/utils/consts/languages';

describe('checkLanguagesPresent', () => {
  it('returns the requested language output when language filter is provided', () => {
    const item = {
      outputs: {
        en: { url: 's3://en' },
      },
    };

    expect(checkLanguagesPresent(item, 'en')).toEqual(item.outputs.en);
  });

  it('returns false when requested language is missing', () => {
    expect(checkLanguagesPresent({ outputs: {} }, 'fr')).toBeFalsy();
  });

  it('returns true when all supported languages are present and no filter is passed', () => {
    const outputs = Object.fromEntries(
      pollyLanguages.map((language) => [language.code, { url: 's3://' + language.code }])
    );

    expect(checkLanguagesPresent({ outputs }, null)).toBe(true);
  });

  it('returns false when one or more supported languages are missing', () => {
    expect(
      checkLanguagesPresent(
        {
          outputs: {
            [pollyLanguages[0].code]: { url: 's3://partial' },
          },
        },
        null
      )
    ).toBe(false);
  });

  it('returns false when outputs object is missing and no filter is passed', () => {
    expect(checkLanguagesPresent({}, null)).toBe(false);
  });
});
