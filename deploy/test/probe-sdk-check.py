"""Offline compatibility check using the installed official SDK, no cloud requests."""
import importlib.util
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from qcloud_cos import CosConfig, CosS3Client

spec = importlib.util.spec_from_file_location('probe', Path(__file__).with_name('network-probe.py'))
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
client = CosS3Client(CosConfig(Region=probe.REGION, SecretId='fixture-id', SecretKey='fixture-key', Scheme='https'))
for method in ('PUT', 'GET', 'DELETE'):
    with patch('qcloud_cos.cos_auth.time.time', return_value=1700000000):
        url = probe.signed_url(client, method, '123-1-1')
    query = parse_qs(urlsplit(url).query)
    assert 'q-signature' in query
    start, end = map(int, query['q-sign-time'][0].split(';'))
    # SDK backdates the start by 60s for clock skew; expiry remains now + 600s.
    assert (start, end) == (1699999940, 1700000600)
    assert 'host' in query['q-header-list'][0]
print('PASS: official SDK host-bound 600-second PUT/GET/DELETE signing; no cloud requests')
