import json

from aiohttp import web
from aiohttp_apispec import (
    docs,
    request_schema,
    response_schema,
    querystring_schema,
)
from marshmallow import fields

from ....messaging.models.openapi import OpenAPISchema
from ....indy.models.proof_request import IndyProofRequestSchema
from ....indy.models.proof import IndyPresSpecSchema, IndyProofSchema
from ....admin.request_context import AdminRequestContext
from ....indy.holder import IndyHolder, IndyHolderError
from ....ledger.error import LedgerError
from ....messaging.models.base import BaseModelError
from ....storage.error import StorageError
from ....wallet.error import WalletNotFoundError
from ....indy.util import generate_pr_nonce
from ....messaging.valid import (
    INDY_EXTRA_WQL,
    NUM_STR_NATURAL,
    NUM_STR_WHOLE
)
from ....indy.models.cred_precis import IndyCredPrecisSchema
from .manager import StaticProofManager

class V10CreateStaticProofRequestSchema(OpenAPISchema):
    """Request schema for creating static proof"""

    proof_request = fields.Nested(IndyProofRequestSchema(),required=True)
    presentation = fields.Nested(IndyPresSpecSchema(),required=True)

class V10StaticProof(OpenAPISchema):
    """Static proof"""
    presentation_request = fields.Nested(IndyProofRequestSchema(),required=True)
    presentation = fields.Nested(
        IndyProofSchema(),
        require=True,
        description="(Indy) presentation (also known as proof)",
    )

class V10VerifyStaticProofResponseSchema(OpenAPISchema):
    """Response schema of verify static proof"""
    valid = fields.Boolean(
        description="Is static proof valid"
    )

class CredentialsFetchQueryStringSchema(OpenAPISchema):
    """Parameters and validators for credentials fetch request query string."""

    referent = fields.Str(
        description="Proof request referents of interest, comma-separated",
        required=False,
        example="1_name_uuid,2_score_uuid",
    )
    start = fields.Str(
        description="Start index",
        required=False,
        strict=True,
        **NUM_STR_WHOLE,
    )
    count = fields.Str(
        description="Maximum number to retrieve",
        required=False,
        **NUM_STR_NATURAL,
    )
    extra_query = fields.Str(
        description="(JSON) object mapping referents to extra WQL queries",
        required=False,
        **INDY_EXTRA_WQL,
    )


@docs(
    tags=["static proof"],
    summary="Create static proof",
)
@request_schema(V10CreateStaticProofRequestSchema())
@response_schema(V10StaticProof())
async def create_proof(request: web.BaseRequest):
    """
    Request handler for creating a static proof.

    Args:
        request: aiohttp request object
    """
    context: AdminRequestContext = request["context"]
    profile = context.profile
    body = await request.json()

    indy_proof_request = body.get("proof_request")
    # set nonce to proof request
    indy_proof_request["nonce"] = await generate_pr_nonce()
    try:
        static_proof_manager = StaticProofManager(profile)

        proof = await static_proof_manager.create_presentation(
            indy_proof_request,
            body.get("presentation")
        )
        result = {
            "presentation" : proof,
            "presentation_request": indy_proof_request,
        }
        return web.json_response(result)
    except(
        BaseModelError,
        IndyHolderError,
        LedgerError,
        StorageError,
        WalletNotFoundError,
    ) as err:
        raise web.HTTPBadRequest(reason=err.roll_up)

@docs(
    tags=["static proof"],
    summary="Verify static proof",
)
@request_schema(V10StaticProof())
@response_schema(V10VerifyStaticProofResponseSchema())
async def verify_proof(request: web.BaseRequest):
    """
    Request handler for verifying a static proof.

    Args:
        request: aiohttp request object
    """
    context: AdminRequestContext = request["context"]
    profile = context.profile
    body = await request.json()

    try:
        static_proof_manager = StaticProofManager(profile)
        valid = await static_proof_manager.verify_presentation(
            body.get("presentation_request"),
            body.get("presentation")
        )
        result = {
            "valid" : valid
        }
        return web.json_response(result)
    except (BaseModelError, LedgerError, StorageError) as err:
        raise web.HTTPBadRequest(reason=err.roll_up)

@docs(
    tags=["static proof"],
    summary="Fetch credentials for a presentation request from wallet",
)
@querystring_schema(CredentialsFetchQueryStringSchema())
@request_schema(IndyProofRequestSchema())
@response_schema(IndyCredPrecisSchema(many=True), 200, description="")
async def credentials_list(request: web.BaseRequest):
    """
    Request handler for searching applicable credentials records

    Args:
        request: aiohttp request object
    Returns:
        The credentials list response
    """
    context: AdminRequestContext = request["context"]
    profile = context.profile
    indy_proof_request = await request.json()
    # set nonce to proof request
    indy_proof_request["nonce"] = await generate_pr_nonce()

    referents = request.query.get("referent")
    presentation_referents = (
        (r.strip() for r in referents.split(",")) if referents else ()
    )

    start = request.query.get("start")
    count = request.query.get("count")

    # url encoded json extra_query
    encoded_extra_query = request.query.get("extra_query") or "{}"
    extra_query = json.loads(encoded_extra_query)

    # defaults
    start = int(start) if isinstance(start, str) else 0
    count = int(count) if isinstance(count, str) else 10

    holder = profile.inject(IndyHolder)

    try:
        credentials = await holder.get_credentials_for_presentation_request_by_referent(
            indy_proof_request,
            presentation_referents,
            start,
            count,
            extra_query,
        )
        return web.json_response(credentials)
    except IndyHolderError as err:
        raise web.HTTPBadRequest(reason=err.roll_up)


async def register(app: web.Application):
    """Register routes"""

    app.add_routes(
        [
            web.post("/static-proof/create",create_proof),
            web.post("/static-proof/verify", verify_proof),
            web.post("/static-proof/credentials", credentials_list)
        ]
    )

def post_process_routes(app: web.Application):
    """Amend swagger API."""

    # Add top-level tags description
    if "tags" not in app._state["swagger_dict"]:
        app._state["swagger_dict"]["tags"] = []
    app._state["swagger_dict"]["tags"].append(
        {
            "name": "static proof",
            "description": "Static proof",
        }
    )
