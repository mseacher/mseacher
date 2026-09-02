from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import traceback

app = FastAPI(title="Mseacher API Backend - Multi-Key Mode")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_KEYS_CONFIG = (
    "brix_qRHkZeFRyGgV3sqvBns2XPpWlp7y02PtlbfcuEd2zvqvgUX3,"
    "brix_XZi402frJIuCbTYiBUoTjm1ijCaL4oc7iW6N7_v9F8Dno2NJ,"
    "brix_Bj2TrhC_5TBhUIFS0-AOi_H0Vcj6ejbpUs1czChLDfEOKyUl,"
    "brix_MJr1Ai_lHtTOYEQvdK_UFRPSaA0uoER7fEaocWbDzk_opvYS,"
    "brix_4W4kpwSQ-UOzwpXyCW4W6dbijfW1pFuFc5qg4PHlkb-VffDb,"
    "brix_3DK98_aUkerNfhLCbTF6FRBE37PK2dhVC-o6DlCDrLtTOly6,"
    "brix_bQDt88K4uAKqoYxY_42nu9yBgjcwLV944Wh-rOkHCyOm40XS,"
    "brix_K0EEY_iabscB0B0MdYuWEeIUMokvMFJfutZRuveeIUYgLtjw,"
    "brix_J0lnsmljuAX81wOxgn1ZRUy_T7i4i81VV0WxrYDOEuHBeLIj,"
    "brix_XeL8k-5aEYqkCXzaLOKpianJbmrHqtycUr66qiNIOLw3ri06"
)

API_KEYS = [k.strip() for k in API_KEYS_CONFIG.split(",") if k.strip()]
key_quotas = {key: 1000 for key in API_KEYS}
key_lock = threading.Lock()

BASE_URL = "https://api.brixhub.to/api/v1"
BLOCKED_TERMS = {"msebengi", "alimasi", "mse"}

class SearchRequest(BaseModel):
    criteria: dict

def obtenir_cles_disponibles(nombre=1):
    """Récupère un pool de clés pour la recherche"""
    with key_lock:
        if not API_KEYS:
            return []
        sorted_keys = sorted(API_KEYS, key=lambda k: key_quotas.get(k, 0), reverse=True)
        return sorted_keys[:nombre]

def fetch_with_key(payload, key):
    """Exécute une requête de recherche avec une clé spécifique selon la spec BrixHub"""
    headers = {"X-API-Key": key, "Content-Type": "application/json"}
    
    try:
        response = requests.post(f"{BASE_URL}/search", headers=headers, json=payload, timeout=8)
        print(f"[DEBUG] Requête avec clé {key[:10]}... - Status Code: {response.status_code}")
        
        remaining = response.headers.get("x-ratelimit-remaining-day")
        if remaining is not None:
            try:
                with key_lock:
                    key_quotas[key] = int(remaining)
            except ValueError:
                pass
        
        if response.status_code == 429:
            with key_lock:
                key_quotas[key] = 0
            return []
            
        if response.status_code == 200:
            json_data = response.json()
            results = json_data.get("data", {}).get("results", [])
            if isinstance(results, list):
                return results
                
    except Exception as e:
        print(f"[DEBUG] Erreur requête avec clé {key[:10]}: {e}")
        
    return []

@app.get("/")
def read_root():
    return {"status": "online", "message": "Bienvenue sur l'API Mseacher ! Le backend fonctionne."}

@app.post("/api/search")
def run_search(req: SearchRequest):
    print(f"[DEBUG] Requête reçue avec les critères bruts : {req.criteria}")
    
    if not req.criteria or not isinstance(req.criteria, dict):
        raise HTTPException(status_code=400, detail="Critères de recherche invalides.")
        
    criteria = req.criteria.copy()
    
    for val in criteria.values():
        if val:
            val_clean = str(val).lower().strip()
            for term in BLOCKED_TERMS:
                if term in val_clean:
                    raise HTTPException(status_code=400, detail="Recherche non autorisée.")

    # Construction du payload officiel accepté par l'API BrixHub avec tous les champs du HTML
    payload = {"flexible": True} 
    
    champs_standards = [
        "nom_famille", "prenom", "nom_affichage", "ville", 
        "code_postal", "email", "telephone", "adresse_ip", 
        "discord_id", "fivem_license", "siret", "siren", "iban"
    ]
    for champ in champs_standards:
        valeur = criteria.get(champ)
        if valeur:
            payload[champ] = str(valeur).strip()

    # Gestion propre des critères de date selon la documentation BrixHub
    req_a = str(criteria.get("dob_annee", "")).strip()
    req_m = str(criteria.get("dob_mois", "")).strip().zfill(2) if criteria.get("dob_mois") else ""
    req_j = str(criteria.get("dob_jour", "")).strip().zfill(2) if criteria.get("dob_jour") else ""

    if req_a:
        if req_m and req_j:
            payload["date_naissance"] = f"{req_a}-{req_m}-{req_j}"
        else:
            payload["annee_naissance"] = req_a

    tous_les_resultats = []
    
    # Utilisation d'une seule clé pour le test de performance réseau
    cles_a_utiliser = obtenir_cles_disponibles(nombre=1)
    
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future_to_key = {executor.submit(fetch_with_key, payload, key): key for key in cles_a_utiliser}
            for future in as_completed(future_to_key):
                try:
                    res = future.result()
                    if res:
                        tous_les_resultats.extend(res)
                except Exception as e:
                    print(f"[DEBUG] Erreur thread clé: {e}")
    except Exception as e:
        print(f"[DEBUG] Erreur critique ThreadPool: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Erreur interne lors du traitement en parallèle.")

    # Nettoyage et filtrage anti-doublons de base
    seen_ids = set()
    profils_propres = []
    for res in tous_les_resultats:
        if not isinstance(res, dict):
            continue
        unique_key = tuple(sorted(str(v) for k, v in res.items() if k in ["email", "telephone", "adresse", "id"] and v))
        if unique_key and unique_key in seen_ids:
            continue
        if unique_key:
            seen_ids.add(unique_key)
        profils_propres.append(res)

    print(f"[DEBUG] Recherche terminée. Résultats uniques totaux : {len(profils_propres)}")
    
    return {
        "status": 200,
        "message": "ok",
        "data": {
            "results": profils_propres
        },
        "meta": {
            "total": len(profils_propres)
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
