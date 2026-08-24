import { instrumentHandler } from '../../utils/metrics';

const handler = async (event: any, _context: any, _callback: any) => {
  return event;
};

const main = instrumentHandler('pre_translate', handler);

export { main };
