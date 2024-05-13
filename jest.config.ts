import type { Config } from '@jest/types';

const config: Config.InitialOptions = {
  preset: 'ts-jest',
  testEnvironment: 'node',
  collectCoverage: true,
  collectCoverageFrom: ['**/{src,lib}/**/*.{ts,js}', '!**/*.d.ts'],
};

export default config;
