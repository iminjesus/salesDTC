#!/usr/bin/env python3
"""Kept so `python crawl_jbhifi.py` still works. The crawler now handles several
retailers, so it lives in crawl.py and takes a --site argument:

    python crawl.py --site jbhifi
    python crawl.py --site harveynorman
"""
import runpy
import sys

if not any(a == '--site' or a.startswith('--site=') for a in sys.argv[1:]):
    sys.argv += ['--site', 'jbhifi']
sys.argv[0] = 'crawl.py'
runpy.run_path('crawl.py', run_name='__main__')
