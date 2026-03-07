"""Small CLI argument parsers that do not depend on the runtime stack."""


def parse_gateway_args(argv: list[str]) -> tuple[int | None, bool]:
    """Parse arguments for the gateway subcommand."""
    port: int | None = None
    verbose = False
    i = 0

    while i < len(argv):
        arg = argv[i]
        if arg in {"-v", "--verbose", "--logs"}:
            verbose = True
            i += 1
            continue
        if arg in {"-p", "--port"}:
            if i + 1 >= len(argv):
                raise ValueError(f"Missing value for {arg}")
            try:
                port = int(argv[i + 1])
            except ValueError as exc:
                raise ValueError(f"Invalid port: {argv[i + 1]}") from exc
            i += 2
            continue
        raise ValueError(f"Unknown gateway option: {arg}")

    return port, verbose


def parse_whatsapp_args(argv: list[str]) -> str:
    """Parse arguments for the whatsapp subcommand."""
    if not argv:
        raise ValueError("Missing WhatsApp action. Use: 0xclaw whatsapp login")
    if any(arg in {"-h", "--help"} for arg in argv):
        return "help"
    if len(argv) == 1 and argv[0] == "login":
        return "login"
    raise ValueError(f"Unknown WhatsApp command: {' '.join(argv)}")
