"""Install a verified Node 24 runtime inside this workspace when Linux Node is absent."""
import hashlib
import io
import pathlib
import re
import tarfile
import urllib.request

root = pathlib.Path(__file__).resolve().parents[1]
base = "https://nodejs.org/dist/latest-v24.x/"
manifest = urllib.request.urlopen(base + "SHASUMS256.txt", timeout=60).read().decode()
digest, filename = re.search(r"([0-9a-f]{64})\s+(node-v24\.[\d.]+-linux-x64\.tar\.xz)", manifest).groups()
payload = urllib.request.urlopen(base + filename, timeout=120).read()
if hashlib.sha256(payload).hexdigest() != digest:
    raise SystemExit("Node archive checksum mismatch")
target = root / ".tools"
target.mkdir(exist_ok=True)
with tarfile.open(fileobj=io.BytesIO(payload), mode="r:xz") as archive:
    archive.extractall(target, filter="data")
link = target / "node"
if not link.exists():
    link.symlink_to(filename.removesuffix(".tar.xz"), target_is_directory=True)
print(link / "bin" / "node")
