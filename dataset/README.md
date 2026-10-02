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
  no private addresses or host names.

**Status: infrastructure in progress. There are no findings yet.** The runs published so far are
tests of the plumbing and measurements of the substrate, not results about monitoring.

An `.eval` file is a zip archive with zstd-compressed members; read it with
`inspect_ai.log.read_eval_log` or with Python's `zipfile` and the `zipfile-zstd` package.
