# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in Memgentic, please report it responsibly.

### How to report

**Email:** security@memgentic.dev

Please include:
- A description of the vulnerability
- Steps to reproduce
- Affected versions
- Any potential impact

### What to expect

- **Acknowledgment** within 48 hours
- **Assessment** within 7 days
- **Fix timeline** communicated within 14 days
- **Credit** in the release notes (unless you prefer anonymity)

### Do NOT

- Open a public GitHub issue for security vulnerabilities
- Share the vulnerability publicly before it's been fixed
- Test vulnerabilities against production systems you don't own

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

| Version | Supported |
|---------|-----------|
| 0.4.x   | Yes       |
| < 0.4   | No        |
