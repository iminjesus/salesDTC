#!/usr/bin/env python3
"""How a customer is divided up, in one place so both pages agree.

The account name is only ever used to say which side of the business a row is
on - online or offline. Everything below that is Type, then Type2, then Portal
Group. So `E-STORE`, `E-STORE_B2B` and anything else that is not marked offline
all become one channel, and the detail comes from the levels underneath rather
than from a name that was never meant to carry it.
"""
from __future__ import annotations

import re

ONLINE = 'E-STORE'
OFFLINE = 'OFF-LINE'
BLANK = '(blank)'
NO_MATCH = '(no customer match)'

# 'off-line', 'OFF LINE', 'Offline' - the exports have used all of them.
_OFFLINE = re.compile(r'off\W*line', re.I)

# The customer drill, top first. Reordering this list reorders both pages.
LEVELS = [
    ('Channel',      'channel', ()),
    ('Type',         'type',    ('Type', 'customer_type')),
    ('Portal Group', 'portal',  ('Portal Group', 'portal_group')),
    ('Type2',        'type2',   ('Type2', 'Type 2', 'Type_2', 'Sub Type')),
]
ACCOUNT_NAMES = ('Account Name', 'account_name', 'Cus_group', 'Customer Group')


def channel_of(account_name: str, matched: bool = True) -> str:
    """Which side of the business a row sits on, from its account name."""
    t = str(account_name or '').strip()
    if not t:
        return BLANK if matched else NO_MATCH
    return OFFLINE if _OFFLINE.search(t) else ONLINE
