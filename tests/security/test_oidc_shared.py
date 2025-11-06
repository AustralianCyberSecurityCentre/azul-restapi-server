import unittest

from azul_restapi_server.security import oidc_shared


class TestOIDC(unittest.TestCase):
    def testclaims_to_user(self):
        user = oidc_shared.claims_to_user(
            {
                "preferred_username": "maraka",
                "org": "klombine",
                "email": "maraka@klombine.com",
                "roles": ["/a", "b", "c"],
                "sub": "maraka-sub-id",
            }
        )
        self.assertEqual(user.username, "maraka")
        self.assertEqual(user.org, "klombine")
        self.assertEqual(user.email, "maraka@klombine.com")
        self.assertEqual(user.roles, ["a", "b", "c"])
        self.assertEqual(user.unique_id, "maraka-sub-id")

        user = oidc_shared.claims_to_user(
            {
                "preferred_username": "maraka",
                "sub": "maraka-sub-id",
            }
        )
        self.assertEqual(user.username, "maraka")
        self.assertEqual(user.org, "unknown")
        self.assertEqual(user.email, "")
        self.assertEqual(user.roles, [])
        self.assertEqual(user.unique_id, "maraka-sub-id")

        user = oidc_shared.claims_to_user(
            {
                "azpacr": 7,
                "azp": "my_service",
                "sub": "my_service_id",
            }
        )
        self.assertEqual(user.username, "my_service")
        self.assertEqual(user.org, "unknown")
        self.assertEqual(user.email, "")
        self.assertEqual(user.roles, [])
        self.assertEqual(user.unique_id, "my_service_id")

        user = oidc_shared.claims_to_user(
            {
                "azpacr": 7,
                "azp": "my_service",
                "org": "klombine",
                "email": "maraka@klombine.com",
                "roles": ["/a", "b", "c"],
                "sub": "my_service_id",
            }
        )
        self.assertEqual(user.username, "my_service")
        self.assertEqual(user.org, "klombine")
        self.assertEqual(user.email, "maraka@klombine.com")
        self.assertEqual(user.roles, ["a", "b", "c"])
        self.assertEqual(user.unique_id, "my_service_id")
