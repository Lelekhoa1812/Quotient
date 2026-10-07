"""Run the Quotient MCP server on 127.0.0.1:8080."""

from __future__ import annotations


def main() -> None:
    import uvicorn

    uvicorn.run(
        "quotient.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=8080,
    )


if __name__ == "__main__":
    main()
