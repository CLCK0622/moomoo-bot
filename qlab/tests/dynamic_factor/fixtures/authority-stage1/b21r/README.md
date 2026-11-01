These are read-only, historical test inputs. They cannot be selected by a
production request and do not authorize an installation or certify complete N.

Source: B21R independent review attachment
`01a1997b-210b-7e90-a494-d08288e15180`, SHA-256
`618a5da7bdf57e16c37574011ae2fd9a5f2efc9777e27ea32b5e54f42426aaec`.
The original ruling archive is its nested `EVO883-T1-and-N03-review-v1.zip`.

- `v24.jsonl.gz` decompresses to the exact ruling v24 archive; `v24.tip.json`
  and `v4.tip.json` retain their original bytes.
- `seq1148.jsonl.gz` and `seq1148.tip.json` retain the exact bytes of
  `results/t1-original-39locked/original-truncated-1148-matching-witness.*`.
  The prefix ends at sequence 1148 / N756 and its witness matches locally.
  Both interpreters' independent review outputs contained identical bytes.
- `manifest.json` records both stored and original hashes. Compression only
  reduces repository size; the tests hash and consume the decompressed bytes.

For the private N03 installation positive control only, a separate in-memory
witness copy names the schema-required project v2 basename. No archive or
original witness is rewritten. T1-05 consumes the unmodified prefix/witness.
