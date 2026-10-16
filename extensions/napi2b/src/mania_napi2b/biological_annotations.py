"""Canonical regions and explicit, complete Dataset system site annotations."""

from dataclasses import asdict, dataclass

from mania_napi2b.canonical_reference import CanonicalResidueReference
from mania_napi2b.canonical_reference_io import load_default_napi2b_canonical_reference

NAPI2B_ECD_START = 234
NAPI2B_ECD_END = 361
NAPI2B_MX35_START = 311
NAPI2B_MX35_END = 341


class BiologicalAnnotationError(ValueError):
    """Invalid canonical biological annotation or incomplete system metadata."""


def _residue(number: int, name: str | None = None) -> CanonicalResidueReference:
    try:
        residue = load_default_napi2b_canonical_reference().residue_at(number)
        if name is not None and (
            type(name) is not str or name != residue.canonical_resname
        ):
            raise ValueError("Canonical resname must match the pinned reference")
        return residue
    except (ValueError, TypeError):
        raise BiologicalAnnotationError(
            "Canonical residue must match the pinned reference."
        ) from None


def _text(value: object, name: str) -> None:
    if type(value) is not str or not value or value != value.strip():
        raise BiologicalAnnotationError(f"{name} must be a non-empty stripped string")


def _bool(value: object, name: str) -> None:
    if type(value) is not bool:
        raise BiologicalAnnotationError(f"{name} must be an exact bool")


def is_napi2b_ecd_residue(canonical_residue_number: int) -> bool:
    _residue(canonical_residue_number)
    return NAPI2B_ECD_START <= canonical_residue_number <= NAPI2B_ECD_END


def is_napi2b_mx35_residue(canonical_residue_number: int) -> bool:
    _residue(canonical_residue_number)
    return NAPI2B_MX35_START <= canonical_residue_number <= NAPI2B_MX35_END


@dataclass(frozen=True)
class GlycosylationSiteAnnotation:
    canonical_residue_number: int
    canonical_resname: str
    present_in_topology: bool
    glycan_name: str
    source: str
    verifier: str

    def __post_init__(self) -> None:
        _text(self.canonical_resname, "canonical_resname")
        _residue(self.canonical_residue_number, self.canonical_resname)
        _bool(self.present_in_topology, "present_in_topology")
        for name in ("glycan_name", "source", "verifier"):
            _text(getattr(self, name), name)


@dataclass(frozen=True)
class CanonicalVariantSiteAnnotation:
    """An explicitly supplied site; no bond-pair semantics are implied."""

    canonical_residue_number: int
    canonical_resname: str
    source: str
    verifier: str

    def __post_init__(self) -> None:
        _text(self.canonical_resname, "canonical_resname")
        _residue(self.canonical_residue_number, self.canonical_resname)
        _text(self.source, "source")
        _text(self.verifier, "verifier")


@dataclass(frozen=True)
class CanonicalResidueBiologicalAnnotation:
    """Flags with complete system evidence; absence from site lists means false."""

    canonical_residue_number: int
    canonical_resname: str
    is_ecd: bool
    is_mx35_region: bool
    is_glycosylation_site: bool
    glycosylation_present_in_topology: bool | None
    glycan_name: str | None
    glycosylation_source: str | None
    glycosylation_verifier: str | None
    is_disulfide_variant_site: bool
    is_cysteine_variant_site: bool

    def __post_init__(self) -> None:
        _text(self.canonical_resname, "canonical_resname")
        _residue(self.canonical_residue_number, self.canonical_resname)
        for name in (
            "is_ecd",
            "is_mx35_region",
            "is_glycosylation_site",
            "is_disulfide_variant_site",
            "is_cysteine_variant_site",
        ):
            _bool(getattr(self, name), name)
        if self.is_ecd != is_napi2b_ecd_residue(
            self.canonical_residue_number
        ) or self.is_mx35_region != is_napi2b_mx35_residue(
            self.canonical_residue_number
        ):
            raise BiologicalAnnotationError("Region flags must match canonical ranges")
        details = (
            "glycosylation_present_in_topology",
            "glycan_name",
            "glycosylation_source",
            "glycosylation_verifier",
        )
        if self.is_glycosylation_site:
            _bool(self.glycosylation_present_in_topology, details[0])
            for name in details[1:]:
                _text(getattr(self, name), name)
        elif any(getattr(self, name) is not None for name in details):
            raise BiologicalAnnotationError(
                "Non-site glycosylation details must be None"
            )


@dataclass(frozen=True)
class DatasetSystemBiologicalAnnotations:
    dataset_id: str
    system_id: str
    annotation_scope: str
    glycosylation_sites: tuple[GlycosylationSiteAnnotation, ...]
    disulfide_variant_sites: tuple[CanonicalVariantSiteAnnotation, ...]
    cysteine_variant_sites: tuple[CanonicalVariantSiteAnnotation, ...]

    def __post_init__(self) -> None:
        _text(self.dataset_id, "dataset_id")
        _text(self.system_id, "system_id")
        if type(self.annotation_scope) is not str or (
            self.annotation_scope != "complete_for_system"
        ):
            raise BiologicalAnnotationError(
                "annotation_scope must be complete_for_system"
            )
        for name, model in (
            ("glycosylation_sites", GlycosylationSiteAnnotation),
            ("disulfide_variant_sites", CanonicalVariantSiteAnnotation),
            ("cysteine_variant_sites", CanonicalVariantSiteAnnotation),
        ):
            sites = getattr(self, name)
            if type(sites) is not tuple or any(
                type(site) is not model for site in sites
            ):
                raise BiologicalAnnotationError(
                    f"{name} must be a tuple of exact sites"
                )
            for site in sites:
                site.__post_init__()
            numbers = [site.canonical_residue_number for site in sites]
            if len(set(numbers)) != len(numbers):
                raise BiologicalAnnotationError(f"{name} site numbers must be unique")
            if numbers != sorted(numbers):
                raise BiologicalAnnotationError(f"{name} must follow canonical order")

    def to_dict(self) -> dict[str, object]:
        return {
            "dataset_id": self.dataset_id,
            "system_id": self.system_id,
            "annotation_scope": self.annotation_scope,
            "glycosylation_sites": [asdict(site) for site in self.glycosylation_sites],
            "disulfide_variant_sites": [
                asdict(site) for site in self.disulfide_variant_sites
            ],
            "cysteine_variant_sites": [
                asdict(site) for site in self.cysteine_variant_sites
            ],
        }

    def annotation_for_residue(
        self, canonical_residue_number: int
    ) -> CanonicalResidueBiologicalAnnotation:
        self.__post_init__()
        residue = _residue(canonical_residue_number)
        glyco = next(
            (
                site
                for site in self.glycosylation_sites
                if site.canonical_residue_number == canonical_residue_number
            ),
            None,
        )
        return CanonicalResidueBiologicalAnnotation(
            canonical_residue_number,
            residue.canonical_resname,
            is_napi2b_ecd_residue(canonical_residue_number),
            is_napi2b_mx35_residue(canonical_residue_number),
            glyco is not None,
            glyco.present_in_topology if glyco else None,
            glyco.glycan_name if glyco else None,
            glyco.source if glyco else None,
            glyco.verifier if glyco else None,
            any(
                site.canonical_residue_number == canonical_residue_number
                for site in self.disulfide_variant_sites
            ),
            any(
                site.canonical_residue_number == canonical_residue_number
                for site in self.cysteine_variant_sites
            ),
        )
