"""Conservative bounds for the existing in-memory Quant import path.

The parsed rows are materialized and fingerprinted before protected storage.
These limits bound that representation; they are not a promise that a parser can
accept every source file up to the separate 20 MiB byte ceiling.
"""

MAX_SOURCE_BYTES = 20 * 1024 * 1024
MAX_DATA_ROWS = 10_000
MAX_VARIABLES = 200
MAX_DATA_CELLS = 100_000
