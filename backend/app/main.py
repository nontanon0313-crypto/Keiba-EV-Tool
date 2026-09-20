from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.app.routers import races, predictions, vote_plans, health, analytics
app = FastAPI(title="Keiba-EV-Tool API", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(health.router)
app.include_router(races.router)
app.include_router(predictions.router)
app.include_router(vote_plans.router)
app.include_router(analytics.router)


@app.get("/")
def root():
    return {"service": "Keiba-EV-Tool", "status": "ok"}
