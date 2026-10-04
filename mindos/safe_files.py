"""Shared local file boundary for learning inputs and user practice outputs."""
from pathlib import Path

class SafeFiles:
 def __init__(self,store,namespace):
  if namespace not in {'resources','artifacts'}:raise ValueError('文件目录无效')
  self.base=store.path.parent;self.directory=self.base/namespace
 def root(self):
  if self.directory.is_symlink() or self.directory.resolve().parent!=self.base.resolve():raise ValueError('资料目录路径无效')
  return self.directory.resolve()
 def write(self,identifier,suffix,data):
  self.root();self.directory.mkdir(parents=True,exist_ok=True)
  if not identifier or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in identifier) or suffix not in {'.pdf','.png','.jpg','.txt','.bin'}:raise ValueError('本地文件名无效')
  path=self.root()/(identifier+suffix)
  with path.open('xb') as stream:stream.write(data)
  return path
 def file(self,identifier,name,suffixes):
  if not name or Path(name).name!=name or name not in {identifier+ext for ext in suffixes}:raise ValueError('本地资料路径无效')
  root=self.root();path=root/name
  if path.is_symlink() or path.resolve().parent!=root or not path.is_file():raise ValueError('本地资料不存在')
  return path
