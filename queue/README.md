# Queue

One YAML file per run. `scripts/run-queue run` takes the oldest file in `pending/` that fits
before its deadline, moves it to `running/`, runs it, and moves it to `done/` or `failed/`.
An interrupted run goes back to `pending/` with a `resume` marker and continues later with
`inspect eval-retry` on its partial log. The file name is the run id.

    estimated_minutes: 40        # required: D12 timing per trajectory times the sample count
    note: APPS honest, 20 samples
    inspect:
      - eval
      - control/apps/task.py@apps_tm_honest
      - --limit
      - "20"
      - --max-samples
      - "1"                      # one sample at a time: reproducible (D12.4)
      - --time-limit
      - "1800"                   # per sample: 8192 thinking tokens take about 630 s alone (E2). The HTTP
                                 # client timeout (1500 s) is set in control/apps/task.py, not here.
      - --message-limit
      - "8"
      - --no-fail-on-error       # one sample error must not fail the whole run (and the night)

Estimates and time limits when the always-on small router is answering chats on the same GPU (measured
2026-10-08, `a3-gen-attack-probe-small` against `e3-gen-attack-probe`, one 200-token chat in flight without
pause): the untrusted model's sample time grows by a factor of **1.42** (149 to 211 min for the same 10
attack samples) and the trajectories are unchanged token for token. Use the factor on `estimated_minutes`
for any run that may share the box with chat, and on the per-sample `--time-limit`: an attack sample that
needs a second call takes 2,150 to 2,280 s alone (E3), about 3,100 s under this load, so attack generation at
budget 12288 beside a busy notepad needs `--time-limit 3600`, not 2700 (the longest A3 sample took 2,475 s
of its 2,700). An idle small router costs nothing measurable.

`scripts/run-queue check queue/pending/<id>.yaml` validates a spec. The runner is described in
`tm/queue.py`; the machine side (`mini-mode`, the nightly window, the dead-man check) lives in the
dotfiles repository of the box.
