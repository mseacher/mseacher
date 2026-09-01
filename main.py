from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

app = FastAPI(title="Mseacher API Backend")

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

def obtenir_meilleure_cle():
    with key_lock:
        if not API_KEYS:
            return None
        sorted_keys = sorted(API_KEYS, key=lambda k: key_quotas.get(k, 0), reverse=True)
        return sorted_keys[0]

def filtrer_profils(results, criteria):
    if not isinstance(results, list):
        return []
        
    profils_propres = []
    seen_ids = set()
    
    req_a = str(criteria.get("dob_annee", "")).strip()
    req_m = str(criteria.get("dob_mois", "")).strip().zfill(2) if criteria.get("dob_mois") else ""
    req_j = str(criteria.get("dob_jour", "")).strip().zfill(2) if criteria.get("dob_jour") else ""
    
    for res in results:
        if not isinstance(res, dict):
            continue
            
        # Anti-doublons sécurisé
        unique_key = tuple(sorted(str(v) for k, v in res.items() if k in ["email", "telephone", "adresse"] and v))
        if unique_key and unique_key in seen_ids:
            continue
        if unique_key:
            seen_ids.add(unique_key)

        # 1. Sécurité (termes bloqués)
        try:
            if any(any(term in str(v).lower() for term in BLOCKED_TERMS) for v in res.values()):
                continue
        except Exception:
            continue
            
        # 2. Filtrage intelligent de la date
        if req_a or req_m or req_j:
            res_date = str(res.get("Naissance") or res.get("date_naissance") or res.get("birth_date") or res.get("dob") or "").strip()
            
            if not res_date:
                continue
                
            rejete_date = False
            if req_a and req_a not in res_date: rejete_date = True
            if req_m and req_m not in res_date: rejete_date = True
            if req_j and req_j not in res_date: rejete_date = True
            
            if rejete_date:
                continue

        # 3. Filtrage du texte
        rejete = False
        champs_a_verifier = ["ville", "nom_famille", "prenom", "email", "telephone"]
        
        for champ in champs_a_verifier:
            valeur_recherchee = str(criteria.get(champ, "")).lower().strip()
            if valeur_recherchee:
                valeur_profil = str(res.get(champ, "")).lower()
                if valeur_recherchee not in valeur_profil:
                    rejete = True
                    break
                    
        if rejete:
            continue
        
        champs_remplis = sum(1 for k, v in res.items() if v and not k.startswith("_"))
        if champs_remplis >= 1:
            profils_propres.append(res)
            
    def score_fiabilite(profil):
        try:
            sources_str = " ".join([str(s).lower() for s in profil.get("_sources", [])])
            score = 0
            if "caf" in sources_str: score += 50
            if "ants" in sources_str: score += 50
            score += sum(1 for k, v in profil.items() if v and not k.startswith("_"))
            return score
        except Exception:
            return 0

    profils_propres.sort(key=score_fiabilite, reverse=True)
    return profils_propres

def fetch_page(payload, page):
    data_payload = payload.copy()
    data_payload["page"] = page
    
    attempts = 0
    total_keys = len(API_KEYS) if API_KEYS else 1
    
    while attempts < total_keys * 2:
        key = obtenir_meilleure_cle()
        if not key:
            break
            
        headers = {"X-API-Key": key, "Content-Type": "application/json"}
        
        try:
            response = requests.post(f"{BASE_URL}/search", headers=headers, json=data_payload, timeout=10)
            
            # Gestion sécurisée du quota dans les en-têtes
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
                attempts += 1
                continue
                
            if response.status_code == 200:
                try:
                    json_data = response.json()
                    results = json_data.get("data", {}).get("results", [])
                    if isinstance(results, list):
                        return results
                except ValueError:
                    # Erreur si la réponse n'est pas du JSON valide (ex: HTML Cloudflare)
                    pass
                
        except (requests.exceptions.RequestException, Exception):
            pass
            
        attempts += 1
    return []

@app.post("/api/search")
def run_search(req: SearchRequest):
    if not req.criteria or not isinstance(req.criteria, dict):
        raise HTTPException(status_code=400, detail="Critères de recherche invalides.")
        
    criteria = req.criteria.copy()
    
    # Sécurité globale sur les termes bloqués
    for val in criteria.values():
        if val:
            val_clean = str(val).lower().strip()
            for term in BLOCKED_TERMS:
                if term in val_clean:
                    raise HTTPException(status_code=400, detail="Recherche non autorisée.")

    req_a = str(criteria.get("dob_annee", "")).strip()
    req_m = str(criteria.get("dob_mois", "")).strip().zfill(2) if criteria.get("dob_mois") else ""
    req_j = str(criteria.get("dob_jour", "")).strip().zfill(2) if criteria.get("dob_jour") else ""

    if req_a and not criteria.get("nom_famille") and not criteria.get("prenom"):
        if req_m and req_j:
            criteria["date_naissance"] = f"{req_a}-{req_m}-{req_j}"
        else:
            criteria["date_naissance"] = req_a

    tous_les_resultats = []
    pages_a_recuperer = list(range(1, 11))
    
    try:
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_page = {executor.submit(fetch_page, criteria, p): p for p in pages_a_recuperer}
            for future in as_completed(future_to_page):
                try:
                    res = future.result()
                    if res:
                        tous_les_resultats.extend(res)
                except Exception:
                    pass
    except Exception:
        raise HTTPException(status_code=500, detail="Erreur interne lors du traitement en parallèle.")

    profils_finaux = filtrer_profils(tous_les_resultats, req.criteria)
    
    return {
        "status": 200,
        "message": "ok",
        "data": {
            "results": profils_finaux
        },
        "meta": {
            "total": len(profils_finaux)
        }
    }