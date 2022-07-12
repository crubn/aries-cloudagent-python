from aiohttp import web
from aiohttp_apispec import (
    docs,
    request_schema,
    response_schema,
)
from marshmallow import fields

from ....messaging.models.openapi import OpenAPISchema
from ....indy.models.proof_request import IndyProofRequestSchema
from ....indy.models.proof import IndyPresSpecSchema, IndyProofSchema
from ....admin.request_context import AdminRequestContext
from ....indy.holder import IndyHolderError
from ....ledger.error import LedgerError
from ....messaging.models.base import BaseModelError
from ....storage.error import StorageError
from ....wallet.error import WalletNotFoundError
from ....indy.util import generate_pr_nonce


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


async def register(app: web.Application):
    """Register routes"""

    app.add_routes(
        [
            web.post("/static-proof/create",create_proof),
            web.post("/static-proof/verify", verify_proof),

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
