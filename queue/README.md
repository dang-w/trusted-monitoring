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
      - --time-limit
      - "1200"                   # per sample; one sample looped at the token limit for 1033 s (D12.4)

`scripts/run-queue check queue/pending/<id>.yaml` validates a spec. The runner is described in
`tm/queue.py`; the machine side (`mini-mode`, the nightly window, the dead-man check) lives in the
dotfiles repository of the box.
