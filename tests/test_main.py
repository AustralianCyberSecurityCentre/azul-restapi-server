from starlette.testclient import TestClient

from azul_restapi_server.main import app

client = TestClient(app)

import unittest


class TestNoAuthWarning(unittest.TestCase):
    def test_warns_when_security_is_none(self):
        import importlib
        import io
        import sys

        from azul_restapi_server import settings

        self.assertEqual(settings.restapi.security, settings.RestapiSecurityEnum.none)

        captured = io.StringIO()
        old_stderr = sys.stderr
        sys.stderr = captured
        try:
            from azul_restapi_server import main as main_module

            importlib.reload(main_module)
        finally:
            sys.stderr = old_stderr

        self.assertIn("RESTAPI_SECURITY=none", captured.getvalue())


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
