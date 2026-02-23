import unittest
from azul_bedrock.exception_enums import ExceptionCodeEnum

import httpretty
from azul_bedrock.models_restapi import pat as azm_pat
from .restapi.test_oidc_pat_modern import (
    client,
    create_pat_successfully,
    setup_security_environment_variables,
    FakeOpensearch,
)
from unittest.mock import patch


class TestPATFunctionality(unittest.TestCase):
    """Test the functionality of Opensearch/PAT interactions."""

    @classmethod
    @httpretty.activate(verbose=True, allow_net_connect=False)
    def setUpClass(cls) -> None:
        setup_security_environment_variables()
        cls.mock_opensearch = FakeOpensearch()
        cls.admin_token, cls.pat_issue = create_pat_successfully(
            pat_name="class_level_pat", mock_opensearch=cls.mock_opensearch
        )
        return super().setUpClass()

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_delete_token(self):
        with patch("azul_restapi_server.security.pat_core.get_opensearch_pat_admin_session") as mock_os:
            mock_os.return_value = self.mock_opensearch
            admin_token_2, pat_issue_2 = create_pat_successfully(
                pat_name="pat_to_delete", mock_opensearch=self.mock_opensearch
            )
            # Should be two PATs
            resp = client.get("/v0/authenticate/pat/list", headers={"Authorization": self.admin_token})
            self.assertEqual(len(resp.json().get("pats", [])), 2)
            # Delete PAT
            resp = client.delete(
                "/v0/authenticate/pat", params={"id": pat_issue_2.id}, headers={"Authorization": admin_token_2}
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json(), {"result": "success"})
            resp = client.delete(
                "/v0/authenticate/pat", params={"id": pat_issue_2.id}, headers={"Authorization": admin_token_2}
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json(), {"result": "not found can't delete"})

            # Should be one PAT again
            resp = client.get("/v0/authenticate/pat/list", headers={"Authorization": self.admin_token})
            self.assertEqual(len(resp.json().get("pats", [])), 1)

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_list_tokens(self):
        with patch("azul_restapi_server.security.pat_core.get_opensearch_pat_admin_session") as mock_os:
            mock_os.return_value = self.mock_opensearch
            resp = client.get("/v0/authenticate/pat/list", headers={"Authorization": self.admin_token})
            self.assertEqual(resp.status_code, 200)
            self.assertGreaterEqual(len(resp.json().get("pats", [])), 1)

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_fail_to_use_pat_for_pat_operations(self):
        """You can't look at and modify PATs with PATs."""
        with patch("azul_restapi_server.security.pat_core.get_opensearch_pat_admin_session") as mock_os:
            mock_os.return_value = self.mock_opensearch
            # Create PATS
            resp = client.post(
                "/v0/authenticate/pat",
                json=azm_pat.PATRequest(name="test_pat_success", roles=["s-test1", "s-test2", "s-test3"]).model_dump(),
                headers={"X-API-Key": self.pat_issue.ready_api_key},
            )
            print(resp.content)
            self.assertEqual(resp.status_code, 403)
            self.assertEqual(
                resp.json().get("detail", {}).get("internal"), ExceptionCodeEnum.RestapiAllowedPATAction.value
            )
            # Delete PATS
            resp = client.delete(
                "/v0/authenticate/pat",
                params={"id": "random-id"},
                headers={"X-API-Key": self.pat_issue.ready_api_key},
            )
            print(resp.content)
            self.assertEqual(resp.status_code, 403)
            self.assertEqual(
                resp.json().get("detail", {}).get("internal"), ExceptionCodeEnum.RestapiAllowedPATAction.value
            )
            # List PATs
            resp = client.get(
                "/v0/authenticate/pat/list",
                headers={"X-API-Key": self.pat_issue.ready_api_key},
            )
            print(resp.content)
            self.assertEqual(resp.status_code, 403)
            self.assertEqual(
                resp.json().get("detail", {}).get("internal"), ExceptionCodeEnum.RestapiAllowedPATAction.value
            )
