"""Production entrypoint: establish the startup clock before importing Uvicorn/API."""

from api import performance


def main() -> None:
    import os

    import uvicorn

    uvicorn.run("api.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8080")))


if __name__ == "__main__":
    main()
