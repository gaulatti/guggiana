import { main } from '../../../../src/functions/translate/pre_translate';

test('main function returns the event', async () => {
  const event = {};
  const context = {};
  const callback = jest.fn();

  const result = await main(event, context, callback);

  expect(result).toEqual(event);
});
