"""Hala Handmade Business OS ASGI entrypoint."""

from app_bootstrap import lifespan
from app_factory import create_app


app = create_app(lifespan)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
