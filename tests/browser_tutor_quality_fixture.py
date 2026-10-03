"""Disposable P6 courses; one deterministic quality repair, developer mode only."""
import os,runpy,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
os.environ['MINDOS_DEBUG_LEARNING']='1'
import tutor_fixture
original=tutor_fixture.packet
counts={}
def packet(payload):
 value=original(payload);q=payload['message'];counts[q]=counts.get(q,0)+1
 if q=='质量改写验收：解释QKV' and counts[q]==1:
  value['blocks']=[{'type':'paragraph','content':'今天讲蛋糕做法，包括材料准备、烤箱的使用和装饰。'*20}]
 return value
tutor_fixture.packet=packet
runpy.run_path(str(ROOT/'tests/browser_tutor_p6_fixture.py'),run_name='__main__')
