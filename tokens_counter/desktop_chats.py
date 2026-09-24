"""
The title of the Claude Desktop chat you're in, read from Desktop's own
local cache. Opt-in (see config.load_app_settings): chat titles are generated
from your messages, and everywhere else this app never reads conversation
content.

Desktop is an Electron app running claude.ai, and caches each chat it shows
in the page's IndexedDB - a Chromium leveldb under
`<profile>/IndexedDB/https_claude.ai_0.indexeddb.leveldb`. A cached chat is a
record with `product: "chat"`, `conversationUpdatedAt`, `messageCount` and a
`tree` object that starts with the conversation's `uuid`, `name`, `summary`,
`model`, ... and then its messages. This module decodes just those leading
scalar fields and stops; it never decodes past `model`, so message text is
never turned into a Python string.

Only the leveldb write-ahead `.log` files are read. Older data is compacted
into `.ldb` tables whose blocks are snappy-compressed (no stdlib decoder),
but a chat you're actively using is rewritten into the `.log` on every
update, so the current chat is always there.

None of this is a stable format - it's Chromium's storage layout plus V8's
value serialization - so every step degrades to "no title" rather than
raising, and the widget falls back to plain "Claude Desktop".
"""

import glob
import os
import struct
from datetime import datetime, timezone

IDB_DIR = os.path.join("IndexedDB", "https_claude.ai_0.indexeddb.leveldb")
_BLOCK = 32768
_CHAT_MARKER = b'"\x07product"\x04chat'
_TREE_KEY = b'"\x04tree'

# path -> ((st_mtime_ns, st_size), {uuid: chat}). The log is ~2MB and read on
# every widget refresh; only re-decode it when it changed.
_CACHE = {}


def _log_records(data):
    """Reassemble leveldb log records: FULL=1, FIRST=2, MIDDLE=3, LAST=4."""
    pending = b""
    for offset in range(0, len(data), _BLOCK):
        block = data[offset:offset + _BLOCK]
        pos = 0
        while pos + 7 <= len(block):
            length, kind = struct.unpack_from("<HB", block, pos + 4)
            if kind == 0 and length == 0:
                break
            payload = block[pos + 7:pos + 7 + length]
            pos += 7 + length
            if kind == 1:
                yield payload
            elif kind == 2:
                pending = payload
            elif kind == 3:
                pending += payload
            elif kind == 4:
                yield pending + payload
                pending = b""


def _varint(buf, i):
    result = shift = 0
    while True:
        byte = buf[i]
        i += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, i
        shift += 7


def _value_after(buf, key, start=0, end=None):
    """
    The V8-serialized value following property `key`, or None.

    Handles the three value kinds these fields use: one-byte strings ('"',
    Latin-1), two-byte strings ('c', UTF-16LE) and doubles ('N'). Returns
    (value, index_after_value); index -1 when the key isn't there.
    """
    needle = b'"' + bytes([len(key)]) + key.encode("ascii")
    i = buf.find(needle, start, end if end is not None else len(buf))
    if i < 0:
        return None, -1
    j = i + len(needle)
    tag = buf[j]
    if tag == 0x4E:
        return struct.unpack_from("<d", buf, j + 1)[0], j + 9
    if tag == 0x49:
        n, k = _varint(buf, j + 1)
        return (n >> 1) ^ -(n & 1), k
    if tag in (0x22, 0x63):
        n, k = _varint(buf, j + 1)
        raw = buf[k:k + n]
        text = raw.decode("latin-1") if tag == 0x22 else raw.decode("utf-16-le", "replace")
        return text, k + n
    return None, j


def _chat_from_record(record):
    if _CHAT_MARKER not in record:
        return None
    tree = record.find(_TREE_KEY)
    if tree < 0:
        return None
    updated, _ = _value_after(record, "conversationUpdatedAt", 0, tree)
    count, _ = _value_after(record, "messageCount", 0, tree)
    uuid, after_uuid = _value_after(record, "uuid", tree)
    if not isinstance(uuid, str) or after_uuid < 0:
        return None
    # `name` and `model` sit right after `uuid` in the tree; bound the search
    # so a key of the same name inside a message can never be picked up.
    window_end = after_uuid + 4096
    name, _ = _value_after(record, "name", after_uuid, window_end)
    model, _ = _value_after(record, "model", after_uuid, window_end)
    if not isinstance(updated, (int, float)):
        return None
    return {
        "uuid": uuid,
        "title": name.strip() if isinstance(name, str) else "",
        "model": model if isinstance(model, str) else None,
        "message_count": count if isinstance(count, int) else None,
        "updated_at": datetime.fromtimestamp(updated / 1000, timezone.utc),
    }


def _chats_in_log(path):
    try:
        st = os.stat(path)
    except OSError:
        return {}
    key = (st.st_mtime_ns, st.st_size)
    cached = _CACHE.get(path)
    if cached and cached[0] == key:
        return cached[1]
    chats = {}
    try:
        with open(path, "rb") as f:
            data = f.read()
        for record in _log_records(data):
            try:
                chat = _chat_from_record(record)
            except (IndexError, struct.error, ValueError):
                continue
            if chat and (chat["uuid"] not in chats
                         or chat["updated_at"] >= chats[chat["uuid"]]["updated_at"]):
                chats[chat["uuid"]] = chat
    except (OSError, IndexError, struct.error):
        return {}
    _CACHE[path] = (key, chats)
    return chats


def get_active_chat(desktop_dir):
    """
    The most recently updated chat in Desktop's cache, or None.

    Returns {"uuid", "title", "model", "message_count", "updated_at"}.
    `title` can be "" for a chat Desktop hasn't named yet.
    """
    chats = {}
    for path in glob.glob(os.path.join(desktop_dir, IDB_DIR, "*.log")):
        for uuid, chat in _chats_in_log(path).items():
            if uuid not in chats or chat["updated_at"] >= chats[uuid]["updated_at"]:
                chats[uuid] = chat
    if not chats:
        return None
    return max(chats.values(), key=lambda c: c["updated_at"])
