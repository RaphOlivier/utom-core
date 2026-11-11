#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
utom_build123d.py — UTOM Geometry v0.1 : backend réel build123d (prototype).

Statut : proposition de travail, NON publié. La suite de tests ci-dessous
(golden tests à métriques analytiques + démonstrateur vis M8×30) est la porte
d'acceptation.

    python3 utom_build123d.py    # exécute les tests d'acceptation
                                 (nécessite : pip install build123d)

Périmètre (étape 1) : catalogue lot 1 de la spécification Geometry v0.1
derrière le contrat backend (§5.1) : execute/capabilities/version, repères
nommés (descripteurs position/normale), sélection d'arêtes par repère plan
(pour chamfer/fillet/drill), démonstrateur vis M8×30 (ISO 4017).

Conventions géométriques v0.1 :
  - primitives posées sur Z=0, centrées en X/Y ;
  - repères : {"kind": "axis"|"plane"|"point", "origin": [x,y,z],
    "direction"/"normal": [dx,dy,dz]} ;
  - drill pénètre à l'opposé de la normale du repère plan cible.

Dépendances : build123d (backend), utom_geometry (interpréteur).
Licence : Apache-2.0 (décision du 2026-11-10).
"""

from __future__ import annotations

import math
import sys
from importlib.metadata import version as _pkg_version

from build123d import (
    Align,
    Box,
    Circle,
    Compound,
    Cylinder,
    Polygon,
    Pos,
    RegularPolygon,
    chamfer,
    extrude,
    fillet,
)

from utom_geometry import MMQ, QUDT, UtomError, execute_recipe

TOL = 1e-6


def _b3d_version() -> str:
    try:
        return _pkg_version("build123d")
    except Exception:
        return "unknown"


def _plane(origin, normal):
    return {"kind": "plane", "origin": [float(origin[0]), float(origin[1]), float(origin[2])],
            "normal": [float(normal[0]), float(normal[1]), float(normal[2])]}


def _axis(origin, direction=(0.0, 0.0, 1.0)):
    return {"kind": "axis", "origin": [float(origin[0]), float(origin[1]), float(origin[2])],
            "direction": [float(direction[0]), float(direction[1]), float(direction[2])]}


def _point(origin):
    return {"kind": "point", "origin": [float(origin[0]), float(origin[1]), float(origin[2])]}


def _shift_datum(d, tx, ty, tz):
    d = dict(d)
    o = d.get("origin")
    if o:
        d["origin"] = [o[0] + tx, o[1] + ty, o[2] + tz]
    return d


def _unsupported(msg: str):
    raise UtomError("UTOM-GEO-013", msg)


def _edges_in_plane(shape, z: float):
    """Arêtes entièrement portées par le plan horizontal z (repère cible)."""
    out = []
    for e in shape.edges():
        bb = e.bounding_box()
        if abs(bb.min.Z - z) < TOL and abs(bb.max.Z - z) < TOL:
            out.append(e)
    if not out:
        _unsupported(f"aucune arête sur le plan cible (z={z})")
    return out


class Build123dBackend:
    """Backend réel build123d pour le lot 1 d'UTOM Geometry v0.1."""

    def __init__(self):
        self.calls = []

    def version(self) -> str:
        return "build123d/" + _b3d_version()

    def capabilities(self):
        return ["box", "cylinder", "hexPrism", "circle2d", "polygon2d", "extrude",
                "union", "subtract", "intersect", "chamfer", "fillet", "drill",
                "patternLinear", "transform", "datumPlane"]

    def execute(self, op, params, inputs, target):
        self.calls.append(op)

        if op == "box":
            w, d, h = params["width"], params["depth"], params["height"]
            g = Box(w, d, h, align=(Align.CENTER, Align.CENTER, Align.MIN))
            return {"geometry": g, "volume": g.volume, "datums": {
                "top": _plane((0, 0, h), (0, 0, 1)),
                "bottom": _plane((0, 0, 0), (0, 0, -1)),
                "left": _plane((-w / 2, 0, 0), (-1, 0, 0)),
                "right": _plane((w / 2, 0, 0), (1, 0, 0)),
                "front": _plane((0, -d / 2, 0), (0, -1, 0)),
                "back": _plane((0, d / 2, 0), (0, 1, 0)),
            }}

        if op == "cylinder":
            r, h = params["diameter"] / 2.0, params["height"]
            g = Cylinder(radius=r, height=h, align=(Align.CENTER, Align.CENTER, Align.MIN))
            return {"geometry": g, "volume": g.volume, "datums": {
                "axis": _axis((0, 0, 0)),
                "top": _plane((0, 0, h), (0, 0, 1)),
                "bottom": _plane((0, 0, 0), (0, 0, -1)),
            }}

        if op == "hexPrism":
            w, h = params["widthAcrossFlats"], params["height"]
            g = extrude(RegularPolygon(radius=w / 2, side_count=6, major_radius=False), h)
            return {"geometry": g, "volume": g.volume, "datums": {
                "axis": _axis((0, 0, 0)),
                "top": _plane((0, 0, h), (0, 0, 1)),
                "bottom": _plane((0, 0, 0), (0, 0, -1)),
            }}

        if op == "circle2d":
            g = Circle(radius=params["diameter"] / 2.0)
            return {"geometry": g, "volume": 0.0, "area": g.area, "profile": True,
                    "datums": {"center": _point((0, 0, 0))}}

        if op == "polygon2d":
            g = Polygon(*params["points"], align=None)
            return {"geometry": g, "volume": 0.0, "area": g.area, "profile": True,
                    "datums": {"center": _point((0, 0, 0))}}

        if op == "extrude":
            prof = inputs[0]
            g = extrude(prof["geometry"], params["height"])
            h = params["height"]
            datums = {k: _shift_datum(v, 0, 0, 0) for k, v in prof["datums"].items()}
            datums["top"] = _plane((0, 0, h), (0, 0, 1))
            datums["bottom"] = _plane((0, 0, 0), (0, 0, -1))
            return {"geometry": g, "volume": g.volume, "datums": datums}

        if op in ("union", "subtract", "intersect"):
            a, b = inputs[0]["geometry"], inputs[1]["geometry"]
            g = a + b if op == "union" else a - b if op == "subtract" else a & b
            return {"geometry": g, "volume": g.volume,
                    "datums": dict(inputs[0]["datums"])}

        if op in ("chamfer", "fillet"):
            td = target["result"]
            datum = td["datums"][target["datum"]]
            if datum["kind"] != "plane":
                _unsupported(f"{op} : le repère cible doit être un plan")
            if abs(datum["normal"][2]) < 1 - TOL:
                _unsupported(f"{op} : seul un plan horizontal est pris en charge en v0.1")
            edges = _edges_in_plane(td["geometry"], datum["origin"][2])
            g = chamfer(edges, params["size"]) if op == "chamfer" \
                else fillet(edges, params["size"])
            return {"geometry": g, "volume": g.volume, "datums": dict(td["datums"])}

        if op == "drill":
            td = target["result"]
            datum = td["datums"][target["datum"]]
            if datum["kind"] != "plane":
                _unsupported("drill : le repère cible doit être un plan")
            o, n = datum["origin"], datum["normal"]
            if abs(abs(n[2]) - 1.0) > TOL:
                _unsupported("drill : seul l'axe Z est pris en charge en v0.1")
            r, depth = params["diameter"] / 2.0, params["depth"]
            z0 = o[2] - depth if n[2] > 0 else o[2]
            cyl = Pos(o[0], o[1], z0) * Cylinder(
                radius=r, height=depth, align=(Align.CENTER, Align.CENTER, Align.MIN))
            g = td["geometry"] - cyl
            return {"geometry": g, "volume": g.volume, "datums": dict(td["datums"])}

        if op == "patternLinear":
            direction = params["direction"]
            if direction not in ("x", "y", "z"):
                _unsupported(f"patternLinear : direction inconnue : {direction!r}")
            count, spacing = int(params["count"]), params["spacing"]
            base = inputs[0]["geometry"]
            step = {"x": (spacing, 0.0, 0.0), "y": (0.0, spacing, 0.0),
                    "z": (0.0, 0.0, spacing)}[direction]
            instances = [Pos(i * step[0], i * step[1], i * step[2]) * base
                         for i in range(count)]
            g = Compound(children=instances)
            return {"geometry": g, "volume": g.volume,
                    "datums": {"instances": _point((0, 0, 0))}}

        if op == "transform":
            tx, ty, tz = params["tx"], params["ty"], params["tz"]
            g = Pos(tx, ty, tz) * inputs[0]["geometry"]
            datums = {k: _shift_datum(v, tx, ty, tz)
                      for k, v in inputs[0]["datums"].items()}
            return {"geometry": g, "volume": g.volume, "datums": datums}

        if op == "datumPlane":
            off = params.get("offset", 0.0)
            return {"geometry": None, "volume": 0.0,
                    "datums": {"plane": _plane((0, 0, off), (0, 0, 1))}}

        _unsupported(f"opération non implémentée par le backend : {op!r}")


# ---------------------------------------------------------------------------
# Tests d'acceptation : golden tests à métriques analytiques
# ---------------------------------------------------------------------------

def expect_close(actual, expected, tol, name):
    assert abs(actual - expected) <= tol, \
        f"{name} : attendu {expected}, obtenu {actual} (écart {actual - expected})"


def run_tests() -> int:
    failures = 0

    def run(name, fn):
        nonlocal failures
        try:
            fn()
            print(f"PASS  {name}")
        except Exception as e:  # noqa: BLE001 — rapport de test volontairement large
            failures += 1
            print(f"FAIL  {name} : {e}")

    def t_box():
        b = Build123dBackend()
        r = b.execute("box", {"width": 10.0, "depth": 20.0, "height": 5.0}, [], None)
        expect_close(r["volume"], 1000.0, 1e-6, "volume box")
        bb = r["geometry"].bounding_box()
        expect_close(bb.size.X, 10.0, 1e-6, "bbox X")
        expect_close(bb.size.Y, 20.0, 1e-6, "bbox Y")
        expect_close(bb.min.Z, 0.0, 1e-6, "bbox zmin")
        expect_close(bb.max.Z, 5.0, 1e-6, "bbox zmax")

    def t_cylinder():
        b = Build123dBackend()
        r = b.execute("cylinder", {"diameter": 8.0, "height": 10.0}, [], None)
        expect_close(r["volume"], math.pi * 16.0 * 10.0, 1e-6, "volume cylindre")
        bb = r["geometry"].bounding_box()
        expect_close(bb.size.X, 8.0, 1e-6, "bbox X")
        expect_close(bb.max.Z, 10.0, 1e-6, "bbox zmax")
        expect_close(r["datums"]["top"]["origin"][2], 10.0, 1e-9, "repère top")

    def t_hexprism():
        b = Build123dBackend()
        r = b.execute("hexPrism", {"widthAcrossFlats": 13.0, "height": 5.3}, [], None)
        expect_close(r["volume"], (math.sqrt(3.0) / 2.0) * 13.0 ** 2 * 5.3, 1e-6,
                     "volume prisme hexagonal")
        bb = r["geometry"].bounding_box()
        across_corners = 13.0 / math.cos(math.pi / 6)
        expect_close(max(bb.size.X, bb.size.Y), across_corners, 1e-4, "entre pointes")
        expect_close(min(bb.size.X, bb.size.Y), 13.0, 1e-4, "entre flats")
        expect_close(bb.max.Z, 5.3, 1e-6, "bbox zmax")

    def t_profiles():
        b = Build123dBackend()
        c = b.execute("circle2d", {"diameter": 10.0}, [], None)
        expect_close(c["area"], math.pi * 25.0, 1e-6, "aire disque")
        assert c["profile"] is True, "circle2d doit produire un profil"
        p = b.execute("polygon2d", {"points": [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0),
                                               (0.0, 10.0)]}, [], None)
        expect_close(p["area"], 100.0, 1e-6, "aire carré")
        e = b.execute("extrude", {"height": 7.0}, [c], None)
        expect_close(e["volume"], math.pi * 25.0 * 7.0, 1e-6, "volume extrusion")
        expect_close(e["geometry"].bounding_box().max.Z, 7.0, 1e-6, "extrusion zmax")

    def t_booleans():
        b = Build123dBackend()
        box = b.execute("box", {"width": 10.0, "depth": 10.0, "height": 10.0}, [], None)
        cyl = b.execute("cylinder", {"diameter": 4.0, "height": 20.0}, [], None)
        through = math.pi * 4.0 * 10.0
        u = b.execute("union", {}, [box, cyl], None)
        expect_close(u["volume"], 1000.0 + math.pi * 4.0 * 20.0 - through, 1e-6, "union")
        s = b.execute("subtract", {}, [box, cyl], None)
        expect_close(s["volume"], 1000.0 - through, 1e-6, "subtract")
        i = b.execute("intersect", {}, [box, cyl], None)
        expect_close(i["volume"], through, 1e-6, "intersect")

    def t_chamfer():
        b = Build123dBackend()
        cyl = b.execute("cylinder", {"diameter": 8.0, "height": 10.0}, [], None)
        target = {"node": "shaft", "datum": "bottom", "result": cyl}
        r = b.execute("chamfer", {"size": 1.0}, [], target)
        removed = math.pi * 1.0 ** 2 * (4.0 - 1.0 / 3.0)
        expect_close(r["volume"], math.pi * 16.0 * 10.0 - removed, 1e-4,
                     "volume chanfreiné (cône exact)")

    def t_fillet():
        b = Build123dBackend()
        cyl = b.execute("cylinder", {"diameter": 8.0, "height": 10.0}, [], None)
        target = {"node": "shaft", "datum": "bottom", "result": cyl}
        r = b.execute("fillet", {"size": 1.0}, [], target)
        removed = math.pi * (2.0 * (1.0 - math.pi / 4.0) * 3.0 + 1.0 / 3.0)
        expect_close(r["volume"], math.pi * 16.0 * 10.0 - removed, 1e-4,
                     "volume congé (tore exact)")

    def t_drill():
        b = Build123dBackend()
        cyl = b.execute("cylinder", {"diameter": 8.0, "height": 10.0}, [], None)
        target = {"node": "shaft", "datum": "top", "result": cyl}
        r = b.execute("drill", {"diameter": 4.0, "depth": 5.0}, [], target)
        expect_close(r["volume"], math.pi * 16.0 * 10.0 - math.pi * 4.0 * 5.0, 1e-6,
                     "volume percé")

    def t_pattern():
        b = Build123dBackend()
        box = b.execute("box", {"width": 5.0, "depth": 5.0, "height": 5.0}, [], None)
        r = b.execute("patternLinear",
                      {"count": 3, "spacing": 10.0, "direction": "x"}, [box], None)
        expect_close(r["volume"], 375.0, 1e-6, "volume motif")
        expect_close(r["geometry"].bounding_box().size.X, 25.0, 1e-6, "étendue motif")

    def t_transform():
        b = Build123dBackend()
        box = b.execute("box", {"width": 5.0, "depth": 5.0, "height": 5.0}, [], None)
        r = b.execute("transform", {"tx": 0.0, "ty": 0.0, "tz": 10.0}, [box], None)
        expect_close(r["volume"], 125.0, 1e-6, "volume translaté")
        bb = r["geometry"].bounding_box()
        expect_close(bb.min.Z, 10.0, 1e-6, "translation zmin")
        expect_close(bb.max.Z, 15.0, 1e-6, "translation zmax")
        expect_close(r["datums"]["top"]["origin"][2], 15.0, 1e-9, "repère translaté")

    def t_datum_plane():
        b = Build123dBackend()
        r = b.execute("datumPlane", {"offset": 2.5}, [], None)
        expect_close(r["datums"]["plane"]["origin"][2], 2.5, 1e-9, "plan décalé")

    def _screw_recipe():
        return {
            "parameters": [
                {"name": "nominalLength", "type": "quantity", "unit": QUDT + "MilliM",
                 "required": True, "min": 5, "max": 300},
            ],
            "nodes": [
                {"id": "shaft", "op": "cylinder",
                 "params": {"diameter": MMQ(8),
                            "height": {"k": "sub",
                                       "args": [{"k": "ref", "name": "nominalLength"},
                                                MMQ(5.3)]}}},
                {"id": "head", "op": "hexPrism",
                 "params": {"widthAcrossFlats": MMQ(13), "height": MMQ(5.3)}},
                {"id": "head-pos", "op": "transform",
                 "params": {"tx": MMQ(0), "ty": MMQ(0),
                            "tz": {"k": "sub",
                                   "args": [{"k": "ref", "name": "nominalLength"},
                                            MMQ(5.3)]}},
                 "inputs": ["head"]},
                {"id": "tip", "op": "chamfer", "params": {"size": MMQ(1)},
                 "target": {"node": "shaft", "datum": "bottom"}},
                {"id": "body", "op": "union", "inputs": ["tip", "head-pos"]},
            ],
            "outputs": {"solid": "body"},
            "exposedDatums": [{"name": "axis", "kind": "axis", "from": "shaft.axis"}],
        }

    def t_screw_golden():
        b = Build123dBackend()
        res = execute_recipe(_screw_recipe(),
                             {"nominalLength": {"value": 30, "unit": QUDT + "MilliM"}}, b)
        expected = ((math.sqrt(3.0) / 2.0) * 13.0 ** 2 * 5.3
                    + math.pi * 16.0 * (30.0 - 5.3)
                    - math.pi * 1.0 ** 2 * (4.0 - 1.0 / 3.0))
        expect_close(res["solid"]["volume"], expected, 1e-4, "volume vis M8×30")
        bb = res["solid"]["geometry"].bounding_box()
        expect_close(bb.min.Z, 0.0, 1e-6, "vis zmin")
        expect_close(bb.max.Z, 30.0, 1e-6, "vis zmax")
        expect_close(max(bb.size.X, bb.size.Y), 13.0 / math.cos(math.pi / 6), 1e-4,
                     "vis entre pointes")
        expect_close(min(bb.size.X, bb.size.Y), 13.0, 1e-4, "vis entre flats")
        assert res["datums"]["axis"] == "shaft.axis", "repère exposé faux"
        axis = res["results"]["shaft"]["datums"]["axis"]
        assert axis["direction"] == [0.0, 0.0, 1.0], "direction d'axe fausse"

    def t_determinism():
        vols = []
        for _ in range(2):
            res = execute_recipe(_screw_recipe(),
                                 {"nominalLength": {"value": 30, "unit": QUDT + "MilliM"}},
                                 Build123dBackend())
            vols.append(res["solid"]["volume"])
        assert abs(vols[0] - vols[1]) < 1e-9, f"exécution non déterministe : {vols}"

    run("box : volume et boîte englobante", t_box)
    run("cylinder : volume, bbox, repères", t_cylinder)
    run("hexPrism : volume analytique et entre-pointes", t_hexprism)
    run("circle2d / polygon2d / extrude", t_profiles)
    run("union / subtract / intersect", t_booleans)
    run("chamfer : volume du cône exact", t_chamfer)
    run("fillet : volume du tore exact", t_fillet)
    run("drill : perçage sur repère plan", t_drill)
    run("patternLinear : motif et étendue", t_pattern)
    run("transform : translation et repères", t_transform)
    run("datumPlane : plan décalé", t_datum_plane)
    run("golden : vis M8×30 (ISO 4017)", t_screw_golden)
    run("déterminisme de la reconstruction", t_determinism)
    return failures


def main() -> int:
    print("UTOM Geometry v0.1 — backend build123d, tests d'acceptation")
    failures = run_tests()
    if failures:
        print(f"\nRÉSULTAT : {failures} échec(s)")
        return 1
    print("\nRÉSULTAT : tous les tests passent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
