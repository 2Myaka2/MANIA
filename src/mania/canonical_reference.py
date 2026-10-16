"""Explicit chain-aware references; no default protein or inferred chemistry."""

import json
from collections.abc import Mapping
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    StringConstraints,
    model_validator,
)

Text = Annotated[str, StringConstraints(min_length=1, pattern=r"^\S(?:.*\S)?$")]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Position = Annotated[int, Field(ge=1)]


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, revalidate_instances="always"
    )

    def to_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")


class InputIdentity(_StrictModel):
    project: Text
    system_id: Text
    trajectory_id: Text
    replica_id: Text
    engine: Literal["gromacs", "namd"]
    condition: Text | None
    variant_id: Text | None
    disulfide_state: Text | None


class AuthorityBinding(_StrictModel):
    role: Text
    path: Text
    sha256: Digest
    source_identity: InputIdentity | None

    @model_validator(mode="after")
    def _portable(self) -> Self:
        path = PurePosixPath(self.path)
        if path.is_absolute() or ".." in path.parts or "\\" in self.path:
            raise ValueError("Authority path must be portable")
        return self


class ChainIdentity(_StrictModel):
    chain_id: Text
    sequence: Annotated[
        str, StringConstraints(min_length=1, pattern=r"^[ARNDCQEGHILKMFPSTWYV]+$")
    ]
    sequence_sha256: Digest

    @model_validator(mode="after")
    def _sequence_digest(self) -> Self:
        if sha256(self.sequence.encode("ascii")).hexdigest() != self.sequence_sha256:
            raise ValueError("Sequence digest mismatch")
        return self


class ReferenceIdentity(_StrictModel):
    reference_id: Text
    reference_sha256: Digest
    chains: tuple[ChainIdentity, ...]

    @model_validator(mode="after")
    def _chain_roster(self) -> Self:
        ids = [chain.chain_id for chain in self.chains]
        if not ids or len(set(ids)) != len(ids):
            raise ValueError("Reference requires unique ordered chains")
        return self


class ReferenceResidueKey(_StrictModel):
    reference_chain_id: Text
    reference_position: Position


class _ReferenceResidue(ReferenceResidueKey):
    one_letter_code: Annotated[
        str, StringConstraints(pattern=r"^[ARNDCQEGHILKMFPSTWYV]$")
    ]
    resname: Text


class _EmptyParameters(_StrictModel):
    pass


class ProteinReference(_StrictModel):
    """Validate the full ordered chemistry roster and its supplied content digest.

    The digest checks declared content, not biological authenticity or authority.
    Identity-only bindings and unchecked model_construct objects are not evidence
    of a verified full reference. Validated references are immutable and reusable.
    """

    _roster_verified: bool = PrivateAttr(default=False)

    schema_version: Literal["mania.reference.v1"]
    kind: Literal["mania_reference"]
    identity: InputIdentity | None
    reference: ReferenceIdentity
    parameters: _EmptyParameters
    records: tuple[_ReferenceResidue, ...]
    authority: tuple[AuthorityBinding, ...]

    @model_validator(mode="after")
    def _roster(self) -> Self:
        expected = [
            (chain.chain_id, position, letter)
            for chain in self.reference.chains
            for position, letter in enumerate(chain.sequence, 1)
        ]
        actual = [
            (row.reference_chain_id, row.reference_position, row.one_letter_code)
            for row in self.records
        ]
        if actual != expected:
            raise ValueError("Ordered reference roster must match explicit sequences")
        residues_by_chain: dict[str, list[dict[str, object]]] = {
            chain.chain_id: [] for chain in self.reference.chains
        }
        for row in self.records:
            residues_by_chain[row.reference_chain_id].append(
                {
                    "reference_position": row.reference_position,
                    "one_letter_code": row.one_letter_code,
                    "resname": row.resname,
                }
            )
        payload = {
            "chains": [
                {
                    "chain_id": chain.chain_id,
                    "sequence": chain.sequence,
                    "residues": residues_by_chain[chain.chain_id],
                }
                for chain in self.reference.chains
            ]
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
        digest = sha256(b"mania.reference-roster.sha256.v1\n" + encoded).hexdigest()
        if digest != self.reference.reference_sha256:
            raise ValueError("Reference roster digest mismatch")
        self._roster_verified = True
        return self

    def model_copy(
        self, *, update: Mapping[str, Any] | None = None, deep: bool = False
    ) -> Self:
        # Pydantic's default update path skips validation even for frozen models.
        copied = super().model_copy(update=update, deep=deep)
        return type(self).model_validate(copied.model_dump())

    def _require_verified(self) -> None:
        if not self._roster_verified:
            raise ValueError("A validated full reference roster is required")

    @classmethod
    def model_construct(
        cls, _fields_set: set[str] | None = None, **values: Any
    ) -> Self:
        # This explicitly unchecked Pydantic path must never inherit trust,
        # including when private attributes are supplied in its keyword values.
        constructed = super().model_construct(_fields_set=_fields_set, **values)
        constructed._roster_verified = False
        return constructed

    def residue_at(self, key: ReferenceResidueKey) -> _ReferenceResidue:
        self._require_verified()
        if type(key) is not ReferenceResidueKey:
            raise ValueError("An explicit reference residue key is required")
        for row in self.records:
            if (row.reference_chain_id, row.reference_position) == (
                key.reference_chain_id,
                key.reference_position,
            ):
                return row
        raise ValueError("Residue is outside the supplied reference roster")


def __getattr__(name: str) -> object:
    if name in (
        "CanonicalProteinReference",
        "CanonicalResidueReference",
        "NAPI2B_CANONICAL_ISOFORM_ID",
        "NAPI2B_CANONICAL_REFERENCE_KIND",
        "NAPI2B_CANONICAL_REFERENCE_SCHEMA_VERSION",
        "NAPI2B_CANONICAL_SEQUENCE_LENGTH",
        "NAPI2B_CANONICAL_SEQUENCE_SHA256",
        "NAPI2B_GENE_SYMBOL",
        "NAPI2B_UNIPROT_ACCESSION",
        "NAPI2B_UNIPROT_ENTRY_NAME",
        "NAPI2B_UNIPROT_SEQUENCE_MD5",
        "NAPI2B_UNIPROT_SEQUENCE_VERSION",
        "_PINNED_FIELDS",
        "_RESNAMES",
    ):
        raise ImportError(
            "Fixed NaPi2b API moved to mania_napi2b.canonical_reference; "
            "install mania-napi2b and explicitly select a profile."
        )
    raise AttributeError(name)
