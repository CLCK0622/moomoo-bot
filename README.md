# moomoo-bot — `qlab` execution layer (branch)

This branch repurposes the repo (per EVO-65) to host **`qlab/`**: the
`quant-strategies` signals wired into a moomoo **OpenD** execution layer,
**paper-trading first**.

➡️ **See [`qlab/README.md`](qlab/README.md)** for everything: layout, run
commands, execution modes, risk controls, OpenD preconditions, and status.

```bash
cd qlab
pip install -r requirements-lock.txt
python -m qlab.run_paper --mode paper --out reports/paper_run   # offline, no OpenD
pytest tests/ -q
```

## About the previous contents

The earlier app (`backend/`, `frontend/`, `ng-backend/`) was cleared from this
branch's working tree per the EVO-65 brief and now lives only in git history —
it remains the **OpenD wiring reference** (its moomoo trade-context usage
informed `qlab/qlab/brokers/moomoo_opend.py`). `main` is untouched.

> ⚠️ **Security note:** the historical tree committed a plaintext trading
> password (`backend/config.py`) and a tracked `.env`. Both are removed from this
> branch head, but **the credentials must be rotated and the history scrubbed**
> (flagged for security review). Never restore them.
