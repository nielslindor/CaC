"""Build distributions and remove machine-owner metadata from the source archive."""

import gzip
import os
from pathlib import Path
import subprocess
import sys
import tarfile

root = Path(__file__).resolve().parents[1]
epoch = int(subprocess.check_output(["git", "log", "-1", "--format=%ct"], cwd=root, text=True).strip())
environment = dict(os.environ)
environment["SOURCE_DATE_EPOCH"] = str(epoch)
subprocess.run([sys.executable, "-m", "build"], cwd=root, env=environment, check=True)
for archive in (root / "dist").glob("*.tar.gz"):
    temporary = archive.with_suffix(".normalized")
    with tarfile.open(archive, "r:gz") as source, temporary.open("wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=epoch) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as destination:
                for member in source.getmembers():
                    if member.name.startswith("/") or ".." in Path(member.name).parts or member.issym() or member.islnk():
                        raise ValueError("Unsafe source archive member")
                    member.uid = member.gid = 0
                    member.uname = member.gname = ""
                    member.mtime = epoch
                    member.pax_headers = {}
                    destination.addfile(member, source.extractfile(member) if member.isfile() else None)
    temporary.replace(archive)
