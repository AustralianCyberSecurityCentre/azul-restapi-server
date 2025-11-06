import unittest

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from azul_restapi_server import security, settings
from azul_restapi_server.api.v1 import users
from azul_restapi_server.security import no_auth

app = FastAPI()
app.include_router(users.router, dependencies=[Depends(security.validate_token)])
client = TestClient(app)


class TestCaseAnony(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        app.dependency_overrides[security.validate_token] = no_auth.validate_token
        settings.reset()

    def test_me(self):
        response = client.get("/v0/users/me")
        self.assertEqual(200, response.status_code)
        self.assertEqual("anony-moose", response.json()["username"])
        self.assertEqual(["validated"], response.json()["roles"])
