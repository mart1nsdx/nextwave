"""FastAPI composition root. The only module allowed to import from anywhere.

Wiring lives here so that every other package stays independently testable.
"""

from fastapi import FastAPI


def create_app() -> FastAPI:
    application = FastAPI(title="Volta", version="0.1.0")

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # Routers mount here as they land: telephony.router, then the dashboard read API.
    return application


app = create_app()
