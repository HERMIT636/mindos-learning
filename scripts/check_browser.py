"""Run opt-in Edge checks against disposable databases (Windows/WSL Node runtime)."""
import argparse,json,os,shutil,subprocess,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('suites',nargs='*',default=['universe']);parser.add_argument('--screenshots',action='store_true');args=parser.parse_args()
node=os.environ.get('MINDOS_NODE') or shutil.which('node') or shutil.which('node.exe') or ''
module=os.environ.get('PLAYWRIGHT_MODULE_WINDOWS','playwright')
fixtures={'authentic':'browser_authentic_fixture.py','final':'browser_final_fixture.py','loop':'browser_loop_fixture.py','presentation':'browser_presentation_fixture.py','universe':'browser_universe_fixture.py','atie':'browser_atie_fixture.py','tutor':'browser_tutor_fixture.py','architecture':'browser_architecture_fixture.py','management':'browser_management_fixture.py','knowledge':'browser_fixture.py','production':'browser_fixture.py','discovery':'browser_discovery_fixture.py'}
if not Path(node).is_file():parser.error('找不到 Node 运行环境，请通过 MINDOS_NODE 指定；另需安装 Playwright 和 Edge。')
for suite in args.suites:
    if suite not in fixtures:parser.error('未知检查：'+suite)
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1')
    fixture=subprocess.Popen([sys.executable,str(ROOT/'tests'/fixtures[suite])],cwd=ROOT,env=env,stdout=subprocess.PIPE,text=True)
    try:
        info=json.loads(fixture.stdout.readline());print('Checking '+suite,flush=True)
        values={'MINDOS_TEST_URL':info['url'],'MINDOS_TEST_COOKIE':info['cookie'],'PLAYWRIGHT_MODULE':module}
        if args.screenshots:values['MINDOS_SCREENSHOTS']='1'
        source=''.join('process.env['+json.dumps(k)+']='+json.dumps(v)+';' for k,v in values.items())
        # WSL loopback forwarding may become visible to Windows after the fixture is ready.
        source+="(async()=>{let ready=false;for(let i=0;i<40;i++){try{const ok=await new Promise((resolve,reject)=>{const req=require('node:http').get(process.env.MINDOS_TEST_URL,res=>{res.resume();res.on('end',()=>resolve(res.statusCode===200));});req.setTimeout(1000,()=>req.destroy(Error('timeout')));req.on('error',reject);});if(ok){ready=true;break;}}catch(_){}await new Promise(r=>setTimeout(r,250));}if(!ready)throw Error('Temporary server is not reachable from Windows');require("+json.dumps('./tests/browser_'+suite+'.cjs')+");})().catch(e=>{console.error(e);process.exit(1);});"
        subprocess.run([node,'-e',source],cwd=ROOT,check=True,timeout=180)
    finally:
        fixture.terminate();fixture.wait(timeout=10)
