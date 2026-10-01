"""Optional temporary browser fixture. Run from the repository; Ctrl+C cleans up."""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from test_prototype import PrototypeTests

if __name__ == '__main__':
    PrototypeTests.setUpClass()
    test = PrototypeTests()
    test.setUp()
    try:
        test.configure()
        course = test.draft_and_confirm('浏览器知识地图课程', '零基础理解与复习')
        print(json.dumps({'url': test.url, 'course': course, 'cookie': test.session_id()}, ensure_ascii=False), flush=True)
        time.sleep(600)
    except KeyboardInterrupt:
        pass
    finally:
        PrototypeTests.tearDownClass()
