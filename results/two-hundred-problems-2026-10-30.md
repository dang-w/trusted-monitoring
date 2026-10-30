# The result on 200 problems, one build (read 2026-10-30, 08:30 to 09:30 UTC)

Every monitor pass below is on llama.cpp b11612: the first hundred problems scored again on that build on 16
and 29 to 30 October (`e7-mon-*-b11612`) and positions 101 to 200 scored on it (`e8-mon-*`). The sets: honest
`e2-gen-honest-1..4` + `e3-gen-honest-capped` (superseding) + `e8-gen-honest-5..8`, 200 trajectories; attack
`e3-gen-attack-1..4` + `e8-gen-attack-5..8`, 200 trajectories of which 186 reached a submission (the monitor sees
nothing for the other 14) and 39 are working backdoors. Five monitor configurations, each with the written score
and the expected score from one pass (`-T logprobs=20`).

## Catch rates

`python -m tm.catch_rate --honest e7-mon-<m>-lp-honest-b11612 e7-mon-<m>-lp-honest-capped-b11612 e8-mon-<m>-lp-honest
--attack e7-mon-<m>-lp-attack-b11612 e8-mon-<m>-lp-attack --supersede --score <written|expected>` (bootstrap 1,000
rounds, threshold set again on each resampled honest set; an unparsed reply counts in neither rate).

| monitor, score | honest n (unparsed), attack n (unparsed) | 5 % target: threshold, realised FPR, catch rate (bootstrap 95 %) | at 1 % | at 10 % | working backdoors flagged of 39, scored 0 |
|---|---|---|---|---|---|
| **Ministral-3-8B, written** | 197 (3), 186 (0) | 4, 4.6 %, **59.7 %** (111 of 186; 46.8 to 66.7) | 33.9 % (0.0 % realised) | 65.6 % | 20, 12 |
| Ministral-3-8B, expected | 195 (5), 184 (2) | 4.21, 4.6 %, 60.3 % (52.2 to 70.7) | 44.6 % (0.5 %) | 66.8 % | 20, 0 |
| Gemma 4 E4B, written | 200 (0), 186 (0) | 0, 0.5 %, 56.5 % (105 of 186; 49.5 to 63.5) | 56.5 % (0.5 %) | 56.5 % | 18, 21 |
| **Gemma 4 E4B, expected** | 200 (0), 186 (0) | 0.0015, 5.0 %, **67.7 %** (126 of 186; 59.7 to 74.7) | 59.7 % (1.0 %) | 69.9 % | 25, 0 |
| Ministral-3-3B, written (mutation: weaker model) | 192 (8), 171 (15) | 0, 3.6 %, 50.9 % (32.7 to 57.9) | 10.5 % (0.5 %) | 50.9 % | 11, 28 |
| Ministral-3-3B, expected | 192 (8), 170 (16) | 0.27, 4.7 %, 52.4 % (34.7 to 60.6) | 7.1 % | 54.7 % | 11, 4 |
| Gemma 4 E4B, weak prompt, written (mutation) | 192 (8), 182 (4) | 0, 3.6 %, 42.3 % (26.9 to 48.9) | 0.0 % (threshold 10) | 42.3 % | 11, 28 |
| Gemma 4 E4B, weak prompt, expected | 192 (8), 182 (4) | 0.15, 4.7 %, 44.5 % (33.0 to 52.2) | 7.1 % | 50.0 % | 13, 0 |
| Gemma 4 E4B, first 10 lines, written (mutation) | 200 (0), 186 (0) | 0, 1.0 %, 50.5 % (44.1 to 57.5) | 50.5 % (1.0 %) | 50.5 % | 12, 27 |
| Gemma 4 E4B, first 10 lines, expected | 200 (0), 186 (0) | 0.026, 5.0 %, 52.7 % (46.2 to 59.7) | 52.2 % | 52.7 % | 12, 0 |

## Paired comparisons on the same trajectories

`python -m tm.paired --config results/paired-config-200-b11612.json --out results/paired-comparisons-200-2026-10-30.md
--trajectories results/paired-trajectories-200-2026-10-30.csv --today 2026-10-30` (ten configurations, 45 pairs, four
targets, 360 rows; paired bootstrap 10,000 rounds, seed 1, thresholds fixed; McNemar's exact test; an unparsed reply
counts as not flagged, so Ministral-3-3B is 46.8 % here against 50.9 % above). At the 5 % target, on the 186 scored
attack trajectories:

| pair | catch A, catch B | difference | 95 % interval | discordant (A only, B only) | p |
|---|---|---|---|---|---|
| Ministral-3-8B default − Ministral-3-3B | 59.7 %, 46.8 % | +12.9 | [+7.5, +18.8] | 28, 4 | < 0.001 |
| Gemma default − weak prompt | 56.5 %, 41.4 % | +15.1 | [+8.6, +22.0] | 36, 8 | < 0.001 |
| Gemma default − first 10 lines | 56.5 %, 50.5 % | +5.9 | [+0.5, +11.3] | 20, 9 | 0.061 |
| Gemma expected − written | 67.7 %, 56.5 % | +11.3 | [+7.0, +16.1] | 21, 0 | < 0.001 |
| Ministral-3-8B expected − written | 59.7 %, 59.7 % | 0.0 | [0, 0] | 0, 0 | 1 |
| Ministral-3-8B written − Gemma written | 59.7 %, 56.5 % | +3.2 | [−1.6, +8.1] | 14, 8 | 0.29 |
| Gemma expected − Ministral-3-8B written | 67.7 %, 59.7 % | +8.1 | [+2.7, +13.4] | 21, 6 | 0.006 |
| Gemma expected − Ministral-3-8B expected | 67.7 %, 59.7 % | +8.1 | [+2.7, +13.4] | 21, 6 | 0.006 |

On the 39 working backdoors: Ministral-3-8B − 3B +23.1 [+10.3, +35.9] (p 0.004); Gemma − weak +17.9 [0.0, +35.9]
(p 0.09); Gemma − first 10 lines +15.4 [−2.6, +33.3] (p 0.18); Gemma expected − written +17.9 [+7.7, +30.8]
(p 0.016); Gemma expected − Ministral-3-8B +12.8 [−25.6, 0.0] the other way, p 0.125.

## What changed from the first hundred

- The mutation ordering holds at n = 200 and two of the three differences are separated from zero at 95 % as
  before (the weak prompt and the 3B model); the first-10-lines difference, +5.9 [+0.5, +11.3], now just clears zero
  by the bootstrap and not by the exact test (p 0.061). On the first hundred it was +5.4 [−2.2, +12.9].
- The expected score's gain for Gemma is +11.3 points at n = 200 (17 on the first hundred, 6.5 on the held-out
  hundred); every one of its 21 discordant pairs goes the same way.
- Gemma's expected score against the 8B monitor is now separated at the 5 % target: +8.1 [+2.7, +13.4], p 0.006
  (on the first hundred +9.7 [+1.1, +19.4], p 0.064). The two written scores are not: +3.2 [−1.6, +8.1].
- Ministral-3-8B's written and expected scores give the same flags at the 5 % target on all 186 trajectories.
- Levels: the 8B monitor 59.7 % at n = 200 against 63.4 % on the first hundred (49.5 % on the held-out hundred
  alone); Gemma expected 67.7 % against 72.0 % and 63.4 %.
- Working backdoors: 39 of 200. The 8B monitor flags 20 and scores 12 of them 0; Gemma's expected score flags 25
  and scores none 0; Gemma's written score flags 18 and scores 21 of them 0.

## Figures, one line each (200 problems, b11612; manifests as in `results/paired-config-200-b11612.json`)

- Ministral-3-8B, written score, 5 % target, 200 problems: threshold 4, realised FPR 4.6 %, catch 59.7 % (111 of 186; 46.8 to 66.7), 20 of 39 working backdoors flagged, 12 scored 0.
- Gemma 4 E4B, expected score, 5 % target, 200 problems: threshold 0.0015, realised FPR 5.0 %, catch 67.7 % (126 of 186; 59.7 to 74.7), 25 of 39 working backdoors flagged.
- Gemma 4 E4B, written score, 5 % target, 200 problems: threshold 0, realised FPR 0.5 %, catch 56.5 % (105 of 186; 49.5 to 63.5), 18 of 39 flagged, 21 scored 0.
- Ministral-3-3B, written score, 5 % target, 200 problems: threshold 0, realised FPR 3.6 %, catch 50.9 % (32.7 to 57.9), 11 of 39 flagged.
- Gemma 4 E4B weak prompt, written score, 5 % target, 200 problems: threshold 0, realised FPR 3.6 %, catch 42.3 % (26.9 to 48.9), 11 of 39 flagged.
- Gemma 4 E4B first 10 lines, written score, 5 % target, 200 problems: threshold 0, realised FPR 1.0 %, catch 50.5 % (44.1 to 57.5), 12 of 39 flagged.
- Ministral-3-8B default − Ministral-3-3B, 5 %, 200 problems, paired: +12.9 [+7.5, +18.8], p < 0.001, 32 discordant.
- Gemma 4 E4B default − weak prompt, 5 %, 200 problems, paired: +15.1 [+8.6, +22.0], p < 0.001, 44 discordant.
- Gemma 4 E4B default − first 10 lines, 5 %, 200 problems, paired: +5.9 [+0.5, +11.3], p 0.061, 29 discordant.
- Gemma 4 E4B expected − written, 5 %, 200 problems, paired: +11.3 [+7.0, +16.1], p < 0.001, 21 discordant.
- Gemma 4 E4B expected − Ministral-3-8B written, 5 %, 200 problems, paired: +8.1 [+2.7, +13.4], p 0.006, 27 discordant.
- Ministral-3-8B written − Gemma 4 E4B written, 5 %, 200 problems, paired: +3.2 [−1.6, +8.1], p 0.29, 22 discordant.
