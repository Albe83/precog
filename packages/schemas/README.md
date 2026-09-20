# precog-schemas

Canonical Pydantic wire models for the Precog Execution API.

This package contains the public request, response and execution-capability DTOs
shared by the API and Python client. It intentionally does not contain engine
internals, TimesFM evaluator types, or the MCP semantic contract.

Most consumers should install `precog-client`, which depends on this package.
`precog-schemas` is published separately so the SDK can remain a normal,
installable Python package without copying the execution contract into the
client.

The schema and client packages use one synchronized Python-package version and
are built and published together.
