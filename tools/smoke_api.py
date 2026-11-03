"""使用真实 HTTP 对 13 个操作进行冒烟检查；可自启动隔离本地服务。"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def wait_ready(url, process):
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('Local service exited before readiness')
        try:
            if httpx.get(url, timeout=1, trust_env=False).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.15)
    raise RuntimeError('Local service did not become ready')


def smoke(base_url, frontend_url=None):
    records = []
    with httpx.Client(base_url=base_url, timeout=90, trust_env=False) as client:
        def call(method, path, expected=200, **kwargs):
            response = client.request(method, path, **kwargs)
            if response.status_code != expected:
                raise AssertionError(f'{method} {path}: expected {expected}, got {response.status_code}: {response.text[:300]}')
            if response.headers.get('content-type', '').startswith('application/json'):
                body = response.json()
            else:
                body = {'byte_count': len(response.content), 'prefix_hex': response.content[:4].hex()}
            records.append({'method': method, 'path': path, 'input': kwargs.get('json') or kwargs.get('params'),
                            'status': response.status_code, 'body': body})
            if path.startswith('/api/'):
                assert response.headers.get('x-request-id')
            return body

        health = call('GET', '/api/health')
        assert health['knowledge_base_ready'] and health['generation_mode'] == 'extractive'
        course = call('GET', '/api/course')
        chapters = call('GET', '/api/chapters')['chapters']
        chapter_id = chapters[0]['chapter_id']
        call('GET', '/api/chapters/' + chapter_id)
        session = str(uuid4())
        qa = call('POST', '/api/qa', json={'question': '什么是智能体 Agent？',
            'chapter_id': chapter_id, 'session_id': session, 'retrieval_mode': 'bm25', 'debug': True})
        assert qa['citations'] and qa['generation_mode'] == 'extractive' and not qa['insufficient_evidence']
        source = call('GET', '/api/sources/' + qa['citations'][0]['chunk_id'])
        assert source['text'] == qa['citations'][0]['text']
        pdf = call('GET', '/api/course/source', expected=206, headers={'Range': 'bytes=0-3'})
        assert pdf['prefix_hex'] == b'%PDF'.hex()
        summary = call('POST', '/api/summary', json={'chapter_id': chapter_id})
        assert summary['citations'] and summary['coverage']
        quiz = call('POST', '/api/quiz', json={'chapter_id': chapter_id, 'count': 5,
            'question_types': ['short_answer', 'multiple_choice'], 'difficulty': 'medium'})
        assert len(quiz['questions']) == 5
        params = {'session_id': session}
        assert call('GET', '/api/history', params=params)['total'] == 1
        item_path = '/api/history/' + qa['history_id']
        assert call('GET', item_path, params=params)['id'] == qa['history_id']
        call('GET', item_path, expected=404, params={'session_id': str(uuid4())})
        call('DELETE', item_path, expected=204, params=params)
        assert call('DELETE', '/api/history', params=params)['deleted'] == 0
        call('POST', '/api/qa', expected=422, json={'question': '   '})
        call('POST', '/api/qa', expected=503, json={'question': 'Agent', 'retrieval_mode': 'vector'})
        call('GET', '/docs')
        spec = call('GET', '/openapi.json')
        operation_count = sum(m in {'get', 'post', 'delete'} for p in spec['paths'].values() for m in p)
        assert operation_count == 13
        if frontend_url:
            assert httpx.get(frontend_url + '/_stcore/health', timeout=5, trust_env=False).status_code == 200
            assert httpx.get(frontend_url, timeout=5, trust_env=False).status_code == 200
    result = {'result': 'PASS', 'operations': operation_count, 'routes': len(spec['paths']),
              'chapters': len(chapters), 'chunks': course['chunk_count'], 'frontend_http_ready': bool(frontend_url),
              'generation_mode': qa['generation_mode'], 'retrieval_mode': qa['retrieval_mode'], 'records': records}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--start-local', action='store_true', help='临时端口启动 Uvicorn，退出时关闭')
    parser.add_argument('--with-frontend', action='store_true', help='同时启动 Streamlit 并检查 HTTP 就绪；需 --start-local')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.with_frontend and not args.start_local:
        parser.error('--with-frontend requires --start-local')
    processes = []
    handles = []
    with TemporaryDirectory(prefix='course-api-smoke-') as temp:
        try:
            frontend_url = None
            if args.start_local:
                port = free_port()
                args.base_url = f'http://127.0.0.1:{port}'
                env = dict(os.environ, GENERATION_MODE='extractive', DEFAULT_RETRIEVAL_MODE='bm25',
                    DATABASE_PATH=str(Path(temp) / 'history.sqlite3'), PYTHONUTF8='1',
                    PYTHONIOENCODING='utf-8', EMBEDDING_BASE_URL='', EMBEDDING_MODEL='')
                log = (Path(temp) / 'uvicorn.log').open('w', encoding='utf-8')
                handles.append(log)
                process = subprocess.Popen([sys.executable, '-B', '-m', 'uvicorn', 'backend.main:app',
                    '--host', '127.0.0.1', '--port', str(port), '--no-access-log'], cwd=ROOT,
                    env=env, stdout=log, stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                processes.append(process)
                wait_ready(args.base_url + '/api/health', process)
                if args.with_frontend:
                    port = free_port()
                    frontend_url = f'http://127.0.0.1:{port}'
                    env['BACKEND_URL'] = args.base_url
                    log = (Path(temp) / 'streamlit.log').open('w', encoding='utf-8')
                    handles.append(log)
                    process = subprocess.Popen([sys.executable, '-B', '-m', 'streamlit', 'run',
                        str(ROOT / 'frontend/app.py'), '--server.address', '127.0.0.1', '--server.port', str(port),
                        '--server.headless', 'true', '--browser.gatherUsageStats', 'false'], cwd=ROOT,
                        env=env, stdout=log, stderr=subprocess.STDOUT,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                    processes.append(process)
                    wait_ready(frontend_url + '/_stcore/health', process)
            result = smoke(args.base_url, frontend_url)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                assert json.loads(args.output.read_text('utf-8'))['result'] == 'PASS'
            print('SMOKE PASS: operations={operations}, routes={routes}, chapters={chapters}, chunks={chunks}, '
                  'frontend_http_ready={frontend_http_ready}, mode={retrieval_mode}+{generation_mode}'.format(**result))
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            for handle in handles:
                handle.close()


if __name__ == '__main__':
    main()
