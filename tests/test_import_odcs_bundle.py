import pytest
from typer.testing import CliRunner

from datacontract.cli import app
from datacontract.data_contract import DataContract
from datacontract.model.exceptions import DataContractException

BASE = "./fixtures/odcs_bundle/base.odcs.yaml"


def test_cli():
    result = CliRunner().invoke(app, ["import", "odcs-bundle", "--source", BASE])
    assert result.exit_code == 0
    assert "name: orders" in result.stdout


def test_ref_glob_replaced_by_the_schemas_of_the_matching_files_in_file_order():
    result = DataContract.import_from_source("odcs-bundle", BASE)

    assert result.id == "orders-contract"
    assert result.team.name == "checkout"
    assert [schema.name for schema in result.schema_] == ["customers", "addresses", "orders"]
    assert [p.name for p in result.schema_[2].properties] == ["order_id", "order_total"]


def test_inline_schemas_keep_their_place_next_to_references():
    result = DataContract.import_from_source("odcs-bundle", "./fixtures/odcs_bundle/base-inline.odcs.yaml")

    assert [schema.name for schema in result.schema_] == ["audit_log", "orders"]


def test_schemas_directory_is_appended(tmp_path):
    base = tmp_path / "base.yaml"
    base.write_text("apiVersion: v3.1.0\nkind: DataContract\nid: c\nversion: 1.0.0\nstatus: active\n")
    (tmp_path / "schemas").mkdir()
    (tmp_path / "schemas" / "b.yml").write_text("name: b\n")
    (tmp_path / "schemas" / "a.yaml").write_text("schema:\n  - name: a\n")
    (tmp_path / "schemas" / "notes.txt").write_text("not a schema")

    result = DataContract.import_from_source("odcs-bundle", str(base), schemas=str(tmp_path / "schemas"))

    assert [schema.name for schema in result.schema_] == ["a", "b"]


def test_reference_without_matching_files_fails(tmp_path):
    base = tmp_path / "base.yaml"
    base.write_text(
        "apiVersion: v3.1.0\nkind: DataContract\nid: c\nversion: 1.0.0\nstatus: active\n"
        "schema:\n  - $ref: missing/*.yaml\n"
    )

    with pytest.raises(DataContractException, match="missing/\\*.yaml"):
        DataContract.import_from_source("odcs-bundle", str(base))


def test_duplicate_schema_names_fail():
    with pytest.raises(DataContractException, match="orders"):
        DataContract.import_from_source("odcs-bundle", BASE, schemas="./fixtures/odcs_bundle/schemas")


def test_base_file_that_is_not_a_data_contract_fails(tmp_path):
    base = tmp_path / "base.yaml"
    base.write_text("kind: DataProduct\n")

    with pytest.raises(DataContractException, match="kind: DataContract"):
        DataContract.import_from_source("odcs-bundle", str(base))
