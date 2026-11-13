# Contributing

Thanks for helping. The most useful things, in order:

1. **Real-world results.** Run it on your footage, follow `docs/EVALUATION.md`, open an issue with your numbers (even bad ones).
2. **Venue configs.** Add a tested YAML under `configs/` for a new setting (platform, temple queue, airport security, stadium gate).
3. **Roadmap items** listed in the README. Comment on an issue first so work is not duplicated.

## Ground rules
- Keep the metrics engine free of camera and model code: it must stay unit-testable.
- Every new metric needs a test with a hand-calculated expected value.
- Never add anything that identifies individuals (faces, re-ID, per-person storage). Such PRs will be declined.
- Do not claim accuracy numbers you did not measure.

```bash
pip install -e ".[dev]"
pytest
```
