from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from backend.app.routers import races, predictions, vote_plans, health, analytics, results, bets, tickets, storage, models, horses
app = FastAPI(title="Keiba-EV-Tool API", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.include_router(health.router)
app.include_router(races.router)
app.include_router(predictions.router)
app.include_router(vote_plans.router)
app.include_router(analytics.router)
app.include_router(results.router)
app.include_router(bets.router)
app.include_router(tickets.router)
app.include_router(storage.router)
app.include_router(models.router)
app.include_router(horses.router)


@app.on_event("shutdown")
def on_shutdown():
    """アプリ終了時に共有 Turso クライアントを1回だけクローズする。"""
    from backend.app.services import turso_client
    turso_client.close_client()


@app.get("/")
def root():
    return {"service": "Keiba-EV-Tool", "status": "ok"}
