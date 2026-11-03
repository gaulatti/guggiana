import type { Config } from '@jest/types';

// eslint-disable-next-line @typescript-eslint/no-require-imports
const { jest: declared } = require('./package.json');

const config: Config.InitialOptions = {
  preset: 'ts-jest',
  testEnvironment: 'node',
  collectCoverage: true,
  collectCoverageFrom: ['**/{src,lib}/**/*.{ts,js}', '!**/*.d.ts'],
  // The minimum coverage is declared in package.json (`jest.coverageThreshold`).
  coverageThreshold: declared.coverageThreshold,
};

export default config;
