"""Load the configured security provider."""

from .. import settings

_provider_name = settings.restapi.security

if _provider_name == settings.RestapiSecurityEnum.oidc_pat:
    from . import oidc_pat_modern as security_source
elif _provider_name == settings.RestapiSecurityEnum.oidc:
    from . import oidc_modern as security_source
elif _provider_name == settings.RestapiSecurityEnum.oidc_legacy:
    from . import oidc_legacy as security_source
elif _provider_name == settings.RestapiSecurityEnum.none:
    from . import no_auth as security_source
else:
    raise Exception("unknown security provider")

validate_token = security_source.validate_token
