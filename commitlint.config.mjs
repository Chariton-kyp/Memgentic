// @ts-check
/**
 * commitlint configuration for Memgentic.
 *
 * Aligned with docs/architecture/conventional-commits.md.
 * Validates PR titles in CI; individual commits are validated locally
 * via the commitizen pre-commit hook (added in PR 6).
 */
export default {
  extends: ['@commitlint/config-conventional'],
  rules: {
    // Subject line caps
    'header-max-length': [2, 'always', 100],
    'subject-case': [0],
    'subject-empty': [2, 'never'],
    'subject-full-stop': [2, 'never', '.'],

    // Type and scope
    'type-empty': [2, 'never'],
    'type-case': [2, 'always', 'lower-case'],
    'scope-case': [2, 'always', 'lower-case'],
    'type-enum': [
      2,
      'always',
      [
        'feat',
        'fix',
        'perf',
        'revert',
        'refactor',
        'docs',
        'test',
        'tests',
        'build',
        'ci',
        'chore',
        'style',
        'security',
        'dx',
      ],
    ],

    // Body & footer
    'body-leading-blank': [1, 'always'],
    'footer-leading-blank': [1, 'always'],
    'body-max-line-length': [0],
    'footer-max-line-length': [0],
  },
};
