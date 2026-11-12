#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
utom_geometry.py — UTOM Geometry v0.1 : interpréteur de graphe (prototype).

Statut : proposition de travail, NON publié. La suite de tests ci-dessous
est la porte d'acceptation.

    python3 utom_geometry.py     # exécute les tests d'acceptation

Périmètre : validation de recette (règles V1–V13 de la spécification),
ordonnancement topologique déterministe, expressions typées (arbres JSON,
jamais d'eval), exécution avec propagation (seuls les nœuds affectés sont
recalculés), repères nommés (dont repère externe via datumNode), MockBackend
à métriques analytiques.

Hors périmètre : backend réel build123d (voir utom_build123d.py), esquisses
contraintes, assemblages multi-pièces.

Dépendances : aucune (bibliothèque standard). Python >= 3.10.
Remarque : UtomError est dupliqué d'utom_core.py pour garder ce fichier
autonome ; dans le dépôt, les deux fichiers partageront un module commun.
Licence : Apache-2.0 (décision du 2026-11-10).
"""

from __future__ import annotations

import math
import re
import sys

QUDT = "http://qudt.org/vocab/unit/"
UNIT_DIMS = {
    QUDT + "MilliM": "length",
    QUDT + "DEG": "angle",
    QUDT + "RAD": "angle",
    QUDT + "One": "dimensionless",
}
ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
PARAM_RE = re.compile(r"^[a-z][a-zA-Z0-9]{0,63}$")


class UtomError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


def _req(cond, code: str, message: str):
    if not cond:
        raise UtomError(code, message)


# ---------------------------------------------------------------------------
# Expressions typées (arbres JSON, jamais d'eval)
# ---------------------------------------------------------------------------

def dim_of_unit(u):
    _req(isinstance(u, str) and u in UNIT_DIMS, "UTOM-GEO-011",
         f"unité non reconnue en v0.1 : {u!r}")
    return UNIT_DIMS[u]


def eval_expr(e, env, ctx: str):
    """Évalue une expression ; renvoie (valeur, dimension)."""
    _req(isinstance(e, dict), "UTOM-EXP-001", f"{ctx} : expression objet attendue")
    k = e.get("k")
    if k == "qty":
        v = e.get("value")
        _req(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v),
             "UTOM-GEO-012", f"{ctx} : valeur numérique finie requise")
        unit = e.get("unit")
        d = dim_of_unit(unit)
        if unit == QUDT + "DEG":
            v = math.radians(v)
        return (float(v), d)
    if k == "ref":
        name = e.get("name")
        _req(name in env, "UTOM-GEO-005", f"{ctx} : paramètre inconnu : {name!r}")
        return env[name]
    if k in ("add", "sub", "mul", "div"):
        args = e.get("args")
        _req(isinstance(args, list) and len(args) == 2, "UTOM-EXP-001",
             f"{ctx} : {k} exige deux arguments")
        return _arith(k, eval_expr(args[0], env, ctx), eval_expr(args[1], env, ctx), ctx)
    if k == "fn":
        name = e.get("name")
        _req(name in ("min", "max", "abs", "sin", "cos"), "UTOM-EXP-002",
             f"{ctx} : fonction hors liste blanche : {name!r}")
        args = [eval_expr(x, env, ctx) for x in e.get("args", [])]
        if name in ("min", "max"):
            _req(len(args) >= 1, "UTOM-EXP-001", f"{ctx} : {name} exige au moins un argument")
            dims = {d for _, d in args}
            _req(len(dims) == 1, "UTOM-GEO-007", f"{ctx} : {name} sur dimensions mélangées")
            vals = [v for v, _ in args]
            return ((min(vals) if name == "min" else max(vals)), args[0][1])
        if name == "abs":
            _req(len(args) == 1, "UTOM-EXP-001", f"{ctx} : abs exige un argument")
            return ((abs(args[0][0]), args[0][1]))
        _req(len(args) == 1 and args[0][1] == "angle", "UTOM-GEO-007",
             f"{ctx} : {name} exige un argument angle")
        f = math.sin if name == "sin" else math.cos
        return ((f(args[0][0]), "dimensionless"))
    raise UtomError("UTOM-EXP-001", f"{ctx} : forme d'expression inconnue : {k!r}")


def _arith(k, a, b, ctx):
    (va, da), (vb, db) = a, b
    if k in ("add", "sub"):
        _req(da == db, "UTOM-GEO-007",
             f"{ctx} : dimensions incompatibles ({da} vs {db})")
        return ((va + vb) if k == "add" else (va - vb), da)
    if k == "mul":
        if da in ("dimensionless", "count"):
            return ((va * vb), db)
        if db in ("dimensionless", "count"):
            return ((va * vb), da)
        raise UtomError("UTOM-GEO-008", f"{ctx} : produit {da}×{db} hors v0.1")
    _req(vb != 0, "UTOM-EXP-003", f"{ctx} : division par zéro")
    if db in ("dimensionless", "count"):
        return ((va / vb), da)
    if da == db:
        return ((va / vb), "dimensionless")
    raise UtomError("UTOM-GEO-008", f"{ctx} : quotient {da}/{db} hors v0.1")


# ---------------------------------------------------------------------------
# Catalogue d'opérations (lot 1)
# ---------------------------------------------------------------------------

OPS = {
    "box": {"params": {"width": "length", "depth": "length", "height": "length"},
            "required": ["width", "depth", "height"], "inputs": 0, "target": False,
            "datums": ["top", "bottom", "left", "right", "front", "back"]},
    "cylinder": {"params": {"diameter": "length", "height": "length"},
                 "required": ["diameter", "height"], "inputs": 0, "target": False,
                 "datums": ["axis", "top", "bottom"]},
    "hexPrism": {"params": {"widthAcrossFlats": "length", "height": "length"},
                 "required": ["widthAcrossFlats", "height"], "inputs": 0, "target": False,
                 "datums": ["axis", "top", "bottom"]},
    "circle2d": {"params": {"diameter": "length"}, "required": ["diameter"],
                 "inputs": 0, "target": False, "datums": ["center"]},
    "polygon2d": {"params": {"points": "points"}, "required": ["points"],
                  "inputs": 0, "target": False, "datums": ["center"]},
    "extrude": {"params": {"height": "length"}, "required": ["height"],
                "inputs": 1, "target": False, "datums": ["top", "bottom"]},
    "union": {"params": {}, "required": [], "inputs": 2, "target": False, "datums": "pass"},
    "subtract": {"params": {}, "required": [], "inputs": 2, "target": False, "datums": "pass"},
    "intersect": {"params": {}, "required": [], "inputs": 2, "target": False, "datums": "pass"},
    "chamfer": {"params": {"size": "length"}, "required": ["size"], "inputs": 0,
                "target": True, "datums": "pass"},
    "fillet": {"params": {"size": "length"}, "required": ["size"], "inputs": 0,
               "target": True, "datums": "pass"},
    "drill": {"params": {"diameter": "length", "depth": "length"},
              "required": ["diameter", "depth"], "inputs": 0, "target": True,
              "datums": "pass"},
    "patternLinear": {"params": {"count": "count", "spacing": "length",
                                 "direction": "text"},
                      "required": ["count", "spacing", "direction"], "inputs": 1,
                      "target": False, "datums": ["instances"]},
    "transform": {"params": {"tx": "length", "ty": "length", "tz": "length"},
                  "required": ["tx", "ty", "tz"], "inputs": 1, "target": False,
                  "datums": "pass"},
    "datumPlane": {"params": {"offset": "length", "ox": "length", "oy": "length",
                              "oz": "length", "nx": "dimensionless",
                              "ny": "dimensionless", "nz": "dimensionless"},
                   "required": [], "inputs": 0, "target": False,
                   "datums": ["plane"]},
}


# ---------------------------------------------------------------------------
# Validation de recette (V1–V13)
# ---------------------------------------------------------------------------

def _topo_order(nodes):
    ids = {n["id"] for n in nodes}
    remaining = {}
    for n in nodes:
        d = set(n.get("inputs", []))
        t = n.get("target")
        if t:
            d.add(t["node"])
            if isinstance(t.get("datumNode"), str):
                d.add(t["datumNode"])
        remaining[n["id"]] = d & ids
    order = []
    while remaining:
        ready = sorted(i for i, d in remaining.items()
                       if not (d & set(remaining)))
        _req(ready, "UTOM-GEO-001", "cycle détecté dans le graphe de la recette")
        for i in ready:
            order.append(i)
            del remaining[i]
    return order


def validate_recipe(recipe):
    _req(isinstance(recipe, dict), "UTOM-GEO-000", "recette : objet attendu")
    params = recipe.get("parameters")
    _req(isinstance(params, list), "UTOM-GEO-000", "parameters : liste requise")
    seen = set()
    for p in params:
        _req(isinstance(p, dict), "UTOM-GEO-000", "parameter : objet attendu")
        name = p.get("name")
        _req(isinstance(name, str) and PARAM_RE.match(name) and name not in seen,
             "UTOM-GEO-009", f"paramètre invalide ou dupliqué : {name!r}")
        seen.add(name)
        _req(p.get("type") in ("quantity", "text", "count"),
             "UTOM-GEO-000", f"{name} : type inconnu")
        if p.get("type") == "quantity":
            dim_of_unit(p.get("unit"))
    nodes = recipe.get("nodes")
    _req(isinstance(nodes, list) and len(nodes) > 0, "UTOM-GEO-000",
         "nodes : liste non vide requise")
    ids = set()
    for n in nodes:
        _req(isinstance(n, dict), "UTOM-GEO-000", "node : objet attendu")
        nid = n.get("id")
        _req(isinstance(nid, str) and ID_RE.match(nid) and nid not in ids,
             "UTOM-GEO-009", f"id de nœud invalide ou dupliqué : {nid!r}")
        ids.add(nid)
        _req(n.get("op") in OPS, "UTOM-GEO-006",
             f"{nid} : opération inconnue : {n.get('op')!r}")
    for n in nodes:
        for ref in n.get("inputs", []):
            _req(ref in ids, "UTOM-GEO-002",
                 f"{n['id']} : nœud d'entrée inconnu : {ref!r}")
        t = n.get("target")
        if t is not None:
            _req(isinstance(t, dict) and t.get("node") in ids, "UTOM-GEO-002",
                 f"{n['id']} : nœud cible inconnu")
            dn = t.get("datumNode")
            if dn is not None:
                _req(isinstance(dn, str) and dn in ids, "UTOM-GEO-002",
                     f"{n['id']} : nœud porteur de repère inconnu : {dn!r}")
        spec = OPS[n["op"]]
        for name in spec["required"]:
            _req(name in (n.get("params") or {}), "UTOM-GEO-005",
                 f"{n['id']} : paramètre requis manquant : {name!r}")
    out = recipe.get("outputs")
    _req(isinstance(out, dict) and out.get("solid") in ids, "UTOM-GEO-010",
         "outputs.solid : nœud inexistant")
    for d in recipe.get("exposedDatums", []):
        _req(isinstance(d, dict) and isinstance(d.get("name"), str),
             "UTOM-GEO-000", "exposedDatums : nom requis")
        frm = d.get("from", "")
        _req(isinstance(frm, str) and "." in frm, "UTOM-GEO-000",
             "exposedDatums.from : forme 'node.datum' attendue")
        node = frm.split(".", 1)[0]
        _req(node in ids, "UTOM-GEO-002", f"exposedDatums : nœud inconnu : {node!r}")
    _topo_order(nodes)
    return recipe


# ---------------------------------------------------------------------------
# Exécution avec propagation
# ---------------------------------------------------------------------------

def _as_expr(raw, ctx):
    if isinstance(raw, dict):
        if "k" in raw:
            return raw
        if "value" in raw and "unit" in raw:
            return {"k": "qty", "value": raw["value"], "unit": raw["unit"]}
        raise UtomError("UTOM-GEO-012", f"{ctx} : objet de paramètre non reconnu")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        raise UtomError("UTOM-GEO-012",
                        f"{ctx} : nombre nu refusé, fournir {{value, unit}}")
    raise UtomError("UTOM-GEO-012", f"{ctx} : type de paramètre non pris en charge")


def _check_points(raw, ctx):
    _req(isinstance(raw, list) and 3 <= len(raw) <= 64, "UTOM-GEO-004",
         f"{ctx} : points : liste de 3 à 64 requise")
    pts = []
    for pt in raw:
        _req(isinstance(pt, list) and len(pt) == 2, "UTOM-GEO-012",
             f"{ctx} : point = [x, y] attendu")
        xv, dx = eval_expr(_as_expr(pt[0], ctx), {}, ctx)
        yv, dy = eval_expr(_as_expr(pt[1], ctx), {}, ctx)
        _req(dx == "length" and dy == "length", "UTOM-GEO-007",
             f"{ctx} : coordonnées de point en longueur attendues")
        pts.append((xv, yv))
    return pts


def _collect_param_refs(n):
    found = set()

    def walk(e):
        if isinstance(e, dict):
            if e.get("k") == "ref" and isinstance(e.get("name"), str):
                found.add(e["name"])
            for v in e.values():
                walk(v)
        elif isinstance(e, list):
            for x in e:
                walk(x)

    walk(n.get("params") or {})
    return found


def _check_param(p, v, name):
    t = p["type"]
    if t == "quantity":
        _req(isinstance(v, dict) and "value" in v and "unit" in v,
             "UTOM-GEO-012", f"{name} : {{value, unit}} requis")
        _req(v["unit"] == p["unit"], "UTOM-GEO-011",
             f"{name} : unité {v['unit']!r} différente de l'unité déclarée {p['unit']!r}")
        val, dim = eval_expr({"k": "qty", "value": v["value"], "unit": v["unit"]}, {}, name)
        if "min" in p:
            _req(v["value"] >= p["min"], "UTOM-GEO-004",
                 f"{name} : {v['value']} < min {p['min']}")
        if "max" in p:
            _req(v["value"] <= p["max"], "UTOM-GEO-004",
                 f"{name} : {v['value']} > max {p['max']}")
        return (val, dim)
    if t == "count":
        _req(isinstance(v, int) and not isinstance(v, bool), "UTOM-GEO-007",
             f"{name} : entier requis")
        return ((float(v), "count"))
    _req(isinstance(v, str), "UTOM-GEO-007", f"{name} : texte requis")
    return ((v, "text"))


def _exec_node(n, env, results, backend):
    spec = OPS[n["op"]]
    ctx = f"nœud {n['id']!r}"
    params = {}
    for pname, raw in (n.get("params") or {}).items():
        ptype = spec["params"].get(pname)
        if ptype is None:
            raise UtomError("UTOM-GEO-006",
                            f"{ctx} : paramètre inconnu pour {n['op']!r} : {pname!r}")
        if ptype == "text":
            _req(isinstance(raw, str), "UTOM-GEO-007", f"{ctx} : {pname} attendu texte")
            params[pname] = raw
        elif ptype == "count":
            _req(isinstance(raw, int) and not isinstance(raw, bool) and raw >= 1,
                 "UTOM-GEO-004", f"{ctx} : {pname} : entier ≥ 1 requis")
            params[pname] = raw
        elif ptype == "points":
            params[pname] = _check_points(raw, ctx)
        else:
            v, d = eval_expr(_as_expr(raw, ctx), env, ctx)
            _req(d == ptype, "UTOM-GEO-007",
                 f"{ctx} : {pname} attendu {ptype}, obtenu {d}")
            params[pname] = v
    inputs = []
    for ref in n.get("inputs", []):
        _req(ref in results, "UTOM-GEO-002", f"{ctx} : entrée non calculée : {ref!r}")
        inputs.append(results[ref])
    target = None
    if n.get("target"):
        tnode, tdatum = n["target"]["node"], n["target"].get("datum")
        tres = results.get(tnode)
        _req(tres is not None, "UTOM-GEO-002", f"{ctx} : cible non calculée : {tnode!r}")
        dnode = n["target"].get("datumNode")
        if dnode:
            dres = results.get(dnode)
            _req(dres is not None, "UTOM-GEO-002",
                 f"{ctx} : porteur de repère non calculé : {dnode!r}")
            _req(isinstance(tdatum, str) and tdatum in dres["datums"], "UTOM-GEO-003",
                 f"{ctx} : repère inexistant : {dnode}.{tdatum!r}")
            desc = dres["datums"][tdatum]
        else:
            _req(isinstance(tdatum, str) and tdatum in tres["datums"], "UTOM-GEO-003",
                 f"{ctx} : repère inexistant : {tnode}.{tdatum!r}")
            desc = tres["datums"][tdatum]
        target = {"node": tnode, "datum": tdatum, "result": tres, "datumDesc": desc}
    _req(n["op"] in backend.capabilities(), "UTOM-GEO-013",
         f"{ctx} : opération non prise en charge par le backend")
    return backend.execute(n["op"], params, inputs, target)


def execute_recipe(recipe, values, backend, cache=None):
    """Exécute une recette. cache = {"results": …, "values": …} du run
    précédent : seuls les nœuds affectés sont recalculés."""
    validate_recipe(recipe)
    spec_params = {p["name"]: p for p in recipe["parameters"]}
    for name in values:
        _req(name in spec_params, "UTOM-GEO-014",
             f"paramètre fourni inconnu : {name!r}")
    env = {}
    for name, p in spec_params.items():
        if name in values:
            env[name] = _check_param(p, values[name], name)
        elif p.get("required"):
            raise UtomError("UTOM-GEO-005", f"paramètre requis manquant : {name!r}")
    by_id = {n["id"]: n for n in recipe["nodes"]}
    order = _topo_order(recipe["nodes"])
    results = {} if cache is None else dict(cache.get("results", {}))
    changed = set()
    if cache is not None:
        prev = cache.get("values", {})
        for name in set(values) | set(prev):
            if values.get(name) != prev.get(name):
                changed.add(name)
    recomputed = set()
    for nid in order:
        n = by_id[nid]
        need = cache is None or nid not in results
        if not need and changed and (_collect_param_refs(n) & changed):
            need = True
        if not need:
            deps = list(n.get("inputs", []))
            if n.get("target"):
                deps.append(n["target"]["node"])
                if isinstance(n["target"].get("datumNode"), str):
                    deps.append(n["target"]["datumNode"])
            if any(ref in recomputed for ref in deps):
                need = True
        if need:
            results[nid] = _exec_node(n, env, results, backend)
            recomputed.add(nid)
    solid = results.get(recipe["outputs"]["solid"])
    _req(solid is not None, "UTOM-GEO-010", "sortie non produite")
    datums_out = {}
    for d in recipe.get("exposedDatums", []):
        node, datum = d["from"].split(".", 1)
        r = results[node]
        _req(datum in r["datums"], "UTOM-GEO-003",
             f"repère inexistant : {d['from']!r}")
        datums_out[d["name"]] = d["from"]
    return {"solid": solid, "datums": datums_out, "recomputed": sorted(recomputed),
            "results": results}


# ---------------------------------------------------------------------------
# MockBackend : métriques analytiques (ne remplace pas build123d)
# ---------------------------------------------------------------------------

def _shoelace(pts):
    s = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return s / 2.0


class MockBackend:
    """Backend factice à métriques analytiques, pour tester l'interpréteur."""

    def __init__(self):
        self.calls = []

    def version(self):
        return "mock-0.1"

    def capabilities(self):
        return sorted(OPS.keys())

    def execute(self, op, params, inputs, target):
        self.calls.append(op)
        if op == "box":
            return {"volume": params["width"] * params["depth"] * params["height"],
                    "datums": list(OPS["box"]["datums"])}
        if op == "cylinder":
            return {"volume": math.pi / 4.0 * params["diameter"] ** 2 * params["height"],
                    "datums": ["axis", "top", "bottom"]}
        if op == "hexPrism":
            w = params["widthAcrossFlats"]
            return {"volume": (math.sqrt(3.0) / 2.0) * w * w * params["height"],
                    "datums": ["axis", "top", "bottom"]}
        if op == "circle2d":
            return {"volume": 0.0, "area": math.pi / 4.0 * params["diameter"] ** 2,
                    "profile": True, "datums": ["center"]}
        if op == "polygon2d":
            return {"volume": 0.0, "area": abs(_shoelace(params["points"])),
                    "profile": True, "datums": ["center"]}
        if op == "extrude":
            _req(inputs and inputs[0].get("profile"), "UTOM-GEO-007",
                 "extrude exige un profil en entrée")
            return {"volume": inputs[0]["area"] * params["height"],
                    "datums": ["top", "bottom"]}
        if op in ("union", "subtract", "intersect"):
            a, b = inputs[0], inputs[1]
            vol = (a["volume"] + b["volume"] if op == "union"
                   else a["volume"] - b["volume"] if op == "subtract"
                   else min(a["volume"], b["volume"]))
            return {"volume": vol, "datums": list(a["datums"])}
        if op in ("chamfer", "fillet"):
            return {"volume": target["result"]["volume"],
                    "datums": list(target["result"]["datums"])}
        if op == "drill":
            removed = math.pi / 4.0 * params["diameter"] ** 2 * params["depth"]
            return {"volume": target["result"]["volume"] - removed,
                    "datums": list(target["result"]["datums"])}
        if op == "patternLinear":
            return {"volume": inputs[0]["volume"] * params["count"],
                    "datums": ["instances"]}
        if op == "transform":
            return {"volume": inputs[0]["volume"], "datums": list(inputs[0]["datums"])}
        if op == "datumPlane":
            return {"volume": 0.0, "datums": ["plane"]}
        raise UtomError("UTOM-GEO-013", f"opération non implémentée par le mock : {op!r}")


# ---------------------------------------------------------------------------
# Tests d'acceptation
# ---------------------------------------------------------------------------

def MMQ(v):
    return {"k": "qty", "value": v, "unit": QUDT + "MilliM"}


def _screw_recipe():
    return {
        "parameters": [
            {"name": "nominalLength", "type": "quantity", "unit": QUDT + "MilliM",
             "required": True, "min": 5, "max": 300},
        ],
        "nodes": [
            {"id": "head", "op": "hexPrism",
             "params": {"widthAcrossFlats": MMQ(13), "height": MMQ(5.3)}},
            {"id": "shaft", "op": "cylinder",
             "params": {"diameter": MMQ(8),
                        "height": {"k": "sub",
                                   "args": [{"k": "ref", "name": "nominalLength"},
                                            MMQ(5.3)]}}},
            {"id": "body", "op": "union", "inputs": ["head", "shaft"]},
            {"id": "tip", "op": "chamfer", "params": {"size": MMQ(1)},
             "target": {"node": "shaft", "datum": "bottom"}},
        ],
        "outputs": {"solid": "tip"},
        "exposedDatums": [{"name": "axis", "kind": "axis", "from": "shaft.axis"}],
    }


def expect_error(fn, code, test_name):
    try:
        fn()
    except UtomError as e:
        if e.code != code:
            raise AssertionError(f"{test_name} : code attendu {code}, obtenu {e.code} ({e})")
        return
    raise AssertionError(f"{test_name} : erreur {code} attendue, aucune levée")


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

    def t_order():
        r = _screw_recipe()
        validate_recipe(r)
        order = _topo_order(r["nodes"])
        pos = {nid: i for i, nid in enumerate(order)}
        assert pos["head"] < pos["body"] and pos["shaft"] < pos["body"], "ordre topologique faux"
        assert order == _topo_order(r["nodes"]), "ordonnancement non déterministe"

    def t_cycle():
        r = _screw_recipe()
        r["nodes"] = [{"id": "a", "op": "union", "inputs": ["b"]},
                      {"id": "b", "op": "union", "inputs": ["a"]}]
        r["outputs"] = {"solid": "a"}
        r["exposedDatums"] = []
        expect_error(lambda: validate_recipe(r), "UTOM-GEO-001", "cycle")

    def t_unknown_input():
        r = _screw_recipe()
        r["nodes"][2]["inputs"] = ["nope"]
        expect_error(lambda: validate_recipe(r), "UTOM-GEO-002", "entrée inconnue")

    def t_unknown_datum():
        r = _screw_recipe()
        r["nodes"][3]["target"]["datum"] = "side"
        b = MockBackend()
        expect_error(lambda: execute_recipe(r, {"nominalLength": {"value": 30, "unit": QUDT + "MilliM"}}, b),
                     "UTOM-GEO-003", "repère inconnu")

    def t_domain():
        r = _screw_recipe()
        b = MockBackend()
        expect_error(lambda: execute_recipe(r, {"nominalLength": {"value": 1, "unit": QUDT + "MilliM"}}, b),
                     "UTOM-GEO-004", "hors domaine")

    def t_missing():
        r = _screw_recipe()
        expect_error(lambda: execute_recipe(r, {}, MockBackend()),
                     "UTOM-GEO-005", "paramètre requis manquant")

    def t_unknown_op():
        r = _screw_recipe()
        r["nodes"][0]["op"] = "torus"
        expect_error(lambda: validate_recipe(r), "UTOM-GEO-006", "opération inconnue")

    def t_type_mismatch():
        r = _screw_recipe()
        r["nodes"][0]["params"]["height"] = {
            "k": "add", "args": [MMQ(1), {"k": "qty", "value": 1, "unit": QUDT + "DEG"}]}
        b = MockBackend()
        expect_error(lambda: execute_recipe(r, {"nominalLength": {"value": 30, "unit": QUDT + "MilliM"}}, b),
                     "UTOM-GEO-007", "longueur + angle")

    def t_mul_dims():
        e = {"k": "mul", "args": [MMQ(2), MMQ(3)]}
        expect_error(lambda: eval_expr(e, {}, "test"), "UTOM-GEO-008", "longueur × longueur")

    def t_duplicate_id():
        r = _screw_recipe()
        r["nodes"].append(dict(r["nodes"][0]))
        expect_error(lambda: validate_recipe(r), "UTOM-GEO-009", "id dupliqué")

    def t_bad_output():
        r = _screw_recipe()
        r["outputs"] = {"solid": "nope"}
        expect_error(lambda: validate_recipe(r), "UTOM-GEO-010", "sortie inexistante")

    def t_bare_number():
        r = _screw_recipe()
        r["nodes"][0]["params"]["height"] = 5.3
        b = MockBackend()
        expect_error(lambda: execute_recipe(r, {"nominalLength": {"value": 30, "unit": QUDT + "MilliM"}}, b),
                     "UTOM-GEO-012", "nombre nu")

    def t_unknown_unit():
        e = {"k": "qty", "value": 1, "unit": QUDT + "INCH"}
        expect_error(lambda: eval_expr(e, {}, "test"), "UTOM-GEO-011", "unité inconnue")

    def t_trig():
        v, d = eval_expr({"k": "fn", "name": "cos",
                          "args": [{"k": "qty", "value": 0, "unit": QUDT + "DEG"}]}, {}, "test")
        assert d == "dimensionless" and abs(v - 1.0) < 1e-12, "cos(0°) != 1"

    def t_execution():
        r = _screw_recipe()
        b = MockBackend()
        res = execute_recipe(r, {"nominalLength": {"value": 30, "unit": QUDT + "MilliM"}}, b)
        assert res["solid"]["volume"] > 0, "volume nul"
        assert res["datums"]["axis"] == "shaft.axis", "repère exposé faux"
        assert len(b.calls) == 4, f"4 exécutions attendues, obtenu {len(b.calls)}"

    def t_propagation():
        r = _screw_recipe()
        v30 = {"nominalLength": {"value": 30, "unit": QUDT + "MilliM"}}
        v40 = {"nominalLength": {"value": 40, "unit": QUDT + "MilliM"}}
        b1 = MockBackend()
        r1 = execute_recipe(r, v30, b1)
        assert len(b1.calls) == 4, "premier run : 4 nœuds exécutés"
        cache = {"results": r1["results"], "values": v30}
        b2 = MockBackend()
        r2 = execute_recipe(r, v40, b2, cache=cache)
        assert b2.calls == ["cylinder", "union", "chamfer"], \
            f"recalcul attendu [cylinder, union, chamfer], obtenu {b2.calls}"
        assert "head" not in r2["recomputed"], "head n'aurait pas dû être recalculé"
        assert {"shaft", "body", "tip"} <= set(r2["recomputed"]), \
            "les nœuds affectés doivent être recalculés"
        assert abs(r2["solid"]["volume"] - r1["solid"]["volume"]) > 1.0, \
            "le volume aurait dû changer"

    def t_datum_node():
        one = {"k": "qty", "value": 1, "unit": QUDT + "One"}
        zero = {"k": "qty", "value": 0, "unit": QUDT + "One"}
        r = {
            "parameters": [],
            "nodes": [
                {"id": "part", "op": "box",
                 "params": {"width": MMQ(10), "depth": MMQ(10), "height": MMQ(10)}},
                {"id": "hole", "op": "drill",
                 "params": {"diameter": MMQ(4), "depth": MMQ(5)},
                 "target": {"node": "part", "datum": "plane", "datumNode": "dp"}},
                {"id": "dp", "op": "datumPlane",
                 "params": {"ox": MMQ(5), "oy": MMQ(0), "oz": MMQ(5),
                            "nx": one, "ny": zero, "nz": zero}},
            ],
            "outputs": {"solid": "hole"},
            "exposedDatums": [],
        }
        res = execute_recipe(r, {}, MockBackend())
        removed = math.pi / 4.0 * 4.0 ** 2 * 5.0
        assert abs(res["solid"]["volume"] - (1000.0 - removed)) < 1e-9, \
            "perçage via repère externe faux"
        assert res["recomputed"] == ["dp", "hole", "part"], \
            f"ordre topologique avec datumNode faux : {res['recomputed']}"

    def t_bad_datum_node():
        v30 = {"nominalLength": {"value": 30, "unit": QUDT + "MilliM"}}
        r = _screw_recipe()
        r["nodes"].append({"id": "dp", "op": "datumPlane", "params": {}})
        r["nodes"][3]["target"]["datumNode"] = "nope"
        expect_error(lambda: validate_recipe(r), "UTOM-GEO-002", "datumNode inconnu")
        r2 = _screw_recipe()
        r2["nodes"].append({"id": "dp", "op": "datumPlane", "params": {}})
        r2["nodes"][3]["target"]["datumNode"] = "dp"
        expect_error(lambda: execute_recipe(r2, v30, MockBackend()),
                     "UTOM-GEO-003", "repère absent du porteur")

    run("validation et ordre topologique déterministe", t_order)
    run("cycle rejeté", t_cycle)
    run("entrée inconnue rejetée", t_unknown_input)
    run("repère inconnu rejeté", t_unknown_datum)
    run("paramètre hors domaine rejeté", t_domain)
    run("paramètre requis manquant rejeté", t_missing)
    run("opération inconnue rejetée", t_unknown_op)
    run("longueur + angle rejeté", t_type_mismatch)
    run("longueur × longueur rejeté", t_mul_dims)
    run("id dupliqué rejeté", t_duplicate_id)
    run("sortie inexistante rejetée", t_bad_output)
    run("nombre nu rejeté", t_bare_number)
    run("unité inconnue rejetée", t_unknown_unit)
    run("cos(0°) = 1 sans dimension", t_trig)
    run("exécution vis M8×30", t_execution)
    run("propagation : recalcul ciblé", t_propagation)
    run("datumNode : cible avec repère externe", t_datum_node)
    run("datumNode invalide rejeté", t_bad_datum_node)
    return failures


def main() -> int:
    print("UTOM Geometry v0.1 — tests d'acceptation")
    failures = run_tests()
    if failures:
        print(f"\nRÉSULTAT : {failures} échec(s)")
        return 1
    print("\nRÉSULTAT : tous les tests passent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
