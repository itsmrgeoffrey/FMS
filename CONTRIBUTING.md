# Contributing to FMS

Thanks for your interest in improving open-source AML/compliance tooling.

## High-value contributions

- **Database adapters** — new read-only adapters (PostgreSQL, Oracle, etc.) implementing `backend/adapters/base.py`.
- **Detection signals** — additional, well-documented risk components in `backend/services/analyzer.py`, ideally with tests.
- **Jurisdiction thresholds** — CTR/SAR-equivalent thresholds for additional currencies/regulators, with a source citation.
- **Documentation** — deployment guides, schema-mapping examples.

## Development setup

```bash
pip install -r requirements.txt
python -m pytest            # the deterministic risk engine is fully unit-tested — keep it that way
cd frontend && npm install && npm run build
```

## Guidelines

- The risk engine must stay **deterministic and explainable** — every signal produces a human-readable reason. Please don't move scoring decisions into the LLM.
- Add or update tests in `tests/` for any change to scoring or CTR/SAR logic.
- Never commit secrets or real transaction data. `.env`, `bank_config.yaml`, and `fms.db` are git-ignored — keep them that way.
- Open an issue to discuss substantial changes before a large PR.

## Reporting security issues

See [SECURITY.md](SECURITY.md) — do not open public issues for vulnerabilities.
