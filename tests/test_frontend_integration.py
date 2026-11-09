import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app import create_app

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {'/', '/login', '/nodes', '/egresses', '/subscriptions', '/tasks', '/settings', '/pool'}


def test_frontend_routes_and_assets(tmp_path):
    app = create_app(tmp_path / 'frontend-test', cookie_secure=False)
    with TestClient(app) as client:
        manifest = client.get('/manus-routes.json')
        assert manifest.status_code == 200
        assert 'application/json' in manifest.headers['content-type']
        routes = {entry['path'] for entry in manifest.json()['routes']}
        assert routes == EXPECTED
        for route in routes:
            result = client.get(route)
            assert result.status_code == 200
            assert '<!doctype html>' in result.text.lower()
        index = client.get('/').text
        for asset in re.findall(r'(?:src|href)="(/assets/[^"]+)"', index):
            result = client.get(asset)
            assert result.status_code == 200, asset
        for module in (ROOT / 'web/assets').glob('*.js'):
            text = module.read_text()
            for imported in re.findall(r"from ['\"]([^'\"]+)['\"]", text):
                if imported.startswith('./'):
                    assert client.get('/assets/' + imported[2:]).status_code == 200
        assert client.get('/assets/%2e%2e/index.html').status_code == 404
        assert client.get('/assets/nonexistent.js').status_code == 404
        assert client.get('/api/dashboard').status_code == 401
        assert client.get('/api/not-a-route').status_code == 401
        assert client.get('/not-a-page').status_code == 404
