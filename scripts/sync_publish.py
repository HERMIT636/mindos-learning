"""Synchronize reviewable source only; exclude local data, credentials and caches."""
from pathlib import Path
import argparse,shutil

DIRECTORIES=('mindos','web','tests','docs','scripts','prompts','.github')
FILES=('.env.example','.gitattributes','.gitignore','CONTRIBUTING.md','LICENSE','README.md','ROADMAP.md','requirements.txt','MindOS_最终设计大纲.md')
EXCLUDED={'__pycache__','.pytest_cache','node_modules'}

def source_files(root):
    for name in FILES:
        if (root/name).is_file():yield root/name
    for directory in DIRECTORIES:
        for path in sorted((root/directory).rglob('*')):
            if path.is_file() and not EXCLUDED.intersection(path.relative_to(root).parts) and path.suffix not in ('.pyc','.pyo'):yield path

def sync(root,check=False):
    destination=root/'release'/'github-publish';changed=[];files=list(source_files(root))
    for source in files:
        relative=source.relative_to(root);target=destination/relative
        if not target.is_file() or source.read_bytes()!=target.read_bytes():
            changed.append(str(relative))
            if not check:target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    return {'checked':len(files),'differences':changed,'mode':'check' if check else 'sync'}

if __name__=='__main__':
    import json
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    if not (root/'release'/'github-publish').is_dir():parser.error('请在项目根目录使用此脚本，发布仓库中无需再次同步')
    report=sync(root,args.check);print(json.dumps(report,ensure_ascii=False,indent=2))
    if args.check and report['differences']:raise SystemExit(1)
