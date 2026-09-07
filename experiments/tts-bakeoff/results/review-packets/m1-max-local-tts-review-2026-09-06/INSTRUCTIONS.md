# Blinded TTS review instructions

Review clips in the randomized order in `scores.csv`. Do not inspect repository
results or the separately held engine key until every score is locked.

Use whole-number scores from 1 (unacceptable) to 5 (excellent):

- **Intelligibility:** every intended word is understandable.
- **Naturalness:** the clip sounds like fluent, human speech rather than an artifact.
- **Cadence:** pacing, pauses, and emphasis fit the prompt.
- **Pronunciation:** names, numbers, dates, currency, acronyms, and quotations are spoken correctly.
- **Accent fit:** the voice fits the stated locale. `es-US` requires a qualified U.S.-Spanish reviewer; do not treat `es-MX` or generic Spanish as exact locale evidence.

Mark `truncation_or_repetition` yes/no and explain any suspected missing tail,
repeated phrase, hallucination, corruption, or scoring uncertainty in
`reviewer_notes`. Scores are human evidence, not legal approval or an engine
selection. Record reviewer qualification and conflict-of-interest attestations
outside this public packet before unblinding.
