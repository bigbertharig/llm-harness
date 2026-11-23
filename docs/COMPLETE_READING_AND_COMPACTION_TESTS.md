# Complete reading and long-context compaction tests

## Two read contracts

`workspace_read` exposes two deliberately different operations.

- A **targeted read** searches for relevant text and reads bounded line ranges with
  `read_workspace_file`. It is the normal choice for code review and focused questions.
- A **complete read** starts `read_workspace_document_chunk` at character cursor `0`, then follows
  each returned `next_cursor` with the same `snapshot_sha256` until `complete=true`. The execution
  receipt, not the model's prose, decides whether the document was completely covered.

The complete-read cursor is a decoded Unicode character offset. `total_bytes` and
`total_characters` are both reported so callers do not confuse byte and character limits. A changed
file fails its snapshot check. A nonzero cursor without the snapshot hash fails immediately.

The current delegated agent remains bounded to six model steps, twelve tool calls, 32 KB per tool
result, and 160 KB total tool evidence. Therefore this primitive proves full coverage only when the
document fits those limits. It must not be described as an unlimited-document reader.

For the current driver, one model request at cursor zero is sufficient. Harness follows each returned
cursor without another model decision, pins the first snapshot digest, journals all chunks, and gives
the model the normalized evidence once. Larger-than-budget documents still require the durable
map/reduce driver described below; increasing a prompt or MCP line limit is not a substitute.

## Large-document driver

Documents larger than the usable model context need a harness-owned driver rather than a prompt
that tells the model to keep reading. That driver should:

1. Pin the file path, byte size, character count, and SHA-256 snapshot.
2. Advance one deterministic cursor at a time with no model-selected gaps.
3. Produce bounded structured notes for every chunk, linked to its exact character range and hash.
4. Validate that the chunk manifest covers `[0, total_characters)` contiguously.
5. Reduce the notes in a tree, retaining child range manifests at every level.
6. Permit final synthesis only after the root manifest proves complete coverage.

Raw chunks and intermediate notes should be durable artifacts so a failed run resumes from the last
verified cursor. Targeted lookup and complete reading must remain separate modes: targeted lookup is
allowed to omit irrelevant text; complete reading is not.

## 250K compaction campaign

The long-context test should use a route actually served with a 262,144-token context window. Use
the route tokenizer when available; otherwise record the conservative estimator and its uncertainty.
Do not call an estimated character count an actual token count.

Each test document should contain deterministic probes distributed across the context:

- immutable early facts;
- corrected facts whose superseded values must be rejected;
- exact strings and checksums;
- relationships and ordering constraints;
- standing operating rules that must survive every compaction.

The main retention lane is blind: do not quiz the model between compactions, because restating facts
would refresh them. Run independent 3-, 5-, and 10-compaction trials, or fork an identical prepared
state before final evaluation. Keep a no-tools memory lane separate from any external-memory lane.

### Staged execution

1. Run a scaled mechanics test to validate token filling, event capture, and scoring.
2. Run a true-boundary three-compaction gate at the route's real context size.
3. If that passes, run five compactions as an endurance gate.
4. Run ten compactions overnight only after the earlier gates are reliable. Ten 250K-boundary cycles
   process roughly 2.5 million input tokens before output and retry overhead.

Include a cold harness or process restart after a saved milestone to test persisted state rather than
only live process memory. Compare native/default compaction policy with a separately labeled tuned
policy; never combine their results.

### Required event and result receipt

For every attempted compaction, record:

- route, resolved model, advertised and effective context limits;
- tokenizer identity or estimator method;
- target tokens, measured input tokens, cached tokens, and output tokens;
- compaction start, durable summary creation, error-free completion, and elapsed time;
- summary token and byte counts plus growth between cycles;
- client timeout separately from a server operation that continued;
- probe answers, expected answers, superseded-value rejections, and exact-match scores;
- process-restart point and whether the final answer used tools or external memory.

A compaction counts only when start, persisted summary, and successful end are all observed. Failed
attempts stay in the receipt. A milestone passes only if its required number of completed compactions
and all critical standing constraints survive. The 3/5/10 results should be reported independently so
a late endurance failure does not erase evidence from the shorter gates.
