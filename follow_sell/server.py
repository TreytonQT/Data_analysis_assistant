from __future__ import annotations

from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from threading import Lock
import os
import secrets
import sys

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from follow_sell import VERSION
from follow_sell.processor import Result, ValidationError, process_mabang, process_oa


def bundle_root():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))


def program_root():
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(os.environ.get('FOLLOW_SELL_HOME', r'D:\AI_project\Output\AmazonFollowSell'))


class SaveRequest(BaseModel):
    output_dir: str


def create_app(resources=None, web_dir=None, home=None):
    resources = Path(resources or os.environ.get('FOLLOW_SELL_RESOURCES', bundle_root() / 'follow_sell/resources'))
    web_dir = Path(web_dir or os.environ.get('FOLLOW_SELL_WEB', bundle_root() / 'follow_sell/web'))
    home = Path(home or program_root())
    app = FastAPI(title='亚马逊跟卖表格助手', docs_url=None, redoc_url=None, openapi_url=None)
    token = secrets.token_urlsafe(32)
    cache = OrderedDict()
    lock = Lock()
    app.state.shutdown = lambda: None

    @app.middleware('http')
    async def local_only(request, call_next):
        host = request.url.hostname
        if host not in {'127.0.0.1', 'localhost', 'testserver'}:
            return JSONResponse({'detail': '仅允许本机访问。'}, status_code=403)
        if request.method not in {'GET', 'HEAD'}:
            origin = request.headers.get('origin')
            if (origin and origin != str(request.base_url).rstrip('/')) or not secrets.compare_digest(request.headers.get('x-follow-sell-token', ''), token):
                return JSONResponse({'detail': '会话已失效，请刷新页面。'}, status_code=403)
        return await call_next(request)

    @app.exception_handler(ValidationError)
    async def validation_error(request, exc):
        return JSONResponse({'detail': {'message': str(exc), 'count': len(exc.issues), 'issues': exc.issues}}, status_code=422)

    @app.get('/api/health')
    def health():
        return {'ok': True, 'app': 'amazon-follow-sell', 'version': VERSION}

    @app.get('/api/settings')
    def settings():
        return {'output_dir': str(home / 'output'), 'token': token}

    async def read_upload(upload):
        name = Path(upload.filename or '').name
        if not name.lower().endswith('.xlsx'):
            raise ValidationError([{'file': name, 'message': '仅支持xlsx文件，请另存为xlsx后重试。'}])
        content = await upload.read(50 * 1024 * 1024 + 1)
        if len(content) > 50 * 1024 * 1024:
            raise ValidationError([{'file': name, 'message': '单文件超过50MB，请拆分后重试。'}])
        return name, content

    def remember(result: Result):
        result_id = secrets.token_urlsafe(24)
        with lock:
            cache[result_id] = {'result': result, 'saved_path': None}
            while len(cache) > 12:
                cache.popitem(last=False)
        return {'result_id': result_id, 'summary': result.summary, 'columns': result.columns,
                'rows': result.rows, 'warnings': result.warnings, 'filename': result.filename}

    @app.post('/api/process/oa')
    async def oa(mapping: UploadFile = File(), oa: UploadFile = File(), prices: UploadFile = File()):
        from starlette.concurrency import run_in_threadpool

        uploads = [await read_upload(file) for file in (mapping, oa, prices)]
        result = await run_in_threadpool(process_oa, *[item[1] for item in uploads], [item[0] for item in uploads], resources)
        return remember(result)

    @app.post('/api/process/mabang')
    async def mabang(mapping: UploadFile = File(), generated: UploadFile = File(), original: UploadFile = File()):
        from starlette.concurrency import run_in_threadpool

        uploads = [await read_upload(file) for file in (mapping, generated, original)]
        result = await run_in_threadpool(process_mabang, *[item[1] for item in uploads], [item[0] for item in uploads])
        return remember(result)

    def lookup(result_id):
        entry = cache.get(result_id)
        if entry is None:
            raise HTTPException(404, '预览已过期，请重新校验文件。')
        return entry

    @app.post('/api/results/{result_id}/save')
    def save(result_id: str, request: SaveRequest):
        with lock:
            entry = lookup(result_id)
            if entry['saved_path']:
                return {'path': entry['saved_path']}
            output_dir = Path(request.output_dir.strip()).expanduser()
            if not request.output_dir.strip() or not output_dir.is_absolute():
                raise HTTPException(422, '请选择绝对路径的保存目录。')
            result = entry['result']
            path = output_dir / f'{Path(result.filename).stem}_{datetime.now():%Y%m%d_%H%M%S_%f}.xlsx'
            created = False
            try:
                output_dir.mkdir(parents=True, exist_ok=True)
                with path.open('xb') as stream:
                    created = True
                    stream.write(result.content)
            except OSError as exc:
                if created:
                    path.unlink(missing_ok=True)
                raise HTTPException(409, '保存失败：目录不可写或文件被占用，请关闭Excel或更换目录。') from exc
            entry['saved_path'] = str(path)
            return {'path': str(path)}

    @app.get('/api/results/{result_id}/download')
    def download(result_id: str):
        with lock:
            result = lookup(result_id)['result']
        from urllib.parse import quote

        return Response(result.content, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(result.filename)}"})

    @app.get('/api/templates/{number}')
    def template(number: int):
        files = sorted((resources / 'templates').glob(f'【{number}】*.xlsx')) if number in range(1, 6) else []
        if len(files) != 1:
            raise HTTPException(404, '模板不存在。')
        return FileResponse(files[0], filename=files[0].name)

    @app.post('/api/choose-directory')
    def choose_directory():
        # The native dialog is the only Tk surface; the application UI remains React/Ant Design.
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        try:
            selected = filedialog.askdirectory(parent=root, title='选择结果保存目录', initialdir=str(home))
            return {'path': selected or None}
        finally:
            root.destroy()

    @app.post('/api/shutdown')
    def shutdown():
        app.state.shutdown()
        return {'ok': True}

    if web_dir.is_dir():
        app.mount('/', StaticFiles(directory=web_dir, html=True), name='web')
    return app
