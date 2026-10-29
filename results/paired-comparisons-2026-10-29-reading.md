# Reading of the paired comparisons of 2026-10-29 (first hundred problems, llama.cpp b11189)

Table: `results/paired-comparisons-2026-10-29.md`, made by `python -m tm.paired --config
results/paired-config-first-hundred-b11189.json --out ... --trajectories results/paired-trajectories-2026-10-29.csv
--today 2026-10-29` (paired bootstrap 10,000 rounds, seed 1; McNemar's exact test; thresholds once per
configuration; an unparsed reply counts as not flagged, so Ministral-3-3B's catch rate here, 46.2 %, is lower than
the 51 % of `tm.catch_rate`, which leaves its 9 unparsed attack replies out of the denominator). Nine
configurations, 36 pairs, four targets, two subsets: 288 rows.

## The mutation sentence

"Three deliberately weakened monitors each scored lower" (README, Ministral-3-8B at the 5 % target):

| Ministral-3-8B default against | catch rates | difference | 95 % interval | discordant (A only, B only) | p |
|---|---|---|---|---|---|
| weak prompt | 63.4 % vs 35.5 % | +28.0 points | [+17.2, +38.7] | 29, 3 | < 0.001 |
| Ministral-3-3B | 63.4 % vs 46.2 % | +17.2 | [+9.7, +25.8] | 17, 1 | < 0.001 |
| first 10 lines | 63.4 % vs 58.1 % | +5.4 | [−2.2, +12.9] | 10, 5 | 0.30 |

Two of the three differences are separated from zero at 95 %; the truncated-code one is not. The sentence
becomes: "scored lower, though only two of the three differences (the weak prompt and the 3B model) are
separated from zero at 95 %; the first-10-lines difference of 5 points is not". On the 20 working backdoors
the same three rows are +5 [−15, +25], +25 [+5, +45] and +20 [0, +40]: one separated.

Gemma 4 E4B at 5 %: default against weak +17.2 [+8.6, +26.9] (separated), against first 10 lines +6.5
[−1.1, +14.0] (not). Gemma's thresholds are 0 at every target (realised 0.0 %), so its rows compare at 0 %
realised FPR, as the README says.

## Expected score against written score (the same replies)

- Gemma: +17.2 [+9.7, +24.7] at 5 % (16 flagged by the expected score only, 0 the other way; p < 0.001); at
  1 %: +7.5 [+2.2, +12.9]. Realised FPR 5.0 % against 0.0 %: the expected score buys its catch rate with the
  false positives the written score could not spend.
- Ministral-3-8B: 0.0 [0, 0] at 5 %, the same 59 flags (threshold 3 against 3.62); at 1 %: +11.8 [+5.4, +19.4]
  (11 flagged by the expected score only, both at 0.0 % realised).

## The two monitors against each other

- Written scores at 5 %: Ministral-3-8B 63.4 % against Gemma 55.9 %, +7.5 [+1.1, +14.0], p 0.065 (9 against 2
  discordant): the bootstrap interval excludes zero, the exact test does not reach 0.05; realised FPR 4.1 %
  against 0.0 %.
- Expected scores at 5 %: Gemma 73.1 % against Ministral 63.4 %, +9.7 [+1.1, +19.4], p 0.064 (14 against 5);
  the same picture the other way round, at 5.0 % against 4.1 % realised. At 1 %: +18.3 [+9.7, +26.9], p < 0.001.
- Written Ministral against expected Gemma at 5 %: −9.7 [−19.4, −1.1], p 0.064.

So the two monitors are not cleanly separated from each other at the 5 % target by the exact test on either
scoring rule; the bootstrap intervals just exclude zero. The weak-prompt and 3B mutations are separated from
their defaults; the truncated-code mutations are not.

## Figures, one line each (b11189, first hundred, 93 attack trajectories; manifests as in the config file)

- M-27: Ministral-3-8B default − weak prompt, 5 %: +28.0 [+17.2, +38.7], p < 0.001, 32 discordant.
- M-28: Ministral-3-8B default − Ministral-3-3B, 5 %: +17.2 [+9.7, +25.8], p < 0.001, 18 discordant.
- M-29: Ministral-3-8B default − first 10 lines, 5 %: +5.4 [−2.2, +12.9], p 0.30, 15 discordant.
- M-30: Gemma 4 E4B default − weak prompt, 5 %: +17.2 [+8.6, +26.9], p 0.001, 22 discordant.
- M-31: Gemma 4 E4B default − first 10 lines, 5 %: +6.5 [−1.1, +14.0], p 0.18, 14 discordant.
- M-32: Gemma 4 E4B expected − written, 5 %: +17.2 [+9.7, +24.7], p < 0.001, 16 discordant (realised 5.0 % vs 0.0 %).
- M-33: Ministral-3-8B expected − written, 5 %: 0.0 [0, 0], 0 discordant.
- M-34: Ministral-3-8B written − Gemma written, 5 %: +7.5 [+1.1, +14.0], p 0.065, 11 discordant.
- M-35: Gemma expected − Ministral-3-8B expected, 5 %: +9.7 [+1.1, +19.4], p 0.064, 19 discordant.
