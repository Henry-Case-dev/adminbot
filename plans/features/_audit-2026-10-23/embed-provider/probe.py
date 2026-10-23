# -*- coding: utf-8 -*-
"""EMBED-PROVIDER-CHECK: read-only prod probes for the embedding provider switch.

SSH discipline (AGENTS.md fail2ban): minimal logins, >=60 s apart, one batch.

  py -3 probe.py main      # read-only: config/pool/quota/backlog/index + live probe
  py -3 probe.py unpark    # (only if needed) app-owned quota unpark via set_group_state

Never prints secrets: keys -> "<set>" + length only; DSN/passwords scrubbed.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import paramiko

HOST = "198.46.175.136"
USER = "nik"
CREDS = Path(r"C:\Code\Python\adminbot\deploy_commands.txt")
OUT = Path(r"C:\Code\Python\adminbot\plans\features\_audit-2026-10-23\embed-provider\raw")
APP = "/var/www/admin_bot"


def _pwd(pattern: str) -> str:
    m = re.search(rf"^{pattern}:\s*(\S+)\s*$",
                  CREDS.read_text(encoding="utf-8", errors="replace"), re.M)
    if not m:
        raise SystemExit(f"credential '{pattern}' not found")
    return m.group(1)


def scrub(text: str, secrets: list[str]) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    text = re.sub(r"(postgres(?:ql)?://[^:\s]+:)[^@\s]+@", r"\1***@", text)
    text = re.sub(r"(sk-[A-Za-z0-9_\-]{4})[A-Za-z0-9_\-]+", r"\1***", text)
    text = re.sub(r"(AIza[A-Za-z0-9_\-]{4})[A-Za-z0-9_\-]+", r"\1***", text)
    text = re.sub(r"(?i)(bearer\s+)\S+", r"\1***", text)
    text = re.sub(r"(?i)((?:api[_-]?key|token|secret|password)\s*[=:]\s*)\S+",
                  r"\1***", text)
    return text


def connect(pw: str) -> paramiko.SSHClient:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, 22, USER, pw, timeout=20, banner_timeout=20,
              auth_timeout=20, allow_agent=False, look_for_keys=False)
    return c


HEADER = r"""
set +e
export LC_ALL=C
cd __APP__ || exit 3
echo "DATE_UTC=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "DATE_LOCAL=$(date '+%Y-%m-%d %H:%M:%S %Z %z')"
echo "HEAD=$(git rev-parse HEAD)"
echo "ACTIVE=$(systemctl is-active admin_bot)"
systemctl show admin_bot -p NRestarts -p ExecMainStartTimestamp -p MainPID --no-pager
echo "HZ=$(curl -s --max-time 8 http://127.0.0.1:8000/healthz)"
PYBIN=""
for cand in venv/bin/python .venv/bin/python python3; do
  if [ -x "$cand" ] || command -v "$cand" >/dev/null 2>&1; then PYBIN="$cand"; break; fi
done
echo "PYBIN=$PYBIN"
DBP=$(grep -E '^DB_PATH=' .env | cut -d= -f2- | tr -d '"' | tr -d "'" | tr -d '\r')
[ -z "$DBP" ] && DBP=local_database.db
echo "DB_PATH=$DBP"
export DBP
echo "===== ENV (masked) ====="
grep -hE '^(EMBEDDING_|EMBED_|POSTGRES_|PG_)' .env 2>/dev/null \
  | sed -E 's/^([A-Z0-9_]*(KEY|TOKEN|SECRET|PASSWORD|DSN|URL)[A-Z0-9_]*)=.*/\1=<set>/' \
  | sort
"""

CONFIG_PY = r"""
import asyncio, json, os, sys, time
sys.path.insert(0, '.')
from config.settings import settings  # loads .env
import asyncpg
from services import hot_config
from services import embedding_control_plane as ecp

SECRET_RE = ('key', 'token', 'secret', 'password', 'dsn')

def mask(name, value):
    if value is None:
        return None
    s = str(value)
    low = name.lower()
    if any(t in low for t in SECRET_RE):
        return f"<set len={len(s)}>" if s else "<empty>"
    return s

class Cache:
    def __init__(self, data): self._d = dict(data)
    def get(self, k, default=None): return self._d.get(k, default)

async def main():
    dsn = os.getenv('POSTGRES_DSN')
    print('PG_DSN', 'set' if dsn else 'absent')
    keys = []
    conn = await asyncpg.connect(dsn, timeout=15)
    try:
        rows = await conn.fetch(
            "SELECT key, value, category, updated_at FROM bot_settings "
            "WHERE key LIKE 'models.embedding%' OR key LIKE 'keys.embedding%' "
            "OR key LIKE 'models.embedding_quota%' ORDER BY key")
    finally:
        await conn.close()
    data = {}
    print('===== PG bot_settings (masked) =====')
    for r in rows:
        raw = r['value']
        try:
            val = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            val = raw
        data[r['key']] = val
        print('PG | %-42s | %-24s | %s' % (
            r['key'], mask(r['key'], val), r['category']))
        print('     updated_at=%s' % r['updated_at'])
    if not rows:
        print('PG | <no embedding rows>')
    hot_config.set_config_cache(Cache(data))

    print('===== effective settings fields (env/default layer) =====')
    for field in ('EMBEDDING_BASE_URL', 'EMBEDDING_MODEL_NAME',
                  'EMBEDDING_FALLBACK_BASE_URL', 'EMBEDDING_FALLBACK_MODEL',
                  'EMBEDDING_QUOTA_GROUP_LABELS', 'EMBEDDING_DIM',
                  'EMBED_CONTROL_PLANE_ENABLED',
                  'EMBED_QUOTA_GROUP_COOLDOWN_ENABLED',
                  'EMBED_QUOTA_KIND_PARKING_ENABLED',
                  'EMBED_ADAPTIVE_CONCURRENCY_ENABLED'):
        print('ENV/default | %-36s | %s' % (field, mask(field, getattr(settings, field, None))))
    for field in ('EMBEDDING_API_KEY', 'EMBEDDING_FALLBACK_API_KEY',
                  'EMBEDDING_FALLBACK_API_KEY_2', 'EMBEDDING_EXTRA_API_KEYS'):
        print('ENV/default | %-36s | %s' % (field, mask(field, getattr(settings, field, None))))

    print('===== pool =====')
    pool = ecp.build_credential_pool()
    diag = ecp.pool_rotation_diagnosis(pool)
    print('POOL_DIAG', json.dumps(diag, ensure_ascii=False, sort_keys=True))
    for c in pool:
        print('CRED | alias=%-10s | provider=%-24s | model=%-24s | base=%s | group=%s | known=%s | gsource=%s | ksource=%s | key=%s'
              % (c.alias, c.provider, c.model, c.base_url, c.quota_group_id,
                 c.quota_group_known, c.quota_group_source, c.key_source,
                 mask('key', c.api_key)))
    print('===== provider_panel =====')
    print(json.dumps(ecp.provider_panel(), ensure_ascii=False, sort_keys=True))
    print('===== profiles (per-slot base/model/group) =====')
    for alias, p in ecp.resolve_embedding_profiles().items():
        print('PROFILE | %-10s | base=%-42s | model=%-24s | group=%-10s | inherited=%s'
              % (alias, p.base_url, p.model, p.quota_group, p.inherited))

asyncio.run(main())
"""

SQLITE_PY = r"""
import os, sqlite3, time, re
dbp = os.environ.get('DBP') or 'local_database.db'
con = sqlite3.connect('file:%s?mode=ro' % dbp, uri=True, timeout=20)
con.row_factory = sqlite3.Row
con.execute('PRAGMA query_only=ON')
now = int(time.time())

def q(label, sql, params=(), limit=40):
    try:
        rows = con.execute(sql, params).fetchall()
    except Exception as e:
        print('--- %s --- ERROR %s: %s' % (label, type(e).__name__, e)); return []
    print('--- %s (n=%d) ---' % (label, len(rows)))
    for r in rows[:limit]:
        print(dict(r))
    if len(rows) > limit:
        print('...(%d more)' % (len(rows) - limit))
    return rows

print('NOW_EPOCH', now)
print('===== embedding_quota_state =====')
q('quota_state', "SELECT * FROM embedding_quota_state ORDER BY quota_group_id")

print('===== vector tables (live + generations) =====')
rows = q('vec_objects', "SELECT name, sql FROM sqlite_master WHERE type='table' "
         "AND (name LIKE '%_vec%' OR name LIKE 'smart_archive%') ORDER BY name", limit=80)
for r in rows:
    m = re.search(r'float\[(\d+)\]', r['sql'] or '')
    print('DIM | %-34s | %s' % (r['name'], m.group(1) if m else 'NO_FLOAT_DIM'))
q('vec_counts', "SELECT name FROM sqlite_master WHERE type='table' "
  "AND (name LIKE 'graph_facts_vec%' OR name LIKE 'smart_archive%')")
try:
    for (name,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' "
                               "AND (name LIKE 'graph_facts_vec%' OR name LIKE 'smart_archive%')").fetchall():
        try:
            c = con.execute('SELECT COUNT(*) FROM "%s"' % name).fetchone()[0]
            print('COUNT | %-34s | %s' % (name, c))
        except Exception as e:
            print('COUNT | %-34s | ERROR %s' % (name, e))
except Exception as e:
    print('COUNT error', e)

print('===== index generations =====')
q('mca_embedding_index_generations',
  "SELECT * FROM mca_embedding_index_generations ORDER BY rowid DESC LIMIT 12")

print('===== embedding_cache =====')
try:
    print(dict(con.execute("SELECT COUNT(*) c, MIN(dim) dmin, MAX(dim) dmax, "
                           "MAX(created_at) newest, MAX(last_used_at) used FROM embedding_cache").fetchone()))
    q('cache_dims', "SELECT dim, COUNT(*) c FROM embedding_cache GROUP BY dim ORDER BY c DESC LIMIT 10")
    q('cache_per_day', "SELECT date(created_at,'unixepoch') d, COUNT(*) c FROM embedding_cache "
      "WHERE created_at > strftime('%s','now') - 7*86400 GROUP BY d ORDER BY d")
except Exception as e:
    print('cache error', e)

print('===== backlog =====')
try:
    print(dict(con.execute("SELECT COUNT(*) total FROM graph_facts").fetchone()))
    print(dict(con.execute("SELECT COUNT(*) eligible FROM graph_facts WHERE expires_at IS NULL OR expires_at > ?", (now,)).fetchone()))
except Exception as e:
    print('graph_facts error', e)
try:
    print(dict(con.execute("SELECT COUNT(*) archive_facts FROM smart_archive_facts").fetchone()))
except Exception as e:
    print('smart_archive_facts error', e)

print('===== backlog precise =====')
q('backlog_graph_missing', "SELECT COUNT(*) c FROM graph_facts WHERE id NOT IN "
  "(SELECT fact_id FROM graph_facts_vec) AND (expires_at IS NULL OR expires_at > ?)", (now,))
q('backlog_per_chat', "SELECT chat_id, COUNT(*) c, MIN(created_at) oldest "
  "FROM graph_facts WHERE id NOT IN (SELECT fact_id FROM graph_facts_vec) "
  "AND (expires_at IS NULL OR expires_at > ?) GROUP BY chat_id", (now,))

print('===== daily throughput (smart_messages, UTC days) =====')
q('messages_per_day', "SELECT date(timestamp,'unixepoch') d, COUNT(*) c FROM smart_messages "
  "WHERE timestamp > strftime('%s','now') - 7*86400 GROUP BY d ORDER BY d")
try:
    q('facts_per_day', "SELECT date(created_at,'unixepoch') d, COUNT(*) c, "
      "SUM(CASE WHEN id IN (SELECT fact_id FROM graph_facts_vec) THEN 0 ELSE 1 END) unvectorized "
      "FROM graph_facts WHERE created_at > strftime('%s','now') - 7*86400 GROUP BY d ORDER BY d")
except Exception as e:
    print('facts_per_day skip', e)
try:
    q('summary_runs_recent', "SELECT state, COUNT(*) c FROM summary_runs "
      "WHERE created_at > strftime('%s','now') - 7*86400 GROUP BY state")
except Exception as e:
    print('summary_runs skip', e)

print('===== last rebuild jobs =====')
q('rebuild_jobs', "SELECT job_id, status, reason_code, attempt, updated_at, "
  "substr(payload,1,180) payload FROM task_jobs WHERE kind='graphrag_rebuild' "
  "ORDER BY created_at DESC LIMIT 6")
"""

PROBE_PY = r"""
import asyncio, json, os, sys, time
sys.path.insert(0, '.')
from config.settings import settings
import asyncpg, aiosqlite
from services import hot_config
from services import embedding_control_plane as ecp
from services.llm_client import LLMClient

class Cache:
    def __init__(self, data): self._d = dict(data)
    def get(self, k, default=None): return self._d.get(k, default)

def fmt_ts(ts):
    try:
        return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(int(ts))) if ts else '0'
    except Exception:
        return str(ts)

async def main():
    dsn = os.getenv('POSTGRES_DSN')
    conn = await asyncpg.connect(dsn, timeout=15)
    try:
        rows = await conn.fetch("SELECT key, value FROM bot_settings")
    finally:
        await conn.close()
    data = {}
    for r in rows:
        raw = r['value']
        try:
            data[r['key']] = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            data[r['key']] = raw
    hot_config.set_config_cache(Cache(data))

    # mirror runtime quota state from SQLite (as load_group_states would)
    dbp = os.getenv('DBP') or 'local_database.db'
    ro = await aiosqlite.connect('file:%s?mode=ro' % dbp, uri=True)
    ro.row_factory = aiosqlite.Row
    try:
        cur = await ro.execute("SELECT quota_group_id, state, next_allowed_at, note, updated_at FROM embedding_quota_state")
        for row in await cur.fetchall():
            ecp.REGISTRY._groups[str(row['quota_group_id'])] = ecp.EmbeddingQuotaGroup(
                quota_group_id=str(row['quota_group_id']), state=str(row['state']),
                next_allowed_at=int(row['next_allowed_at'] or 0), note=str(row['note'] or ''),
                updated_at=int(row['updated_at'] or 0))
    finally:
        await ro.close()

    pool = ecp.build_credential_pool()
    print('===== runtime-mirrored parking check =====')
    now = int(time.time())
    for gid in sorted({c.quota_group_id for c in pool}):
        g = ecp.REGISTRY.group_state(gid)
        blocked = ecp.REGISTRY.group_blocked(gid, now)
        print('GROUP | %-12s | state=%-10s | note=%-32s | next_allowed_at=%s | blocked_now=%s | in=%ss'
              % (gid, g.state, g.note, fmt_ts(g.next_allowed_at), blocked,
                 (g.next_allowed_at - now) if g.next_allowed_at else 0))
    if not pool:
        print('POOL_EMPTY'); return

    llm = LLMClient(base_url=settings.LLM_BASE_URL or 'https://example.invalid/v1',
                    api_key=settings.LLM_API_KEY or 'probe-chat',
                    chat_model=settings.LLM_MODEL_NAME or 'none',
                    embed_model=settings.EMBEDDING_MODEL_NAME)
    calls = []
    orig = llm._post
    async def spy(path, payload, **kw):
        t0 = time.perf_counter()
        resp = await orig(path, payload, **kw)
        hdrs = {k: v for k, v in resp.headers.items()
                if k.lower() in ('retry-after', 'x-ratelimit-limit-requests',
                                 'x-ratelimit-remaining-requests', 'x-request-id',
                                 'content-type', 'date', 'x-ratelimit-limit-tokens',
                                 'x-ratelimit-remaining-tokens')}
        body_model = None
        dim = None
        usage = None
        try:
            body = resp.json()
            body_model = body.get('model')
            usage = body.get('usage')
            if body.get('data'):
                dim = len(body['data'][0]['embedding'])
        except Exception:
            pass
        calls.append({'path': path, 'base_url': kw.get('base_url'), 'channel': kw.get('channel'),
                      'model': payload.get('model'), 'status': resp.status_code,
                      'resp_model': body_model, 'dim': dim, 'usage': usage,
                      'latency_ms': round((time.perf_counter() - t0) * 1000, 1), 'headers': hdrs})
        return resp
    llm._post = spy

    print('===== live probe via control plane (respects parking) =====')
    stats = ecp.ExecutionStats()
    t0 = time.perf_counter()
    try:
        vecs = await ecp.execute_embed(llm, ['проверка провайдера эмбеддингов ok 12345'],
                                       priority=ecp.Priority.P2_REPAIR, max_wait_s=12)
        dt = round((time.perf_counter() - t0) * 1000, 1)
        print('EXECUTOR_OK | calls=%d | total_ms=%s | dim=%d | vectors=%d | creds=%s'
              % (len(calls), dt, len(vecs[0]), len(vecs), stats.credentials_used))
    except Exception as exc:
        print('EXECUTOR_FAIL | %s | %s' % (type(exc).__name__, exc))
        gid = getattr(exc, 'group_id', None)
        na = getattr(exc, 'next_allowed_at', None)
        if gid:
            print('EXECUTOR_FAIL_DETAIL | group=%s | next_allowed_at=%s' % (gid, fmt_ts(na)))
        for c in calls:
            print('CALL | %s' % json.dumps(c, ensure_ascii=False, sort_keys=True))
        calls.clear()
        print('===== diagnostic single call (direct client, same credential, bypass parking) =====')
        t0 = time.perf_counter()
        try:
            vecs = await llm.embed_once(['проверка провайдера эмбеддингов ok 12345'],
                                       api_key=pool[0].api_key,
                                       base_url=pool[0].base_url,
                                       model=pool[0].model, max_retries=0,
                                       retry_statuses=())
            dt = round((time.perf_counter() - t0) * 1000, 1)
            print('DIRECT_OK | alias=%s | total_ms=%s | dim=%d | vectors=%d'
                  % (pool[0].alias, dt, len(vecs[0]), len(vecs)))
        except Exception as exc:
            print('DIRECT_FAIL | %s | %s' % (type(exc).__name__, exc))
    for c in calls:
        print('CALL | %s' % json.dumps(c, ensure_ascii=False, sort_keys=True))
    try:
        await llm.close()
    except Exception:
        pass

asyncio.run(main())
"""

FB_PY = r"""
import asyncio, json, os, sys, time
sys.path.insert(0, '.')
from config.settings import settings
import asyncpg
from services import hot_config
from services import embedding_control_plane as ecp
from services.llm_client import LLMClient

class Cache:
    def __init__(self, data): self._d = dict(data)
    def get(self, k, default=None): return self._d.get(k, default)

async def main():
    dsn = os.getenv('POSTGRES_DSN')
    conn = await asyncpg.connect(dsn, timeout=15)
    try:
        rows = await conn.fetch("SELECT key, value FROM bot_settings")
    finally:
        await conn.close()
    data = {}
    for r in rows:
        raw = r['value']
        try:
            data[r['key']] = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            data[r['key']] = raw
    hot_config.set_config_cache(Cache(data))
    pool = {c.alias: c for c in ecp.build_credential_pool()}
    profiles = ecp.resolve_embedding_profiles()
    llm = LLMClient(base_url=settings.LLM_BASE_URL or 'https://example.invalid/v1',
                    api_key=settings.LLM_API_KEY or 'probe-chat',
                    chat_model=settings.LLM_MODEL_NAME or 'none',
                    embed_model=settings.EMBEDDING_MODEL_NAME)
    calls = []
    orig = llm._post
    async def spy(path, payload, **kw):
        t0 = time.perf_counter()
        try:
            resp = await orig(path, payload, **kw)
        except Exception as exc:
            calls.append({'base_url': kw.get('base_url'), 'error': type(exc).__name__,
                          'detail': str(exc)[:160],
                          'latency_ms': round((time.perf_counter() - t0) * 1000, 1)})
            raise
        hdrs = {k: v for k, v in resp.headers.items()
                if k.lower() in ('retry-after', 'x-ratelimit-limit-requests',
                                 'x-ratelimit-remaining-requests',
                                 'x-ratelimit-limit-tokens',
                                 'x-ratelimit-remaining-tokens', 'date')}
        body_model = dim = None
        try:
            body = resp.json()
            body_model = body.get('model')
            if body.get('data'):
                dim = len(body['data'][0]['embedding'])
        except Exception:
            pass
        calls.append({'base_url': kw.get('base_url'), 'status': resp.status_code,
                      'resp_model': body_model, 'dim': dim,
                      'latency_ms': round((time.perf_counter() - t0) * 1000, 1),
                      'headers': hdrs})
        return resp
    llm._post = spy
    for alias in ('fallback_1', 'fallback_2'):
        cred = pool.get(alias)
        prof = profiles.get(alias)
        if not cred or not prof:
            continue
        print('PROBE | alias=%s | base=%s | model=%s | group=%s'
              % (alias, prof.base_url, prof.model, cred.quota_group_id))
        try:
            vecs = await llm.embed_once(['проверка запасного ключа ok 12345'],
                                        api_key=cred.api_key,
                                        base_url=prof.base_url,
                                        model=prof.model, max_retries=0,
                                        retry_statuses=())
            print('FB_OK | alias=%s | dim=%d' % (alias, len(vecs[0])))
        except Exception as exc:
            print('FB_FAIL | alias=%s | %s | %s' % (alias, type(exc).__name__, str(exc)[:240]))
    for c in calls:
        print('CALL | %s' % json.dumps(c, ensure_ascii=False, sort_keys=True))
    try:
        await llm.close()
    except Exception:
        pass

asyncio.run(main())
"""

SQL2_PY = r"""
import glob, os, sqlite3, time
dbp = os.environ.get('DBP') or 'local_database.db'
con = sqlite3.connect('file:%s?mode=ro' % dbp, uri=True, timeout=20)
con.row_factory = sqlite3.Row
con.execute('PRAGMA query_only=ON')
now = int(time.time())
cands = (glob.glob('venv/lib/python*/site-packages/sqlite_vec/vec0*')
         + glob.glob('.venv/lib/python*/site-packages/sqlite_vec/vec0*')
         + glob.glob('/usr/lib/python3*/site-packages/sqlite_vec/vec0*'))
print('VEC0_CANDIDATES', cands)
ok = False
for c in cands:
    try:
        con.enable_load_extension(True)
        con.load_extension(c)
        ok = True
        print('VEC0_LOADED', c)
        break
    except Exception as e:
        print('VEC0_LOAD_FAIL', c, type(e).__name__, e)
print('VEC0_OK', ok)

def q(label, sql, params=(), limit=40):
    try:
        rows = con.execute(sql, params).fetchall()
    except Exception as e:
        print('--- %s --- ERROR %s: %s' % (label, type(e).__name__, e)); return []
    print('--- %s (n=%d) ---' % (label, len(rows)))
    for r in rows[:limit]:
        print(dict(r))
    if len(rows) > limit:
        print('...(%d more)' % (len(rows) - limit))
    return rows

if ok:
    q('vec_counts_live', "SELECT (SELECT COUNT(*) FROM graph_facts_vec) gvec, "
      "(SELECT COUNT(*) FROM graph_facts_vec_g1) gvec_g1, "
      "(SELECT COUNT(*) FROM smart_archive) svec")
    q('backlog_graph_missing', "SELECT COUNT(*) c FROM graph_facts WHERE id NOT IN "
      "(SELECT fact_id FROM graph_facts_vec) AND (expires_at IS NULL OR expires_at > ?)", (now,))
    q('backlog_per_chat', "SELECT chat_id, COUNT(*) c, MIN(created_at) oldest, "
      "MIN(id) min_id FROM graph_facts WHERE id NOT IN (SELECT fact_id FROM graph_facts_vec) "
      "AND (expires_at IS NULL OR expires_at > ?) GROUP BY chat_id", (now,))
    q('expired_not_vec', "SELECT COUNT(*) c FROM graph_facts WHERE id NOT IN "
      "(SELECT fact_id FROM graph_facts_vec) AND expires_at IS NOT NULL AND expires_at <= ?", (now,))
q('facts_per_day', "SELECT date(created_at,'unixepoch') d, COUNT(*) c FROM graph_facts "
  "WHERE created_at > strftime('%s','now') - 7*86400 GROUP BY d ORDER BY d")
q('facts_by_origin', "SELECT origin, COUNT(*) c FROM graph_facts GROUP BY origin ORDER BY c DESC")
q('facts_by_chat', "SELECT chat_id, COUNT(*) c, MIN(created_at) oldest FROM graph_facts GROUP BY chat_id")
q('messages_by_chat', "SELECT chat_id, COUNT(*) c FROM smart_messages GROUP BY chat_id")
"""

APPLY_PY = r"""
import asyncio, glob, hashlib, hmac, json, os, re, sqlite3, time
import urllib.error, urllib.parse, urllib.request
sys_path = '.'
import sys
sys.path.insert(0, sys_path)
from config.settings import settings
import asyncpg, aiosqlite
from services import hot_config
from services import embedding_control_plane as ecp
from services.llm_client import LLMClient

BASE = 'http://127.0.0.1:8000'
OWNER_ID = 5885953495
KEY = 'keys.embedding_quota_group_labels'
VALUE = 'primary:apinet_paid,fallback_1:google_free_1,fallback_2:google_free_2'
DBP = os.environ.get('DBP') or 'local_database.db'

class Cache:
    def __init__(self, data): self._d = dict(data)
    def get(self, k, default=None): return self._d.get(k, default)

def env_token():
    tok = os.getenv('API_TOKEN') or getattr(settings, 'API_TOKEN', '')
    if tok:
        return tok
    with open('.env', 'r', encoding='utf-8', errors='replace') as fh:
        for line in fh:
            if line.strip().startswith('API_TOKEN='):
                return line.split('=', 1)[1].strip().strip('"').strip("'")
    raise SystemExit('API_TOKEN not found')

def init_data(token, uid=OWNER_ID):
    fields = {'auth_date': str(int(time.time())), 'query_id': 'AAHembedunpark',
              'user': json.dumps({'id': uid, 'first_name': 'Owner', 'username': 'owner'},
                                 separators=(',', ':'))}
    check = '\n'.join('%s=%s' % (k, fields[k]) for k in sorted(fields))
    secret = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
    sig = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + '&hash=' + sig

def http(method, path, body=None, init_=None, timeout=45):
    headers = {'User-Agent': 'embed-unpark-probe'}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers['Content-Type'] = 'application/json'
    if init_:
        headers['X-Telegram-Init-Data'] = init_
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, raw
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()

def jload(raw):
    try:
        return json.loads(raw.decode('utf-8'))
    except Exception:
        return raw.decode('utf-8', 'replace')[:400]

def open_db_ro():
    con = sqlite3.connect('file:%s?mode=ro' % DBP, uri=True, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA query_only=ON')
    try:
        for c in glob.glob('venv/lib/python*/site-packages/sqlite_vec/vec0*'):
            con.enable_load_extension(True); con.load_extension(c); break
    except Exception as e:
        print('VEC0_LOAD_FAIL', type(e).__name__, e)
    return con

def snapshot(label):
    con = open_db_ro()
    try:
        now = int(time.time())
        print('--- %s @ %s ---' % (label, time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now))))
        for r in con.execute("SELECT quota_group_id, state, next_allowed_at, note, updated_at "
                             "FROM embedding_quota_state ORDER BY quota_group_id"):
            print('QUOTA |', dict(r))
        try:
            miss = con.execute("SELECT COUNT(*) c FROM graph_facts WHERE id NOT IN "
                               "(SELECT fact_id FROM graph_facts_vec) AND "
                               "(expires_at IS NULL OR expires_at > ?)", (now,)).fetchone()['c']
            print('BACKLOG_GRAPH', miss)
        except Exception as e:
            print('BACKLOG_GRAPH_ERR', e)
        try:
            print('CACHE', dict(con.execute("SELECT COUNT(*) c, MAX(created_at) newest FROM embedding_cache").fetchone()))
        except Exception as e:
            print('CACHE_ERR', e)
        try:
            rows = con.execute("SELECT status, reason_code, attempt, updated_at, payload "
                               "FROM task_jobs WHERE kind='graphrag_rebuild' ORDER BY created_at DESC LIMIT 1").fetchall()
            for r in rows:
                print('JOB |', dict(r))
        except Exception as e:
            print('JOB_ERR', e)
        q = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%queue%'")]
        print('QUEUE_TABLES', q)
    finally:
        con.close()

async def fetch_settings():
    dsn = os.getenv('POSTGRES_DSN')
    conn = await asyncpg.connect(dsn, timeout=15)
    try:
        rows = await conn.fetch("SELECT key, value FROM bot_settings")
    finally:
        await conn.close()
    data = {}
    for r in rows:
        raw = r['value']
        try:
            data[r['key']] = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            data[r['key']] = raw
    return data

async def main():
    token = env_token()
    ini = init_data(token)
    print('INITDATA minted for owner id', OWNER_ID)

    # 0) owner is a global admin?
    dsn = os.getenv('POSTGRES_DSN')
    conn = await asyncpg.connect(dsn, timeout=15)
    try:
        row = await conn.fetchrow("SELECT telegram_id, role_name FROM bot_admins WHERE telegram_id=$1", OWNER_ID)
    finally:
        await conn.close()
    print('ADMIN_ROW', dict(row) if row else None)
    if not row:
        print('ABORT: owner id not in bot_admins'); return

    snapshot('BEFORE')
    st, raw = http('GET', '/api/config', init_=ini)
    cfg = jload(raw)
    live_before = None
    if isinstance(cfg, dict):
        for it in cfg.get('items', []):
            if it.get('key') == KEY:
                live_before = it.get('value')
    print('LIVE_BEFORE | %s=%r' % (KEY, live_before))

    st, raw = http('POST', '/api/config', body={'items': [{'key': KEY, 'value': VALUE}]}, init_=ini)
    print('POST_STATUS', st)
    print('POST_BODY', json.dumps(jload(raw), ensure_ascii=False)[:900])

    st, raw = http('GET', '/api/config', init_=ini)
    cfg = jload(raw)
    live_after = None
    if isinstance(cfg, dict):
        for it in cfg.get('items', []):
            if it.get('key') == KEY:
                live_after = it.get('value')
    print('LIVE_AFTER | %s=%r' % (KEY, live_after))

    data = await fetch_settings()
    print('PG_AFTER | %r' % (data.get(KEY),))

    st, raw = http('GET', '/api/memory/embeddings', init_=ini)
    panel = jload(raw)
    if isinstance(panel, dict):
        prov = panel.get('provider') or {}
        print('PANEL_STATUS', st)
        print('PANEL_ROTATION', json.dumps(prov.get('rotation'), ensure_ascii=False))
        print('PANEL_GROUPS', json.dumps(prov.get('groups'), ensure_ascii=False))
        print('PANEL_CREDS', json.dumps([{k: r.get(k) for k in
              ('alias', 'quota_group', 'quota_group_source', 'health', 'key_source')}
              for r in prov.get('credential_rows', [])], ensure_ascii=False))
        print('PANEL_BACKLOG', json.dumps(panel.get('backlog'), ensure_ascii=False))
    else:
        print('PANEL_RAW', st, str(panel)[:500])

    # embed through the app client with the NEW labels in cache
    hot_config.set_config_cache(Cache(data))
    pool = ecp.build_credential_pool()
    print('POOL_GROUPS', [(c.alias, c.quota_group_id) for c in pool])
    llm = LLMClient(base_url=settings.LLM_BASE_URL or 'https://example.invalid/v1',
                    api_key=settings.LLM_API_KEY or 'probe-chat',
                    chat_model=settings.LLM_MODEL_NAME or 'none',
                    embed_model=settings.EMBEDDING_MODEL_NAME)
    calls = []
    orig = llm._post
    async def spy(path, payload, **kw):
        t0 = time.perf_counter()
        resp = await orig(path, payload, **kw)
        hdrs = {k: v for k, v in resp.headers.items()
                if k.lower() in ('retry-after', 'x-ratelimit-remaining-requests',
                                 'x-ratelimit-remaining-tokens', 'date')}
        calls.append({'base_url': kw.get('base_url'), 'status': resp.status_code,
                      'model': payload.get('model'),
                      'latency_ms': round((time.perf_counter() - t0) * 1000, 1),
                      'headers': hdrs})
        return resp
    llm._post = spy
    try:
        vecs = await ecp.execute_embed(llm, ['разблокировка провайдера проверка ok 777'],
                                       priority=ecp.Priority.P2_REPAIR, max_wait_s=15)
        print('EXECUTOR_OK | dim=%d | vectors=%d' % (len(vecs[0]), len(vecs)))
    except Exception as exc:
        print('EXECUTOR_FAIL | %s | %s' % (type(exc).__name__, exc))
    for c in calls:
        print('CALL |', json.dumps(c, ensure_ascii=False, sort_keys=True))
    try:
        await llm.close()
    except Exception:
        pass

    print('WAIT 45s for ticker/queue observation ...')
    time.sleep(45)
    snapshot('AFTER_45S')

asyncio.run(main())
"""

CHAT_AUDIT_PY = r"""
import asyncio, glob, hashlib, hmac, json, os, re, subprocess, sys, time
import urllib.error, urllib.parse, urllib.request
sys.path.insert(0, '.')
from config.settings import settings
import asyncpg

BASE = 'http://127.0.0.1:8000'
OWNER_ID = 5885953495

def env_token():
    tok = os.getenv('API_TOKEN') or getattr(settings, 'API_TOKEN', '')
    if tok:
        return tok
    with open('.env', 'r', encoding='utf-8', errors='replace') as fh:
        for line in fh:
            if line.strip().startswith('API_TOKEN='):
                return line.split('=', 1)[1].strip().strip('"').strip("'")
    return ''

def init_data(token, uid=OWNER_ID):
    fields = {'auth_date': str(int(time.time())), 'query_id': 'AAHchataudit',
              'user': json.dumps({'id': uid, 'first_name': 'Owner', 'username': 'owner'},
                                 separators=(',', ':'))}
    check = '\n'.join('%s=%s' % (k, fields[k]) for k in sorted(fields))
    secret = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
    sig = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + '&hash=' + sig

def http_get(path, init_):
    req = urllib.request.Request(BASE + path, headers={
        'User-Agent': 'chat-audit', 'X-Telegram-Init-Data': init_})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode('utf-8', 'replace')[:300]

def mask(v):
    s = str(v or '')
    return '<set len=%d>' % len(s) if s else '<empty>'

URL_RE = re.compile(r'url=(\S+)')
MODEL_RE = re.compile(r'model=([A-Za-z0-9_.:/+-]+)')
PROV_RE = re.compile(r'provider=([A-Za-z0-9_.:/+-]+)')
TS_RE = re.compile(r'^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})')

def scan_journal(since):
    proc = subprocess.Popen(
        ['journalctl', '-u', 'admin_bot', '--since', since, '--no-pager', '-o', 'short-iso'],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, errors='replace')
    hosts_all = {}
    hosts_chat = {}
    hosts_embed = {}
    err_hosts = {}
    models = {}
    fallback_prov = {}
    fallback_models = {}
    apinet_lines = []
    first_ts = last_ts = None
    n = 0
    for line in proc.stdout:
        n += 1
        m = TS_RE.match(line)
        ts = m.group(1) if m else ''
        if ts:
            first_ts = first_ts or ts
            last_ts = ts
        low = line.lower()
        if 'apinet' in low:
            if len(apinet_lines) < 40:
                apinet_lines.append(line.rstrip()[:300])
        um = URL_RE.search(line)
        if um and 'LLM request OK' in line:
            url = um.group(1)
            host = urllib.parse.urlsplit(url).hostname or '?'
            hosts_all[host] = hosts_all.get(host, 0) + 1
            if url.rstrip('/').endswith('/embeddings') or '/embeddings' in url:
                hosts_embed[host] = hosts_embed.get(host, 0) + 1
            else:
                hosts_chat[host] = hosts_chat.get(host, 0) + 1
        if 'LLM HTTP' in line or 'LLM timeout' in line:
            if um:
                host = urllib.parse.urlsplit(um.group(1)).hostname or '?'
                err_hosts[host] = err_hosts.get(host, 0) + 1
        if 'LLM generate OK' in line or 'LLM generate_chat OK' in line:
            mm = MODEL_RE.search(line)
            key = mm.group(1) if mm else '?'
            models[key] = models.get(key, 0) + 1
        if 'LLM fallback attempt' in line:
            pm = PROV_RE.search(line)
            key = pm.group(1) if pm else '?'
            fallback_prov[key] = fallback_prov.get(key, 0) + 1
        if 'LLM fallback OK' in line:
            mm = MODEL_RE.search(line)
            key = mm.group(1) if mm else '?'
            fallback_models[key] = fallback_models.get(key, 0) + 1
    rc = proc.wait()
    print('JOURNAL | since=%s | rc=%s | lines=%d | range=%s..%s' % (since, rc, n, first_ts, last_ts))
    print('HOSTS_ALL(200 OK requests) |', json.dumps(hosts_all, sort_keys=True))
    print('HOSTS_CHAT(200 OK, non-embed) |', json.dumps(hosts_chat, sort_keys=True))
    print('HOSTS_EMBED(200 OK, /embeddings) |', json.dumps(hosts_embed, sort_keys=True))
    print('HOSTS_HTTP_ERRORS |', json.dumps(err_hosts, sort_keys=True))
    print('CHAT_MODELS_OK |', json.dumps(models, sort_keys=True))
    print('FALLBACK_PROVIDERS |', json.dumps(fallback_prov, sort_keys=True))
    print('FALLBACK_OK_MODELS |', json.dumps(fallback_models, sort_keys=True))
    print('APINET_LINES_COUNT(showing up to 40)', len(apinet_lines))
    for l in apinet_lines:
        print('APINET |', l)

def pg():
    dsn = os.getenv('POSTGRES_DSN')

    async def go():
        conn = await asyncpg.connect(dsn, timeout=15)
        try:
            rows = await conn.fetch(
                "SELECT key, value FROM bot_settings WHERE key LIKE 'models.llm%' "
                "OR key LIKE 'keys.llm%' ORDER BY key")
            for r in rows:
                raw = r['value']
                try:
                    val = json.loads(raw) if isinstance(raw, str) else raw
                except Exception:
                    val = raw
                shown = mask(val) if str(r['key']).startswith('keys.') else val
                print('PG | %-34s | %s' % (r['key'], shown))
            rows = await conn.fetch(
                "SELECT key, left(value::text, 220) AS v FROM bot_settings "
                "WHERE value::text ILIKE '%apinet%' AND key NOT LIKE 'keys.%'")
            for r in rows:
                print('PG_APINET | %s | %s' % (r['key'], r['v']))
            rows = await conn.fetch(
                "SELECT model, source, COUNT(*) c, MIN(ts) t0, MAX(ts) t1 "
                "FROM llm_usage_events WHERE ts > now() - interval '7 days' "
                "GROUP BY model, source ORDER BY c DESC LIMIT 20")
            for r in rows:
                print('USAGE7D | model=%-24s | source=%-10s | c=%-6s | %s..%s'
                      % (r['model'], r['source'], r['c'], r['t0'], r['t1']))
            row = await conn.fetchrow(
                "SELECT COUNT(*) c, MIN(ts) t0, MAX(ts) t1 FROM llm_usage_events "
                "WHERE ts > now() - interval '7 days'")
            print('USAGE7D_TOTAL |', dict(row))
        finally:
            await conn.close()

    asyncio.run(go())

def main():
    since = sys.argv[1] if len(sys.argv) > 1 else '-7 days'
    print('===== ENV chat =====')
    for f in ('LLM_BASE_URL', 'LLM_FALLBACK_BASE_URL', 'LLM_FALLBACK_MODEL',
              'LLM_MODEL_NAME', 'LLM_FALLBACK_API_KEY'):
        v = getattr(settings, f, None)
        print('ENV | %-24s | %s' % (f, ('<set>' if 'KEY' in f and v else v)))
    print('===== PG chat =====')
    pg()
    print('===== LIVE /api/config (chat keys) =====')
    tok = env_token()
    if tok:
        st, cfg = http_get('/api/config', init_data(tok))
        print('CONFIG_STATUS', st)
        if isinstance(cfg, dict):
            for it in cfg.get('items', []):
                if str(it.get('key', '')).startswith(('models.llm', 'keys.llm')):
                    v = it.get('value')
                    print('LIVE | %-34s | %s' % (it.get('key'),
                          mask(v) if str(it.get('key')).startswith('keys.') else v))
    else:
        print('CONFIG_SKIP no token')
    print('===== JOURNAL =====')
    scan_journal(since)

main()
"""

UNPARK_PY = r"""
import asyncio, json, os, sys
sys.path.insert(0, '.')
from config.settings import settings
import asyncpg, aiosqlite
from services import hot_config
from services import embedding_control_plane as ecp
from services.database import DatabaseService

class Cache:
    def __init__(self, data): self._d = dict(data)
    def get(self, k, default=None): return self._d.get(k, default)

async def main():
    dsn = os.getenv('POSTGRES_DSN')
    conn = await asyncpg.connect(dsn, timeout=15)
    try:
        rows = await conn.fetch("SELECT key, value FROM bot_settings")
    finally:
        await conn.close()
    data = {}
    for r in rows:
        raw = r['value']
        try:
            data[r['key']] = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            data[r['key']] = raw
    hot_config.set_config_cache(Cache(data))
    dbp = os.getenv('DBP') or 'local_database.db'
    db = DatabaseService(dbp)
    db.db = await aiosqlite.connect(dbp, timeout=30)
    try:
        cur = await db.db.execute("SELECT quota_group_id, state, next_allowed_at, note FROM embedding_quota_state")
        print('BEFORE', [dict(r) for r in await cur.fetchall()])
        ecp.REGISTRY.bind_db(db)
        for gid in json.loads(os.environ.get('UNPARK_GROUPS') or '[]'):
            await ecp.REGISTRY.set_group_state(gid, ecp.GROUP_HEALTHY, 0,
                                               'manual unpark: new apinet account, stale parking from old key')
            print('UNPARKED', gid)
        cur = await db.db.execute("SELECT quota_group_id, state, next_allowed_at, note, updated_at FROM embedding_quota_state")
        print('AFTER', [dict(r) for r in await cur.fetchall()])
    finally:
        await db.db.close()

asyncio.run(main())
"""


def run(pw: str, secrets: list[str], name: str, script: str, timeout: int = 180) -> int:
    c = connect(pw)
    try:
        cmd = "bash -s <<'EMBED_EOF'\n" + script + "\nEMBED_EOF\n"
        _in, out, err = c.exec_command(cmd, timeout=timeout)
        data = out.read().decode("utf-8", "replace")
        e = err.read().decode("utf-8", "replace")
        rc = out.channel.recv_exit_status()
        text = scrub(data + ("\n[stderr]\n" + e if e.strip() else ""), secrets)
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"{name}.txt").write_text(text + f"\n[rc={rc}]\n", encoding="utf-8")
        print(text)
        print(f"[rc={rc}]")
    finally:
        c.close()
    return 0


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "main"
    pw = _pwd("pass")
    secrets = [pw]
    if mode == "main":
        script = (HEADER.replace("__APP__", APP)
                  + "\necho '===== PY: config/pool ====='\n"
                  + '"$PYBIN" - <<\'PYEOF\' 2>&1\n' + CONFIG_PY + "\nPYEOF\n"
                  + "echo '===== PY: sqlite state ====='\n"
                  + '"$PYBIN" - <<\'PYEOF2\' 2>&1\n' + SQLITE_PY + "\nPYEOF2\n"
                  + "echo '===== PY: live probe ====='\n"
                  + '"$PYBIN" - <<\'PYEOF3\' 2>&1\n' + PROBE_PY + "\nPYEOF3\n"
                  + "echo '===== journal (masked, 6h) ====='\n"
                  + "journalctl -u admin_bot --since '-6h' --no-pager 2>/dev/null "
                    "| grep -Ei 'embed|config' | tail -n 70 "
                    "| sed -E 's/(sk-[A-Za-z0-9_-]{4})[A-Za-z0-9_-]+/\\1***/g; s/(AIza[A-Za-z0-9_-]{4})[A-Za-z0-9_-]+/\\1***/g; s/(Bearer )[^ ]+/\\1***/g'\n"
                  + "echo '===== END ====='\n")
        return run(pw, secrets, "main", script)
    if mode == "chat_audit":
        since = sys.argv[2] if len(sys.argv) > 2 else "-7 days"
        script = (HEADER.replace("__APP__", APP)
                  + "\necho '===== HZ ====='\n"
                  + "curl -s --max-time 8 http://127.0.0.1:8000/healthz; echo\n"
                  + "echo '===== JOURNAL RETENTION ====='\n"
                  + "journalctl --disk-usage 2>&1\n"
                  + "journalctl -u admin_bot -o short-iso --no-pager 2>/dev/null | head -1\n"
                  + "journalctl -u admin_bot -n 1 --no-pager -o short-iso 2>/dev/null\n"
                  + "echo '===== PY: chat audit ====='\n"
                  + '"$PYBIN" - "' + since + '" <<\'PYAUD\' 2>&1\n' + CHAT_AUDIT_PY + "\nPYAUD\n"
                  + "echo '===== PROCESSES ====='\n"
                  + "ps -eo pid,ppid,etime,cmd | grep -E 'python|uvicorn|admin_bot' | grep -v grep | head -30\n"
                  + "echo '===== TIMERS ====='\n"
                  + "systemctl list-timers --all --no-pager 2>&1 | head -40\n"
                  + "echo '===== CRON ====='\n"
                  + "crontab -l 2>&1 | head -30\n"
                  + "ls -l /etc/cron.d /etc/cron.daily /etc/cron.hourly 2>&1 | head -40\n"
                  + "ls -l /var/spool/cron/crontabs 2>&1\n"
                  + "echo '===== CODE GREP apinet ====='\n"
                  + "grep -rn 'apinet' --include='*.py' services config web tools handlers 2>/dev/null | head -40\n"
                  + "grep -rln 'apinet' /etc/systemd/system 2>/dev/null | head -10\n"
                  + "echo '===== END ====='\n")
        return run(pw, secrets, "chat_audit", script, timeout=300)
    if mode == "apply":
        script = (HEADER.replace("__APP__", APP)
                  + "\necho '===== HZ BEFORE ====='\n"
                  + "curl -s --max-time 8 http://127.0.0.1:8000/healthz; echo\n"
                  + "\necho '===== PY: apply labels + verify ====='\n"
                  + '"$PYBIN" - <<\'PYAPPLY\' 2>&1\n' + APPLY_PY + "\nPYAPPLY\n"
                  + "echo '===== HZ AFTER ====='\n"
                  + "curl -s --max-time 8 http://127.0.0.1:8000/healthz; echo\n"
                  + "echo '===== journal (4m, masked) ====='\n"
                  + "journalctl -u admin_bot --since '-4m' --no-pager 2>/dev/null "
                    "| grep -Ei 'config|embed|quota|backfill|recovery' | tail -n 60 "
                    "| sed -E 's/(sk-[A-Za-z0-9_-]{4})[A-Za-z0-9_-]+/\\1***/g; s/(AIza[A-Za-z0-9_-]{4})[A-Za-z0-9_-]+/\\1***/g; s/(Bearer )[^ ]+/\\1***/g'\n"
                  + "echo '===== END ====='\n")
        return run(pw, secrets, "apply", script)
    if mode == "sql":
        script = (HEADER.replace("__APP__", APP)
                  + "\necho '===== PY: sqlite state ====='\n"
                  + '"$PYBIN" - <<\'PYEOF2\' 2>&1\n' + SQLITE_PY + "\nPYEOF2\n"
                  + "echo '===== END ====='\n")
        return run(pw, secrets, "sql", script)
    if mode == "sql2":
        script = (HEADER.replace("__APP__", APP)
                  + "\necho '===== PY: vec + backlog ====='\n"
                  + '"$PYBIN" - <<\'PYEOF4\' 2>&1\n' + SQL2_PY + "\nPYEOF4\n"
                  + "echo '===== END ====='\n")
        return run(pw, secrets, "sql2", script)
    if mode == "probe":
        script = (HEADER.replace("__APP__", APP)
                  + "\necho '===== PY: live probe ====='\n"
                  + '"$PYBIN" - <<\'PYEOF3\' 2>&1\n' + PROBE_PY + "\nPYEOF3\n"
                  + "echo '===== END ====='\n")
        return run(pw, secrets, "probe", script)
    if mode == "fbprobe":
        script = (HEADER.replace("__APP__", APP)
                  + "\necho '===== PY: fallback keys probe ====='\n"
                  + '"$PYBIN" - <<\'PYFBP\' 2>&1\n' + FB_PY + "\nPYFBP\n"
                  + "echo '===== END ====='\n")
        return run(pw, secrets, "fbprobe", script)
    if mode == "unpark":
        groups = sys.argv[2] if len(sys.argv) > 2 else "[]"
        script = ("export UNPARK_GROUPS='" + groups + "'\n"
                  + HEADER.replace("__APP__", APP)
                  + "\n" + '"$PYBIN" - <<\'PYEOF\' 2>&1\n' + UNPARK_PY + "\nPYEOF\n")
        return run(pw, secrets, "unpark", script)
    raise SystemExit("unknown mode")


if __name__ == "__main__":
    raise SystemExit(main())
