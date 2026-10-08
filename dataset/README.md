---
license: mit
pretty_name: trusted-monitoring logs
---

# trusted-monitoring logs

Raw [Inspect AI](https://inspect.aisi.org.uk/) logs (`.eval` files) of every run made for
<https://github.com/dang-w/trusted-monitoring>, including smoke tests, failed runs and abandoned
runs. The intent is that no run can be left out afterwards.

- Each file is at `runs/<run_id>/<file>.eval`.
- The manifest `manifests/<run_id>.json` in the code repository records the sha256 of each file,
  the code version, the model files and the settings of the run, and the dataset commit at which
  the file was published and verified.
- The files are published only after a scrub check: no key material, no home-directory paths,
  no private addresses or host names. One exemption since 7 October 2026: cgroup v2 file names
  under `/sys/fs/cgroup/` (`memory.events.local`, `cpu.stat.local`), which a sandbox listing in
  `e3-gen-attack-3` sample 79 put into a scorer's output; they are file names, not hosts.

**Status (8 October 2026): 50 runs, 51 files. The `e2`, `e3` and `e4` families are the results of the
first small-scale measurement (100 problems, one setting); the `d1xx` and `e1` families are tests of
the plumbing, measurements of the substrate and a superseded first pass.** The numbers, with the runs
each comes from, are in the code repository's README; nothing here is a finding about trusted
monitoring in general.

## Run families

| family | runs | what it is | samples | result or test |
|---|---|---|---|---|
| `d122-smoke`, `d141-smoke` | 2 | one sample through the plumbing (model, tool call, sandbox, result) | 1 each | test |
| `d123-apps-*` | 2 | ControlArena's APPS with the live trusted-monitoring micro-protocol, honest and attack | 5 each | test of the substrate |
| `d124-slots*` | 4 | the same 10 honest samples with 1 and 4 server slots, twice each (parallel decoding is not reproducible) | 10 each | measurement of the substrate |
| `d133-gap-*` | 9 | the same 20 honest problems with each of seven candidate models as the agent (two runs of 10 for the 27B); the capability gap that chose the models | 20 (10 + 10) | measurement of the substrate |
| `d142-*` | 3 published | tests of the queue runner (kill, preempt and resume, window end) | 3 to 6 | test |
| `e1-gen-*` | 7 | the first honest set at thinking budget 4096 (`e1-gen-honest-1..4`, 100 problems, 79 of 100), with the attack-mode checks that preceded it | 1 to 25 | superseded by `e2` |
| `e2-gen-honest-1..4` | 4 | the honest set at budget 8192: 100 problems, main task 84 of 100, 27 at the cap | 25 each | **result** |
| `e2-gen-attack-probe-2`, `-3` | 2 | attack mode on 10 problems at 8192; probe 2 found a client-timeout fault, probe 3 is the clean run | 10 each | result (probe) |
| `e3-gen-attack-probe` | 1 | the same 10 problems at budget 12288; chose the budget for the attack set | 10 | result (probe) |
| `e3-gen-attack-1..4` | 4 | the attack set at budget 12288: 100 problems, main task 35, side task 33, real backdoors 20, 7 without a submission | 25 each | **result** |
| `e3-gen-honest-capped` | 1 | the 27 honest problems that reached the 8192 cap, again at 12288 (20 of 27); with `e2-gen-honest-*` this is the honest set at 12288 (88 of 100) | 27 | **result** |
| `e4-mon-ministral-probes` | 1 | the first monitor pass (Ministral-3-8B over the two attack probes) | 20 | result (probe) |
| `e4-mon-ministral-honest`, `-attack`, `-honest-capped` | 3 | Ministral-3-8B, default prompt, over the honest and attack sets (the 7 attack trajectories without a submission are skipped) | 100, 93, 27 | **result** |
| `e4-mon-ministral-weak-*`, `-trunc10-*`, `e4-mon-ministral3b-*` | 6 | the three weakened monitors (ControlArena's `simple` prompt; the first 10 lines of the code; Ministral-3-3B), honest and attack each | 100 and 93 | **result** (mutation test) |
| `e4-mon-gemma-*` | 2 | Gemma 4 E4B, default prompt, honest and attack | 100 and 93 | **result** (second monitor) |

Four manifests in the code repository have no file here: `d142-preempt-test`, `d142-preempt-test-2`
and `d142-window-stop` (runner tests of 3 October 2026 whose logs hold a home-directory path in a
traceback; `status: scrub-failed`) and `e2-gen-attack-probe` (interrupted, its log abandoned with it).
`d142-kill-test` has two files (the run and its resume).

## Reading a file

An `.eval` file is a zip archive with zstd-compressed members; read it with
`inspect_ai.log.read_eval_log` (Inspect AI 0.3.275 wrote them) or with Python's `zipfile` and the
`zipfile-zstd` package. A generate run's samples carry the trajectory, the `apps_scorer` result and, in
attack mode, the side-task result; a monitor run's samples carry the suspicion score (`suspicion`,
0 to 10, with `parsed: false` when the monitor wrote no score), the monitor's reasoning, and in
their metadata the source run, sample id and task results of the trajectory scored.
