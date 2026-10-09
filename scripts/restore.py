"""Restore into a NEW directory; never overwrite an existing archive."""
import argparse
import shutil
import sqlite3
import zipfile
from pathlib import Path

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("backup",type=Path)
    parser.add_argument("--destination",type=Path,required=True)
    args=parser.parse_args()
    destination=args.destination.expanduser().resolve()
    if destination.exists():raise SystemExit("恢复目录必须尚不存在；现有资料不会覆盖。")
    with zipfile.ZipFile(args.backup) as archive:
        members=archive.infolist()
        if sum(m.file_size for m in members)>512*1024*1024:raise SystemExit("备份超过512MB恢复上限")
        if not any(m.filename=="feedback.sqlite3" for m in members):raise SystemExit("备份缺少数据库")
        for member in members:
            path=Path(member.filename)
            allowed=member.filename in ("feedback.sqlite3","README.txt") or len(path.parts)==2 and ((path.parts[0]=="pdf" and path.suffix==".pdf") or (path.parts[0]=="html" and path.suffix==".html"))
            if not allowed or not (destination/path).resolve().is_relative_to(destination):raise SystemExit("备份包含非预期路径")
        destination.mkdir(parents=True,mode=0o700)
        for member in members:
            path=destination/member.filename;path.parent.mkdir(exist_ok=True,mode=0o700)
            with archive.open(member) as source,path.open("wb") as target:shutil.copyfileobj(source,target)
            path.chmod(0o600)
    with sqlite3.connect(destination/"feedback.sqlite3") as conn:
        if conn.execute("PRAGMA integrity_check").fetchone()[0]!="ok":raise SystemExit("数据库完整性校验失败，请保留原备份")
    print("恢复完成。关闭程序，在 .env 中设置 FEEDBACK_DATA_DIR="+str(destination)+"，然后启动程序。")

if __name__=="__main__":main()
