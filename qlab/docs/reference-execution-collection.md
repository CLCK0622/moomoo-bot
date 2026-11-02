## C11 collection boundary

`execution_receipts.collection.collect_execution` wraps the original collector
(`prefreeze.collection`, patch SHA
`048406f36df6a5f3d4b937fc362c06857d1e4c59deef6b0b48bd40e6469fb2bf`).
The original 15 regression instances remain unchanged. Its old namespace records
provenance; the formal collection has schema `EVO884.ExecutionCollection/v1`.

The host supplies the actual loaded functions and modules, not module names to
import/execute. Current call-site registry for C09/C10 integration:

| Role | Actual object / original evidence interface |
| --- | --- |
| Reference input entry | `reference_producer_v3.prepare` |
| Candidate entry | `pipeline.run_train_pipeline` |
| Definition/profile | `reference_definition_v301.reference_definitions`, `reference_profile_v301.solo_profile` |
| Startup | `execution_startup.StartupBook` methods actually used by the host |
| D1/D2 | Actual shared planner/risk functions from C03/C06 when delivered; missing objects remain gaps |
| Scope/DAG | Existing checked scope file and actual host/worker reading observations, not import graphs |
| Each book's B | Existing proof for each member × fold × attempt, including failed/retried books |

Every entry has actual filename, raw source SHA and line; every existing evidence
file retains raw SHA, length and original document. Every expected book appears,
including missing/unreadable proof with null identity and a reason. Source and
evidence roots must be explicit. No symlinks or paths outside those roots are read.
The collector calls no entry, economic reader, budget, N, installation or writer.

`check_preperformance_collection` compares a fresh collection with the host's
externally retained inventory and rejects changed source/DAG/scope/B or collection
at/after the first performance. A20/A21 here cover collection consistency/time;
the formal C09/C10 receiver must still establish the external registration,
nonauthor review and original source permissions. Self-issued timestamps and
hashes are not proof of those facts. No certification or sealed marker is emitted.
Final S-RESEAL happens after full implementation and nonauthor review.

## G14.P1.2 evidence anchors

The adopted G14 file is included verbatim, SHA
`68200926a94cc672e7f0e47c14cc6473b68920576a7ade1028c07fb5c168334d`.
It is separate from the immutable v3/v3.0.1 freeze. Its qualifications P1.1–P1.5
all remain in force, including stage acceptance, original permissions and L0.

`ForwardAnchors` collects host-observed input visibility/event/decision times,
input and manifest identities, rule/protocol identities, first evaluation ID,
then output identity/production/observation times. Output cannot precede a retained
input. Each completed pair extends a hash-linked sequence; exported data is copied
and existing pairs cannot be replaced through the API. Resume verifies the entire
provided log. Persistence and trusted retention across runs belong to the host;
this in-memory collector does not claim durable tamper resistance.

Offline replay, revisions, result copies, preparatory observations and reused old
samples cannot be collected as new unseen forward evaluations. Previously retained
sample IDs cannot be repeated, nor can a known first evaluation be renamed as new.
Actual provenance and completeness of the retained history require independent
evidence; passing synthetic checks is not a no-lookahead or OOS certification.
No OOS amount, authorization, runtime flag, clock reset or budget mutation is
created. G14 remains UNVERIFIED until original-line acceptance.
