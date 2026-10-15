import glob
from pathlib import Path

import yaml
from open_data_contract_standard.model import OpenDataContractStandard

from datacontract.imports.importer import Importer
from datacontract.model.exceptions import DataContractException


class OdcsBundleImporter(Importer):
    def import_source(self, source: str, import_args: dict, config=None) -> OpenDataContractStandard:
        return import_odcs_bundle(source, import_args.get("schemas"))


def import_odcs_bundle(source: str, schemas_dir: str | None = None) -> OpenDataContractStandard:
    """Assemble one ODCS contract from a base file and separate schema files.

    Entries of the base file's `schema` list that are just `$ref: <glob>` are replaced by the
    schemas in the matching files, resolved relative to the base file. With `schemas_dir`,
    the schemas of every YAML file in that directory are appended.
    """
    base_path = Path(source)
    base = _load_yaml(base_path)
    if not isinstance(base, dict) or base.get("kind") != "DataContract":
        _fail(f"The base file {base_path} is not an ODCS data contract with `kind: DataContract`.")

    schemas = []
    for entry in base.get("schema") or []:
        if isinstance(entry, dict) and set(entry) == {"$ref"}:
            pattern = str(base_path.parent / entry["$ref"])
            files = sorted(Path(match) for match in glob.glob(pattern, recursive=True))
            if not files:
                _fail(f"No schema files match the reference '{entry['$ref']}' in {base_path}.")
            schemas += [schema for file in files for schema in _load_schemas(file)]
        else:
            schemas.append(entry)

    if schemas_dir:
        directory = Path(schemas_dir)
        if not directory.is_dir():
            _fail(f"The schemas directory {directory} does not exist.")
        files = sorted(
            file
            for file in directory.iterdir()
            if file.suffix in (".yaml", ".yml") and file.resolve() != base_path.resolve()
        )
        if not files:
            _fail(f"The schemas directory {directory} contains no .yaml or .yml files.")
        schemas += [schema for file in files for schema in _load_schemas(file)]

    names = [schema.get("name") for schema in schemas]
    duplicates = sorted({name for name in names if name is not None and names.count(name) > 1})
    if duplicates:
        _fail(f"These schemas are defined more than once: {', '.join(duplicates)}")

    if schemas or "schema" in base:
        base["schema"] = schemas
    return OpenDataContractStandard.model_validate(base)


def _load_schemas(file: Path) -> list[dict]:
    """A schema file holds one schema object, a list of them, or a `schema:` list like a contract."""
    content = _load_yaml(file)
    if isinstance(content, dict) and "schema" in content:
        content = content["schema"]
    if isinstance(content, dict):
        content = [content]
    if not isinstance(content, list) or not all(isinstance(schema, dict) for schema in content):
        _fail(f"The schema file {file} holds neither a schema object nor a list of them.")
    return content


def _load_yaml(file: Path):
    try:
        return yaml.safe_load(file.read_text(encoding="utf-8"))
    except Exception as e:
        raise DataContractException(
            type="schema",
            name="Import ODCS bundle",
            reason=f"Failed to read {file}",
            engine="datacontract-cli",
            original_exception=e,
        )


def _fail(reason: str):
    raise DataContractException(type="schema", name="Import ODCS bundle", reason=reason, engine="datacontract-cli")
