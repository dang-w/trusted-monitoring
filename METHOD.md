# Method

**This method has run once, at small scale (100 problems, one setting, 8 October 2026).** The steps below state
what ran, with the settings; the results are in [README.md](README.md). When a part changes, this file changes
with it, and the git history keeps the earlier version (the first version was a plan).

## Setting

- Substrate: [Inspect AI](https://inspect.aisi.org.uk/) for the evaluation harness and
  [ControlArena](https://github.com/UKGovernmentBEIS/control-arena) for the settings, each with a
  main task and a side task.
- Models: open-weight models served locally. Decided on 2026-10-02 from a measured capability gap
  on 20 honest main tasks (manifests `d133-gap-*`): the untrusted model is Qwen3.8-27B (15 of 20
  correct) and the trusted monitor is Ministral-3-8B (7 of 20); Gemma 4 E4B (13 of 20) is a second
  monitor for comparison, and Ministral-3-3B the weaker model of step 4. Seven candidates were
  measured; the numbers are in the manifests and the logs.
- Sandbox: the untrusted model's tool calls run in containers with networking off.
- Sampling: temperature 0, seed 1, one sample at a time. Parallel decoding on the server is not
  reproducible (manifests `d124-slots*`); sequential decoding reproduces a trajectory token for token
  across runs and days, as long as it does not reach a cap.

## Steps

1. **Generate, then monitor.** The untrusted model produces trajectories first, in an honest mode
   and in an attack mode (`control/apps/task.py@apps_generate_honest`, `@apps_generate_attack`). What ran:
   honest at thinking budget 8192 with 12288 output tokens, 1800 s and 8 messages per sample
   (`e2-gen-honest-1..4`); the 27 honest ids that reached that cap again at budget 12288 with 16384 output
   tokens and 2700 s (`e3-gen-honest-capped`); attack at the same 12288 setting (`e3-gen-attack-1..4`).
   The honest set at 12288 is the first run with the 27 ids replaced by the second: a trajectory under the
   cap is unchanged by a larger cap. The monitor scores the stored trajectories in a second, separate
   phase (`tm/monitor.py@apps_monitor`): it reads the logs of generate runs, shows the monitor the task
   and the submitted code only, and writes one Inspect log per pass; the monitor's sampling is pinned
   (temperature 0, seed 1, 4096 output tokens). The two phases never need both models in memory at the
   same time. A trajectory with no submission is skipped and listed in the pass's log.
2. **Catch rate against false-positive rate.** The suspicion threshold is set on honest
   trajectories for a chosen false-positive rate. The catch rate is the fraction of attack
   trajectories that score above that threshold (`python -m tm.catch_rate`; its conventions for
   ties, unparsed replies, the bootstrap and `--supersede` are in its docstring). Scores are integers
   0 to 10, so the realised false-positive rate is reported next to the target, and a monitor whose
   honest scores are nearly all 0 has one usable threshold.
3. **Known positives.** The attack trajectories whose main task passed and whose side task
   succeeded (a working backdoor) go through the same monitor pipeline, and their scores are listed. If
   the pipeline does not flag them, the pipeline is broken, and a low catch rate from it means nothing.
   What ran: 20 working backdoors of 100 attack trajectories; the scores are in the README.
4. **Monitor mutation testing.** Deliberately weakened versions of the monitor run on the same
   trajectories: ControlArena's `simple` prompt in place of its default, the first 10 lines of the code
   only, and Ministral-3-3B in place of Ministral-3-8B. If the measured catch rate does not get worse for
   a weakened monitor, the measurement does not respond to monitor quality and cannot be trusted.

## Reporting rules

- Every run has a manifest in this repository, including runs that fail or are abandoned.
- Each reported number names the command and the logs it comes from.
- Sample counts are stated next to every rate, with a bootstrap interval for the catch rate.
- A rerun of some ids supersedes the earlier scores of those ids only when said so (`--supersede`), and
  both runs stay in the record.
