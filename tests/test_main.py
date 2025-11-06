from starlette.testclient import TestClient

from azul_restapi_server.main import app

client = TestClient(app)

import unittest


class TestCase(unittest.TestCase):
    def test_read_main(self):
        response = client.get("/")
        # even though this is a redirect, requests seems to return the response
        # after the redirect
        assert response.status_code == 200

    def test_read_docs(self):
        response = client.get("/api")
        assert response.status_code == 200

    def test_read_redoc(self):
        response = client.get("/api/redoc")
        assert response.status_code == 200
