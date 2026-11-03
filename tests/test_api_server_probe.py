import json
import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from curllm_core.config import _resolve_api_port as core_resolve_port
from curllm_core.server import app as core_app
from curllm_server.app import app as server_app
from curllm_server.config import _resolve_api_port as server_resolve_port


def test_core_probe_endpoint():
    client = core_app.test_client()
    resp = client.post('/api/execute', json={"probe": True})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get('status') == 'ok'
    assert data.get('probe') is True
    assert data.get('service') == 'curllm'


def test_core_empty_execute_returns_probe():
    client = core_app.test_client()
    resp = client.post('/api/execute', json={})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get('status') == 'ok'
    assert data.get('probe') is True


def test_core_404_error_envelope():
    client = core_app.test_client()
    resp = client.get('/api/nonexistent_route_404')
    assert resp.status_code == 404
    data = resp.get_json()
    assert data.get('status') == 'error'
    assert data.get('error') == 'Not Found'
    assert data.get('code') == 404


def test_server_probe_endpoint():
    client = server_app.test_client()
    resp = client.post('/api/execute', json={"probe": True})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get('status') == 'ok'
    assert data.get('probe') is True


def test_server_404_error_envelope():
    client = server_app.test_client()
    resp = client.get('/api/nonexistent_route_404')
    assert resp.status_code == 404
    data = resp.get_json()
    assert data.get('status') == 'error'
    assert data.get('error') == 'Not Found'
    assert data.get('code') == 404


def test_port_resolution_env_var():
    with mock.patch.dict(os.environ, {"CURLLM_API_PORT": "9050"}):
        assert core_resolve_port() == 9050
        assert server_resolve_port() == 9050


def test_port_resolution_file(tmp_path):
    with mock.patch.dict(os.environ, {}, clear=True):
        os.environ.pop("CURLLM_API_PORT", None)
        os.environ.pop("API_PORT", None)
        fake_port_file = tmp_path / "curllm_api_port"
        fake_port_file.write_text("8045\n", encoding="utf-8")
        with mock.patch("pathlib.Path.is_file", return_value=True), \
             mock.patch("pathlib.Path.read_text", return_value="8045\n"):
            assert core_resolve_port() == 8045
            assert server_resolve_port() == 8045


def test_port_resolution_default():
    with mock.patch.dict(os.environ, {}, clear=True):
        os.environ.pop("CURLLM_API_PORT", None)
        os.environ.pop("API_PORT", None)
        with mock.patch("pathlib.Path.is_file", return_value=False):
            assert core_resolve_port() == 8020
            assert server_resolve_port() == 8020
