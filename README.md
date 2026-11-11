# utom-core

Prototype implementation of **UTOM Core v0.1** and of the **UTOM Geometry v0.1**
interpreter.

UTOM (Universal Technical Object Model) is an open, extensible data model to
define, compose and reconstruct technical objects (mechanical parts, buildings,
electronics, industrial machines) from parametric definitions. The UTOM file
contains the recipe needed to regenerate the geometry; pre-built files such as
STEP or IFC are derived outputs only, never the source of truth.

**Status: prototype, under active design. This is not a published
specification and nothing here claims normative compliance.**

## Contents

- `utom_core.py` — identity (UUIDv7 URNs), canonical JSON serialization with
  SHA-256 digests, typed properties with QUDT units and mandatory provenance,
  immutable versions (semver + digest), linked/embedded/hybrid dependencies
  verified by digest, non-destructive overlays. Includes 8 acceptance tests.
- `utom_geometry.py` — declarative geometry recipe interpreter: typed JSON
  expression trees (no eval), deterministic topological execution, change
  propagation (only affected nodes recompute), named datums instead of
  face/edge indices, mock backend with analytical metrics. Includes 16
  acceptance tests.
- `utom_build123d.py` — real build123d backend for the Geometry lot 1 catalog
  (soft dependency: core and geometry never import it). Analytic golden tests
  (exact volumes, bounding boxes) and the M8x30 screw demonstrator (ISO 4017).
  Includes 13 acceptance tests; requires `pip install build123d`.

## Usage

Run the acceptance tests (plain commands, no dependencies):

    python3 utom_core.py        # expected: 8 PASS lines
    python3 utom_geometry.py    # expected: 16 PASS lines

Optional real-geometry backend:

    pip install build123d
    python3 utom_build123d.py   # expected: 13 PASS lines

## Design rules

- Physical values always carry a QUDT unit; bare numbers are rejected.
- Every value carries provenance; published versions are immutable.
- Geometry is regenerated from declarative recipes; no arbitrary embedded code.
- Standards and dictionaries (ISO, IEC, ECLASS, bSDD, QUDT, IFC, STEP) are
  referenced and linked, never duplicated or replaced.

## License

- Code: Apache-2.0 (see LICENSE and NOTICE).
- Specification and schemas: CC-BY-4.0 (documents maintained outside this
  repository for now).
- Library data (future): CC0 or CC-BY-4.0. 
Never GPL for data.
