import os
from pathlib import Path
from supabase import create_client

BUCKET = os.getenv("STORAGE_BUCKET", "thaw-files")
_client = None

def _bucket():
    global _client
    if _client is None:
        _client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
    return _client.storage.from_(BUCKET)

def _key(path, root):
    return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()

def put_file(path, root, content_type="application/octet-stream"):
    try:
        _bucket().upload(_key(path, root), Path(path).read_bytes(),
                        {"content-type": content_type, "upsert": "true"})
        print(f"✅ Uploaded {path} to Supabase")
    except Exception as e:
        print(f"❌ SUPABASE UPLOAD FAILED for {path}: {e}")

def ensure_local(path, root) -> bool:
    p = Path(path)
    if p.exists():
        return True
    try:
        data = _bucket().download(_key(path, root))
    except Exception:
        return False
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return True

def delete_prefix(prefix):
    b = _bucket()
    stack, keys = [prefix.strip("/")], []
    while stack:
        folder = stack.pop()
        try:
            for item in b.list(folder, {"limit": 1000}):
                name = folder + "/" + item["name"]
                if item.get("id") is None:
                    stack.append(name)
                else:
                    keys.append(name)
        except Exception:
            pass
    for i in range(0, len(keys), 100):
        try:
            b.remove(keys[i:i + 100])
        except Exception:
            pass