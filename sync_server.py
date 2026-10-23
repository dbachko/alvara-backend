"""Unsupported historical entry point retained to fail clearly for old operators."""


def main() -> None:
    raise SystemExit(
        "sync_server.py is a quarantined 2022 prototype. "
        "Use async_server.py and the documented local-safe configuration."
    )


if __name__ == "__main__":
    main()
