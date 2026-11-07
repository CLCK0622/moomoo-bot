B25R F-LEGACY-01 regression data from independent review archive
7278189bfc06be221317611073f601a55dac31a7b28e6c3048d76cab4f7b149b.

frozen-origin-inputs.json is the original 34-actor synthetic input, byte-identical
in the reviewer's Python 3.9.6 and 3.12.13 main runs. SHA256:
9d3d7c3d6b0271fcb1800129334c73bf024009225cbb449d6d4380b38465d612.
independent_old_receipts.py.fixture is the original reviewer script, unchanged.
Always supply the frozen input as its third argument and pass
--expect-legacy-compatible; never select its input-generation branch.

The host test verifies identities, materializes the script outside the checkout,
and asserts its actual subprocess exit code, 306 calls, 238 accepted calls,
34 reader calls and unchanged original R2/missing-consumer rejection points.
These are offline synthetic mechanism inputs, not real source/permission,
account, reference-performance or runtime-authorization evidence.
