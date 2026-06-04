# backend/core/oci_client.py
# ──────────────────────────────────────────────────────────────────
# OCI SDK client factory.
# Returns per-region clients so instances are always fetched from
# the correct region endpoint — fixing the "all resources in any
# region" bug.
# ──────────────────────────────────────────────────────────────────
import oci
from core.config import settings
from core.logging_setup import app_logger

# Base config / signer loaded once
_base_config: dict = {}
_signer       = None

def _load_base():
    global _base_config, _signer
    if settings.OCI_INSTANCE_PRINCIPAL:
        app_logger.info("OCI auth: InstancePrincipal")
        _signer       = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
        _base_config  = {}
    else:
        app_logger.info("OCI auth: ConfigFile (~/.oci/config)")
        _base_config  = oci.config.from_file()
        _signer       = None

try:
    _load_base()
except Exception as exc:
    app_logger.warning(f"OCI base config load failed (OK in CI/test): {exc}")


def get_compute_client(region: str | None = None) -> oci.core.ComputeClient:
    """
    Return a ComputeClient scoped to *region*.
    OCI instances are regional — queries must target the right endpoint.
    If region is None, falls back to the home region in ~/.oci/config.
    """
    cfg = dict(_base_config)
    if region:
        cfg["region"] = region
    kwargs = {"config": cfg}
    if _signer:
        kwargs["signer"] = _signer
    return oci.core.ComputeClient(**kwargs)


def get_identity_client(region: str | None = None) -> oci.identity.IdentityClient:
    cfg = dict(_base_config)
    if region:
        cfg["region"] = region
    kwargs = {"config": cfg}
    if _signer:
        kwargs["signer"] = _signer
    return oci.identity.IdentityClient(**kwargs)


def get_base_config() -> dict:
    return dict(_base_config)


# Convenience singletons for non-regional calls (IAM, tenancy info)
try:
    identity_client = get_identity_client()
    compute_client  = get_compute_client()
except Exception as exc:
    app_logger.warning(f"OCI client init failed (OK in CI/test): {exc}")
    identity_client = None
    compute_client  = None
