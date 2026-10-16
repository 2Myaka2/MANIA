"""Strict supplied generic decision IO; FAIL and pending REVIEW stay distinct."""

from pathlib import Path

from mania._dataset_qc_json import model_bytes, read_model, write_model
from mania.dataset_qc_contract import QCDecisions


def read_dataset_qc_decision_set(path: Path, *, root: Path) -> QCDecisions:
    return read_model(path, QCDecisions, root=root)


dataset_qc_decision_set_bytes = model_bytes
write_dataset_qc_decision_set = write_model
