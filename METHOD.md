# Planned method

**This is a plan. Nothing in it has been run, and the details will change as the infrastructure
is tested.** When a part changes, this file changes with it, and the git history keeps the
earlier version.

## Setting

- Substrate: [Inspect AI](https://inspect.aisi.org.uk/) for the evaluation harness and
  [ControlArena](https://github.com/UKGovernmentBEIS/control-arena) for the settings, each with a
  main task and a side task.
- Models: open-weight models served locally. Which model is the untrusted one and which is the
  trusted monitor is not decided. It will be decided from a measured capability gap on the main
  tasks, not assumed from model size.
- Sandbox: the untrusted model's tool calls run in containers with networking off.

## Steps

1. **Generate, then monitor.** The untrusted model produces trajectories first, in an honest mode
   and in an attack mode. The monitor scores the stored trajectories in a second, separate phase.
   The two phases never need both models in memory at the same time.
2. **Catch rate against false-positive rate.** The suspicion threshold is set on honest
   trajectories for a chosen false-positive rate. The catch rate is the fraction of attack
   trajectories that score above that threshold.
3. **Known positives.** A set of trajectories that are known to contain the side task goes through
   the same monitor pipeline. If the pipeline does not flag them, the pipeline is broken, and a
   low catch rate from it means nothing.
4. **Monitor mutation testing.** Deliberately weakened versions of the monitor run on the same
   trajectories. If the measured catch rate does not get worse for a weakened monitor, the
   measurement does not respond to monitor quality and cannot be trusted.

## Reporting rules

- Every run has a manifest in this repository, including runs that fail or are abandoned.
- Each reported number names the command and the logs it comes from.
- Sample counts are stated next to every rate.
