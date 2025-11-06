import datetime
import json
import os
import unittest

import httpretty
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from jose import jwt

from azul_restapi_server import security, settings
from azul_restapi_server.api.v1 import users
from azul_restapi_server.security import oidc_modern as oidc

app = FastAPI()
app.include_router(users.router, dependencies=[Depends(security.validate_token)])
client = TestClient(app)

_SECRET = "secret.secret.secret.secret.secret.secret."


def gen_token(labels: list[str], user: str):
    """Generate a tests jwt token using a preshared secret."""
    return jwt.encode(
        {
            "roles": labels,
            "sub": user,
            "iss": "http://localhost:8080",
            "iat": datetime.datetime.now() - datetime.timedelta(weeks=1),
            "nbf": datetime.datetime.now() - datetime.timedelta(weeks=1),
            "exp": datetime.datetime.now() + datetime.timedelta(weeks=1),
            "preferred_username": user,
            "aud": "web",
        },
        _SECRET,
        algorithm="HS256",
    )


def register_well_known():
    wellknown = json.dumps(
        {
            "jwks_uri": "http://localhost:8080/keys",
            "id_token_signing_alg_values_supported": "HS256",
            "issuer": "http://localhost:8080",
        }
    )
    httpretty.register_uri(
        httpretty.GET,
        "http://localhost:8080/.well-known/openid-configuration",
        body=wellknown,
    )
    httpretty.register_uri(
        httpretty.GET,
        "http://localhost:8080/keys",
        body=json.dumps("secret.secret.secret.secret.secret.secret."),
    )


class TestOIDC(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ["OIDC_AUTHORITY_URL"] = "http://localhost:8080"
        os.environ["OIDC_CLIENT_ID"] = "web"
        app.dependency_overrides[security.validate_token] = oidc.validate_token
        settings.reset()

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_good_token(self):
        register_well_known()
        token = gen_token(labels=["test1", "test2", "test3"], user="llama")
        resp = client.get("/v0/users/me", headers={"Authorization": token})
        self.assertEqual(200, resp.status_code)
        self.assertEqual("llama", resp.json()["username"])
        self.assertEqual(["test1", "test2", "test3"], resp.json()["roles"])

        # invalid token
        token = "my_token_hac"
        resp = client.get("/v0/users/me", headers={"Authorization": token})
        self.assertEqual(401, resp.status_code)

        # no token
        resp = client.get("/v0/users/me")
        self.assertEqual(403, resp.status_code)
