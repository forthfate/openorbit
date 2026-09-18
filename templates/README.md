# OpenOrbit template packages

Templates can be distributed as ordinary directories. Copy a runner package to
`<app-data>/runner-templates/` to make it available, or copy a Quick Start
package to `<app-data>/quick-starts/`. App data is shown in **Settings** and
can also be selected with `ORBIT_APP_DATA`.

A package keeps its `README.md`, `LICENSE` (or `LICENSE.md`), and any other
supporting files beside its executable entrypoint. Only the declared Python
entrypoint is loaded by OpenOrbit.

## Runner template

```text
my-runner/
  template.json
  runner.py
  README.md
  LICENSE
```

`template.json` contains `id`, `name`, `description`, and optionally
`entrypoint` (default: `runner.py`). IDs must be unique.

## Quick Start

```text
my-quick-start/
  manifest.json
  runner.py
  README.md
  LICENSE
```

`manifest.json` uses the existing Quick Start schema. Set
`assets.runner.source_file` to `runner.py` instead of embedding the runner
source in JSON. A package can also be imported programmatically with
`ConsoleStore.import_quick_start_package(path)`.

The former flat `*.py` + `*.json` runner-template files and flat Quick Start
manifests remain readable for compatibility, but new templates created in the
application use the directory format.

`runner-template.example/` and `quick-start.example/` are minimal, portable
starting points. They are intentionally outside the shipped catalog directories
so they are not presented as production-ready built-in choices.
