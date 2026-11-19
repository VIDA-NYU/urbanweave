"""The errors urbanweave raises.

Every error is an :class:`UrbanweaveError`, so callers can catch one type. The subclasses say
whose problem it is: the caller's input (:class:`InputError`), a combination urbanweave does not
support yet (:class:`UnsupportedError`), or a plan that cannot be run or replayed
(:class:`PlanError`).
"""


class UrbanweaveError(Exception):
    """Base class of every urbanweave error."""


class InputError(UrbanweaveError, ValueError):
    """The input is unusable as given: missing CRS, duplicate or missing IDs, unknown columns."""


class UnsupportedError(UrbanweaveError, ValueError):
    """A method, geometry, value kind or measurement that urbanweave does not support."""


class PlanError(UrbanweaveError, ValueError):
    """A plan that fails validation, or a replay whose artifacts do not verify."""


class MissingDependencyError(UrbanweaveError, ImportError):
    """An optional dependency (an extra) needed by the requested operation is not installed."""
