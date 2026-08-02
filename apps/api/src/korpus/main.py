from fastapi import FastAPI

from korpus.api.routes import router

app = FastAPI(
    title="Korpus API",
    version="0.1.0",
    description="Evidence-first retrieval, learning, and document-assistance API.",
)
app.include_router(router)

