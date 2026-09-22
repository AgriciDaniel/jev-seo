# Security

- API keys are read from the environment or `~/Desktop/Keys/.env` and are never printed, logged or written to reports. `jevseo doctor` reports only whether a key is present.
- The crawler refuses hosts that resolve to private, loopback, link-local or reserved addresses, and re-checks every redirect hop.
- Content fetched from audited sites is treated as data, never as instructions.
- Report a vulnerability privately through GitHub security advisories on this repository rather than a public issue.
