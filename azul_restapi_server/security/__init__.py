"""Load the configured security provider."""

from .. import settings

_provider_name = settings.restapi.security.lower()

if _provider_name == "oidc":
    from . import oidc_modern as security_source
elif _provider_name == "oidc_legacy":
    from . import oidc_legacy as security_source
elif _provider_name == "none":
    from . import no_auth as security_source
else:
    raise Exception("unknown security provider")

validate_token = security_source.validate_token
