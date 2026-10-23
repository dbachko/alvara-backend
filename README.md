# Alvara legacy metadata backend

This repository preserves and tests the 2022 Alvara on-chain genome and layered-art
behavior. It is a local integration component, **not a production-ready NFT service**.
No chain, contract address, public origin, wallet, deployment, or financial action is
selected by this code.

The tracked artwork contains 35 unique layer files at each of two resolutions, copied
under five category directories. Those 350 PNG files are source layers/resolution
copies, not 350 completed NFTs. Artwork rights, collection scope, supply, metadata
storage, chain choice, contract behavior, prior obligations, and release approval all
remain separate launch blockers.

## Safe defaults

- The server binds to `127.0.0.1:8080` outside the container.
- The public metadata origin defaults to `http://127.0.0.1:8080`.
- The RPC URL defaults to local `http://127.0.0.1:8545`.
- Chain reads are disabled unless an explicit contract address, expected chain ID, and
  approved runtime-code hash are configured. Startup checks all three and verifies the
  contract's public trait-data manifest against the local settings hash, supply, and
  category count.
- There are no historical Rinkeby, ngrok, charity, price, wallet, or deployment
  defaults.

The legacy ABI adapter is the reviewed minimal interface in
`abi/AlvaraStorage.json`. It intentionally exposes only the read methods this backend
needs. A changed contract must regenerate and review this artifact; do not copy a
deployment artifact into the repository without review.

## Local setup

With `uv` installed:

```console
uv sync --all-groups
uv run pytest
uv run ruff check .
```

Starting with no chain configuration is allowed for health checks and returns HTTP 503
for token metadata because live reads are intentionally disabled:

```console
uv run python async_server.py
curl http://127.0.0.1:8080/health
```

To read from a separately approved local or test chain, set all identifying values
explicitly:

```console
export ALVARA_RPC_URL=http://127.0.0.1:8545
export ALVARA_CONTRACT_ADDRESS=0x0000000000000000000000000000000000000001
export ALVARA_EXPECTED_CHAIN_ID=31337
export ALVARA_EXPECTED_RUNTIME_CODE_HASH=0x0000000000000000000000000000000000000000000000000000000000000000
export ALVARA_PUBLIC_BASE_URL=http://127.0.0.1:8080
uv run python async_server.py
```

The address and hash are placeholders. Startup rejects them unless the expected chain
contains that exact runtime bytecode and its trait manifest matches `settings.json`.
Obtain the hash from a separately approved local/test deployment and review it before
configuration. Never place secrets in these variables or commit them.

Additional configuration:

| Variable | Default | Purpose |
| --- | --- | --- |
| `ALVARA_HOST` | `127.0.0.1` | Bind host |
| `ALVARA_PORT` | `8080` | Bind port |
| `ALVARA_SETTINGS_PATH` | `settings.json` | Collection schema and layer manifest |
| `ALVARA_ARTIFACTS_DIR` | `artifacts` | Generated local cache |
| `ALVARA_ABI_PATH` | `abi/AlvaraStorage.json` | Reviewed read-only ABI |
| `ALVARA_EXPECTED_RUNTIME_CODE_HASH` | none | Required approved Keccak-256 deployed-code hash |
| `ALVARA_RPC_TIMEOUT_SECONDS` | `10` | Per-request RPC timeout |
| `ALVARA_RENDER_CONCURRENCY` | `2` | Maximum concurrent two-resolution renders |

## Behavior and boundaries

`GET /token/{id}` reads and validates the historical 41-bit genome, rejects the
contract's missing-token sentinel, rejects out-of-range and excluded traits, and then
generates both the 350px and 3000px images before publishing metadata. Rendering is
bounded and runs outside the event loop. Each immutable three-file generation is
published by one atomic current-manifest swap; state and manifests use durable
same-directory replacement, including token ID 0. Cache roots are content-addressed by
chain/address/code, schema, assets, ABI, renderer version, resolutions, and public URL,
so incompatible configurations cannot silently reuse artifacts.

`GET /image/{id}` and `GET /external/{id}` revalidate the current genome and then stream
the current generated 350px and 3000px PNGs. A confirmed burn atomically tombstones the
active generation, so all three token routes return 404.
`external_url` is retained for compatibility with the prototype even though it points
to an image rather than a project web page; changing that public metadata contract is a
product/migration decision.

Expected errors are JSON and stable:

- 400: malformed or out-of-range token ID
- 404: unminted/burned token or missing artifact
- 503: RPC, invalid-genome, render, or persistence failure

The old synchronous server was already incompatible with the asynchronous generator.
`sync_server.py` is retained only as a quarantined entry point that exits with a clear
message.

## Container

The Dockerfile pins Python 3.14.9 by its reviewed multi-platform image digest and pins uv 0.12.21,
installs the exact checked-in
`uv.lock` in frozen production-only mode, runs as UID 10001, and binds `0.0.0.0` only
inside the container. The supplied runner publishes only to host loopback and mounts
the artifact volume at `/app/artifacts`, the path the process actually uses. It does
not contain chain configuration. Re-resolve and review the digest deliberately when upgrading the
base image; a mutable tag alone is not an acceptable release pin.
