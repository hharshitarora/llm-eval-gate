"""Second batch of bug templates.

Two design goals beyond simply adding cases.

**Balance the decoy structure.** The first batch had five of six cases landing a
later commit on the culprit's own file, so when the real agent solved the one
case without that decoy and failed four of the five with it, the pattern was
suggestive and untestable. This batch is deliberately four without and two with,
bringing the set to seven with and five without: enough to tell "the agent blames
the newest edit to the file" apart from "the agent is just wrong".

**Widen the failure taxonomy.** The first batch was mostly deletions of a guard.
Real regressions are also renames that break a caller, a tightened regex, a
dropped timezone, and arithmetic that silently returns the wrong number.
"""
from __future__ import annotations

from .templates import Template, _c

# ---------------------------------------------------------------------------
# 7. import_rename  (medium, no same-file decoy)
# ---------------------------------------------------------------------------
_INV_OK = """def check_stock(sku):
    return _LEVELS.get(sku, 0)


_LEVELS = {"SKU-1": 4, "SKU-2": 0}
"""

_INV_BUG = """def stock_level(sku):
    return _LEVELS.get(sku, 0)


_LEVELS = {"SKU-1": 4, "SKU-2": 0}
"""

_STORE_API = """from store.inventory import check_stock


def availability(sku):
    return {"sku": sku, "available": check_stock(sku) > 0}
"""

IMPORT_RENAME = Template(
    name="import_rename",
    difficulty="medium",
    commits=(
        _c("Add inventory lookup", "Ines Duarte", "ines@example.com",
           {"store/inventory.py": _INV_OK}),
        _c("Add availability endpoint", "Owen Blake", "owen@example.com",
           {"store/api.py": _STORE_API}),
        _c("Rename check_stock to stock_level", "Ines Duarte", "ines@example.com",
           {"store/inventory.py": _INV_BUG}, culprit=True),
        _c("Add basket totals", "Owen Blake", "owen@example.com",
           {"store/basket.py": "def total(lines):\n    return sum(l['price'] * l['qty'] for l in lines)\n"}),
        _c("Add store package doc", "Owen Blake", "owen@example.com",
           {"store/README.md": "# store\n\nInventory, basket and availability.\n"}),
        _c("Add currency constant", "Ines Duarte", "ines@example.com",
           {"store/constants.py": "CURRENCY = 'GBP'\n"}),
    ),
    error_log="""2026-03-22T08:41:02Z ERROR web.boot worker failed to start after deploy 4471
Traceback (most recent call last):
  File "/srv/web/boot.py", line 12, in <module>
    from store.api import availability
  File "/srv/store/api.py", line 1, in <module>
    from store.inventory import check_stock
ImportError: cannot import name 'check_stock' from 'store.inventory'
""",
    expected_error_type="ImportError",
    reference_root_cause=(
        "check_stock in store/inventory.py was renamed to stock_level without updating "
        "store/api.py, which still imports the old name, so the module fails at import time."
    ),
)


# ---------------------------------------------------------------------------
# 8. attribute_rename  (medium, no same-file decoy)
# ---------------------------------------------------------------------------
_USER_OK = """class User:
    def __init__(self, name, email_address):
        self.name = name
        self.email_address = email_address
"""

_USER_BUG = """class User:
    def __init__(self, name, email):
        self.name = name
        self.email = email
"""

_MAILER = """def send_welcome(user, transport):
    return transport.send(to=user.email_address, subject="Welcome")
"""

ATTRIBUTE_RENAME = Template(
    name="attribute_rename",
    # Not "easy": an AttributeError traceback names the *reader* of the
    # attribute, never the file where the class is defined. The agent has to
    # find `class User` itself.
    difficulty="medium",
    commits=(
        _c("Add user model", "Lena Fischer", "lena@example.com", {"models/user.py": _USER_OK}),
        _c("Add welcome mailer", "Sam Okonkwo", "sam@example.com", {"notify/mailer.py": _MAILER}),
        _c("Shorten user email field", "Lena Fischer", "lena@example.com",
           {"models/user.py": _USER_BUG}, culprit=True),
        _c("Add unsubscribe link builder", "Sam Okonkwo", "sam@example.com",
           {"notify/links.py": "def unsubscribe(token):\n    return f'/u/{token}'\n"}),
        _c("Add notify package doc", "Sam Okonkwo", "sam@example.com",
           {"notify/README.md": "# notify\n\nTransactional email.\n"}),
    ),
    error_log="""2026-04-02T19:07:44Z ERROR onboarding.welcome failed for signup 90211
Traceback (most recent call last):
  File "/srv/onboarding/welcome.py", line 28, in run
    send_welcome(user, transport)
  File "/srv/notify/mailer.py", line 2, in send_welcome
    return transport.send(to=user.email_address, subject="Welcome")
AttributeError: 'User' object has no attribute 'email_address'
""",
    expected_error_type="AttributeError",
    reference_root_cause=(
        "The User attribute email_address in models/user.py was renamed to email. "
        "notify/mailer.py still reads user.email_address, so attribute access fails."
    ),
)


# ---------------------------------------------------------------------------
# 9. regex_tightened  (medium, same-file decoy)
# ---------------------------------------------------------------------------
_VER_OK = '''import re

_PATTERN = re.compile(r"v?(\\d+)\\.(\\d+)")


def parse(tag):
    m = _PATTERN.search(tag)
    return int(m.group(1)), int(m.group(2))
'''

_VER_BUG = _VER_OK.replace('r"v?(\\d+)\\.(\\d+)"', 'r"v(\\d+)\\.(\\d+)"')

REGEX_TIGHTENED = Template(
    name="regex_tightened",
    difficulty="medium",
    commits=(
        _c("Add version tag parser", "Petra Nowak", "petra@example.com",
           {"release/version.py": _VER_OK}),
        _c("Sort releases by parsed version", "Diego Salas", "diego@example.com",
           {"release/order.py": "from release.version import parse\n\n\ndef newest(tags):\n    return max(tags, key=parse)\n"}),
        _c("Require the v prefix on version tags", "Petra Nowak", "petra@example.com",
           {"release/version.py": _VER_BUG}, culprit=True),
        _c("Add type hints to parse", "Diego Salas", "diego@example.com",
           {"release/version.py": _VER_BUG.replace("def parse(tag):", "def parse(tag: str) -> tuple[int, int]:")}),
        _c("Add changelog helper", "Diego Salas", "diego@example.com",
           {"release/changelog.py": "def render(entries):\n    return '\\n'.join(f'- {e}' for e in entries)\n"}),
    ),
    error_log="""2026-05-06T14:55:13Z ERROR release.publish pipeline aborted on tag 2.14.0
Traceback (most recent call last):
  File "/srv/release/publish.py", line 63, in main
    latest = newest(tags)
  File "/srv/release/order.py", line 5, in newest
    return max(tags, key=parse)
  File "/srv/release/version.py", line 8, in parse
    return int(m.group(1)), int(m.group(2))
AttributeError: 'NoneType' object has no attribute 'group'
""",
    expected_error_type="AttributeError",
    reference_root_cause=(
        "The version pattern in release/version.py was tightened from v?(\\d+) to v(\\d+), "
        "making the leading v mandatory. Tags published without the prefix no longer match, "
        "so search returns None and m.group raises."
    ),
)


# ---------------------------------------------------------------------------
# 10. timezone_naive  (hard, same-file decoy)
# ---------------------------------------------------------------------------
_WINDOW_OK = '''from datetime import datetime, timezone


def remaining(deadline):
    return deadline - datetime.now(timezone.utc)
'''

_WINDOW_BUG = '''from datetime import datetime, timezone


def remaining(deadline):
    return deadline - datetime.now()
'''

TIMEZONE_NAIVE = Template(
    name="timezone_naive",
    difficulty="hard",
    commits=(
        _c("Add SLA window helper", "Marta Oliveira", "marta@example.com",
           {"sla/window.py": _WINDOW_OK}),
        _c("Warn on tickets close to breach", "Femi Adeyemi", "femi@example.com",
           {"sla/alerts.py": "from sla.window import remaining\n\n\ndef at_risk(tickets):\n    return [t for t in tickets if remaining(t['deadline']).total_seconds() < 3600]\n"}),
        _c("Drop the explicit utc argument", "Marta Oliveira", "marta@example.com",
           {"sla/window.py": _WINDOW_BUG}, culprit=True),
        _c("Document the SLA window contract", "Marta Oliveira", "marta@example.com",
           {"sla/window.py": _WINDOW_BUG + "\n\n# deadline is expected to be timezone-aware.\n"}),
        _c("Add breach counter", "Femi Adeyemi", "femi@example.com",
           {"sla/metrics.py": "def breached(tickets):\n    return sum(1 for t in tickets if t.get('breached'))\n"}),
    ),
    error_log="""2026-06-18T02:15:39Z ERROR sla.sweep hourly at-risk sweep failed
Traceback (most recent call last):
  File "/srv/sla/sweep.py", line 44, in hourly
    risky = at_risk(open_tickets)
  File "/srv/sla/alerts.py", line 5, in at_risk
    return [t for t in tickets if remaining(t['deadline']).total_seconds() < 3600]
  File "/srv/sla/window.py", line 5, in remaining
    return deadline - datetime.now()
TypeError: can't subtract offset-naive and offset-aware datetimes
""",
    expected_error_type="TypeError",
    reference_root_cause=(
        "remaining in sla/window.py dropped the timezone.utc argument from datetime.now(), "
        "making it naive. Ticket deadlines are timezone-aware, and subtracting a naive from "
        "an aware datetime raises."
    ),
)


# ---------------------------------------------------------------------------
# 11. pagination_offset  (medium, no same-file decoy) - silent, no traceback
# ---------------------------------------------------------------------------
_PAGE_OK = """def slice_for(page, size, items):
    offset = (page - 1) * size
    return items[offset:offset + size]
"""

_PAGE_BUG = """def slice_for(page, size, items):
    offset = page * size
    return items[offset:offset + size]
"""

PAGINATION_OFFSET = Template(
    name="pagination_offset",
    difficulty="medium",
    commits=(
        _c("Add pagination helper", "Aoife Brennan", "aoife@example.com",
           {"listing/page.py": _PAGE_OK}),
        _c("Paginate the search endpoint", "Hugo Martins", "hugo@example.com",
           {"listing/search.py": "from listing.page import slice_for\n\n\ndef results(query, page, size, index):\n    return slice_for(page, size, index.match(query))\n"}),
        _c("Simplify offset arithmetic", "Aoife Brennan", "aoife@example.com",
           {"listing/page.py": _PAGE_BUG}, culprit=True),
        _c("Add total-count header", "Hugo Martins", "hugo@example.com",
           {"listing/search.py": "from listing.page import slice_for\n\n\ndef results(query, page, size, index):\n    matched = index.match(query)\n    return {'items': slice_for(page, size, matched), 'total': len(matched)}\n"}),
        _c("Add listing package doc", "Hugo Martins", "hugo@example.com",
           {"listing/README.md": "# listing\n\nSearch and pagination.\n"}),
        _c("Add sort helper", "Hugo Martins", "hugo@example.com",
           {"listing/sort.py": "def by_price(items):\n    return sorted(items, key=lambda i: i['price'])\n"}),
    ),
    error_log="""2026-07-21T10:33:07Z FAIL ci.listing regression suite failed on main
=================================== FAILURES ===================================
__________________________ test_first_page_starts_at_one _______________________

    def test_first_page_starts_at_one():
        items = list(range(1, 51))
>       assert results("all", page=1, size=10, index=stub(items))["items"][0] == 1
E       AssertionError: assert 11 == 1

listing/tests/test_search.py:22: AssertionError
=========================== short test summary info ============================
FAILED listing/tests/test_search.py::test_first_page_starts_at_one
Support reports the first ten results missing from every search since the 07-20 deploy.
Affected entry point: listing/search.py::results
""",
    expected_error_type="none",
    reference_root_cause=(
        "slice_for in listing/page.py changed offset from (page - 1) * size to page * size, "
        "so page 1 starts at index size instead of 0. Nothing raises; the first page of every "
        "result set is silently skipped."
    ),
)


# ---------------------------------------------------------------------------
# 12. recursion_base_case  (medium, same-file decoy)
# ---------------------------------------------------------------------------
_WALK_OK = """def flatten(node):
    if node is None:
        return []
    return flatten(node.get("left")) + [node["value"]] + flatten(node.get("right"))
"""

_WALK_BUG = """def flatten(node):
    return flatten(node.get("left")) + [node["value"]] + flatten(node.get("right"))
"""

RECURSION_BASE_CASE = Template(
    name="recursion_base_case",
    difficulty="medium",
    commits=(
        _c("Add tree flatten", "Bea Lindgren", "bea@example.com", {"tree/walk.py": _WALK_OK}),
        _c("Export category tree as a list", "Nikhil Rao", "nikhil@example.com",
           {"tree/export.py": "from tree.walk import flatten\n\n\ndef as_list(root):\n    return flatten(root)\n"}),
        _c("Remove redundant None check in flatten", "Bea Lindgren", "bea@example.com",
           {"tree/walk.py": _WALK_BUG}, culprit=True),
        _c("Add depth helper", "Bea Lindgren", "bea@example.com",
           {"tree/walk.py": _WALK_BUG + "\n\ndef depth(node, d=0):\n    return d if node is None else d + 1\n"}),
        _c("Cache the exported list", "Nikhil Rao", "nikhil@example.com",
           {"tree/export.py": "from tree.walk import flatten\n\n_CACHE = {}\n\n\ndef as_list(root):\n    return flatten(root)\n"}),
    ),
    error_log="""2026-08-09T06:12:58Z ERROR catalog.export nightly category export failed
Traceback (most recent call last):
  File "/srv/catalog/export.py", line 31, in nightly
    rows = as_list(root)
  File "/srv/tree/export.py", line 5, in as_list
    return flatten(root)
  File "/srv/tree/walk.py", line 2, in flatten
    return flatten(node.get("left")) + [node["value"]] + flatten(node.get("right"))
  File "/srv/tree/walk.py", line 2, in flatten
    return flatten(node.get("left")) + [node["value"]] + flatten(node.get("right"))
  [Previous line repeated 996 more times]
RecursionError: maximum recursion depth exceeded
""",
    expected_error_type="RecursionError",
    reference_root_cause=(
        "flatten in tree/walk.py lost its `if node is None` base case, so recursion never "
        "terminates at a leaf and the call stack is exhausted."
    ),
)


EXTRA_TEMPLATES: tuple[Template, ...] = (
    IMPORT_RENAME,
    ATTRIBUTE_RENAME,
    REGEX_TIGHTENED,
    TIMEZONE_NAIVE,
    PAGINATION_OFFSET,
    RECURSION_BASE_CASE,
)
