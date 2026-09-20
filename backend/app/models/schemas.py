from pydantic import BaseModel
from typing import List, Optional, Literal
from datetime import datetime
class Runner(BaseModel):
    horse_number:int; frame_number:int; horse_id:str; horse_name:str; jockey:str; trainer:str; weight:float; horse_weight:Optional[int]=None; horse_weight_change:Optional[int]=None; odds_win:Optional[float]=None; popularity:Optional[int]=None; status:Literal["出走","取消","除外","変更"]="出走"
class Race(BaseModel):
    race_id:str; venue:str; date:str; race_number:int; start_at:datetime; deadline_at:datetime; surface:Literal["芝","ダート","障害"]; distance:int; runners:List[Runner]; odds_at:Optional[datetime]=None; has_critical_change:bool=False
class Probability(BaseModel):
    horse_number:int; win_prob:float; place_prob:float
class TrifectaProb(BaseModel):
    combo:str; prob:float
class Prediction(BaseModel):
    race_id:str; created_at:datetime; probabilities:List[Probability]; trifecta_probs:List[TrifectaProb]; model_version:str="plackett-luce-v1"
class Bet(BaseModel):
    type:str; combination:str; amount:int; ev:Optional[float]=None; prob:Optional[float]=None; odds:Optional[float]=None
class VotePlan(BaseModel):
    client_plan_id:str; source:str="jra"; venue:str; race_number:int; start_at:datetime; deadline_at:datetime; bets:List[Bet]; total_amount:int; created_at:datetime; race_id:Optional[str]=None
