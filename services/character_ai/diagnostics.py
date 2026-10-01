"""Opt-in, owner-scoped request inspection. Headers/credentials are never stored."""
import time

def record_request(settings,store,owner,character,kind,payload):
    if not settings.enable_test_inspector:return
    entries=store.get('inspection_requests',owner,character,[])
    entries.append(dict(kind=kind,created=time.time(),payload=payload))
    store.put('inspection_requests',owner,character,entries[-12:])
