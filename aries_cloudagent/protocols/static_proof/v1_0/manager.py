"""Manager for static proof."""
import json
import logging
import time


from ....core.profile import Profile
from ....indy.holder import IndyHolder
from ....indy.models.xform import indy_proof_req2non_revoc_intervals
from ....indy.holder import IndyHolderError
from ....multitenant.base import BaseMultitenantManager
from ....ledger.multiple_ledger.ledger_requests_executor import (
    GET_SCHEMA,
    GET_REVOC_REG_DELTA,
    IndyLedgerRequestsExecutor,
)
from ....revocation.models.revocation_registry import RevocationRegistry


LOGGER = logging.getLogger(__name__)


class StaticProofManager:
    """Class for managing static proofs"""

    def __init__(self, profile: Profile) -> None:
        """
        Initialize a StaticProofManager

        Args:
            profile: The profile instance for this static proof manager
        """
        self._profile = profile

    async def create_presentation(
        self,
        proof_request: dict,
        requested_credentials: dict
    ):
        """
        Create a create_presentation

        Args:
            proof_request: indy formatted proof request
            requested_credentials: Indy formatted requested_credentials

        Returns:
            proof: Indy formatted proof schema
        """

        # Get all credentials for this presentation
        holder = self._profile.inject(IndyHolder)
        credentials = {}

        # extract credentials ids and non_revoked
        requested_referents = {}
        non_revoc_intervals = indy_proof_req2non_revoc_intervals(proof_request)
        attr_creds = requested_credentials.get("requested_attributes", {})
        req_attrs = proof_request.get("requested_attributes", {})
        for reft in attr_creds:
            requested_referents[reft] = {"cred_id": attr_creds[reft]["cred_id"]}
            if reft in req_attrs and reft in non_revoc_intervals:
                requested_referents[reft]["non_revoked"] = non_revoc_intervals[reft]
        pred_creds = requested_credentials.get("requested_predicates", {})
        req_preds = proof_request.get("requested_predicates", {})
        for reft in pred_creds:
            requested_referents[reft] = {"cred_id": pred_creds[reft]["cred_id"]}
            if reft in req_preds and reft in non_revoc_intervals:
                requested_referents[reft]["non_revoked"] = non_revoc_intervals[reft]
        # extract mapping of presentation referents to credential ids
        for reft in requested_referents:
            credential_id = requested_referents[reft]["cred_id"]
            if credential_id not in credentials:
                credentials[credential_id] = json.loads(
                    await holder.get_credential(credential_id)
                )
        # remove any timestamps that cannot correspond to non-revoc intervals
        for r in ("requested_attributes", "requested_predicates"):
            for reft, req_item in requested_credentials.get(r, {}).items():
                if not credentials[req_item["cred_id"]].get(
                    "rev_reg_id"
                ) and req_item.pop("timestamp", None):
                    LOGGER.info(
                        f"Removed superfluous timestamp from requested_credentials {r} "
                        f"{reft} for non-revocable credential {req_item['cred_id']}"
                    )
        # Get all schemas, credential definitions, and revocation registries in use
        schemas = {}
        cred_defs = {}
        revocation_registries = {}

        for credential in credentials.values():
            schema_id = credential["schema_id"]
            multitenant_mgr = self._profile.inject_or(BaseMultitenantManager)
            if multitenant_mgr:
                ledger_exec_inst = IndyLedgerRequestsExecutor(self._profile)
            else:
                ledger_exec_inst = self._profile.inject(IndyLedgerRequestsExecutor)
            ledger = (
                await ledger_exec_inst.get_ledger_for_identifier(
                    schema_id,
                    txn_record_type=GET_SCHEMA,
                )
            )[1]
            async with ledger:
                if schema_id not in schemas:
                    schemas[schema_id] = await ledger.get_schema(schema_id)
                cred_def_id = credential["cred_def_id"]
                if cred_def_id not in cred_defs:
                    cred_defs[cred_def_id] = await ledger.get_credential_definition(
                        cred_def_id
                    )
                if credential.get("rev_reg_id"):
                    revocation_registry_id = credential["rev_reg_id"]
                    if revocation_registry_id not in revocation_registries:
                        revocation_registries[
                            revocation_registry_id
                        ] = RevocationRegistry.from_definition(
                            await ledger.get_revoc_reg_def(revocation_registry_id), True
                        )
        # Get delta with non-revocation interval defined in "non_revoked"
        # of the presentation request or attributes
        epoch_now = int(time.time())
        revoc_reg_deltas = {}
        for precis in requested_referents.values():  # cred_id, non-revoc interval
            credential_id = precis["cred_id"]
            if not credentials[credential_id].get("rev_reg_id"):
                continue
            if "timestamp" in precis:
                continue
            rev_reg_id = credentials[credential_id]["rev_reg_id"]
            multitenant_mgr = self._profile.inject_or(BaseMultitenantManager)
            if multitenant_mgr:
                ledger_exec_inst = IndyLedgerRequestsExecutor(self._profile)
            else:
                ledger_exec_inst = self._profile.inject(IndyLedgerRequestsExecutor)
            ledger = (
                await ledger_exec_inst.get_ledger_for_identifier(
                    rev_reg_id,
                    txn_record_type=GET_REVOC_REG_DELTA,
                )
            )[1]
            async with ledger:
                reft_non_revoc_interval = precis.get("non_revoked")
                if reft_non_revoc_interval:
                    key = (
                        f"{rev_reg_id}_"
                        f"{reft_non_revoc_interval.get('from', 0)}_"
                        f"{reft_non_revoc_interval.get('to', epoch_now)}"
                    )
                    if key not in revoc_reg_deltas:
                        (delta, delta_timestamp) = await ledger.get_revoc_reg_delta(
                            rev_reg_id,
                            reft_non_revoc_interval.get("from", 0),
                            reft_non_revoc_interval.get("to", epoch_now),
                        )
                        revoc_reg_deltas[key] = (
                            rev_reg_id,
                            credential_id,
                            delta,
                            delta_timestamp,
                        )
                    for stamp_me in requested_referents.values():
                        # often one cred satisfies many requested attrs/preds
                        if stamp_me["cred_id"] == credential_id:
                            stamp_me["timestamp"] = revoc_reg_deltas[key][3]
        # Get revocation states to prove non-revoked
        revocation_states = {}
        for (
            rev_reg_id,
            credential_id,
            delta,
            delta_timestamp,
        ) in revoc_reg_deltas.values():
            if rev_reg_id not in revocation_states:
                revocation_states[rev_reg_id] = {}
            rev_reg = revocation_registries[rev_reg_id]
            tails_local_path = await rev_reg.get_or_fetch_local_tails_path()
            try:
                revocation_states[rev_reg_id][delta_timestamp] = json.loads(
                    await holder.create_revocation_state(
                        credentials[credential_id]["cred_rev_id"],
                        rev_reg.reg_def,
                        delta,
                        delta_timestamp,
                        tails_local_path,
                    )
                )
            except IndyHolderError as e:
                LOGGER.error(
                    f"Failed to create revocation state: {e.error_code}, {e.message}"
                )
                raise e
        for (referent, precis) in requested_referents.items():
            if "timestamp" not in precis:
                continue
            if referent in requested_credentials["requested_attributes"]:
                requested_credentials["requested_attributes"][referent][
                    "timestamp"
                ] = precis["timestamp"]
            if referent in requested_credentials["requested_predicates"]:
                requested_credentials["requested_predicates"][referent][
                    "timestamp"
                ] = precis["timestamp"]
        indy_proof_json = await holder.create_presentation(
            proof_request,
            requested_credentials,
            schemas,
            cred_defs,
            revocation_states,
        )
        indy_proof = json.loads(indy_proof_json)
        return indy_proof