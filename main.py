import os
import io
import json
import random
import string
import math
import time
from datetime import datetime
from typing import Dict, List

import requests
from fastapi import FastAPI, Form, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.responses import JSONResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

# Email Service
from email_service import EmailService

# --- Load Environment ---
load_dotenv()

app = FastAPI(title="Vit Healthcare AI System")

# --- Mount static folder ---
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Config ---
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
E5_MODEL = "nomic-embed-text"
QWEN_MODEL = "qwen2.5:3b"
OTC_FILE_PATH = r"OTC_Drugs_E5_Format.txt"

SMTP_EMAIL = os.getenv("SMTP_EMAIL", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

email_service = EmailService(SMTP_EMAIL, SMTP_PASSWORD, SMTP_SERVER, SMTP_PORT)

# --- In-memory databases ---
APPOINTMENTS: Dict[str, Dict] = {}
PINCODE_DB = {
    "560001": "Bangalore Central",
    "110001": "New Delhi Central",
    "400001": "Mumbai Fort",
    "700001": "Kolkata Central",
    "380001": "Ahmedabad Central"
}
DOCTORS_DB = [
    {"id": "D100", "name": "Dr. Priya Sharma", "specialty": "general", "pincode": "560001"},
    {"id": "D101", "name": "Dr. Arjun Rao", "specialty": "cardiology", "pincode": "560001"},
    {"id": "D200", "name": "Dr. Sangeeta Das", "specialty": "general", "pincode": "110001"},
]

# --- Helper Functions ---
def generate_id(prefix="P", size=6):
    return prefix + ''.join(random.choices(string.digits, k=size))

def read_otc_file(filepath: str) -> List[Dict]:
    entries = []
    if not os.path.exists(filepath):
        print("⚠️ OTC file not found:", filepath)
        return entries
    with open(filepath, "r", encoding="utf-8") as f:
        raw = f.read().strip().split("\n\n")
    for block in raw:
        lines = [l.strip() for l in block.split("\n") if ":" in l]
        entry = {}
        for line in lines:
            k, v = line.split(":", 1)
            entry[k.strip()] = v.strip()
        if "Condition" in entry:
            entries.append(entry)
    print(f"✅ Loaded {len(entries)} OTC entries.")
    return entries

def ollama_embeddings(text: str, model=E5_MODEL):
    try:
        res = requests.post(f"{OLLAMA_URL}/api/embeddings", json={"model": model, "prompt": text}, timeout=30)
        res.raise_for_status()
        data = res.json()
        if isinstance(data, dict) and "embedding" in data:
            return data["embedding"]
        elif isinstance(data, dict) and "embeddings" in data:
            return data["embeddings"]
        elif isinstance(data, list) and len(data) > 0:
            return data[0]
        return None
    except Exception as e:
        print("Embedding error:", e)
        return None

def cosine_similarity(v1, v2):
    if not v1 or not v2:
        return 0.0
    dot = sum(a*b for a,b in zip(v1,v2))
    norm1 = math.sqrt(sum(a*a for a in v1))
    norm2 = math.sqrt(sum(a*a for a in v2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1*norm2)

def generate_pdf(prescription: Dict) -> bytes:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    y = 800
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, y, "Vit Healthcare Prescription")
    y -= 30
    c.setFont("Helvetica", 11)
    for key, val in prescription.items():
        c.drawString(50, y, f"{key}: {val}")
        y -= 16
        if y < 100:
            c.showPage()
            y = 800
    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.read()

def rule_based_risk_score(age:int, sex:str, symptoms:str, add_symptoms:str=""):
    total = 0
    txt = (symptoms + " " + add_symptoms).lower()
    if "chest pain" in txt or "breath" in txt: total += 4
    if "bleeding" in txt: total += 4
    if "fever" in txt: total += 2
    if "rash" in txt: total += 1
    if age > 60: total += 3
    if sex.lower() == "male": total += 1
    return min(100, total * 10)



# --- Load OTC Database with Embeddings ---
OTC_DATA = read_otc_file(OTC_FILE_PATH)

def check_ollama_ready(url: str, retries: int = 10, delay: int = 5) -> bool:
    """Check if Ollama is reachable before generating embeddings."""
    for attempt in range(1, retries + 1):
        try:
            print(f"🔍 Checking Ollama connection (attempt {attempt}/{retries})...")
            res = requests.get(f"{url}/api/tags", timeout=5)
            if res.status_code == 200:
                print("✅ Ollama is reachable and running.")
                return True
        except Exception as e:
            print(f"⚠️ Ollama not reachable: {e}")
        time.sleep(delay)
    return False

# --- Generate embeddings only if Ollama is up ---
if check_ollama_ready(OLLAMA_URL):
    print("🔄 Generating embeddings for OTC-drugs list via Ollama...")
    for i, entry in enumerate(OTC_DATA, start=1):
        try:
            condition = entry.get("Condition", "")
            if condition:
                entry["embedding"] = ollama_embeddings(condition)
                print(f"✅ Embedded {i}/{len(OTC_DATA)}: {condition}")
        except Exception as e:
            print(f"⚠️ Embedding failed for entry {i}: {e}")
    print("✅ All embeddings generated successfully.")
else:
    print("⚠️ Ollama not reachable after multiple retries. Skipping embedding generation.")
    for entry in OTC_DATA:
        entry["embedding"] = None

# --- ROUTES ---

@app.get("/")
def root():
    return RedirectResponse("/static/initialization.html")

@app.post("/api/prescription/start")
async def generate_prescription(
    name: str = Form(...),
    age: int = Form(...),
    sex: str = Form(...),
    blood_group: str = Form(""),
    symptoms: str = Form(...),
    additional_symptoms: str = Form(""),
    patient_email: str = Form(None)
):
    risk = rule_based_risk_score(age, sex, symptoms, additional_symptoms)
    if risk >= 50:
        return {"ok": True, "risk_score": risk, "message": "High risk detected. Book ambulance."}

    # --- Find closest condition using E5 embeddings ---
    user_vec = ollama_embeddings(symptoms + " " + additional_symptoms)
    best_match, best_score = None, 0
    for e in OTC_DATA:
        sim = cosine_similarity(user_vec, e.get("embedding"))
        if sim > best_score:
            best_match, best_score = e, sim

    if not best_match:
        raise HTTPException(status_code=404, detail="No match found")

    # --- Generate prescription ---
    presc_id = generate_id("P")
    today = datetime.now().strftime("%Y-%m-%d")
    prescription = {
        "Prescription ID": presc_id,
        "Date": today,
        "Name": name,
        "Age": age,
        "Sex": sex,
        "Blood Group": blood_group,
        "Condition": best_match.get("Condition"),
        "Generic Name": best_match.get("Generic Name"),
        "OTC Brand Names": best_match.get("OTC Brand Names"),
        "Precaution Measures": best_match.get("Precaution Measures"),
        "Dosages": best_match.get("Dosages"),
        "Duration": best_match.get("Duration"),
        "Age Suitability": best_match.get("Age Suitability"),
    }

    pdf_bytes = generate_pdf(prescription)

    # --- Send prescription email ---
    if patient_email:
        subject = f"Prescription {presc_id} - Vit Healthcare"
        body = f"Dear {name},\n\nYour AI-generated prescription for {best_match.get('Condition')} is attached.\n\nStay healthy,\nVit Healthcare"
        email_service.send_email_with_attachment(patient_email, subject, body, f"prescription_{presc_id}.pdf", pdf_bytes)

    return {"ok": True, "risk_score": risk, "similarity": best_score, "prescription": prescription}
  