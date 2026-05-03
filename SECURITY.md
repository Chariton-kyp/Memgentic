# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in Memgentic, please report it
responsibly via **GitHub Security Advisories**:

➡️ **[Open a private vulnerability report](https://github.com/Chariton-kyp/Memgentic/security/advisories/new)**

This keeps the discussion private until a fix lands and a coordinated
disclosure is published.

Please include:

- A description of the vulnerability
- Steps to reproduce
- Affected versions
- Any potential impact

### What to expect

This project is maintained by a single developer in their spare time, so
response times are best-effort rather than contractual:

- **Acknowledgment**: as soon as the maintainer sees the advisory
- **Assessment / fix timeline**: communicated in the advisory thread once
  the report has been triaged
- **Credit** in the release notes and GitHub Security Advisory (unless
  you prefer anonymity)

### Do NOT

- Open a public GitHub issue for security vulnerabilities
- Share the vulnerability publicly before it's been fixed
- Test vulnerabilities against systems you don't own

## Scope

The following are in scope:
- `memgentic` core library (memory storage, processing, credential scrubbing)
- `memgentic-api` REST API (authentication, authorization, input validation)
- `memgentic-native` Rust module (memory safety, input parsing)
- MCP server (tool execution, data exposure)
- Dashboard (XSS, CSRF, authentication bypass)
- Daemon (file system access, privilege escalation)

## Security Features

Memgentic includes several security measures by default:

- **Credential scrubbing** — 16 patterns (API keys, tokens, PEM, JWT, connection strings) redacted before storage
- **Security headers** — X-Content-Type-Options, X-Frame-Options, CSP, HSTS, Permissions-Policy
- **Request size limits** — 10MB maximum payload
- **Rate limiting** — configurable per-endpoint via slowapi
- **Non-root Docker** — runs as user 1001, not root
- **Optional API key auth** — HMAC-SHA256 constant-time comparison
- **No telemetry** — zero outbound network calls except to configured embedding providers

## Supported Versions

Only the latest minor release receives security fixes. Older releases are
documented in the GitHub Releases page but not patched.

| Version                   | Supported |
|---------------------------|-----------|
| Latest minor (e.g. 0.7.x) | Yes       |
| Older                     | No        |
