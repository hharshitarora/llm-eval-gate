"""Bug templates that become fixture git repositories.

Each template is a short commit history with exactly one commit that introduces
a real defect, followed by decoy commits. Decoys are the difficulty knob:

  * every template lands commits *after* the culprit, so "blame HEAD" scores 0
  * several decoys touch a culprit file, so "blame the newest edit to the file
    named in the traceback" also scores 0

Anything that passes has to actually read the diffs.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Commit:
    message: str
    author: str
    email: str
    files: dict[str, str]
    is_culprit: bool = False


@dataclass(frozen=True)
class Template:
    name: str
    difficulty: str
    commits: tuple[Commit, ...]
    error_log: str
    expected_error_type: str
    reference_root_cause: str


def _c(msg, author, email, files, culprit=False):
    return Commit(message=msg, author=author, email=email, files=files, is_culprit=culprit)


# ---------------------------------------------------------------------------
# 1. config_keyerror  (easy)
# ---------------------------------------------------------------------------
_SETTINGS_OK = '''"""Runtime settings."""

DEFAULTS = {"timeout": 30, "retries": 3, "region": "us-east-1"}


def load(overrides=None):
    cfg = dict(DEFAULTS)
    if overrides:
        cfg.update(overrides)
    return cfg


def get_timeout(cfg):
    return cfg.get("timeout", 30)
'''

_SETTINGS_BUG = _SETTINGS_OK.replace('return cfg.get("timeout", 30)', 'return cfg["timeout"]')

_WORKER = '''from app.settings import get_timeout


def build_worker_config(region):
    return {"region": region, "retries": 5}


def start(region):
    cfg = build_worker_config(region)
    return {"timeout": get_timeout(cfg), "region": cfg["region"]}
'''

_REGIONS = """VALID = {'us-east-1', 'eu-west-1'}


def check(r):
    return r in VALID
"""

CONFIG_KEYERROR = Template(
    name="config_keyerror",
    difficulty="easy",
    commits=(
        _c("Add settings loader", "Priya Raman", "priya@example.com",
           {"app/settings.py": _SETTINGS_OK}),
        _c("Add worker bootstrap", "Marcus Ihde", "marcus@example.com",
           {"app/worker.py": _WORKER}),
        _c("Simplify settings access", "Dana Lee", "dana@example.com",
           {"app/settings.py": _SETTINGS_BUG}, culprit=True),
        _c("Add region validation helper", "Priya Raman", "priya@example.com",
           {"app/regions.py": _REGIONS}),
        _c("Document settings defaults", "Dana Lee", "dana@example.com",
           {"app/settings.py": _SETTINGS_BUG + "\n\n# Defaults are applied by load() only.\n"}),
        _c("Bump retries for the worker pool", "Marcus Ihde", "marcus@example.com",
           {"app/worker.py": _WORKER.replace('"retries": 5', '"retries": 8')}),
    ),
    error_log="""2026-03-04T09:14:22Z ERROR worker.bootstrap Unhandled exception starting worker pool
Traceback (most recent call last):
  File "/srv/app/bootstrap.py", line 41, in main
    pool = start(region="eu-west-1")
  File "/srv/app/worker.py", line 9, in start
    return {"timeout": get_timeout(cfg), "region": cfg["region"]}
  File "/srv/app/settings.py", line 14, in get_timeout
    return cfg["timeout"]
KeyError: 'timeout'
""",
    expected_error_type="KeyError",
    reference_root_cause=(
        "get_timeout in app/settings.py was changed from cfg.get('timeout', 30) to a direct "
        "cfg['timeout'] subscript, removing the default. build_worker_config in app/worker.py "
        "builds a config with no 'timeout' key, so the lookup raises."
    ),
)


# ---------------------------------------------------------------------------
# 2. split_indexerror  (medium)
# ---------------------------------------------------------------------------
_PARSE_OK = """def parse_tag(raw):
    parts = raw.split(":")
    if len(parts) < 2:
        return raw, ""
    return parts[0], parts[1]
"""

_PARSE_BUG = """def parse_tag(raw):
    parts = raw.split(":")
    return parts[0], parts[1]
"""

_INDEX_V1 = """from lib.tags import parse_tag


def build(raws):
    return {k: v for k, v in (parse_tag(r) for r in raws)}
"""

_INDEX_V2 = """from lib.tags import parse_tag


def build(raws):
    d = {k: v for k, v in (parse_tag(r) for r in raws)}
    return dict(sorted(d.items()))
"""

SPLIT_INDEXERROR = Template(
    name="split_indexerror",
    difficulty="medium",
    commits=(
        _c("Add tag parser", "Ana Ferreira", "ana@example.com", {"lib/tags.py": _PARSE_OK}),
        _c("Add tag index", "Tom Vance", "tom@example.com", {"lib/index.py": _INDEX_V1}),
        _c("Drop redundant length guard in parse_tag", "Tom Vance", "tom@example.com",
           {"lib/tags.py": _PARSE_BUG}, culprit=True),
        _c("Sort index keys for stable output", "Ana Ferreira", "ana@example.com",
           {"lib/index.py": _INDEX_V2}),
        _c("Add type hints to parse_tag", "Ana Ferreira", "ana@example.com",
           {"lib/tags.py": _PARSE_BUG.replace(
               "def parse_tag(raw):", "def parse_tag(raw: str) -> tuple[str, str]:")}),
        _c("Add README for lib", "Tom Vance", "tom@example.com",
           {"lib/README.md": "# lib\n\nTag parsing and indexing helpers.\n"}),
    ),
    error_log="""2026-04-11T17:02:55Z ERROR ingest.pipeline batch 88213 failed
Traceback (most recent call last):
  File "/srv/ingest/pipeline.py", line 77, in run_batch
    idx = build(raw_tags)
  File "/srv/lib/index.py", line 5, in build
    d = {k: v for k, v in (parse_tag(r) for r in raws)}
  File "/srv/lib/tags.py", line 3, in parse_tag
    return parts[0], parts[1]
IndexError: list index out of range
""",
    expected_error_type="IndexError",
    reference_root_cause=(
        "parse_tag in lib/tags.py lost its `if len(parts) < 2` guard, so any tag without a "
        "':' separator produces a one-element list and parts[1] raises IndexError."
    ),
)


# ---------------------------------------------------------------------------
# 3. none_attributeerror  (medium)
# ---------------------------------------------------------------------------
_NORM_OK = """def normalise(name):
    if name is None:
        return ""
    return name.strip().lower()
"""

_NORM_BUG = """def normalise(name):
    return name.strip().lower()
"""

_MERGE_V1 = """from core.names import normalise


def merge(records):
    return {normalise(r.get('name')): r for r in records}
"""

_MERGE_V2 = """from core.names import normalise


def merge(records):
    out = {}
    for r in records:
        out[normalise(r.get('name'))] = r
    return out
"""

NONE_ATTRIBUTEERROR = Template(
    name="none_attributeerror",
    difficulty="medium",
    commits=(
        _c("Add name normaliser", "Sofia Klein", "sofia@example.com", {"core/names.py": _NORM_OK}),
        _c("Use normaliser in customer merge", "Ravi Menon", "ravi@example.com",
           {"core/merge.py": _MERGE_V1}),
        _c("Tidy normalise", "Sofia Klein", "sofia@example.com",
           {"core/names.py": _NORM_BUG}, culprit=True),
        _c("Preserve original casing on the record", "Ravi Menon", "ravi@example.com",
           {"core/merge.py": _MERGE_V2}),
        _c("Add unicode note", "Sofia Klein", "sofia@example.com",
           {"core/names.py": _NORM_BUG + "\n\n# NOTE: NFKC normalisation is handled upstream.\n"}),
    ),
    error_log="""2026-05-19T03:31:08Z ERROR crm.sync nightly customer merge aborted
Traceback (most recent call last):
  File "/srv/crm/sync.py", line 120, in nightly
    merged = merge(batch)
  File "/srv/core/merge.py", line 6, in merge
    out[normalise(r.get('name'))] = r
  File "/srv/core/names.py", line 2, in normalise
    return name.strip().lower()
AttributeError: 'NoneType' object has no attribute 'strip'
""",
    expected_error_type="AttributeError",
    reference_root_cause=(
        "normalise in core/names.py dropped its `if name is None` guard. core/merge.py passes "
        "r.get('name'), which is None for records with no name, so .strip() fails."
    ),
)


# ---------------------------------------------------------------------------
# 4. zero_division  (medium)
# ---------------------------------------------------------------------------
_STATS_OK = """def mean(values):
    if not values:
        return 0.0
    return sum(values) / len(values)
"""

_STATS_BUG = """def mean(values):
    return sum(values) / len(values)
"""

_STATS_BUG_P95 = _STATS_BUG + """

def p95(values):
    s = sorted(values)
    return s[int(len(s) * 0.95) - 1] if s else 0.0
"""

_REPORT_V1 = """from metrics.stats import mean


def daily(samples):
    return {'latency_mean': mean(samples)}
"""

_REPORT_V2 = """from metrics.stats import mean


def daily(samples):
    return {'latency_mean': mean(samples), 'n': len(samples)}
"""

ZERO_DIVISION = Template(
    name="zero_division",
    difficulty="medium",
    commits=(
        _c("Add stats helpers", "Elena Duarte", "elena@example.com",
           {"metrics/stats.py": _STATS_OK}),
        _c("Report daily latency mean", "Jonas Wolff", "jonas@example.com",
           {"metrics/report.py": _REPORT_V1}),
        _c("Inline the empty check", "Elena Duarte", "elena@example.com",
           {"metrics/stats.py": _STATS_BUG}, culprit=True),
        _c("Add p95 helper", "Jonas Wolff", "jonas@example.com",
           {"metrics/stats.py": _STATS_BUG_P95}),
        _c("Include sample count in report", "Jonas Wolff", "jonas@example.com",
           {"metrics/report.py": _REPORT_V2}),
        _c("Add metrics package doc", "Elena Duarte", "elena@example.com",
           {"metrics/README.md": "# metrics\n\nAggregation helpers for the nightly report.\n"}),
    ),
    error_log="""2026-06-02T00:05:41Z ERROR reporting.nightly daily rollup failed for region ap-south-1
Traceback (most recent call last):
  File "/srv/reporting/nightly.py", line 58, in rollup
    row = daily(samples)
  File "/srv/metrics/report.py", line 5, in daily
    return {'latency_mean': mean(samples), 'n': len(samples)}
  File "/srv/metrics/stats.py", line 2, in mean
    return sum(values) / len(values)
ZeroDivisionError: division by zero
""",
    expected_error_type="ZeroDivisionError",
    reference_root_cause=(
        "mean in metrics/stats.py lost its `if not values` early return. A region with no "
        "samples that night yields an empty list, so len(values) is 0 and the division fails."
    ),
)


# ---------------------------------------------------------------------------
# 5. type_error_concat  (easy)
# ---------------------------------------------------------------------------
_FMT_OK = '''def label(name, count):
    return name + " (" + str(count) + ")"
'''

_FMT_BUG = '''def label(name, count):
    return name + " (" + count + ")"
'''

_SIDEBAR_V1 = """from ui.format import label


def render(groups):
    return [label(g['name'], g['count']) for g in groups]
"""

_SIDEBAR_V2 = """from ui.format import label


def render(groups):
    return [label(g['name'], g['count']) for g in sorted(groups, key=lambda g: g['name'])]
"""

TYPE_ERROR_CONCAT = Template(
    name="type_error_concat",
    difficulty="easy",
    commits=(
        _c("Add label formatter", "Nils Berger", "nils@example.com", {"ui/format.py": _FMT_OK}),
        _c("Render sidebar counts", "Yuki Tanaka", "yuki@example.com",
           {"ui/sidebar.py": _SIDEBAR_V1}),
        _c("Simplify label concatenation", "Nils Berger", "nils@example.com",
           {"ui/format.py": _FMT_BUG}, culprit=True),
        _c("Sort sidebar groups by name", "Yuki Tanaka", "yuki@example.com",
           {"ui/sidebar.py": _SIDEBAR_V2}),
        _c("Add empty-state text", "Yuki Tanaka", "yuki@example.com",
           {"ui/empty.py": "EMPTY = 'Nothing here yet.'\n"}),
    ),
    error_log="""2026-02-17T13:48:09Z ERROR web.render sidebar render failed for workspace 4471
Traceback (most recent call last):
  File "/srv/web/render.py", line 33, in sidebar
    items = render(groups)
  File "/srv/ui/sidebar.py", line 5, in render
    return [label(g['name'], g['count']) for g in sorted(groups, key=lambda g: g['name'])]
  File "/srv/ui/format.py", line 2, in label
    return name + " (" + count + ")"
TypeError: can only concatenate str (not "int") to str
""",
    expected_error_type="TypeError",
    reference_root_cause=(
        "label in ui/format.py dropped the str() conversion around count, so concatenating the "
        "integer count onto a string raises TypeError."
    ),
)


# ---------------------------------------------------------------------------
# 6. silent_wrong_total  (hard) - no traceback, only a failing assertion
# ---------------------------------------------------------------------------
_TOTAL_OK = '''from decimal import Decimal, ROUND_HALF_UP


def line_total(unit_price, qty, tax_rate):
    net = Decimal(str(unit_price)) * qty
    tax = (net * Decimal(str(tax_rate))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return net + tax
'''

_TOTAL_BUG = '''from decimal import Decimal, ROUND_HALF_UP


def line_total(unit_price, qty, tax_rate):
    net = Decimal(str(unit_price)) * qty
    tax = (net * Decimal(str(tax_rate))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return (net + tax).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
'''

_TOTAL_BUG_DOC = _TOTAL_BUG.replace(
    "def line_total(unit_price, qty, tax_rate):",
    'def line_total(unit_price, qty, tax_rate):\n    """Net plus tax for one invoice line."""',
)

_INVOICE_V1 = """from billing.totals import line_total


def invoice(lines, tax_rate):
    return sum(line_total(l['price'], l['qty'], tax_rate) for l in lines)
"""

_INVOICE_V2 = """from billing.totals import line_total


def invoice(lines, tax_rate):
    return sum(line_total(l['price'], l['qty'], l.get('tax_rate', tax_rate)) for l in lines)
"""

SILENT_WRONG_TOTAL = Template(
    name="silent_wrong_total",
    difficulty="hard",
    commits=(
        _c("Add line total calculation", "Grace Oyelaran", "grace@example.com",
           {"billing/totals.py": _TOTAL_OK}),
        _c("Add invoice assembly", "Kai Lindqvist", "kai@example.com",
           {"billing/invoice.py": _INVOICE_V1}),
        _c("Round line totals for display", "Grace Oyelaran", "grace@example.com",
           {"billing/totals.py": _TOTAL_BUG}, culprit=True),
        _c("Support per-line tax overrides", "Kai Lindqvist", "kai@example.com",
           {"billing/invoice.py": _INVOICE_V2}),
        _c("Add currency helper", "Kai Lindqvist", "kai@example.com",
           {"billing/currency.py": "SYMBOLS = {'USD': '$', 'EUR': 'EUR'}\n"}),
        _c("Docstring for line_total", "Grace Oyelaran", "grace@example.com",
           {"billing/totals.py": _TOTAL_BUG_DOC}),
    ),
    error_log="""2026-07-08T11:20:33Z FAIL ci.billing regression suite failed on main
=================================== FAILURES ===================================
______________________ test_invoice_matches_ledger _____________________________

    def test_invoice_matches_ledger():
        lines = [{"price": "19.99", "qty": 3}, {"price": "4.50", "qty": 2}]
>       assert invoice(lines, "0.0825") == Decimal("74.19")
E       AssertionError: assert Decimal('75') == Decimal('74.19')
E        +  where Decimal('75') = invoice([{'price': '19.99', 'qty': 3}, ...], '0.0825')

billing/tests/test_invoice.py:14: AssertionError
=========================== short test summary info ============================
FAILED billing/tests/test_invoice.py::test_invoice_matches_ledger
Ledger reconciliation is off by $0.81 across 14,032 invoices since the 07-06 deploy.
Affected entry point: billing/invoice.py::invoice
""",
    expected_error_type="none",
    reference_root_cause=(
        "line_total in billing/totals.py added a final quantize to Decimal('1'), rounding every "
        "line to whole units before summation. Nothing raises; the invoice total is simply "
        "wrong, and the error compounds across lines."
    ),
)


ALL_TEMPLATES: tuple[Template, ...] = (
    CONFIG_KEYERROR,
    SPLIT_INDEXERROR,
    NONE_ATTRIBUTEERROR,
    ZERO_DIVISION,
    TYPE_ERROR_CONCAT,
    SILENT_WRONG_TOTAL,
)
