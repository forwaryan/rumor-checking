# Security Policy

## Reporting a vulnerability

Do not open a public issue for suspected vulnerabilities or leaked credentials. Report privately to the repository maintainers through the hosting platform's private vulnerability-reporting channel. Include impact, reproduction steps, affected revision, and any suggested mitigation.

## Supported version

Security fixes target the current `main` branch. This repository does not currently maintain older release lines.

## Sensitive data

- Never commit API keys, gateway URLs containing credentials, cookies, authorization headers, or `.env` files.
- Do not add private user submissions or authenticated page captures to replay datasets.
- Redact prompts, retrieved content, and trace attributes before exporting them to external observability systems.
- Treat retrieved web content as untrusted input; it must not override system instructions or tool policy.

## Dependency policy

Dependabot monitors Python, npm, and GitHub Actions dependencies. Pull requests are checked for newly introduced high-severity dependency vulnerabilities.
