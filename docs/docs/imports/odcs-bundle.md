---
sidebar_position: 22
title: "Import: ODCS Bundle"
description: "Assemble one data contract from a base ODCS file and separate schema files."
---

# <img className="page-icon" src="/img/icons/odcs.svg" alt="" /> Import: ODCS Bundle

Assembles one [ODCS](../open-data-contract-standard.md) data contract from a base file and separate schema files, so a contract with many schemas can be maintained as one small file per schema.

The base file is an ODCS contract with everything but the schemas: `id`, `name`, `version`, `team`, `servers`, `slaLevels`, and so on. Its `schema` list can reference schema files with `$ref`:

```yaml
# base.odcs.yaml
apiVersion: v3.1.0
kind: DataContract
id: orders-contract
name: Orders
version: 1.0.0
status: active
schema:
  - $ref: schemas/*.yaml        # every schema file in schemas/
  - $ref: shared/customers.yaml # or a single file
  - name: audit_log             # inline schemas still work
    properties:
      - name: event_id
        logicalType: string
```

Each schema file holds one schema object:

```yaml
# schemas/orders.yaml
name: orders
physicalType: table
properties:
  - name: order_id
    logicalType: string
    primaryKey: true
  - name: order_total
    logicalType: integer
```

Run:

```bash
datacontract import odcs-bundle --source base.odcs.yaml --output datacontract.yaml
```

to write the complete contract, with each `$ref` replaced by the schemas of the files it matches.

Instead of references, `--schemas` appends the schemas of every `.yaml` and `.yml` file in a directory, after those listed in the base file:

```bash
datacontract import odcs-bundle --source base.odcs.yaml --schemas schemas/ --output datacontract.yaml
```

## Rules

- A `$ref` is a glob, relative to the base file; `**` matches nested directories. Files are taken in alphabetical order, and a `$ref` that matches no file fails the import.
- A schema file holds one schema object, a list of them, or a `schema:` list like a contract.
- Each schema name may occur once across the base file and all schema files.
- The assembled contract is validated as ODCS v3, like [`import odcs`](./odcs.md).
- The base file and the schema files are read from the local file system.

All options: **[`datacontract import odcs-bundle`](../commands/import/odcs-bundle.md)**.
