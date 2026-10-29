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

# What the master calls the column that decides online from offline. It is a
# channel marker rather than a name, whatever its header says.
ACCOUNT_NAMES = ('Account Name', 'account_name', 'Cus_group', 'Customer Group')
# And what it calls the customer itself. SAP has shipped this under half a
# dozen headers; the first one the file carries wins, and
# --customer-name-column names one these miss.
NAME_COLS = ('Customer Name', 'Sold-to Name', 'Sold To Name', 'Sold-To Name',
             'Name 1', 'Name1', 'Cus_name', 'customer_name', 'Payer Name',
             'Customer Desc', 'Customer Description', 'Account', 'Name')

# The customer drill, top first. Reordering this list reorders both pages.
LEVELS = [
    ('Channel',      'channel', ()),
    ('Type',         'type',    ('Type', 'customer_type')),
    ('Portal Group', 'portal',  ('Portal Group', 'portal_group')),
    ('Type2',        'type2',   ('Type2', 'Type 2', 'Type_2', 'Sub Type')),
    # Who the customer actually is, deepest. "Show me Myer" had no answer
    # above this line: Myer is not a Channel, a Type, a Portal Group or a
    # Type2 - it is one account underneath all four.
    #
    # Its own slot, and not `account`. The column called Account Name holds
    # E-STORE, E-STORE_B2B and off-line - a channel marker, which is all this
    # page ever asked of it - so a level reading it offered those three back
    # and named nobody. The customer's name is a different column, and the
    # build drops this level rather than show the marker again when the
    # master has not got one.
    ('Customer name', 'name', NAME_COLS),
]


def channel_of(account_name: str, matched: bool = True) -> str:
    """Which side of the business a row sits on, from its account name."""
    t = str(account_name or '').strip()
    if not t:
        return BLANK if matched else NO_MATCH
    return OFFLINE if _OFFLINE.search(t) else ONLINE
