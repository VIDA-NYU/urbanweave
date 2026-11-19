"""Plans: versioned JSON recipes of steps, run live or replayed from a pinned run manifest.

A plan names its targets (specs), its runtime sources (bound when it runs), and its steps. Each step
has a unique ``id``; ``"@<id>"`` refers to an earlier step's output, and ``{"target": "<name>"}``
reads a target's geometry as a step's source. Steps are:

``match`` + ``aggregate``
    ``{"id", "source", "match": {"method", "target", ...params}, "aggregate": [reductions]}``
``convert``
    ``{"id", "source", "convert": {"method": "split_lines" | "along_lines" | "zonal_stats", "target", ...}}``
``reduce``
    ``{"id", "source": "@<id>", "reduce": {"by", "target", "aggregate": [ratio_of_sums, sum]}}``

Target kinds: ``h3`` (``resolution``, ``extent`` as a box or ``"source:<name>"``), ``zones`` or
``file`` (``path``), ``osm_streets`` / ``osm_intersections`` (``graphml`` path, or live ``place`` /
``bbox``), ``raster_file`` (``path``). Relative paths resolve against the plan file's folder.

**Preflight.** :meth:`Plan.validate` checks the version, step IDs and references (no forward
references), target and source names, methods and their parameters, reductions, duplicate output
names, and declared value kinds and units, before anything runs. Bound columns, units and value
kinds are checked again against the actual data before each step.

**Reproducibility.** With a ``cache`` folder, :meth:`Plan.run` stores every input as an immutable
artifact named by its fingerprint (the SHA-256 of a file's content, or of a deterministic snapshot
of an in-memory frame or array), records which artifact each target request resolved to, and writes
a run manifest (atomically) with the evaluated arguments and defaults, source and target
fingerprints, package and engine versions, CRSs and each step's report. :func:`replay` reruns a
manifest from its pinned artifacts after verifying their fingerprints and the engine versions, and
names every artifact that is stale, changed, missing or unavailable. Resolving a live target again
is a separate run (:meth:`Plan.run`), never a silent part of a replay.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import importlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import pyproj
import shapely

from ._version import __version__
from .aggregation import REDUCERS, aggregate, check_reduction
from .errors import InputError, PlanError, UnsupportedError, UrbanweaveError
from .matching import METHODS, match
from .reducers import Reduction
from .reports import plain

PLAN_VERSION = 1
MANIFEST_VERSION = 1
CONVERT_METHODS = ("split_lines", "along_lines", "zonal_stats")
TARGET_KINDS = ("h3", "zones", "file", "osm_streets", "osm_intersections", "raster_file")
_ENGINES = ("numpy", "pandas", "shapely", "geopandas", "pyproj", "h3", "rasterio", "exactextract", "osmnx", "networkx")

#: The value kind each reduction's output has, for checking later steps.
_OUTPUT_KIND = {"count": "extensive", "weighted_count": "extensive", "sum": "extensive", "density": "intensive",
                "mean": "intensive", "weighted_mean": "intensive", "median": "intensive", "weighted_median": "intensive",
                "min": None, "max": None, "majority": "categorical", "shares": "intensive", "first": None, "last": None,
                "join": "categorical", "ratio_of_sums": "intensive"}


# ----------------------------------------------------------------------------------------------
# Fingerprints and snapshots.


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_fingerprint(path) -> str:
    """SHA-256 of a file's content, or of a folder's files (names and contents, sorted)."""
    path = Path(path)
    h = hashlib.sha256()
    files = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
    if not files:
        raise PlanError(f"{path} does not exist or is empty.")
    for f in files:
        if path.is_dir():
            h.update(str(f.relative_to(path)).encode() + b"\0")
        with open(f, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()


def _json_value(v):
    if v is None or v is pd.NA or v is pd.NaT:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return None if np.isnan(f) else repr(f) if not np.isfinite(f) else f
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, (pd.Timestamp, _dt.datetime, _dt.date)):
        return v.isoformat()
    if isinstance(v, (list, tuple)):
        return [_json_value(x) for x in v]
    return v


def frame_snapshot(frame: pd.DataFrame) -> bytes:
    """A deterministic text snapshot of a (Geo)DataFrame: schema, index, columns, geometry as WKB hex."""
    geometry = frame.geometry.name if isinstance(frame, gpd.GeoDataFrame) else None
    columns = [c for c in frame.columns if c != geometry]
    doc = {
        "format": "urbanweave-frame-snapshot/1",
        "index": {"name": frame.index.name, "dtype": str(frame.index.dtype), "values": [_json_value(v) for v in frame.index]},
        "columns": [{"name": str(c), "dtype": str(frame[c].dtype), "values": [_json_value(v) for v in frame[c].tolist()]}
                    for c in columns],
    }
    if geometry is not None:
        doc["geometry"] = {"name": geometry, "crs": frame.crs.to_wkt() if frame.crs else None,
                           "wkb_hex": [None if g is None else shapely.to_wkb(g, hex=True, byte_order=1)
                                       for g in frame.geometry.array]}
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def frame_from_snapshot(data: bytes) -> pd.DataFrame:
    doc = json.loads(data)
    cols = {}
    for c in doc["columns"]:
        s = pd.Series(c["values"], dtype=object)
        try:
            s = s.astype(c["dtype"])
        except (TypeError, ValueError):
            pass
        cols[c["name"]] = s
    idx = pd.Index(doc["index"]["values"], name=doc["index"]["name"])
    try:
        idx = idx.astype(doc["index"]["dtype"])
    except (TypeError, ValueError):
        pass
    df = pd.DataFrame(cols)
    df.index = idx
    if "geometry" in doc:
        g = doc["geometry"]
        geoms = gpd.GeoSeries([None if h is None else shapely.from_wkb(h) for h in g["wkb_hex"]], index=idx, crs=g["crs"])
        out = gpd.GeoDataFrame(df, geometry=geoms)
        return out.rename_geometry(g["name"]) if g["name"] != "geometry" else out
    return df


def raster_snapshot(raster) -> tuple[bytes, bytes]:
    """(array .npy bytes, metadata JSON bytes) of an in-memory raster: deterministic."""
    import io

    buf = io.BytesIO()
    np.save(buf, np.ascontiguousarray(raster.array), allow_pickle=False)
    vbuf = io.BytesIO()
    np.save(vbuf, np.ascontiguousarray(raster.valid if raster.valid is not None else np.ones(raster.array.shape, bool)),
            allow_pickle=False)
    meta = {"format": "urbanweave-raster-snapshot/1", "transform": list(raster.transform)[:6], "crs": raster.crs.to_wkt(),
            "bands": [b.to_dict() for b in raster.bands], "valid_sha256": _sha256(vbuf.getvalue())}
    return buf.getvalue() + vbuf.getvalue(), json.dumps(meta, sort_keys=True).encode()


def engine_versions() -> dict:
    out = {"urbanweave": __version__}
    for name in _ENGINES:
        try:
            out[name] = importlib.import_module(name).__version__
        except Exception:  # noqa: BLE001 - an optional engine that is absent
            continue
    return out


# ----------------------------------------------------------------------------------------------
# The artifact cache.


class Cache:
    """Immutable artifacts by fingerprint, and the resolutions that map target requests to them."""

    def __init__(self, root):
        self.root = Path(root)
        (self.root / "artifacts").mkdir(parents=True, exist_ok=True)
        (self.root / "resolutions").mkdir(parents=True, exist_ok=True)
        (self.root / "manifests").mkdir(parents=True, exist_ok=True)

    def path(self, fingerprint: str) -> Path:
        return self.root / "artifacts" / fingerprint

    def has(self, fingerprint: str) -> bool:
        return (self.path(fingerprint) / "artifact.json").exists()

    def put_files(self, fingerprint: str, files: dict[str, bytes | Path], info: dict) -> Path:
        """Store an artifact atomically (written in a temporary folder, then renamed)."""
        dest = self.path(fingerprint)
        if self.has(fingerprint):
            return dest
        tmp = Path(tempfile.mkdtemp(dir=self.root / "artifacts", prefix=".tmp-"))
        for name, content in files.items():
            target = tmp / name
            if isinstance(content, Path):
                shutil.copy2(content, target)
            else:
                target.write_bytes(content)
        (tmp / "artifact.json").write_text(json.dumps(plain(info | {"fingerprint": fingerprint}), indent=1, sort_keys=True))
        try:
            os.replace(tmp, dest)
        except OSError:
            shutil.rmtree(tmp, ignore_errors=True)  # another writer stored it first
        return dest

    def info(self, fingerprint: str) -> dict:
        return json.loads((self.path(fingerprint) / "artifact.json").read_text())

    def record_resolution(self, request_key: str, spec: dict, fingerprint: str) -> None:
        p = self.root / "resolutions" / f"{request_key}.json"
        history = json.loads(p.read_text()) if p.exists() else {"spec": spec, "resolutions": []}
        if not history["resolutions"] or history["resolutions"][-1]["fingerprint"] != fingerprint:
            history["resolutions"].append({"fingerprint": fingerprint, "resolved_at": _now()})
        _atomic_write(p, json.dumps(history, indent=1, sort_keys=True).encode())

    def resolutions(self, request_key: str) -> list:
        p = self.root / "resolutions" / f"{request_key}.json"
        return json.loads(p.read_text())["resolutions"] if p.exists() else []


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)


# ----------------------------------------------------------------------------------------------
# Inputs: what a source or target resolves to, and how it is stored and verified.


class _Input:
    """A resolved input: its object, kind, fingerprint and how to store it."""

    def __init__(self, obj, kind: str, fingerprint: str, origin: str, files: dict, info: dict):
        self.obj = obj
        self.kind = kind  # "vector" or "raster"
        self.fingerprint = fingerprint
        self.origin = origin  # "file" or "memory"
        self.files = files
        self.info = info


_RASTER_SUFFIXES = (".tif", ".tiff", ".vrt", ".img", ".nc")


def _resolve_object(obj, *, base: Path, selector: dict | None = None) -> _Input:
    from .raster import Raster  # noqa: F401 - optional

    selector = selector or {}
    if isinstance(obj, (str, Path)):
        path = Path(obj)
        path = path if path.is_absolute() else base / path
        if not path.exists():
            raise PlanError(f"Input file {path} does not exist.")
        fp = file_fingerprint(path)
        kind = "raster" if path.suffix.lower() in _RASTER_SUFFIXES else "vector"
        return _Input(path, kind, fp, "file", {path.name: path}, {"kind": kind, "origin": "file", "name": path.name,
                                                                  "selector": selector})
    if isinstance(obj, pd.DataFrame):
        data = frame_snapshot(obj)
        fp = _sha256(data)
        return _Input(obj, "vector", fp, "memory", {"frame.json": data}, {"kind": "vector", "origin": "memory",
                                                                          "format": "urbanweave-frame-snapshot/1"})
    try:
        from .raster import Raster
    except ImportError:
        Raster = ()  # noqa: N806
    if Raster and isinstance(obj, Raster):
        if obj.dataset is not None and getattr(obj.dataset, "name", None) and Path(obj.dataset.name).exists():
            path = Path(obj.dataset.name)
            sel = {"bands": [b.index for b in obj.bands]} | selector
            return _Input(obj, "raster", file_fingerprint(path), "file", {path.name: path},
                          {"kind": "raster", "origin": "file", "name": path.name, "selector": sel})
        arr, meta = raster_snapshot(obj)
        fp = _sha256(arr + meta)
        return _Input(obj, "raster", fp, "memory", {"raster.npy": arr, "raster.json": meta},
                      {"kind": "raster", "origin": "memory", "format": "urbanweave-raster-snapshot/1"})
    raise PlanError(f"Cannot bind {type(obj).__name__} as a plan input; give a GeoDataFrame, a Raster, or a file path.")


def _load_artifact(cache: Cache, fingerprint: str):
    """The object stored as an artifact, after checking its content still has its fingerprint."""
    if not cache.has(fingerprint):
        raise PlanError(f"artifact {fingerprint[:12]} is missing from the cache")
    info = cache.info(fingerprint)
    folder = cache.path(fingerprint)
    if info["origin"] == "file":
        path = folder / info["name"]
        if file_fingerprint(path) != fingerprint:
            raise PlanError(f"artifact {fingerprint[:12]} ({info['name']}) changed in the cache")
        if info["kind"] == "raster":
            from .raster import read_raster

            return read_raster(path, bands=info.get("selector", {}).get("bands")), path
        return path, path
    if info["kind"] == "vector":
        data = (folder / "frame.json").read_bytes()
        if _sha256(data) != fingerprint:
            raise PlanError(f"artifact {fingerprint[:12]} changed in the cache")
        return frame_from_snapshot(data), None
    arr_bytes = (folder / "raster.npy").read_bytes()
    meta_bytes = (folder / "raster.json").read_bytes()
    if _sha256(arr_bytes + meta_bytes) != fingerprint:
        raise PlanError(f"artifact {fingerprint[:12]} changed in the cache")
    import io

    from rasterio.transform import Affine

    from .raster import Band, Raster

    meta = json.loads(meta_bytes)
    buf = io.BytesIO(arr_bytes)
    arr = np.load(buf, allow_pickle=False)
    valid = np.load(buf, allow_pickle=False)
    bands = [Band(**{k: v for k, v in b.items()}) for b in meta["bands"]]
    return Raster(transform=Affine(*meta["transform"]), crs=pyproj.CRS.from_wkt(meta["crs"]), width=arr.shape[2],
                  height=arr.shape[1], bands=bands, array=arr, valid=valid), None


def _read_vector(path: Path, spec: dict | None = None) -> gpd.GeoDataFrame:
    if str(path).endswith(".graphml"):
        raise PlanError("A GraphML file is a street target's input, not a vector source.")
    return gpd.read_file(path, layer=(spec or {}).get("layer"))


# ----------------------------------------------------------------------------------------------
# The plan.


def _canonical(obj) -> str:
    return json.dumps(plain(obj), sort_keys=True, separators=(",", ":"))


def _ref(value) -> tuple[str, str]:
    """('step', id), ('target', name) or ('source', name) for a step's source or target slot."""
    if isinstance(value, dict):
        if set(value) != {"target"}:
            raise PlanError(f"A source given as an object must be {{'target': <name>}}, not {value!r}.")
        return "target", value["target"]
    if not isinstance(value, str) or not value:
        raise PlanError(f"A reference must be a name or '@<step id>', not {value!r}.")
    if value.startswith("@"):
        return "step", value[1:]
    return "name", value


class Plan:
    """A plan (see the module docstring). Build one with :meth:`from_json` or from a dict."""

    def __init__(self, spec: dict, *, base_dir=None):
        if not isinstance(spec, dict):
            raise PlanError("A plan is a JSON object.")
        self.spec = json.loads(json.dumps(spec))  # a private copy
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()

    @classmethod
    def from_json(cls, source) -> "Plan":
        if isinstance(source, dict):
            return cls(source)
        text, base = None, None
        if isinstance(source, Path) or (isinstance(source, str) and not source.lstrip().startswith("{")):
            path = Path(source)
            text, base = path.read_text(), path.resolve().parent
        else:
            text = source
        try:
            spec = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PlanError(f"The plan is not valid JSON: {exc}") from None
        return cls(spec, base_dir=base)

    def to_json(self, **kwargs) -> str:
        return json.dumps(self.spec, **kwargs)

    @property
    def fingerprint(self) -> str:
        return _sha256(_canonical(self.spec).encode())

    # -- preflight -------------------------------------------------------------------------

    def validate(self, source_names=None) -> None:
        """Check the plan before running it; raise :class:`PlanError` naming every problem."""
        problems = self._problems(source_names)
        if problems:
            raise PlanError("The plan is not valid:\n- " + "\n- ".join(problems))

    def _problems(self, source_names=None) -> list[str]:
        p: list[str] = []
        s = self.spec
        if s.get("version") != PLAN_VERSION:
            p.append(f"version must be {PLAN_VERSION}, not {s.get('version')!r}.")
        targets = s.get("targets", {}) or {}
        declared = s.get("sources", {}) or {}
        names = set(declared) | set(source_names or [])
        for name, t in targets.items():
            if not isinstance(t, dict) or t.get("kind") not in TARGET_KINDS:
                p.append(f"target {name!r}: kind must be one of {', '.join(TARGET_KINDS)}.")
        kinds: dict[str, dict] = {name: dict((d or {}).get("columns", {})) for name, d in declared.items()}
        seen: list[str] = []
        steps = s.get("steps")
        if not isinstance(steps, list) or not steps:
            p.append("steps must be a non-empty list.")
            return p
        for i, step in enumerate(steps):
            sid = step.get("id") if isinstance(step, dict) else None
            where = f"step {sid or i + 1}"
            if not sid or not isinstance(sid, str):
                p.append(f"step {i + 1} has no id.")
                continue
            if sid in seen:
                p.append(f"{where}: id repeats.")
            ops = [k for k in ("match", "convert", "reduce") if k in step]
            if len(ops) != 1:
                p.append(f"{where}: needs exactly one of match, convert or reduce.")
                seen.append(sid)
                continue
            op = ops[0]
            body = step[op]
            src_cols: dict = {}
            try:
                kind, ref = _ref(step.get("source"))
                if kind == "step":
                    if ref not in seen:
                        p.append(f"{where}: source @{ref} is not an earlier step (forward or unknown reference).")
                    src_cols = kinds.get("@" + ref, {})
                elif kind == "target":
                    if ref not in targets:
                        p.append(f"{where}: unknown target {ref!r}.")
                elif source_names is not None and ref not in names:
                    p.append(f"{where}: source {ref!r} is not bound.")
                elif kind == "name":
                    src_cols = kinds.get(ref, {})
            except PlanError as exc:
                p.append(f"{where}: {exc}")
            tgt = body.get("target") if isinstance(body, dict) else None
            if tgt is None:
                p.append(f"{where}: {op} needs a target.")
            else:
                tk, tref = _ref(tgt)
                if tk == "step" and tref not in seen:
                    p.append(f"{where}: target @{tref} is not an earlier step.")
                elif tk == "name" and tref not in targets:
                    p.append(f"{where}: unknown target {tref!r}.")
            out_cols: dict = {}
            reds = []
            if op == "match":
                method = body.get("method")
                spec = METHODS.get(method)
                if spec is None:
                    p.append(f"{where}: unknown matching method {method!r}.")
                else:
                    params = {k: v for k, v in body.items() if k not in ("method", "target", "source_id", "target_id", "crs")}
                    try:
                        spec.check_params(params)
                    except UrbanweaveError as exc:
                        p.append(f"{where}: {exc}")
                reds = step.get("aggregate") or []
                if not reds:
                    p.append(f"{where}: a match step needs aggregate.")
            elif op == "convert":
                method = body.get("method")
                if method not in CONVERT_METHODS:
                    p.append(f"{where}: unknown conversion {method!r}.")
                reds = body.get("aggregate") or []
                if method in ("along_lines", "zonal_stats") and not reds:
                    p.append(f"{where}: {method} needs aggregate.")
            else:
                if not body.get("by"):
                    p.append(f"{where}: reduce needs by.")
                reds = body.get("aggregate") or []
            aliases = []
            for rd in reds:
                try:
                    r = Reduction.from_dict(rd)
                except (KeyError, TypeError):
                    p.append(f"{where}: a reduction must have a method.")
                    continue
                if r.method == "ratio_of_sums":
                    num, den = r.options.get("numerator"), r.options.get("denominator")
                    unum = (src_cols.get(str(num)) or {}).get("units")
                    uden = (src_cols.get(str(den)) or {}).get("units")
                    derived = None
                    if unum and uden:
                        derived = unum[: -len("*" + uden)] if unum.endswith("*" + uden) else f"{unum}/{uden}"
                    want = r.options.get("units")
                    if want and derived and want != derived:
                        p.append(f"{where}: {r.alias} would be in {derived}, not the declared {want} (incompatible units).")
                    out_cols[r.alias] = {"kind": "intensive", "units": want or derived}
                    aliases.append(r.alias)
                    continue
                if r.method not in REDUCERS:
                    p.append(f"{where}: unknown reduction {r.method!r}.")
                    continue
                kinds_known = {c: d.get("kind") for c, d in src_cols.items() if d.get("kind")}
                if r.column is not None and str(r.column) in kinds_known:
                    kinds_known[r.column] = kinds_known[str(r.column)]
                try:
                    check_reduction(r, None, kinds_known, None)
                except UrbanweaveError as exc:
                    p.append(f"{where}: {exc}")
                col = src_cols.get(str(r.column)) or {}
                if r.options.get("units"):
                    have = col.get("units")
                    if have and r.method in ("sum", "mean", "weighted_mean", "min", "max", "median") and have != r.options["units"]:
                        p.append(f"{where}: {r.alias} would be in {have}, not the declared {r.options['units']} (incompatible units).")
                aliases.append(r.alias)
                col_units = col.get("units")
                out_cols[r.alias] = {"kind": _OUTPUT_KIND.get(r.method) or col.get("kind"),
                                     "units": r.options.get("units") or (col_units if r.method not in ("count", "weighted_count", "shares", "density") else None)}
                if r.options.get("weighted_total_as"):
                    aliases.append(r.options["weighted_total_as"])
                    out_cols[r.options["weighted_total_as"]] = {"kind": "extensive", "units": f"{col_units}*m" if col_units else None}
                if r.options.get("valid_measure_as"):
                    aliases.append(r.options["valid_measure_as"])
                    out_cols[r.options["valid_measure_as"]] = {"kind": "extensive", "units": "m"}
            dup = sorted({a for a in aliases if aliases.count(a) > 1})
            if dup:
                p.append(f"{where}: output names repeat: {', '.join(dup)}.")
            kinds["@" + sid] = {**({} if op != "convert" else src_cols), **out_cols}
            seen.append(sid)
        return p

    # -- running -----------------------------------------------------------------------------

    def run(self, sources: dict | None = None, *, cache=None, manifest_path=None, snapshot: bool = True) -> "PlanRun":
        """Run the plan live: resolve targets anew and bind *sources* (name -> frame, Raster or path).

        With *cache* (a folder), inputs are stored as artifacts and a run manifest is written
        (to *manifest_path*, or under the cache's ``manifests``). ``snapshot=False`` keeps in-memory
        sources out of the cache: a replay then needs them supplied again, and verifies them.
        """
        sources = dict(sources or {})
        self.validate(source_names=list(sources) + list((self.spec.get("sources") or {})))
        store = Cache(cache) if cache is not None else None
        bound = {}
        for name, obj in sources.items():
            inp = _resolve_object(obj, base=self.base_dir)
            if store is not None and (snapshot or inp.origin == "file"):
                store.put_files(inp.fingerprint, inp.files, inp.info)
            inp.info["snapshotted"] = bool(store is not None and (snapshot or inp.origin == "file"))
            bound[name] = inp
        targets = {}
        for name, tspec in (self.spec.get("targets") or {}).items():
            targets[name] = self._resolve_target(name, tspec, bound, store)
        return self._execute(bound, targets, store, manifest_path, mode="live")

    def _resolve_target(self, name, tspec, bound, store):
        kind = tspec["kind"]
        request_key = _sha256(_canonical(tspec).encode())
        from . import targets as T

        if kind == "h3":
            extent = tspec.get("extent")
            if isinstance(extent, str) and extent.startswith("source:"):
                src = bound.get(extent.split(":", 1)[1])
                if src is None:
                    raise PlanError(f"target {name!r}: extent {extent!r} names no bound source.")
                obj = src.obj if not isinstance(src.obj, Path) else _read_vector(src.obj)
                extent = obj
            frame = T.h3_cells(extent, int(tspec["resolution"]), cover=tspec.get("cover", "bbox"))
            inp = _resolve_object(frame, base=self.base_dir)
            inp.obj = frame
        elif kind in ("zones", "file", "raster_file"):
            path = Path(tspec["path"])
            inp = _resolve_object(path, base=self.base_dir, selector={k: v for k, v in tspec.items() if k in ("bands", "layer")})
        elif kind in ("osm_streets", "osm_intersections"):
            from . import streets as S

            if tspec.get("graphml"):
                gpath = Path(tspec["graphml"])
                gpath = gpath if gpath.is_absolute() else self.base_dir / gpath
                fp_file = file_fingerprint(gpath)
                build = S.osm_streets if kind == "osm_streets" else S.osm_intersections
                kw = {"representation": tspec.get("representation", "physical")} if kind == "osm_streets" else {"min_degree": tspec.get("min_degree", 3)}
                frame = build(graphml=gpath, **kw)
                inp = _resolve_object(frame, base=self.base_dir)
                inp.info["built_from"] = {"graphml": gpath.name, "fingerprint": fp_file}
            else:
                build = S.osm_streets if kind == "osm_streets" else S.osm_intersections
                kw = {k: tspec[k] for k in ("place", "bbox", "network_type") if k in tspec}
                if kind == "osm_streets":
                    kw["representation"] = tspec.get("representation", "physical")
                frame = build(**kw)
                inp = _resolve_object(frame, base=self.base_dir)
                inp.info["built_from"] = {"live": True}
        else:
            raise PlanError(f"target {name!r}: unknown kind {kind!r}.")
        inp.info.update({"target_kind": kind, "request_key": request_key, "snapshotted": store is not None})
        if store is not None:
            store.put_files(inp.fingerprint, inp.files, inp.info)
            store.record_resolution(request_key, tspec, inp.fingerprint)
        return inp

    def _execute(self, bound: dict, targets: dict, store, manifest_path, *, mode: str) -> "PlanRun":
        outputs: dict[str, Any] = {}
        reports: dict[str, Any] = {}
        evaluated = []
        cache_objs: dict = {}

        def obj_of(inp):
            if isinstance(inp.obj, Path):
                if inp.kind == "raster":
                    from .raster import read_raster

                    return read_raster(inp.obj, bands=inp.info.get("selector", {}).get("bands"))
                key = id(inp)
                if key not in cache_objs:
                    cache_objs[key] = _read_vector(inp.obj, inp.info.get("selector"))
                return cache_objs[key]
            return inp.obj

        def resolve(slot):
            kind, ref = _ref(slot)
            if kind == "step":
                return outputs[ref]
            if kind == "target":
                return obj_of(targets[ref])
            if ref in bound:
                return obj_of(bound[ref])
            if ref in targets:
                return obj_of(targets[ref])
            raise PlanError(f"{ref!r} is neither a bound source nor a target.")

        declared = {name: dict((d or {}).get("columns", {})) for name, d in (self.spec.get("sources") or {}).items()}
        for step in self.spec["steps"]:
            sid = step["id"]
            source = resolve(step["source"])
            if "match" in step:
                body = dict(step["match"])
                method = body.pop("method")
                tgt = resolve(body.pop("target"))
                kw = {k: body.pop(k) for k in ("source_id", "target_id", "crs") if k in body}
                reds = [Reduction.from_dict(r) for r in step["aggregate"]]
                kinds = {}
                src_name = step["source"] if isinstance(step["source"], str) else None
                for c, d in declared.get(src_name, {}).items():
                    if d.get("kind"):
                        kinds[c] = d["kind"]
                m = match(source, tgt, method, **kw, **body)
                out = aggregate(m, None, reds, value_kinds=kinds)
                ev = {"op": "match", "method": method, "params": plain(m.params), "measurement": m.measurement.to_dict(),
                      "aggregate": [r.to_dict() for r in reds]}
            elif "convert" in step:
                body = dict(step["convert"])
                method = body.pop("method")
                tgt = resolve(body.pop("target"))
                reds = [Reduction.from_dict(r) for r in body.pop("aggregate", [])]
                if method == "split_lines":
                    from .streets import split_lines

                    params = {"shared_boundary": body.get("shared_boundary", "lowest_target_id")}
                    out = split_lines(source, tgt, **params)
                elif method == "along_lines":
                    from .streets import along_lines

                    params = {"coverage_as": body.get("coverage_as", "valid_fraction")}
                    out = along_lines(source, tgt, reds, **params)
                else:
                    from .raster import zonal_stats

                    params = {"method": body.get("rule", "cell_coverage"),
                              "coverage_as": body.get("coverage_as", "coverage")}
                    out = zonal_stats(source, tgt, reds, **params)
                ev = {"op": "convert", "method": method, "params": params, "aggregate": [r.to_dict() for r in reds]}
            else:
                from .streets import reduce as _reduce

                body = step["reduce"]
                tgt = resolve(body["target"])
                reds = [Reduction.from_dict(r) for r in body["aggregate"]]
                out = _reduce(source, by=body["by"], targets=tgt, reductions=reds)
                ev = {"op": "reduce", "by": body["by"], "aggregate": [r.to_dict() for r in reds]}
            outputs[sid] = out
            reports[sid] = out.attrs.get("urbanweave_report")
            evaluated.append({"id": sid, **ev, "report": plain(reports[sid]) if reports[sid] is not None else None})

        manifest = {
            "manifest_version": MANIFEST_VERSION,
            "created": _now(),
            "mode": mode,
            "plan": self.spec,
            "plan_fingerprint": self.fingerprint,
            "base_dir": str(self.base_dir),
            "engines": engine_versions(),
            "sources": {n: {"fingerprint": i.fingerprint, **{k: v for k, v in i.info.items()}} for n, i in bound.items()},
            "targets": {n: {"fingerprint": i.fingerprint, **{k: v for k, v in i.info.items()}} for n, i in targets.items()},
            "steps": evaluated,
        }
        written = None
        if store is not None:
            path = Path(manifest_path) if manifest_path else store.root / "manifests" / f"{self.fingerprint[:12]}-{_now().replace(':', '')}.json"
            _atomic_write(path, json.dumps(plain(manifest), indent=1, sort_keys=True).encode())
            written = path
        return PlanRun(outputs=outputs, reports=reports, manifest=plain(manifest), manifest_path=written)


class PlanRun:
    """The outputs of a plan run (by step ID), each step's report, and the run manifest."""

    def __init__(self, outputs, reports, manifest, manifest_path=None):
        self.outputs = outputs
        self.reports = reports
        self.manifest = manifest
        self.manifest_path = manifest_path

    def __getitem__(self, step_id):
        return self.outputs[step_id]

    @property
    def result(self):
        """The last step's output."""
        return self.outputs[self.manifest["steps"][-1]["id"]]


def _major(version: str) -> str:
    parts = str(version).split(".")
    return parts[0] if parts[0] != "0" else ".".join(parts[:2])


def replay(manifest, *, cache, sources: dict | None = None, allow_engine_drift: bool = False) -> PlanRun:
    """Rerun a manifest from its pinned artifacts (see the module docstring).

    In-memory sources that were not snapshotted must be given again in *sources*; they are
    verified against their recorded fingerprints. Every problem is named in one :class:`PlanError`.
    """
    if not isinstance(manifest, dict):
        manifest = json.loads(Path(manifest).read_text())
    if manifest.get("manifest_version") != MANIFEST_VERSION:
        raise PlanError(f"Unknown manifest version {manifest.get('manifest_version')!r}.")
    store = Cache(cache)
    problems = []
    now = engine_versions()
    for name, version in manifest["engines"].items():
        if name not in now:
            problems.append(f"engine {name} {version} is unavailable")
        elif _major(now[name]) != _major(version):
            if not allow_engine_drift:
                problems.append(f"engine {name} is {now[name]}, the run used {version} (incompatible)")
    plan = Plan(manifest["plan"], base_dir=manifest.get("base_dir"))
    if plan.fingerprint != manifest["plan_fingerprint"]:
        problems.append("the plan in the manifest does not match its fingerprint")
    bound, targets = {}, {}
    given = dict(sources or {})
    for name, rec in manifest["sources"].items():
        try:
            if rec.get("snapshotted"):
                obj, path = _load_artifact(store, rec["fingerprint"])
                inp = _Input(path if path is not None and rec["kind"] == "vector" else obj, rec["kind"], rec["fingerprint"],
                             rec["origin"], {}, rec)
            elif name in given:
                inp = _resolve_object(given[name], base=plan.base_dir)
                if inp.fingerprint != rec["fingerprint"]:
                    problems.append(f"source {name!r} changed: its fingerprint is {inp.fingerprint[:12]}, the run used {rec['fingerprint'][:12]}")
                    continue
            else:
                problems.append(f"source {name!r} was not snapshotted; supply it again to replay")
                continue
            bound[name] = inp
        except PlanError as exc:
            problems.append(f"source {name!r}: {exc}")
    for name, rec in manifest["targets"].items():
        try:
            obj, path = _load_artifact(store, rec["fingerprint"])
            targets[name] = _Input(path if path is not None and rec["kind"] == "vector" else obj, rec["kind"],
                                   rec["fingerprint"], rec["origin"], {}, rec)
        except PlanError as exc:
            problems.append(f"target {name!r}: {exc}")
    if problems:
        raise PlanError("Cannot replay the run:\n- " + "\n- ".join(problems))
    return plan._execute(bound, targets, store, None, mode="replay")
