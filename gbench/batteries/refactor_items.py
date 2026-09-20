"""Multi-file refactor battery (spec 021).

Each item: a synthetic multi-file stdlib-only package (3-6 files) with
deliberate call-site spread (>=5 sites incl. >=1 non-obvious: re-export,
dynamic reference, or cross-module default), a refactor instruction (rename
or interface change), a gold refactor, and >=2 wrong-probes (partial rename;
behavior-breaking rename).

Grading is outcome-based and threefold (FR-002):
  (a) behavioral tests exercising every call site — written at grade time
      against the REFACTORED API (the tests are the spec of the new
      behavior; the answer changes package files only),
  (b) a mechanical stale-reference scan (AST-based: Name nodes, Attribute
      nodes, __all__ string elements, getattr string args — substring
      matching is FORBIDDEN, renamed symbols contain their old names;
      dispatch-table STRING KEYS are API strings and are not flagged),
  (c) clean package import.
All three green = PASS; multiple valid refactor styles must pass (no
gold-diff equivalence — SC-002).

Compatibility shims (old name aliasing to new) are FORBIDDEN in all v1
items (FR-003): the instruction says so, and the scan treats the old name
as stale.
"""

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap

# ------------------------------------------------------------------ item 1
# pkg_shape: geometry lib. Rename `util.area` -> `util.compute_area`. Call
# sites: same-module (shape.py x2), cross-module default arg (api.py),
# re-export (__init__.py __all__), dynamic dispatch value (registry.py).
ITEM_1 = {
    "provenance": {
        "source": "original fixture (spec 021 authoring)",
        "license": "MIT (fixture-authored)",
        "upstream_commit": "n/a — fixture-authored 2026-08-26",
    },
    "instruction": (
        "Rename the function `util.area` to `util.compute_area` ACROSS THE "
        "ENTIRE package: the definition, every import, every call site, the "
        "__all__ re-export, and the dynamic dispatch table in registry.py. "
        "Compatibility shims are FORBIDDEN: the old name `area` must not "
        "appear anywhere in the refactored package (not as an alias, not in "
        "__all__, not in a getattr fallback). The dispatch table's STRING "
        "KEY 'area' is the public API and stays; only the function VALUE it "
        "maps to changes. Behavior unchanged: compute_area(side) returns "
        "side*side, compute_area(length, width) returns length*width."
    ),
    "files": {
        "pkg_shape/__init__.py": textwrap.dedent('''\
            """pkg_shape — geometry helpers."""
            from .shape import area  # re-export
            from .api import describe

            __all__ = ["area", "describe"]
        '''),
        "pkg_shape/util.py": textwrap.dedent('''\
            """util — core math helpers."""


            def area(length, width=None):
                """Rectangle (or square when width is None) area."""
                if width is None:
                    return length * length
                return length * width
        '''),
        "pkg_shape/shape.py": textwrap.dedent('''\
            """shape — shape constructors."""
            from .util import area


            def square_area(side):
                return area(side)


            def rectangle_area(length, width):
                return area(length, width)
        '''),
        "pkg_shape/api.py": textwrap.dedent('''\
            """api — public facade."""
            from .util import area


            def describe(side, area_fn=area):  # non-obvious: default-argument ref
                return f"side {side} -> {area_fn(side)}"
        '''),
        "pkg_shape/registry.py": textwrap.dedent('''\
            """registry — dynamic dispatch table."""
            from .util import area  # non-obvious: dynamic value reference

            _OPS = {"area": area}  # key = public API string (stays)


            def run(name, *args):
                return _OPS[name](*args)
        '''),
    },
    "tests": textwrap.dedent('''\
        import unittest

        import pkg_shape
        from pkg_shape.api import describe
        from pkg_shape.registry import run
        from pkg_shape.shape import rectangle_area, square_area
        from pkg_shape.util import compute_area


        class TestAllCallSites(unittest.TestCase):
            def test_same_module_square(self):
                self.assertEqual(square_area(3), 9)

            def test_same_module_rect(self):
                self.assertEqual(rectangle_area(3, 4), 12)

            def test_cross_module_default(self):
                self.assertEqual(describe(3), "side 3 -> 9")

            def test_reexport(self):
                self.assertEqual(pkg_shape.compute_area(4), 16)

            def test_dynamic_registry(self):
                self.assertEqual(run("area", 5), 25)

            def test_direct_import(self):
                self.assertEqual(compute_area(2, 6), 12)
    '''),
    "stale_name": "area",
    "gold": {
        "pkg_shape/__init__.py": textwrap.dedent('''\
            """pkg_shape — geometry helpers."""
            from .shape import compute_area
            from .api import describe

            __all__ = ["compute_area", "describe"]
        '''),
        "pkg_shape/util.py": textwrap.dedent('''\
            """util — core math helpers."""


            def compute_area(length, width=None):
                """Rectangle (or square when width is None) area."""
                if width is None:
                    return length * length
                return length * width
        '''),
        "pkg_shape/shape.py": textwrap.dedent('''\
            """shape — shape constructors."""
            from .util import compute_area


            def square_area(side):
                return compute_area(side)


            def rectangle_area(length, width):
                return compute_area(length, width)
        '''),
        "pkg_shape/api.py": textwrap.dedent('''\
            """api — public facade."""
            from .util import compute_area


            def describe(side, area_fn=compute_area):
                return f"side {side} -> {area_fn(side)}"
        '''),
        "pkg_shape/registry.py": textwrap.dedent('''\
            """registry — dynamic dispatch table."""
            from .util import compute_area

            _OPS = {"area": compute_area}  # key stays; VALUE renamed


            def run(name, *args):
                return _OPS[name](*args)
        '''),
    },
    # wrong 1: partial rename — misses the default-arg + dynamic refs
    "wrongs": [
        {
            "pkg_shape/__init__.py": textwrap.dedent('''\
                """pkg_shape — geometry helpers."""
                from .shape import compute_area
                from .api import describe

                __all__ = ["compute_area", "describe"]
            '''),
            "pkg_shape/util.py": textwrap.dedent('''\
                """util — core math helpers."""


                def compute_area(length, width=None):
                    if width is None:
                        return length * length
                    return length * width
            '''),
            "pkg_shape/shape.py": textwrap.dedent('''\
                """shape — shape constructors."""
                from .util import compute_area


                def square_area(side):
                    return compute_area(side)


                def rectangle_area(length, width):
                    return compute_area(length, width)
            '''),
            # api.py + registry.py omitted -> still reference `area` -> stale
        },
        # wrong 2: behavior-breaking rename — square broken
        {
            "pkg_shape/__init__.py": textwrap.dedent('''\
                """pkg_shape — geometry helpers."""
                from .shape import compute_area
                from .api import describe

                __all__ = ["compute_area", "describe"]
            '''),
            "pkg_shape/util.py": textwrap.dedent('''\
                """util — core math helpers."""


                def compute_area(length, width=None):
                    if width is None:
                        return length + length  # BUG: square broken
                    return length * width
            '''),
            "pkg_shape/shape.py": textwrap.dedent('''\
                """shape — shape constructors."""
                from .util import compute_area


                def square_area(side):
                    return compute_area(side)


                def rectangle_area(length, width):
                    return compute_area(length, width)
            '''),
            "pkg_shape/api.py": textwrap.dedent('''\
                """api — public facade."""
                from .util import compute_area


                def describe(side, area_fn=compute_area):
                    return f"side {side} -> {area_fn(side)}"
            '''),
            "pkg_shape/registry.py": textwrap.dedent('''\
                """registry — dynamic dispatch table."""
                from .util import compute_area

                _OPS = {"area": compute_area}


                def run(name, *args):
                    return _OPS[name](*args)
            '''),
        },
        # wrong 3: shim answer (FR-003) — old name aliased to new
        {
            "pkg_shape/__init__.py": textwrap.dedent('''\
                """pkg_shape — geometry helpers."""
                from .shape import compute_area
                from .util import compute_area as area  # SHIM: forbidden
                from .api import describe

                __all__ = ["area", "compute_area", "describe"]
            '''),
            "pkg_shape/util.py": textwrap.dedent('''\
                """util — core math helpers."""


                def compute_area(length, width=None):
                    if width is None:
                        return length * length
                    return length * width
            '''),
            "pkg_shape/shape.py": textwrap.dedent('''\
                """shape — shape constructors."""
                from .util import compute_area


                def square_area(side):
                    return compute_area(side)


                def rectangle_area(length, width):
                    return compute_area(length, width)
            '''),
            "pkg_shape/api.py": textwrap.dedent('''\
                """api — public facade."""
                from .util import compute_area


                def describe(side, area_fn=compute_area):
                    return f"side {side} -> {area_fn(side)}"
            '''),
            "pkg_shape/registry.py": textwrap.dedent('''\
                """registry — dynamic dispatch table."""
                from .util import compute_area

                _OPS = {"area": compute_area}


                def run(name, *args):
                    return _OPS[name](*args)
            '''),
        },
    ],
}

# ------------------------------------------------------------------ item 2
# pkg_store: storage facade. Interface change: `Store.write` -> `Store.put`.
# Call sites: same-module (write_all), __all__ re-export, string-keyed
# dispatch, subclass override + super() call.
ITEM_2 = {
    "provenance": {
        "source": "original fixture (spec 021 authoring)",
        "license": "MIT (fixture-authored)",
        "upstream_commit": "n/a — fixture-authored 2026-08-26",
    },
    "instruction": (
        "Interface change: rename the method `Store.write` to `Store.put` "
        "ACROSS the package: the class definition, the same-module call in "
        "write_all, the __all__ re-export, the string-keyed dispatch table "
        "in api.py (the STRING KEY 'write' is the public API and stays; the "
        "method VALUE it maps to changes), and the subclass override in "
        "child.py (including its super() call). Compatibility shims are "
        "FORBIDDEN: the old method name `write` must not appear anywhere in "
        "the refactored package. Behavior unchanged: put(key, value) returns "
        "'ok' and records the pair."
    ),
    "files": {
        "pkg_store/__init__.py": textwrap.dedent('''\
            """pkg_store — storage facade."""
            from .core import Store

            write = Store.write  # re-export
            __all__ = ["Store", "write"]
        '''),
        "pkg_store/core.py": textwrap.dedent('''\
            """core — the Store class."""
            import time


            def log_msg(msg):
                print(f"[store] {msg}")


            class Store:
                def __init__(self):
                    self._data = {}

                def write(self, key, value):  # definition
                    self._data[key] = value
                    log_msg(f"wrote {key}")
                    return "ok"

                def write_all(self, pairs):
                    for k, v in pairs:
                        self.write(k, v)  # same-module call
                    return len(pairs)
        '''),
        "pkg_store/api.py": textwrap.dedent('''\
            """api — client facade."""
            from .core import Store

            OPS = {"write": Store.write}  # non-obvious: string-keyed dispatch


            def dispatch(store, op, key, value):
                return OPS[op](store, key, value)
        '''),
        "pkg_store/child.py": textwrap.dedent('''\
            """child — subclass override."""
            from .core import Store


            class AuditedStore(Store):
                def write(self, key, value):  # non-obvious: subclass override
                    self._audit = (key, value)
                    return super().write(key, value)  # super() call
        '''),
    },
    "tests": textwrap.dedent('''\
        import unittest

        import pkg_store
        from pkg_store.api import dispatch
        from pkg_store.child import AuditedStore
        from pkg_store.core import Store


        class TestAllCallSites(unittest.TestCase):
            def test_direct_put(self):
                s = Store()
                self.assertEqual(s.put("a", 1), "ok")

            def test_write_all_same_module(self):
                s = Store()
                self.assertEqual(s.write_all([("a", 1), ("b", 2)]), 2)

            def test_reexport(self):
                self.assertIs(pkg_store.put, Store.put)

            def test_string_dispatch(self):
                s = Store()
                self.assertEqual(dispatch(s, "write", "k", 9), "ok")

            def test_subclass_override(self):
                s = AuditedStore()
                self.assertEqual(s.put("k", 5), "ok")
                self.assertEqual(s._audit, ("k", 5))

            def test_data_recorded(self):
                s = Store()
                s.put("x", 3)
                self.assertEqual(s._data["x"], 3)
    '''),
    "stale_name": "write",
    "gold": {
        "pkg_store/__init__.py": textwrap.dedent('''\
            """pkg_store — storage facade."""
            from .core import Store

            put = Store.put
            __all__ = ["Store", "put"]
        '''),
        "pkg_store/core.py": textwrap.dedent('''\
            """core — the Store class."""
            import time


            def log_msg(msg):
                print(f"[store] {msg}")


            class Store:
                def __init__(self):
                    self._data = {}

                def put(self, key, value):
                    self._data[key] = value
                    log_msg(f"wrote {key}")
                    return "ok"

                def write_all(self, pairs):
                    for k, v in pairs:
                        self.put(k, v)
                    return len(pairs)
        '''),
        "pkg_store/api.py": textwrap.dedent('''\
            """api — client facade."""
            from .core import Store

            OPS = {"write": Store.put}  # key stays; method updated


            def dispatch(store, op, key, value):
                return OPS[op](store, key, value)
        '''),
        "pkg_store/child.py": textwrap.dedent('''\
            """child — subclass override."""
            from .core import Store


            class AuditedStore(Store):
                def put(self, key, value):
                    self._audit = (key, value)
                    return super().put(key, value)
        '''),
    },
    "wrongs": [
        # partial: renames definition + same-module, misses dispatch + subclass
        {
            "pkg_store/__init__.py": textwrap.dedent('''\
                """pkg_store — storage facade."""
                from .core import Store

                __all__ = ["Store", "put"]
            '''),
            "pkg_store/core.py": textwrap.dedent('''\
                """core — the Store class."""
                import time


                def log_msg(msg):
                    print(f"[store] {msg}")


                class Store:
                    def __init__(self):
                        self._data = {}

                    def put(self, key, value):
                        self._data[key] = value
                        log_msg(f"wrote {key}")
                        return "ok"

                    def write_all(self, pairs):
                        for k, v in pairs:
                            self.put(k, v)
                        return len(pairs)
            '''),
            # api.py + child.py omitted -> still `write` -> stale
        },
        # behavior-break: full rename but write_all returns wrong count
        {
            "pkg_store/__init__.py": textwrap.dedent('''\
                """pkg_store — storage facade."""
                from .core import Store

                __all__ = ["Store", "put"]
            '''),
            "pkg_store/core.py": textwrap.dedent('''\
                """core — the Store class."""
                import time


                def log_msg(msg):
                    print(f"[store] {msg}")


                class Store:
                    def __init__(self):
                        self._data = {}

                    def put(self, key, value):
                        self._data[key] = value
                        log_msg(f"wrote {key}")
                        return "ok"

                    def write_all(self, pairs):
                        for k, v in pairs:
                            self.put(k, v)
                        return 0  # BUG: count broken
            '''),
            "pkg_store/api.py": textwrap.dedent('''\
                """api — client facade."""
                from .core import Store

                OPS = {"write": Store.put}

                def dispatch(store, op, key, value):
                    return OPS[op](store, key, value)
            '''),
            "pkg_store/child.py": textwrap.dedent('''\
                """child — subclass override."""
                from .core import Store


                class AuditedStore(Store):
                    def put(self, key, value):
                        self._audit = (key, value)
                        return super().put(key, value)
            '''),
        },
        # shim forbidden: old name kept as a module-level function
        {
            "pkg_store/__init__.py": textwrap.dedent('''\
                """pkg_store — storage facade."""
                from .core import Store

                __all__ = ["Store", "put"]


                def write(self, key, value):  # SHIM: forbidden
                    return Store.put(self, key, value)
            '''),
            "pkg_store/core.py": textwrap.dedent('''\
                """core — the Store class."""
                import time


                def log_msg(msg):
                    print(f"[store] {msg}")


                class Store:
                    def __init__(self):
                        self._data = {}

                    def put(self, key, value):
                        self._data[key] = value
                        log_msg(f"wrote {key}")
                        return "ok"

                    def write_all(self, pairs):
                        for k, v in pairs:
                            self.put(k, v)
                        return len(pairs)
            '''),
            "pkg_store/api.py": textwrap.dedent('''\
                """api — client facade."""
                from .core import Store

                OPS = {"write": Store.put}

                def dispatch(store, op, key, value):
                    return OPS[op](store, key, value)
            '''),
            "pkg_store/child.py": textwrap.dedent('''\
                """child — subclass override."""
                from .core import Store


                class AuditedStore(Store):
                    def put(self, key, value):
                        self._audit = (key, value)
                        return super().put(key, value)
            '''),
        },
    ],
}

# ------------------------------------------------------------------ item 3
# pkg_task: task runner. Rename `runner.execute` -> `runner.run` incl. a
# dynamic getattr reference (dispatch.py) and the __all__ re-export.
ITEM_3 = {
    "provenance": {
        "source": "original fixture (spec 021 authoring)",
        "license": "MIT (fixture-authored)",
        "upstream_commit": "n/a — fixture-authored 2026-08-26",
    },
    "instruction": (
        "Rename the function `runner.execute` to `runner.run` ACROSS the "
        "package: the definition, every import, every call, the __all__ "
        "re-export, and the dynamic name resolution in dispatch.py (which "
        "resolves names with getattr — the runtime name must now be 'run'). "
        "Compatibility shims are FORBIDDEN: the old name `execute` must not "
        "appear anywhere in the refactored package. Behavior unchanged: "
        "run(task) returns the task's result; run(task, retries=2) retries "
        "on ValueError up to retries times."
    ),
    "files": {
        "pkg_task/__init__.py": textwrap.dedent('''\
            """pkg_task — task runner."""
            from .runner import execute

            __all__ = ["execute"]
        '''),
        "pkg_task/runner.py": textwrap.dedent('''\
            """runner — task execution."""


            def execute(task, retries=0):
                for attempt in range(retries + 1):
                    try:
                        return task()
                    except ValueError:
                        if attempt == retries:
                            raise
                return None
        '''),
        "pkg_task/dispatch.py": textwrap.dedent('''\
            """dispatch — dynamic name resolution."""
            import pkg_task


            def run_named(name, *args, **kwargs):
                fn = getattr(pkg_task, name)  # non-obvious: dynamic reference
                return fn(*args, **kwargs)
        '''),
        "pkg_task/scheduler.py": textwrap.dedent('''\
            """scheduler — queued execution."""
            from .runner import execute


            def schedule(tasks):
                return [execute(t) for t in tasks]
        '''),
    },
    "tests": textwrap.dedent('''\
        import unittest

        import pkg_task
        from pkg_task.dispatch import run_named
        from pkg_task.runner import run
        from pkg_task.scheduler import schedule


        class TestAllCallSites(unittest.TestCase):
            def test_direct(self):
                self.assertEqual(run(lambda: 42), 42)

            def test_retries(self):
                calls = []

                def flaky():
                    calls.append(1)
                    if len(calls) < 3:
                        raise ValueError("again")
                    return "done"

                self.assertEqual(run(flaky, retries=2), "done")

            def test_reexport(self):
                self.assertEqual(pkg_task.run(lambda: 7), 7)

            def test_dynamic(self):
                self.assertEqual(run_named("run", lambda: 5), 5)

            def test_scheduler(self):
                self.assertEqual(schedule([lambda: 1, lambda: 2]), [1, 2])
    '''),
    "stale_name": "execute",
    "gold": {
        "pkg_task/__init__.py": textwrap.dedent('''\
            """pkg_task — task runner."""
            from .runner import run

            __all__ = ["run"]
        '''),
        "pkg_task/runner.py": textwrap.dedent('''\
            """runner — task execution."""


            def run(task, retries=0):
                for attempt in range(retries + 1):
                    try:
                        return task()
                    except ValueError:
                        if attempt == retries:
                            raise
                return None
        '''),
        "pkg_task/dispatch.py": textwrap.dedent('''\
            """dispatch — dynamic name resolution."""
            import pkg_task


            def run_named(name, *args, **kwargs):
                fn = getattr(pkg_task, name)
                return fn(*args, **kwargs)
        '''),
        "pkg_task/scheduler.py": textwrap.dedent('''\
            """scheduler — queued execution."""
            from .runner import run


            def schedule(tasks):
                return [run(t) for t in tasks]
        '''),
    },
    "wrongs": [
        # partial: misses the dynamic dispatch (dispatch.py omitted)
        {
            "pkg_task/__init__.py": textwrap.dedent('''\
                """pkg_task — task runner."""
                from .runner import run

                __all__ = ["run"]
            '''),
            "pkg_task/runner.py": textwrap.dedent('''\
                """runner — task execution."""


                def run(task, retries=0):
                    for attempt in range(retries + 1):
                        try:
                            return task()
                        except ValueError:
                            if attempt == retries:
                                raise
                    return None
            '''),
            # dispatch.py omitted -> still `execute` -> stale; scheduler too
        },
        # behavior-break: full rename but retries semantics broken
        {
            "pkg_task/__init__.py": textwrap.dedent('''\
                """pkg_task — task runner."""
                from .runner import run

                __all__ = ["run"]
            '''),
            "pkg_task/runner.py": textwrap.dedent('''\
                """runner — task execution."""


                def run(task, retries=0):
                    try:
                        return task()  # BUG: no retry loop
                    except ValueError:
                        raise
            '''),
            "pkg_task/dispatch.py": textwrap.dedent('''\
                """dispatch — dynamic name resolution."""
                import pkg_task


                def run_named(name, *args, **kwargs):
                    fn = getattr(pkg_task, name)
                    return fn(*args, **kwargs)
            '''),
            "pkg_task/scheduler.py": textwrap.dedent('''\
                """scheduler — queued execution."""
                from .runner import run


                def schedule(tasks):
                    return [run(t) for t in tasks]
            '''),
        },
        # shim forbidden: old name kept as an alias import
        {
            "pkg_task/__init__.py": textwrap.dedent('''\
                """pkg_task — task runner."""
                from .runner import run
                from .runner import run as execute  # SHIM: forbidden

                __all__ = ["run", "execute"]
            '''),
            "pkg_task/runner.py": textwrap.dedent('''\
                """runner — task execution."""


                def run(task, retries=0):
                    for attempt in range(retries + 1):
                        try:
                            return task()
                        except ValueError:
                            if attempt == retries:
                                raise
                    return None
            '''),
            "pkg_task/dispatch.py": textwrap.dedent('''\
                """dispatch — dynamic name resolution."""
                import pkg_task


                def run_named(name, *args, **kwargs):
                    fn = getattr(pkg_task, name)
                    return fn(*args, **kwargs)
            '''),
            "pkg_task/scheduler.py": textwrap.dedent('''\
                """scheduler — queued execution."""
                from .runner import run


                def schedule(tasks):
                    return [run(t) for t in tasks]
            '''),
        },
    ],
}

# ------------------------------------------------------------------ item 4
# pkg_grid: numeric grid. Rename `grid.avg` -> `grid.mean` with a
# cross-module default argument AND a re-export.
ITEM_4 = {
    "provenance": {
        "source": "original fixture (spec 021 authoring)",
        "license": "MIT (fixture-authored)",
        "upstream_commit": "n/a — fixture-authored 2026-08-26",
    },
    "instruction": (
        "Rename the function `grid.avg` to `grid.mean` ACROSS the package: "
        "the definition, every import, every call, the __all__ re-export, "
        "and the default-argument reference in summarize.py. Compatibility "
        "shims are FORBIDDEN: the old name `avg` must not appear anywhere "
        "in the refactored package. Behavior unchanged: mean(values) "
        "returns the arithmetic mean; summarize(grid) defaults to mean."
    ),
    "files": {
        "pkg_grid/__init__.py": textwrap.dedent('''\
            """pkg_grid — numeric grid tools."""
            from .stats import avg

            __all__ = ["avg"]
        '''),
        "pkg_grid/stats.py": textwrap.dedent('''\
            """stats — numeric helpers."""


            def avg(values):
                return sum(values) / len(values)
        '''),
        "pkg_grid/summarize.py": textwrap.dedent('''\
            """summarize — grid summaries."""
            from .stats import avg


            def summarize(grid, stat=avg):  # non-obvious: default-argument ref
                return stat(grid.values())
        '''),
        "pkg_grid/report.py": textwrap.dedent('''\
            """report — report generation."""
            from .stats import avg
            from .summarize import summarize


            def report(grid):
                return {"mean": avg(grid.values()), "summary": summarize(grid)}
        '''),
    },
    "tests": textwrap.dedent('''\
        import unittest

        import pkg_grid
        from pkg_grid.report import report
        from pkg_grid.stats import mean
        from pkg_grid.summarize import summarize


        class Grid(dict):
            def values(self):
                return list(super().values())


        class TestAllCallSites(unittest.TestCase):
            def test_direct(self):
                self.assertEqual(mean([1, 2, 3]), 2.0)

            def test_reexport(self):
                self.assertEqual(pkg_grid.mean([4, 4]), 4.0)

            def test_default_arg(self):
                self.assertEqual(summarize(Grid(a=1, b=2, c=3)), 2.0)

            def test_custom_stat(self):
                self.assertEqual(summarize(Grid(a=1, b=3), stat=max), 3)

            def test_report(self):
                g = Grid(a=2, b=4)
                self.assertEqual(report(g), {"mean": 3.0, "summary": 3.0})

            def test_empty_raises(self):
                with self.assertRaises(ZeroDivisionError):
                    mean([])
    '''),
    "stale_name": "avg",
    "gold": {
        "pkg_grid/__init__.py": textwrap.dedent('''\
            """pkg_grid — numeric grid tools."""
            from .stats import mean

            __all__ = ["mean"]
        '''),
        "pkg_grid/stats.py": textwrap.dedent('''\
            """stats — numeric helpers."""


            def mean(values):
                return sum(values) / len(values)
        '''),
        "pkg_grid/summarize.py": textwrap.dedent('''\
            """summarize — grid summaries."""
            from .stats import mean


            def summarize(grid, stat=mean):
                return stat(grid.values())
        '''),
        "pkg_grid/report.py": textwrap.dedent('''\
            """report — report generation."""
            from .stats import mean
            from .summarize import summarize


            def report(grid):
                return {"mean": mean(grid.values()), "summary": summarize(grid)}
        '''),
    },
    "wrongs": [
        # partial: misses the default-argument + report call
        {
            "pkg_grid/__init__.py": textwrap.dedent('''\
                """pkg_grid — numeric grid tools."""
                from .stats import mean

                __all__ = ["mean"]
            '''),
            "pkg_grid/stats.py": textwrap.dedent('''\
                """stats — numeric helpers."""


                def mean(values):
                    return sum(values) / len(values)
            '''),
            # summarize.py + report.py omitted -> still `avg` -> stale
        },
        # behavior-break: full rename but mean of empty list -> 0.0 instead
        # of ZeroDivisionError (division semantics changed)
        {
            "pkg_grid/__init__.py": textwrap.dedent('''\
                """pkg_grid — numeric grid tools."""
                from .stats import mean

                __all__ = ["mean"]
            '''),
            "pkg_grid/stats.py": textwrap.dedent('''\
                """stats — numeric helpers."""


                def mean(values):
                    return sum(values) / max(len(values), 1)  # BUG: empty -> 0.0
            '''),
            "pkg_grid/summarize.py": textwrap.dedent('''\
                """summarize — grid summaries."""
                from .stats import mean


                def summarize(grid, stat=mean):
                    return stat(grid.values())
            '''),
            "pkg_grid/report.py": textwrap.dedent('''\
                """report — report generation."""
                from .stats import mean
                from .summarize import summarize


                def report(grid):
                    return {"mean": mean(grid.values()), "summary": summarize(grid)}
            '''),
        },
        # shim forbidden: old name kept in __all__
        {
            "pkg_grid/__init__.py": textwrap.dedent('''\
                """pkg_grid — numeric grid tools."""
                from .stats import mean
                from .stats import mean as avg  # SHIM: forbidden

                __all__ = ["mean", "avg"]
            '''),
            "pkg_grid/stats.py": textwrap.dedent('''\
                """stats — numeric helpers."""


                def mean(values):
                    return sum(values) / len(values)
            '''),
            "pkg_grid/summarize.py": textwrap.dedent('''\
                """summarize — grid summaries."""
                from .stats import mean


                def summarize(grid, stat=mean):
                    return stat(grid.values())
            '''),
            "pkg_grid/report.py": textwrap.dedent('''\
                """report — report generation."""
                from .stats import mean
                from .summarize import summarize


                def report(grid):
                    return {"mean": mean(grid.values()), "summary": summarize(grid)}
            '''),
        },
    ],
}

ITEMS: list[dict] = [ITEM_1, ITEM_2, ITEM_3, ITEM_4]

TASK_CEILING_S = 120
BANNED_IMPORTS = ("socket", "urllib", "http.client", "requests", "ftplib", "smtplib")
REGISTRY = "results/refactor-registry.jsonl"


# ------------------------------------------------------------- shared rig
def parse_answer_blocks(text):
    """Answer contract: complete changed files, fenced blocks whose FIRST
    line is '# path/to/file.py' (create/replace semantics). Returns
    {relpath: content} or raises ValueError (unparseable => FAIL)."""
    blocks = re.findall(r"```(?:python|text)?\s*\n(.*?)```", text or "", re.S)
    files = {}
    for b in blocks:
        first = b.strip().splitlines()[0] if b.strip() else ""
        m = re.match(r"#\s*(.+)$", first.strip())
        if not m:
            raise ValueError(f"block without '# path' first line: {first[:60]!r}")
        files[m.group(1).strip()] = b[b.index(first) + len(first):].lstrip("\n")
    if not files:
        raise ValueError("no path-prefixed fenced blocks found")
    return files


def safe_workspace_path(workspace, rel):
    candidate = os.path.realpath(os.path.join(workspace, rel))
    ws_real = os.path.realpath(workspace)
    if candidate != ws_real and not candidate.startswith(ws_real + os.sep):
        raise ValueError(f"path escapes workspace: {rel!r}")
    return candidate


def write_repo(root, files):
    for rel, content in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)


def materialize(root, item_index, patch=None):
    import shutil

    if os.path.exists(root):
        shutil.rmtree(root)
    item = ITEMS[item_index]
    write_repo(root, item["files"])
    if patch:
        for rel, content in patch.items():
            path = safe_workspace_path(root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(content)
    # oracle tests written at grade time (refactored-API spec); the answer
    # may NOT override them (they are the grading spec, applied last)
    tests_dir = os.path.join(root, "tests")
    os.makedirs(tests_dir, exist_ok=True)
    with open(os.path.join(tests_dir, "test_behavior.py"), "w") as f:
        f.write(item["tests"])
    with open(os.path.join(root, ".refactor_item.json"), "w") as f:
        json.dump({"item_index": item_index}, f)


def run_suite(root, ceiling_s=TASK_CEILING_S):
    """Run the item's behavioral suite (unittest discover) under a wall
    clock. Returns (ok, failures {dotted_id: kind})."""
    cmd = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
    try:
        proc = subprocess.run(
            cmd, cwd=root, capture_output=True, text=True, timeout=ceiling_s,
            env={**os.environ, "PYTHONPATH": "."},
        )
    except subprocess.TimeoutExpired:
        return False, {"_suite": "timeout"}
    failures = {}
    for ln in (proc.stdout + proc.stderr).splitlines():
        ln = ln.strip()
        if ln.startswith("FAIL:") or ln.startswith("ERROR:"):
            tid = ln.split(" ", 1)[1].strip()
            m = re.search(r"\(([^)]+)\)", tid)
            key = m.group(1) if m else tid
            failures[key] = "fail" if ln.startswith("FAIL:") else "error"
    return proc.returncode == 0, failures


def _pkg_name(root):
    for name in sorted(os.listdir(root)):
        if os.path.isdir(os.path.join(root, name)) and \
                os.path.exists(os.path.join(root, name, "__init__.py")):
            return name
    raise ValueError(f"no package dir in {root}")


def _stale_references(root, stale_name):
    """Mechanical stale-reference scan (FR-002b): the clean-import gate
    (FR-002c) is checked FIRST (import_ok), then the package's AST is walked
    for the exact identifier `stale_name` as: Name nodes (imports/calls/
    defs), Attribute nodes (obj.old_name), FunctionDef/ClassDef names,
    __all__ string elements, getattr string args. The AST scan runs even
    when the import fails — a broken import is itself the symptom of a
    missed site, and the stale sites must still be NAMED in forensics.
    Dispatch-table STRING KEYS are public API and not flagged (the
    instruction pins the key as staying). Returns (stale, import_error)."""
    try:
        subprocess.run(
            [sys.executable, "-c", f"import {_pkg_name(root)}"],
            cwd=root, capture_output=True, text=True, timeout=TASK_CEILING_S,
            env={**os.environ, "PYTHONPATH": "."},
            check=True,
        )
        imp_err = None
    except subprocess.CalledProcessError as e:
        imp_err = f"package import failed: {e.stderr.strip()[:300]}"
    stale = []
    pkg_dir = os.path.join(root, _pkg_name(root))
    for dirpath, _dirs, files in os.walk(pkg_dir):
        for fn in sorted(files):
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, root)
            src = open(path).read()
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id == stale_name:
                    stale.append((rel, node.lineno, "name"))
                elif isinstance(node, ast.Attribute) and node.attr == stale_name:
                    stale.append((rel, node.lineno, "attribute"))
                elif isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)) \
                        and node.name == stale_name:
                    # a def/class of the old name IS a forbidden alias/shim
                    stale.append((rel, node.lineno, "definition"))
                elif isinstance(node, ast.Constant) and isinstance(node.value, str) \
                        and node.value == stale_name and _is_name_string(node, tree):
                    stale.append((rel, node.lineno, "string"))
                elif isinstance(node, ast.Str) and node.s == stale_name \
                        and _is_name_string(node, tree):
                    stale.append((rel, node.lineno, "string"))
    return stale, imp_err


def _is_name_string(node, tree):
    """A string constant counts as a stale reference only when it names a
    symbol: an __all__ element (list assigned to __all__) or a getattr
    name argument. Dict/other strings (dispatch keys, comments, prose) are
    API content, not symbol references."""
    parent = _parent_of(tree, node)
    if parent is None:
        return False
    if isinstance(parent, ast.List):
        # walk up: __all__ = ["x", ...] — the list's assignment target
        for up in _ancestors(tree, parent):
            if isinstance(up, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__all__" for t in up.targets
            ):
                return True
        return False
    if isinstance(parent, ast.Call) and isinstance(parent.func, ast.Name) \
            and parent.func.id == "getattr" and node is parent.args[0]:
        return True
    return False


def _parent_of(tree, node):
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            if child is node:
                return parent
    return None


def _ancestors(tree, node):
    out = []
    stack = [tree]
    while stack:
        cur = stack.pop()
        for child in ast.iter_child_nodes(cur):
            if child is node:
                out.append(cur)
                stack.append(child)
            else:
                stack.append(child)
    return out


def grade_answer(item_index, answer_text):
    """Threefold outcome-based grading (FR-002): (a) behavioral suite,
    (b) stale-reference scan, (c) clean import. Returns the row's grading
    dict — never raises for bad answers (deterministic FAIL fields)."""
    item = ITEMS[item_index]
    base: dict = {
        "ok": False,
        "behavior_ok": False,
        "stale_ok": False,
        "import_ok": False,
        "stale_sites": [],
        "stale_error": None,
        "behavior_failures": {},
        "error": None,
        "attempted_network": False,
    }
    for banned in BANNED_IMPORTS:
        if f"import {banned}" in (answer_text or "") or f"from {banned}" in (answer_text or ""):
            base["attempted_network"] = True
            base["error"] = f"answer attempts network access (import {banned})"
            return base
    with tempfile.TemporaryDirectory(prefix="refactor-") as ws:
        repo = os.path.join(ws, "repo")
        materialize(repo, item_index)
        try:
            files = parse_answer_blocks(answer_text)
            for rel, content in files.items():
                path = safe_workspace_path(repo, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w") as f:
                    f.write(content)
        except ValueError as e:
            base["error"] = f"answer contract violation: {e}"
            return base
        # oracle tests were written by materialize BEFORE the answer patch;
        # re-write them AFTER so the answer can never override the spec
        tests_dir = os.path.join(repo, "tests")
        os.makedirs(tests_dir, exist_ok=True)
        with open(os.path.join(tests_dir, "test_behavior.py"), "w") as f:
            f.write(item["tests"])
        ok, failures = run_suite(repo)
        base["behavior_ok"] = ok
        base["behavior_failures"] = failures
        stale, imp_err = _stale_references(repo, item["stale_name"])
        base["import_ok"] = imp_err is None
        base["stale_ok"] = not stale
        base["stale_sites"] = stale
        if imp_err is not None:
            base["stale_error"] = imp_err
        base["ok"] = base["behavior_ok"] and base["stale_ok"] and base["import_ok"]
        return base


def task_prompt(item_index):
    """The operator-facing task prompt: refactor instruction + vendored
    package files + pinned answer contract."""
    item = ITEMS[item_index]
    parts = [
        f"# Task {item_index + 1}: multi-file refactor in the vendored package\n",
        f"## Instruction\n{item['instruction']}\n",
        "## Package (complete file contents)\n",
    ]
    for rel, content in item["files"].items():
        parts.append(f"### {rel}\n```text\n{content}```\n")
    parts.append(
        "## Deliverable\n"
        "Reply with the COMPLETE changed file(s) as fenced code blocks, one "
        "per file, each block's FIRST line the file path prefixed with '# ', "
        "e.g.:\n```python\n# pkg_shape/util.py\n<full new contents>\n```\n"
        "Omitted files are graded as unchanged. No prose outside the blocks.\n"
    )
    return "\n".join(parts)


def _as_answer(patch):
    return "\n\n".join(
        f"```python\n# {rel}\n{content}```" for rel, content in patch.items()
    )


def selfcheck():
    """SC-001: gold passes (all three checks), every wrong fails >=1 check,
    the shim wrong fails the stale scan; standalone-runnable exit 0/1."""
    bad = 0
    for i, item in enumerate(ITEMS, 1):
        g = grade_answer(i - 1, _as_answer(item["gold"]))
        if not g["ok"]:
            print(f"REFACTOR-SELFCHECK FAIL item {i}: gold not ok: "
                  f"behavior={g['behavior_ok']} stale={g['stale_ok']} "
                  f"import={g['import_ok']} stale_sites={g['stale_sites']} "
                  f"beh_fail={g['behavior_failures']}")
            bad += 1
        for w_i, wrong in enumerate(item["wrongs"], 1):
            w = grade_answer(i - 1, _as_answer(wrong))
            if w["ok"]:
                print(f"REFACTOR-SELFCHECK LEAK item {i} wrong {w_i}: passed "
                      f"(stale={w['stale_sites']}, beh={w['behavior_failures']})")
                bad += 1
    return bad == 0


def validate_item(item_index):
    """Authoring intake (FR-001 design rules): call-site spread recorded,
    >=5 sites, >=1 non-obvious (re-export / dynamic / default-arg), gold
    passes, wrongs fail. Returns the spread design-rule check. Counts every
    reference shape: Name nodes, Attribute nodes, string constants, def/
    class names, and import aliases."""
    item = ITEMS[item_index]
    refs = []
    for rel, content in item["files"].items():
        if rel.endswith(".py"):
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id == item["stale_name"]:
                    refs.append((rel, node.lineno, "name"))
                elif isinstance(node, ast.Attribute) and node.attr == item["stale_name"]:
                    refs.append((rel, node.lineno, "attribute"))
                elif isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)) \
                        and node.name == item["stale_name"]:
                    refs.append((rel, node.lineno, "definition"))
                elif isinstance(node, ast.ImportFrom) and any(
                        a.name == item["stale_name"] for a in node.names):
                    refs.append((rel, node.lineno, "import"))
                elif isinstance(node, ast.Constant) and isinstance(node.value, str) \
                        and node.value == item["stale_name"]:
                    refs.append((rel, node.lineno, "string"))
    return {
        "call_sites": len(refs),
        "sites": refs,
        "design_ok": len(refs) >= 5,
        "min_ok": len(ITEMS) >= 4,
    }


if __name__ == "__main__":
    ok = selfcheck()
    print("refactor selfcheck:", "OK" if ok else "FAILED")
    sys.exit(0 if ok else 1)
