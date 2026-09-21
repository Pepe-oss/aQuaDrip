# aQuaDrip

**[中文](README.md) | English**

An intelligent drip irrigation design and fertigation analysis platform built on **QGIS + WNTR**.

aQuaDrip couples a GIS front end for network digitizing and agronomy-driven design with a
hydraulic simulation core ([wdrip-core](wdrip-core/)) that wraps WNTR/EPANET for drip-specific
modeling: per-emitter discharge laws, pressure-compensating (PC) and non-PC emitters in mixed
networks, valve-gated rotation shifts, and irrigation uniformity metrics.

## Features

- **Project management** — standard GeoPackage projects (fields / pipes / pumps / valves /
  nodes / observation points) with *Save As* that carries data, simulation history and the
  QGIS project file to a new location in one step.
- **Agronomy-driven design** — generate laterals from field polygons using planting pattern,
  row spacing and emitter spacing; place single laterals manually (segment-by-segment on
  interrupted fields) to reproduce as-built farm layouts.
- **Topology by geometry** — pipes are connected by geometric intersection with hierarchy
  rules (mainline → submain → lateral); crossing nodes, trimming and direction fixing are
  built in.
- **Hydraulic simulation** — three-tier engine strategy (EPANET toolkit → WNTR simulator →
  in-house fixed-point iterative solver) with automatic detection and fault fallback;
  pressure-dependent demand (PDD); emitter discharge q = k·P^x with per-node exponents;
  closed valves modeled with strict shutoff semantics; DEM-based elevations.
- **Irrigation quality metrics** — Christiansen's CU, distribution uniformity (DU) and
  emission uniformity (EU) per ASAE EP405.1.
- **Model calibration** — observation-point based, hf²-weighted roughness adjustment with
  joint source-head calibration for supply-limited networks.
- **Management zones & rotation** — single-valve or multi-valve zones (manual custom labels
  or flow-based auto grouping); rotation scheduling simulates each valve group as one shift.
- **Results & export** — thematic visualization of any historical run; export node results
  (pressure + emitter flow) to GPKG / GeoJSON / Shapefile; pipe pressure-rating check;
  EPANET INP export.
- **Bilingual UI** — Simplified Chinese and English in a single package, following the QGIS
  language by default.

## Installation

### Requirements

| Dependency | Notes |
|---|---|
| QGIS ≥ 3.28 | LTR or newer |
| Python package `wntr` | hydraulic engine (QGIS ships numpy/pandas; only wntr needs to be installed) |

### Option 1: Install from ZIP (recommended)

1. **Download** the latest `aquadrip-<version>.zip` from the GitHub *Releases* page
   (the ZIP bundles the `wdrip` core library and translation files — nothing else to fetch).
2. **Install**: QGIS menu `Plugins → Manage and Install Plugins → Install from ZIP`,
   pick the downloaded file → `Install Plugin`.
3. **Add the simulation dependency** — install wntr into the Python environment shipped
   with QGIS:

   | Platform | Command |
   |---|---|
   | macOS | `/Applications/QGIS.app/Contents/MacOS/bin/python3 -m pip install wntr` |
   | Windows (OSGeo4W Shell) | `python-o4w -m pip install wntr` |
   | Linux | `python3 -m pip install wntr --user` (use the interpreter QGIS runs on) |

4. **Enable** the plugin in the manager; the aQuaDrip toolbar appears when installed.

> Without wntr the plugin still loads, but simulation features will report the missing
> dependency.

### Option 2: From source (for development)

```bash
git clone https://github.com/Pepe-oss/aQuaDrip.git
```

Symlink the repository's `aquadrip-plugin` directory into the QGIS plugin folder
(the plugin auto-detects the sibling `wdrip-core`, and code changes take effect after
restarting QGIS):

| Platform | QGIS plugin directory (default profile) |
|---|---|
| macOS | `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins` |
| Windows | `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins` |
| Linux | `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins` |

```bash
# macOS example
ln -s "$(pwd)/aquadrip-plugin" \
  "$HOME/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/aquadrip"
```

Install wntr as in Option 1, step 3.

### Build a release ZIP

From the repository root (output goes to `dist/`):

```bash
python scripts/make_zip.py
```

## UI Language

The plugin ships with **Simplified Chinese** and **English** in a single package:

- Follows the QGIS UI language by default.
- Switch manually via `Plugins → aQuaDrip → 语言 Language`, then **restart QGIS**.

Translation sources live in `aquadrip-plugin/i18n/` (`.ts` sources, `.qm` compiled — both
are distributed). To update translations:

```bash
# 1. Re-extract strings after changing UI text
python -m PyQt5.pylupdate_main <plugin py files...> -ts aquadrip-plugin/i18n/aquadrip_en_US.ts
# 2. Edit the <translation> entries in the .ts file
# 3. Compile
lrelease aquadrip-plugin/i18n/aquadrip_en_US.ts
```

## Project Structure

```
aQuaDrip/
├── wdrip-core/          # Core Python library (usable standalone, without QGIS)
│   ├── wdrip/
│   │   ├── network/     # Data model (DripNetwork, emitters, links)
│   │   ├── topology/    # Topology engine
│   │   ├── builder/     # Network builders
│   │   ├── equipment/   # Equipment system
│   │   ├── simulation/  # WNTR simulation wrapper (3-tier engine strategy)
│   │   ├── analysis/    # Result analysis (CU/DU/EU, …)
│   │   ├── io/          # Import / export
│   │   ├── emitter_db/  # Emitter parameter database
│   │   ├── optimizer/   # Optimizer (V3+)
│   │   └── settings/    # Configuration management
│   └── setup.py
├── aquadrip-plugin/     # QGIS plugin
├── docs/                # Documentation
└── examples/            # Example data
```

## Status

- Version: 0.1.x — core workflows (design → simulation → calibration → rotation) functional.
- See `DEVELOPMENT_PLAN.md` for the roadmap.

## License

See the repository for license information.
