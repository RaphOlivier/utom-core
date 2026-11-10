#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
utom_core.py — UTOM Core v0.1, prototype d'implementation de reference.

Statut : proposition de travail, NON publiee. La suite de tests ci-dessous
(section 9.2 de la specification) est la porte d'acceptation.

    python3 utom_core.py        # execute les tests d'acceptation

Perimetre v0.1 :
  - identite : UUID v7 en URN (ADR-0001) ;
  - serialisation canonique JSON + empreinte SHA-256 ;
  - validation structurelle minimale (labels multilingues, unites QUDT
    obligatoires, provenance obligatoire, editions ISO/IEC obligatoires) ;
  - versions immuables (libelle semver + empreinte) ;
  - dependances linked / embedded / hybrid avec verification d'empreinte ;
  - overlays non destructifs sur une base immuable.

Hors perimetre : langage geometrique, paquet .utom (ZIP), SHACL, adaptateurs.
Dependances : aucune (bibliothèque standard uniquement). Python >= 3.10.
Licence : Apache-2.0 (decision du 2026-11-10).
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import secrets
import sys
import time

SCHEMA_VERSION = "0.1"
UTOM_TYPE = "uto:ObjectDefinition"
QUDT_UNIT_PREFIX = "http://qudt.org/vocab/unit/"
MM = QUDT_UNIT_PREFIX + "MilliM"

UUID_RE = re.compile(
    r"^urn:uuid:[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
LANG_RE = re.compile(r"^[a-z]{2}(-[A-Z]{2})?$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")

PROVENANCE_KINDS = {
    "normative-reference", "manufacturer-data", "measured",
    "computed", "simulated", "assumed", "manual-entry",
}
MATCH_TYPES = {"exact", "conditional", "broader", "narrower", "related", "none"}
DEP_MODES = {"linked", "embedded", "hybrid"}
CHANGE_TYPES = {
    "parameter_override", "property_override", "component_add",
    "component_replace", "relationship_add_remove", "geometry_operation_add",
    "occurrence_property_override", "constraint_add_remove",
}
APPLIED_CHANGE_TYPES = {"parameter_override", "property_override",
                        "occurrence_property_override"}


class UtomError(Exception):
    """Erreur UTOM typée. .code porte le code stable (ex. UTOM-VAL-002)."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


# ---------------------------------------------------------------------------
# Identité (ADR-0001)
# ---------------------------------------------------------------------------

def uuid7() -> str:
    """UUID v7 : 48 bits d'horodatage unix-ms + aléatoire, version 7."""
    ts = time.time_ns() // 1_000_000
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)
    b = bytearray(16)
    b[0] = (ts >> 40) & 0xFF
    b[1] = (ts >> 32) & 0xFF
    b[2] = (ts >> 24) & 0xFF
    b[3] = (ts >> 16) & 0xFF
    b[4] = (ts >> 8) & 0xFF
    b[5] = ts & 0xFF
    b[6] = 0x70 | ((rand_a >> 8) & 0x0F)
    b[7] = rand_a & 0xFF
    b[8] = 0x80 | ((rand_b >> 56) & 0x3F)
    for i in range(9, 16):
        b[i] = (rand_b >> (8 * (15 - i))) & 0xFF
    h = b.hex()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def new_id() -> str:
    return "urn:uuid:" + uuid7()


# ---------------------------------------------------------------------------
# Sérialisation canonique et empreintes
# ---------------------------------------------------------------------------

def canonical(obj) -> str:
    """Sérialisation canonique : clés triées, séparateurs compacts, UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest_of(obj) -> str:
    return "sha256:" + hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()


def content_digest(obj) -> str:
    """Empreinte du contenu d'une version : l'empreinte portée par
    version.digest est exclue du calcul (sinon auto-référence). C'est la
    valeur que portent Dependency.digest et baseDefinition.digest."""
    o = copy.deepcopy(obj)
    if isinstance(o.get("version"), dict) and "digest" in o["version"]:
        del o["version"]["digest"]
    return digest_of(o)


def parse(text: str):
    return json.loads(text)


def round_trip(obj) -> str:
    """Vérifie la stabilité du round-trip et renvoie le texte canonique."""
    text1 = canonical(obj)
    text2 = canonical(parse(text1))
    if text1 != text2:
        raise UtomError("UTOM-RT-001", "round-trip non stable")
    return text1


# ---------------------------------------------------------------------------
# Validation structurelle minimale
# ---------------------------------------------------------------------------

def _require(cond, code: str, message: str):
    if not cond:
        raise UtomError(code, message)


def validate_label(label, ctx: str = "label"):
    _require(isinstance(label, dict), "UTOM-VAL-001", f"{ctx} : objet multilingue attendu")
    _require("fr" in label, "UTOM-VAL-001", f"{ctx} : libellé français obligatoire")
    for lang, text in label.items():
        _require(isinstance(lang, str) and LANG_RE.match(lang),
                 "UTOM-VAL-001", f"{ctx} : code de langue invalide : {lang!r}")
        _require(isinstance(text, str) and text.strip() != "",
                 "UTOM-VAL-001", f"{ctx} : texte vide pour {lang!r}")


def validate_quantity(q, ctx: str):
    _require(isinstance(q, dict), "UTOM-VAL-002", f"{ctx} : quantity objet attendu")
    v = q.get("value")
    _require(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v),
             "UTOM-VAL-002", f"{ctx} : valeur numérique finie requise")
    u = q.get("unit")
    _require(isinstance(u, str) and u.startswith(QUDT_UNIT_PREFIX),
             "UTOM-VAL-002", f"{ctx} : unité QUDT obligatoire ({QUDT_UNIT_PREFIX}…)")


def validate_provenance(p, ctx: str):
    _require(isinstance(p, dict) and p.get("kind") in PROVENANCE_KINDS,
             "UTOM-VAL-003", f"{ctx} : provenance avec kind connu requise")
    if p.get("kind") == "normative-reference":
        _require(isinstance(p.get("source"), str) and p["source"].strip() != "",
                 "UTOM-VAL-003", f"{ctx} : source obligatoire pour une référence normative")


def validate_classification(c, ctx: str):
    _require(isinstance(c, dict), "UTOM-VAL-004", f"{ctx} : objet attendu")
    _require(isinstance(c.get("scheme"), str) and c["scheme"].strip() != "",
             "UTOM-VAL-004", f"{ctx} : scheme requis")
    _require(isinstance(c.get("code"), str) and c["code"].strip() != "",
             "UTOM-VAL-004", f"{ctx} : code requis")
    if c.get("scheme") in ("ISO", "IEC"):
        _require(isinstance(c.get("edition"), str) and c["edition"].strip() != "",
                 "UTOM-VAL-004", f"{ctx} : édition obligatoire pour ISO/IEC")
    if "matchType" in c:
        _require(c["matchType"] in MATCH_TYPES,
                 "UTOM-VAL-005", f"{ctx} : matchType inconnu : {c['matchType']!r}")


def validate_property_value(pv, ctx: str):
    _require(isinstance(pv, dict), "UTOM-VAL-006", f"{ctx} : objet attendu")
    _require(isinstance(pv.get("property"), str) and pv["property"].strip() != "",
             "UTOM-VAL-006", f"{ctx} : identifiant de propriété requis")
    _require(("value" in pv) != ("quantity" in pv), "UTOM-VAL-006",
             f"{ctx} : exactement un de value/quantity est requis")
    if "quantity" in pv:
        validate_quantity(pv["quantity"], ctx)
    else:
        v = pv["value"]
        if isinstance(v, bool):
            pass  # booléen accepté
        elif isinstance(v, (int, float)):
            raise UtomError("UTOM-VAL-002",
                            f"{ctx} : nombre nu refusé, utiliser quantity avec unité QUDT")
        elif isinstance(v, str):
            pass
        else:
            raise UtomError("UTOM-VAL-006", f"{ctx} : type de valeur non pris en charge")
    _require("provenance" in pv, "UTOM-VAL-003", f"{ctx} : provenance obligatoire")
    validate_provenance(pv["provenance"], ctx)


def validate_dependency(d, ctx: str):
    _require(isinstance(d, dict), "UTOM-VAL-007", f"{ctx} : objet attendu")
    _require(isinstance(d.get("target"), str) and UUID_RE.match(d["target"]),
             "UTOM-VAL-007", f"{ctx} : cible URN UUID v7 requise")
    _require(isinstance(d.get("version"), str) and SEMVER_RE.match(d["version"]),
             "UTOM-VAL-007", f"{ctx} : version sémantique requise")
    _require(isinstance(d.get("digest"), str) and d["digest"].startswith("sha256:"),
             "UTOM-VAL-007", f"{ctx} : empreinte sha256 requise")
    _require(d.get("mode") in DEP_MODES, "UTOM-VAL-007", f"{ctx} : mode inconnu")
    _require(isinstance(d.get("license"), str) and d["license"].strip() != "",
             "UTOM-VAL-007", f"{ctx} : licence requise")


def validate_version(v, ctx: str = "version"):
    _require(isinstance(v, dict) and SEMVER_RE.match(v.get("label", "")),
             "UTOM-VAL-008", f"{ctx} : libellé sémantique requis (x.y.z)")
    _require(isinstance(v.get("digest"), str) and v["digest"].startswith("sha256:"),
             "UTOM-VAL-008", f"{ctx} : empreinte sha256 requise")


def validate_object_definition(obj):
    """Valide une ObjectDefinition (ou un overlay) ; renvoie l'objet."""
    _require(isinstance(obj, dict), "UTOM-VAL-000", "objet JSON attendu")
    _require(obj.get("@type") == UTOM_TYPE, "UTOM-VAL-009", "@type inattendu")
    _require(obj.get("schemaVersion") == SCHEMA_VERSION,
             "UTOM-VAL-010", f"schemaVersion doit être {SCHEMA_VERSION!r}")
    _require(isinstance(obj.get("@id"), str) and UUID_RE.match(obj["@id"]),
             "UTOM-VAL-011", "@id : URN UUID v7 requis")
    validate_version(obj.get("version"), "version")
    validate_label(obj.get("label"), "label")
    if "maturity" in obj:
        m = obj["maturity"]
        _require(isinstance(m, int) and not isinstance(m, bool) and 0 <= m <= 5,
                 "UTOM-VAL-012", "maturity : entier 0..5 requis")
    for i, c in enumerate(obj.get("classification", [])):
        validate_classification(c, f"classification[{i}]")
    for i, pv in enumerate(obj.get("properties", [])):
        validate_property_value(pv, f"properties[{i}]")
    for i, d in enumerate(obj.get("dependencies", [])):
        validate_dependency(d, f"dependencies[{i}]")
    if "baseDefinition" in obj:
        bd = obj["baseDefinition"]
        _require(isinstance(bd, dict)
                 and isinstance(bd.get("target"), str) and UUID_RE.match(bd["target"])
                 and isinstance(bd.get("version"), str) and SEMVER_RE.match(bd["version"])
                 and isinstance(bd.get("digest"), str) and bd["digest"].startswith("sha256:"),
                 "UTOM-VAL-013", "baseDefinition invalide")
        changes = obj.get("changes")
        _require(isinstance(changes, list) and len(changes) > 0,
                 "UTOM-VAL-013", "changes : liste non vide requise pour un overlay")
        for i, ch in enumerate(changes):
            _require(isinstance(ch, dict) and ch.get("type") in CHANGE_TYPES,
                     "UTOM-VAL-014", f"changes[{i}] : type de modification inconnu")
    return obj


# ---------------------------------------------------------------------------
# Versions immuables
# ---------------------------------------------------------------------------

def stamp_version(obj, label: str):
    """Fixe la version : libellé + empreinte du contenu sans empreinte."""
    _require(SEMVER_RE.match(label), "UTOM-VAL-008", "libellé sémantique requis (x.y.z)")
    o = copy.deepcopy(obj)
    o["version"] = {"label": label}
    o["version"] = {"label": label, "digest": digest_of(o)}
    return o


# ---------------------------------------------------------------------------
# Dépendances : linked / embedded / hybrid
# ---------------------------------------------------------------------------

def resolve_dependencies(obj, library: dict):
    """Résout les dépendances. library : {urn: {version, definition}}.

    Aucune mise à jour silencieuse : version et empreinte doivent correspondre.
    L'empreinte attendue est celle de la version cible (contenu sans
    version.digest), cf. content_digest.
    """
    out = {}
    for dep in obj.get("dependencies", []):
        target, mode = dep["target"], dep["mode"]
        if mode in ("embedded", "hybrid") and "embedded" in dep:
            embedded = dep["embedded"]
            if content_digest(embedded) != dep["digest"]:
                raise UtomError("UTOM-DEP-001", f"empreinte embarquée invalide : {target}")
            out[target] = embedded
            continue
        entry = library.get(target)
        if entry is None:
            raise UtomError("UTOM-DEP-002", f"dépendance non résolue : {target}")
        if entry.get("version") != dep["version"]:
            raise UtomError("UTOM-DEP-004",
                            f"version différente pour {target} : "
                            f"{entry.get('version')!r} != {dep['version']!r}")
        definition = entry.get("definition")
        if content_digest(definition) != dep["digest"]:
            raise UtomError("UTOM-DEP-001", f"empreinte invalide pour {target}")
        out[target] = definition
    return out


# ---------------------------------------------------------------------------
# Overlays non destructifs
# ---------------------------------------------------------------------------

def apply_overlay(base, overlay):
    """Applique un overlay à une base immuable et renvoie la vue résolue.

    La base n'est jamais modifiée. Les types de modification appliqués en v0.1 :
    parameter_override / property_override / occurrence_property_override.
    Les autres (component_add, geometry_operation_add, …) sont déclarés et
    conservés dans « declaredChanges » sans être appliqués (hors périmètre).
    """
    validate_object_definition(base)
    _require("baseDefinition" not in base, "UTOM-OVL-004",
             "overlay sur overlay non pris en charge en v0.1")
    validate_object_definition(overlay)
    bd = overlay["baseDefinition"]
    _require(bd["target"] == base["@id"], "UTOM-OVL-002",
             "la cible de l'overlay diffère de la base")
    _require(bd["digest"] == content_digest(base), "UTOM-OVL-001",
             "empreinte de base invalide : la base référencée n'est pas celle-ci")
    resolved = copy.deepcopy(base)
    declared = []
    for ch in overlay.get("changes", []):
        t = ch["type"]
        if t in APPLIED_CHANGE_TYPES:
            target = ch.get("target")
            found = False
            for pv in resolved.setdefault("properties", []):
                if pv.get("property") == target:
                    if "quantity" in ch:
                        pv.pop("value", None)
                        pv["quantity"] = copy.deepcopy(ch["quantity"])
                    elif "value" in ch:
                        pv.pop("quantity", None)
                        pv["value"] = ch["value"]
                    if "provenance" in ch:
                        pv["provenance"] = copy.deepcopy(ch["provenance"])
                    validate_property_value(pv, "overlay")
                    found = True
                    break
            if not found:
                raise UtomError("UTOM-OVL-003", f"cible de surcharge introuvable : {target!r}")
        else:
            declared.append(copy.deepcopy(ch))
    if declared:
        resolved["declaredChanges"] = declared
    return resolved


# ---------------------------------------------------------------------------
# Exemple de référence : vis hexagonale M8 × 30 (ISO 4017)
# ---------------------------------------------------------------------------

def make_screw_example():
    """Exemple de la spécification §8. Les éditions ISO sont à confirmer."""
    return {
        "@id": new_id(),
        "@type": UTOM_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "label": {"fr": "Vis hexagonale M8 × 30",
                  "en": "Hexagon head screw M8 × 30",
                  "nl": "Zeskantbout M8 × 30"},
        "domain": "mechanical",
        "maturity": 1,
        "classification": [
            {"scheme": "ISO", "code": "4017", "edition": "to-confirm",
             "matchType": "exact"},
        ],
        "properties": [
            {"property": "uto:p/threadDesignation", "value": "M8",
             "provenance": {"kind": "normative-reference", "source": "ISO 4017",
                            "edition": "to-confirm"}},
            {"property": "uto:p/nominalLength",
             "quantity": {"value": 30, "unit": MM},
             "provenance": {"kind": "normative-reference", "source": "ISO 4017",
                            "edition": "to-confirm"}},
            {"property": "uto:p/propertyClass", "value": "8.8",
             "provenance": {"kind": "normative-reference", "source": "ISO 898-1",
                            "edition": "to-confirm"}},
        ],
        "geometryRecipe": {
            "generator": "utom:mechanical/hex-head-screw",
            "generatorVersion": "0.1",
            "inputs": {"thread": "uto:p/threadDesignation",
                       "length": "uto:p/nominalLength"},
            "status": "unspecified",
        },
        "representations": [],
        "dependencies": [],
    }


def make_hinge_example():
    """Définition minimale de charnière, servie comme dépendance de test."""
    return {
        "@id": new_id(),
        "@type": UTOM_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "label": {"fr": "Charnière modèle A", "en": "Hinge model A"},
        "domain": "mechanical",
        "maturity": 1,
        "properties": [
            {"property": "uto:p/leafThickness",
             "quantity": {"value": 3, "unit": MM},
             "provenance": {"kind": "manufacturer-data", "source": "fiche fabricant"}},
        ],
    }


# ---------------------------------------------------------------------------
# Tests d'acceptation (spécification §9.2)
# ---------------------------------------------------------------------------

def expect_error(fn, code: str, test_name: str) -> None:
    try:
        fn()
    except UtomError as e:
        if e.code != code:
            raise AssertionError(
                f"{test_name} : code attendu {code}, obtenu {e.code} ({e})")
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

    def t_uuid7():
        u = new_id()
        assert UUID_RE.match(u), f"format UUID v7 invalide : {u}"

    def t_round_trip():
        obj = stamp_version(make_screw_example(), "1.0.0")
        validate_object_definition(obj)
        text1 = round_trip(obj)
        assert digest_of(obj) == digest_of(parse(text1)), "empreinte instable au round-trip"
        assert canonical(parse(text1)) == text1, "sérialisation non canonique"

    def t_dependencies():
        hinge = stamp_version(make_hinge_example(), "2.1.0")
        library = {hinge["@id"]: {"version": "2.1.0", "definition": hinge}}
        base = make_screw_example()

        linked = copy.deepcopy(base)
        linked["dependencies"] = [{
            "@id": new_id(), "target": hinge["@id"], "version": "2.1.0",
            "digest": hinge["version"]["digest"], "mode": "linked",
            "license": "CC0-1.0",
        }]
        resolved = resolve_dependencies(linked, library)
        assert hinge["@id"] in resolved, "dépendance liée non résolue"

        embedded = copy.deepcopy(base)
        embedded["dependencies"] = [{
            "@id": new_id(), "target": hinge["@id"], "version": "2.1.0",
            "digest": hinge["version"]["digest"], "mode": "embedded",
            "license": "CC0-1.0", "embedded": copy.deepcopy(hinge),
        }]
        resolved = resolve_dependencies(embedded, {})
        assert hinge["@id"] in resolved, "dépendance embarquée non résolue"

        bad = copy.deepcopy(linked)
        bad["dependencies"][0]["digest"] = "sha256:" + "0" * 64
        expect_error(lambda: resolve_dependencies(bad, library),
                     "UTOM-DEP-001", "empreinte fausse")

        missing = copy.deepcopy(linked)
        expect_error(lambda: resolve_dependencies(missing, {}),
                     "UTOM-DEP-002", "dépendance non résolue")

    def t_overlay():
        base = stamp_version(make_screw_example(), "1.0.0")
        digest_before = digest_of(base)
        overlay = {
            "@id": new_id(), "@type": UTOM_TYPE, "schemaVersion": SCHEMA_VERSION,
            "label": {"fr": "Vis M8 × 40 (variante atelier)"},
            "version": {"label": "1.0.0", "digest": "sha256:" + "1" * 64},
            "baseDefinition": {"target": base["@id"], "version": "1.0.0",
                               "digest": base["version"]["digest"]},
            "changes": [
                {"type": "parameter_override", "target": "uto:p/nominalLength",
                 "quantity": {"value": 40, "unit": MM},
                 "provenance": {"kind": "manual-entry", "author": "atelier"}},
                {"type": "geometry_operation_add", "id": "hex-socket"},
            ],
        }
        resolved = apply_overlay(base, overlay)
        assert digest_of(base) == digest_before, "la base a été modifiée"
        lengths = [p for p in resolved["properties"]
                   if p["property"] == "uto:p/nominalLength"]
        assert len(lengths) == 1 and lengths[0]["quantity"]["value"] == 40, \
            "surcharge de paramètre non appliquée"
        assert resolved["declaredChanges"][0]["id"] == "hex-socket", \
            "modification déclarée perdue"
        bad_overlay = copy.deepcopy(overlay)
        bad_overlay["baseDefinition"]["digest"] = "sha256:" + "2" * 64
        expect_error(lambda: apply_overlay(base, bad_overlay),
                     "UTOM-OVL-001", "empreinte de base invalide")

    def t_bare_number_rejected():
        pv = {"property": "uto:p/nominalLength", "value": 30,
              "provenance": {"kind": "manual-entry"}}
        expect_error(lambda: validate_property_value(pv, "test"),
                     "UTOM-VAL-002", "nombre nu refusé")

    def t_label_fr_required():
        obj = stamp_version(make_screw_example(), "0.1.0")
        obj["label"] = {"en": "Hexagon head screw"}
        expect_error(lambda: validate_object_definition(obj),
                     "UTOM-VAL-001", "libellé français obligatoire")

    def t_iso_edition_required():
        obj = stamp_version(make_screw_example(), "0.1.0")
        obj["classification"][0].pop("edition")
        expect_error(lambda: validate_object_definition(obj),
                     "UTOM-VAL-004", "édition ISO obligatoire")

    def t_stamp_version_consistent():
        obj = make_screw_example()
        stamped = stamp_version(obj, "0.1.0")
        without = copy.deepcopy(stamped)
        without["version"].pop("digest")
        assert stamped["version"]["digest"] == digest_of(without), \
            "empreinte de version incohérente"

    run("uuid7 : format URN UUID v7", t_uuid7)
    run("round-trip : sérialisation canonique stable", t_round_trip)
    run("dépendances : linked / embedded / empreintes", t_dependencies)
    run("overlay : non destructif et tracé", t_overlay)
    run("valeur sans unité refusée", t_bare_number_rejected)
    run("label sans français refusé", t_label_fr_required)
    run("classification ISO sans édition refusée", t_iso_edition_required)
    run("stamp_version : empreinte cohérente", t_stamp_version_consistent)
    return failures


def main() -> int:
    print("UTOM Core v0.1 — tests d'acceptation")
    failures = run_tests()
    if failures:
        print(f"\nRÉSULTAT : {failures} échec(s)")
        return 1
    print("\nRÉSULTAT : tous les tests passent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
