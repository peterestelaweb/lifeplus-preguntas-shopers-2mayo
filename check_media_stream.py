import os
import requests
from dotenv import load_dotenv

load_dotenv('.env')
public_url = os.getenv('PUBLIC_URL')
if not public_url:
    print("No se encontró PUBLIC_URL en el .env")
    exit(1)

url = public_url.rstrip('/') + '/media-stream'
print(f'Probando: {url}')
try:
    resp = requests.get(url)
    print(f'Respuesta HTTP: {resp.status_code}')
    print(f'Texto: {resp.text[:200]}')
    if resp.status_code == 405 or resp.status_code == 426:
        print('✅ FastAPI está escuchando en la URL correcta.')
    else:
        print('⚠️ FastAPI responde, pero el código no es el esperado.')
except Exception as e:
    print(f'❌ No se pudo conectar a {url}: {e}')
