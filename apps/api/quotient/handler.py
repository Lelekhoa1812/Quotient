"""AWS Lambda entrypoint for Quotient API via Mangum ASGI adapter."""

from __future__ import annotations

from mangum import Mangum

from quotient.app import create_app

app = create_app()
handler = Mangum(app, lifespan="off")
