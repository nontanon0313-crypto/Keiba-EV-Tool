import os, httpx
from backend.app.models.schemas import VotePlan
from dotenv import load_dotenv
load_dotenv()
MEMO_DB: list = []
def send_plan(plan: VotePlan):
    url=os.getenv("VOTE_MANAGER_URL")
    api_key=os.getenv("VOTE_MANAGER_API_KEY")
    if not url:
        MEMO_DB.append(plan.model_dump())
        return {"status":"memo_saved","client_plan_id":plan.client_plan_id}
    headers={"Authorization":f"Bearer {api_key}"} if api_key else {}
    try:
        r=httpx.post(url, json=plan.model_dump(mode='json'), headers=headers, timeout=10)
        return r.json()
    except Exception as e:
        return {"status":"error","detail":str(e)}
