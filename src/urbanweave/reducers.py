"""Reductions: what :func:`urbanweave.aggregate` computes per target.

Each constructor returns a :class:`Reduction`, a plain description that is also JSON
(:meth:`Reduction.to_dict`) and so can appear in a plan. ``as_`` names the output column
(``as`` in JSON); the default is ``<method>_<column>``, or the method's name for ``count`` and
``weighted_count``.

``where`` filters the matches a reduction sees, by the source's attributes: a dict
``{"column": ..., "op": ..., "value": ...}`` with ``op`` one of ``==, !=, <, <=, >, >=, in,
not in, isnull, notnull``, or a list of such dicts (all must hold). A Python callable taking the
matched source rows and returning a boolean mask also works, but cannot be saved in a plan.

The rules each reduction follows are in :mod:`urbanweave.aggregation`.

This module defines functions named ``sum``, ``min`` and ``max``: import it as a module, or use
``uw.sum`` and friends.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class Reduction:
    method: str
    column: Any = None
    as_: str | None = None
    where: Any = None
    fill_empty: Any = None
    options: dict = field(default_factory=dict)

    @property
    def alias(self) -> str:
        if self.as_:
            return self.as_
        if self.column is None:
            return self.method
        return f"{self.method}_{self.column}"

    @property
    def serializable(self) -> bool:
        return self.method != "custom" and not callable(self.where)

    def to_dict(self) -> dict:
        if not self.serializable:
            raise TypeError(f"Reduction {self.alias!r} holds a Python callable and cannot be saved as JSON.")
        d = {"method": self.method, "as": self.alias}
        if self.column is not None:
            d["column"] = self.column
        if self.where is not None:
            d["where"] = self.where
        if self.fill_empty is not None:
            d["fill_empty"] = self.fill_empty
        d.update(self.options)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Reduction":
        d = dict(d)
        method = d.pop("method")
        column = d.pop("column", None)
        as_ = d.pop("as", None)
        where = d.pop("where", None)
        fill_empty = d.pop("fill_empty", None)
        return cls(method=method, column=column, as_=as_, where=where, fill_empty=fill_empty, options=d)


def count(*, as_: str | None = None, where=None, fill_empty=None) -> Reduction:
    """The number of matches per target (whole number). ``fill_empty=0`` gives targets without matches 0."""
    return Reduction("count", None, as_, where, fill_empty)


def weighted_count(*, as_: str | None = None, where=None, fill_empty=None) -> Reduction:
    """The sum of the matches' allocation fractions per target; can be fractional."""
    return Reduction("weighted_count", None, as_, where, fill_empty)


def sum(column, *, as_: str | None = None, where=None, fill_empty=None) -> Reduction:  # noqa: A001
    """Σ allocation fraction × value, for extensive values. Integers stay exact with unit fractions."""
    return Reduction("sum", column, as_, where, fill_empty)


def density(column, *, as_: str | None = None, where=None, denominator: str = "target_size") -> Reduction:
    """The allocated sum divided by the target's size (per km², per km or per node), or with
    ``denominator="overlap_length"`` by the km of matched source lines inside the target."""
    return Reduction("density", column, as_, where, None, {"denominator": denominator})


def mean(column, *, as_: str | None = None, where=None) -> Reduction:
    """The unweighted mean of the matched valid values."""
    return Reduction("mean", column, as_, where)


def weighted_mean(column, *, as_: str | None = None, where=None, basis: str | None = None,
                  weighted_total_as: str | None = None, valid_measure_as: str | None = None) -> Reduction:
    """Σ basis × value / Σ basis over valid values; the basis is the method's (overlap, sample weight...).

    ``weighted_total_as`` and ``valid_measure_as`` also output the numerator and denominator, so a
    later step can pool them (``ratio_of_sums``).
    """
    opts = {}
    if basis:
        opts["basis"] = basis
    if weighted_total_as:
        opts["weighted_total_as"] = weighted_total_as
    if valid_measure_as:
        opts["valid_measure_as"] = valid_measure_as
    return Reduction("weighted_mean", column, as_, where, None, opts)


def median(column, *, as_: str | None = None, where=None) -> Reduction:
    """The median of the matched valid values (the mean of the middle two for an even count)."""
    return Reduction("median", column, as_, where)


def weighted_median(column, *, as_: str | None = None, where=None, basis: str | None = None) -> Reduction:
    """The weighted median: the smallest value whose cumulative basis reaches half the total; when the
    cumulative basis equals exactly half, the mean of that value and the next."""
    return Reduction("weighted_median", column, as_, where, None, {"basis": basis} if basis else {})


def min(column, *, as_: str | None = None, where=None) -> Reduction:  # noqa: A001
    """The smallest matched valid value (integers stay integers)."""
    return Reduction("min", column, as_, where)


def max(column, *, as_: str | None = None, where=None) -> Reduction:  # noqa: A001
    """The largest matched valid value (integers stay integers)."""
    return Reduction("max", column, as_, where)


def majority(column, *, as_: str | None = None, where=None, basis: str | None = None) -> Reduction:
    """The category with the largest total basis; ties go to the smallest category."""
    return Reduction("majority", column, as_, where, None, {"basis": basis} if basis else {})


def shares(column, *, as_: str | None = None, where=None, basis: str | None = None) -> Reduction:
    """One column per category, ``<as>_<category>``: its share of the valid matched basis."""
    return Reduction("shares", column, as_, where, None, {"basis": basis} if basis else {})


def first(column, *, as_: str | None = None, where=None) -> Reduction:
    """The first valid value in the method's order (nearest first, largest overlap first, or by source ID)."""
    return Reduction("first", column, as_, where)


def last(column, *, as_: str | None = None, where=None) -> Reduction:
    """The last valid value in the method's order."""
    return Reduction("last", column, as_, where)


def join(column, *, as_: str | None = None, where=None, delimiter: str = ", ") -> Reduction:
    """The matched valid values as text in the method's order, separated by ``delimiter``."""
    return Reduction("join", column, as_, where, None, {"delimiter": delimiter})


def custom(fn: Callable, *, as_: str, columns=None, where=None) -> Reduction:
    """``fn(rows)`` per target, where ``rows`` are the matched source rows with the match quantities.
    Cannot be saved in a plan."""
    return Reduction("custom", None, as_, where, None, {"fn": fn, "columns": columns})
