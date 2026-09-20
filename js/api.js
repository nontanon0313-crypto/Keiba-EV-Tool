const API_BASE = localStorage.getItem('api_base') || 'http://localhost:8000';
async function fetchRaces(){const res=await fetch(`${API_BASE}/races`);return res.json();}
async function fetchPrediction(raceId){const res=await fetch(`${API_BASE}/predictions/${raceId}`);return res.json();}
async function createVotePlan(raceId,budget=2000){const res=await fetch(`${API_BASE}/vote-plans?race_id=${raceId}&budget=${budget}`,{method:'POST'});return res.json();}
