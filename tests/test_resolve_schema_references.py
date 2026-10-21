"""Tests for `$ref` entries in a contract's top-level `schema` list.

A contract can keep each schema in its own file: an entry `$ref: <file or glob>` is
replaced by the schema objects in the matching files when the contract is loaded,
so every command (lint, test, export, changelog, ...) sees the assembled contract.
"""

from pathlib import Path
from textwrap import dedent

import pytest
import responses
import yaml
from typer.testing import CliRunner

from datacontract.cli import app
from datacontract.data_contract import DataContract
from datacontract.lint.resolve import resolve_data_contract, resolve_data_contract_dict
from datacontract.model.exceptions import DataContractException
from datacontract.model.run import ResultEnum

HEADER = """
apiVersion: v3.1.0
kind: DataContract
id: orders-contract
version: 1.0.0
status: active
"""


def _write(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(body).lstrip())
    return path


def _contract(directory: Path, schema: str) -> Path:
    return _write(directory / "datacontract.odcs.yaml", HEADER + "schema:\n" + dedent(schema))


@pytest.fixture
def split_contract(tmp_path) -> Path:
    _write(tmp_path / "schemas" / "orders.yaml", "name: orders\nproperties:\n  - name: order_id\n")
    _write(tmp_path / "schemas" / "crm" / "customers.yaml", "- name: customers\n- name: addresses\n")
    return _contract(
        tmp_path,
        """
        - $ref: schemas/**/*.yaml
        - name: audit_log
        """,
    )


def test_references_are_replaced_by_the_schemas_of_the_matching_files_in_path_order(split_contract):
    contract = resolve_data_contract(str(split_contract))

    assert [schema.name for schema in contract.schema_] == ["customers", "addresses", "orders", "audit_log"]
    assert contract.schema_[2].properties[0].name == "order_id"


def test_export_odcs_writes_the_assembled_contract(split_contract):
    result = CliRunner().invoke(app, ["export", "odcs", str(split_contract)])

    assert result.exit_code == 0
    assert [schema["name"] for schema in yaml.safe_load(result.stdout)["schema"]] == [
        "customers",
        "addresses",
        "orders",
        "audit_log",
    ]


def test_import_odcs_assembles_the_contract(split_contract):
    contract = DataContract.import_from_source("odcs", str(split_contract))

    assert [schema.name for schema in contract.schema_] == ["customers", "addresses", "orders", "audit_log"]


def test_the_contract_as_a_dict_is_assembled(split_contract):
    contract = resolve_data_contract_dict(str(split_contract))

    assert [schema["name"] for schema in contract["schema"]] == ["customers", "addresses", "orders", "audit_log"]


def test_lint_validates_the_schemas_from_the_referenced_files(tmp_path):
    _write(tmp_path / "orders.yaml", "name: orders\nproperties:\n  - name: order_id\n    logicalType: strin\n")

    run = DataContract(data_contract_file=str(_contract(tmp_path, "- $ref: orders.yaml\n"))).lint()

    assert run.result == ResultEnum.failed
    assert "schema.orders.properties.order_id.logicalType: 'strin' is not one of" in run.checks[0].reason


def test_lint_warns_that_schema_references_are_not_odcs(split_contract):
    run = DataContract(data_contract_file=str(split_contract)).lint()

    assert run.result == ResultEnum.warning
    assert any(
        check.result == ResultEnum.warning and "datacontract-cli extension" in check.reason for check in run.checks
    )


def test_a_file_name_with_glob_characters_can_be_referenced(tmp_path):
    _write(tmp_path / "schemas [v1]" / "orders.yaml", "name: orders\n")

    contract = resolve_data_contract(str(_contract(tmp_path, "- $ref: 'schemas [v1]/orders.yaml'\n")))

    assert [schema.name for schema in contract.schema_] == ["orders"]


def test_a_glob_never_matches_the_contract_itself(tmp_path):
    _write(tmp_path / "orders.yaml", "name: orders\n")

    contract = resolve_data_contract(str(_contract(tmp_path, "- $ref: '*.yaml'\n")))

    assert [schema.name for schema in contract.schema_] == ["orders"]


def test_a_schema_defined_more_than_once_fails(tmp_path):
    _write(tmp_path / "schemas" / "orders.yaml", "name: orders\n")

    with pytest.raises(DataContractException, match="These schemas are defined more than once: orders"):
        resolve_data_contract(str(_contract(tmp_path, "- $ref: schemas/orders.yaml\n- $ref: schemas/*.yaml\n")))


def test_a_definition_file_link_stays_relative_to_the_schema_file_that_holds_it(tmp_path):
    _write(tmp_path / "schemas" / "definitions" / "order_id.yaml", "description: The order id\n")
    _write(
        tmp_path / "schemas" / "orders.yaml",
        """
        name: orders
        properties:
          - name: order_id
            authoritativeDefinitions:
              - type: businessDefinition
                url: definitions/order_id.yaml
        """,
    )

    contract = resolve_data_contract(str(_contract(tmp_path, "- $ref: schemas/orders.yaml\n")), inline_references=True)

    assert contract.schema_[0].properties[0].description == "The order id"


def test_a_definition_link_shared_through_a_yaml_alias_is_rewritten_once(tmp_path):
    _write(tmp_path / "schemas" / "definitions" / "id.yaml", "description: An id\n")
    _write(
        tmp_path / "schemas" / "orders.yaml",
        """
        name: orders
        properties:
          - name: order_id
            authoritativeDefinitions: &id
              - type: businessDefinition
                url: definitions/id.yaml
          - name: customer_id
            authoritativeDefinitions: *id
        """,
    )

    contract = resolve_data_contract(str(_contract(tmp_path, "- $ref: schemas/orders.yaml\n")), inline_references=True)

    assert [prop.description for prop in contract.schema_[0].properties] == ["An id", "An id"]


def test_a_link_with_a_scheme_is_kept(tmp_path):
    _write(
        tmp_path / "schemas" / "orders.yaml",
        """
        name: orders
        authoritativeDefinitions:
          - type: canonicalUrl
            url: "urn:example:orders#v1"
        """,
    )

    contract = resolve_data_contract(str(_contract(tmp_path, "- $ref: schemas/orders.yaml\n")))

    assert contract.schema_[0].authoritativeDefinitions[0].url == "urn:example:orders#v1"


def test_duplicate_inline_schemas_are_left_to_lint(tmp_path):
    _write(tmp_path / "customers.yaml", "name: customers\n")
    schema = (
        "- name: orders\n  physicalName: orders_eu\n- name: orders\n  physicalName: orders_us\n- $ref: customers.yaml\n"
    )

    contract = resolve_data_contract(str(_contract(tmp_path, schema)))

    assert [schema.name for schema in contract.schema_] == ["orders", "orders", "customers"]


def test_a_reference_with_a_fragment_fails(tmp_path):
    _write(tmp_path / "orders.yaml", "name: orders\n")

    with pytest.raises(DataContractException, match="without a `#` fragment"):
        resolve_data_contract(str(_contract(tmp_path, "- $ref: orders.yaml#/0\n")))


def test_a_reference_without_a_matching_file_fails(tmp_path):
    with pytest.raises(DataContractException, match="'missing/\\*.yaml': no file matches it"):
        resolve_data_contract(str(_contract(tmp_path, "- $ref: missing/*.yaml\n")))


def test_a_referenced_file_cannot_reference_further_files(tmp_path):
    _write(tmp_path / "index.yaml", "- $ref: orders.yaml\n")
    _write(tmp_path / "orders.yaml", "name: orders\n")

    with pytest.raises(DataContractException, match="index.yaml' must hold a schema object or a list of them"):
        resolve_data_contract(str(_contract(tmp_path, "- $ref: index.yaml\n")))


def test_a_reference_entry_with_other_fields_fails(tmp_path):
    _write(tmp_path / "orders.yaml", "name: orders\n")

    with pytest.raises(DataContractException, match="holds `\\$ref: <file or glob>` and nothing else"):
        resolve_data_contract(str(_contract(tmp_path, "- $ref: orders.yaml\n  physicalName: orders_v2\n")))


def test_a_contract_without_a_file_location_cannot_resolve_references():
    contract_str = HEADER + "schema:\n  - $ref: orders.yaml\n"

    run = DataContract(data_contract_str=contract_str).lint()

    assert run.result == ResultEnum.failed
    assert "pass the contract as a local file" in run.checks[0].reason


@responses.activate
def test_a_contract_read_from_a_url_cannot_resolve_references():
    responses.add(responses.GET, "https://example.com/datacontract.yaml", body=HEADER + "schema:\n  - $ref: o.yaml\n")

    with pytest.raises(DataContractException, match="pass the contract as a local file"):
        resolve_data_contract("https://example.com/datacontract.yaml")


def test_a_split_contract_can_be_the_target_of_a_definition_reference(tmp_path):
    _write(tmp_path / "business" / "artists.yaml", "name: artists\nproperties:\n  - name: name\n    description: X\n")
    _contract(tmp_path / "business", "- $ref: artists.yaml\n")
    technical = _contract(
        tmp_path,
        """
        - name: t
          properties:
            - name: artist
              authoritativeDefinitions:
                - type: businessDefinition
                  url: business/datacontract.odcs.yaml#schema/artists/properties/name
        """,
    )

    contract = resolve_data_contract(str(technical), inline_references=True)

    assert contract.schema_[0].properties[0].description == "X"
