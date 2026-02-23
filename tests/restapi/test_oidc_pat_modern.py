import base64
import datetime
import json
import os
import unittest
from unittest.mock import patch

import httpretty
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from jose import jwt
from azul_restapi_server import security, settings
from azul_restapi_server.api.v1 import users, pat_api
from azul_restapi_server.security import oidc_pat_modern
from azul_restapi_server.security import pat_core
import copy
import unittest
from azul_bedrock.models_restapi import pat as azm_pat
from opensearchpy import exceptions as opensearchpy_exceptions

from azul_restapi_server.api.v1.pat_api import generate_pat

app = FastAPI()
app.include_router(users.router, dependencies=[Depends(security.validate_token)])
app.include_router(pat_api.router, dependencies=[Depends(security.validate_token)])
client = TestClient(app)

_SECRET = "secret.secret.secret.secret.secret.secret."


class FakeOpensearch:
    """Fake opensearch class to be used in place of an opensearch session in mock tests."""

    def __init__(self):
        self.stored_pats: dict[str, azm_pat.PATIssue] = dict()

    def index(self, *, body: dict[str, str], index: str, refresh: bool = True, **kwargs) -> dict:
        """Mock for adding a document into an opensearch index."""
        shallow_body = copy.copy(body)
        # Generate random id.
        generated_id = generate_pat(10)
        shallow_body["id"] = generated_id
        shallow_body["ready_api_key"] = ""
        self.stored_pats[generated_id] = azm_pat.PATIssue.model_validate(shallow_body)

        return {
            "_index": index,
            "_id": generated_id,
            "_version": 1,
            "result": "created",
            "forced_refresh": refresh,
            "_shards": {"total": 3, "successful": 3, "failed": 0},
            "_seq_no": 10,
            "_primary_term": 1,
        }

    def search(self, *, body: dict, index: str, ignore: list[str] = [], **kwargs) -> dict:
        """Mock for search results."""
        terms = body.get("query", {}).get("bool", {}).get("must", [])
        if terms:
            pat_name_to_find = ""
            pat_owner_username_to_fine = ""
            for term in terms:
                for k, v in term.get("term").items():
                    if k == "pat_name":
                        pat_name_to_find = v
                    elif k == "owner_username":
                        pat_owner_username_to_fine = v
                    else:
                        raise Exception(f"Bad term query provided unexpected key/value {k}/{v}")
            for pat_id, pat_val in self.stored_pats.items():
                if pat_val.owner_username == pat_owner_username_to_fine and pat_val.pat_name == pat_name_to_find:
                    return {
                        "took": 1,
                        "timed_out": False,
                        "_shards": {"total": 1, "successful": 1, "skipped": 0, "failed": 0},
                        "hits": {
                            "total": {"value": 1, "relation": "eq"},
                            "max_score": 2.0,
                            "hits": [
                                {
                                    "_index": index,
                                    "_id": pat_val.id,
                                    "_score": 2.0,
                                    "_source": {
                                        "pat_name": pat_val.pat_name,
                                        "description": pat_val.description,
                                        "pat": pat_val.pat,
                                        "roles": pat_val.roles,
                                        "owner_username": pat_val.owner_username,
                                        "creation_date": pat_val.creation_date,
                                        "last_used_date": pat_val.last_used_date,
                                    },
                                }
                            ],
                        },
                    }
            # not found
            return {
                "took": 1,
                "timed_out": False,
                "_shards": {"total": 1, "successful": 1, "skipped": 0, "failed": 0},
                "hits": {"total": {"value": 0, "relation": "eq"}, "max_score": None, "hits": []},
            }

        elif body.get("query", {}).get("match_all", None) is not None:
            # Get full listing of stored pats.
            hits: list[dict] = []
            for p in self.stored_pats.values():
                hits.append(
                    {
                        "_index": index,
                        "_id": p.id,
                        "_score": 1.0,
                        "_source": {
                            "last_used_date": p.last_used_date,
                            "pat_name": p.pat_name,
                            "roles": p.roles,
                            "owner_username": p.owner_username,
                            "description": p.description,
                            "creation_date": p.creation_date,
                        },
                    }
                )

            return {
                "took": 1,
                "timed_out": False,
                "_shards": {"total": 1, "successful": 1, "skipped": 0, "failed": 0},
                "hits": {
                    "total": {"value": len(hits), "relation": "eq"},
                    "max_score": 1.0 if len(hits) > 0 else None,
                    "hits": hits,
                },
            }
        else:
            raise Exception(f"Unexpected body for opensearch search {body}")

    def update(self, *, body: dict, index: str, ignore: list[str] = [], **kwargs):
        """Mock update which is used to update last modified date."""
        pass

    def delete(self, *, index, id) -> dict:
        """Mock for deleting ids from index in opensearch."""
        if id in self.stored_pats:
            del self.stored_pats[id]
            return {}
        raise opensearchpy_exceptions.NotFoundError()

    def get(self, *, index: str, id: str, ignore: list[str], **kwargs) -> dict:
        """Mock for getting documents from index in Opensearch."""
        if id in self.stored_pats:
            pat = self.stored_pats[id]
            return {
                "_index": index,
                "_id": pat.id,
                "_version": 1,
                "_seq_no": 11,
                "_primary_term": 1,
                "found": True,
                "_source": {
                    "pat_name": pat.pat_name,
                    "description": pat.description,
                    "pat": pat.pat,
                    "roles": pat.roles,
                    "owner_username": pat.owner_username,
                    "creation_date": pat.creation_date,
                    "last_used_date": pat.last_used_date,
                },
            }
        # not found
        return {"_index": index, "_id": id, "found": False}


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


@patch("azul_bedrock.datastore.get_user_account", return_value={"roles": ["admin", "s-test1", "s-test2", "s-test3"]})
def create_pat_successfully(
    mock_get_user_account, *, pat_name: str, mock_opensearch: FakeOpensearch
) -> tuple[str, azm_pat.PATIssue]:
    with patch("azul_restapi_server.security.pat_core.get_opensearch_pat_admin_session") as mock_get_session:
        mock_get_session.return_value = mock_opensearch
        register_well_known()
        admin_token = gen_token(labels=["admin", "s-test1", "s-test2", "s-test3"], user="apiUser")
        created_pat_resp = client.post(
            "/v0/authenticate/pat",
            json=azm_pat.PATRequest(name=pat_name, roles=["s-test1", "s-test2", "s-test3"]).model_dump(),
            headers={"Authorization": admin_token},
        )
        return admin_token, azm_pat.PATIssue.model_validate(created_pat_resp.json())


def setup_security_environment_variables():
    """Setup required environment variables for azul-security to work."""
    os.environ["OIDC_AUTHORITY_URL"] = "http://localhost:8080"
    os.environ["OIDC_CLIENT_ID"] = "web"
    os.environ["SECURITY_DEFAULT"] = "LOW"
    os.environ["SECURITY_ADMIN_ROLES"] = json.dumps(["admin"])
    os.environ["SECURITY_LABELS"] = json.dumps(
        {
            "classification": {
                "title": "Classifications",
                "options": [
                    {"name": "LOW", "priority": "10"},
                    {"name": "test1", "priority": "10"},
                    {"name": "test2", "priority": "10"},
                    {"name": "test3", "priority": "10"},
                    {"name": "MEDIUM", "priority": "30"},
                ],
            },
            "caveat": {
                "title": "Required",
                "options": [
                    {"name": "MOD1", "priority": "5"},
                ],
            },
            "releasability": {
                "title": "Groups",
                "origin": "REL:APPLE",
                "origin_alt_name": "APPLEO",
                "prefix": "REL:",
                "options": [
                    {"name": "REL:APPLE", "priority": "0"},
                ],
            },
            "tlp": {
                "title": "TLP",
                "options": [
                    {"name": "TLP:CLEAR", "priority": "10"},
                    {"name": "TLP:GREEN", "priority": "20"},
                ],
            },
        }
    )
    os.environ["SECURITY_ALLOW_RELEASABILITY_PRIORITY_GTE"] = "30"
    os.environ["security_minimum_required_access"] = json.dumps(["test1"])
    app.dependency_overrides[security.validate_token] = oidc_pat_modern.validate_token
    settings.reset()


class TestOIDC(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        setup_security_environment_variables()
        cls.mock_opensearch = FakeOpensearch()

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_good_token(self):
        with patch("azul_restapi_server.security.pat_core.get_opensearch_pat_admin_session") as mock_os:
            mock_os.return_value = self.mock_opensearch
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
            self.assertEqual(401, resp.status_code)

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_api_pat_success(self):
        with patch("azul_restapi_server.security.pat_core.get_opensearch_pat_admin_session") as mock_os:
            mock_os.return_value = self.mock_opensearch
            _admin_token, issued_token = create_pat_successfully(
                pat_name="test_pat_success", mock_opensearch=self.mock_opensearch
            )
            self.assertEqual(issued_token.roles, ["s-test1", "s-test2", "s-test3", "s-any"])
            self.assertEqual(issued_token.pat_name, "test_pat_success")
            self.assertEqual(issued_token.owner_username, "apiUser")

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_api_pat_failures(self):
        with patch("azul_restapi_server.security.pat_core.get_opensearch_pat_admin_session") as mock_os:
            mock_os.return_value = self.mock_opensearch
            # Try a self made JWT
            api_user_pat = pat_core._gen_opensearch_jwt(roles=["test1", "test2", "test3"], user="apiUser")
            resp = client.get("/v0/users/me", headers={"X-API-Key": api_user_pat})
            self.assertEqual(401, resp.status_code)

            # non-base64 invalid token
            token = "bad_token"
            resp = client.get("/v0/users/me", headers={"X-API-Key": token})
            self.assertEqual(401, resp.status_code)

            # base64 invalid token
            token = base64.b64encode("fake_token_id:bad_token".encode())
            resp = client.get("/v0/users/me", headers={"X-API-Key": token.decode()})
            self.assertEqual(401, resp.status_code)
