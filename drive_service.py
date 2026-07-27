import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from fastapi import UploadFile
import io

# Configuración
SCOPES = ['https://www.googleapis.com/auth/drive.file']
FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")
CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "service-account.json")

def get_drive_service():
    """Autentica y retorna el servicio de Google Drive."""
    creds = None
    
    # 1. Intentar desde Variable de Entorno (JSON string) - Prioridad Railway
    if CREDENTIALS_JSON:
        try:
            info = json.loads(CREDENTIALS_JSON)
            creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        except Exception as e:
            print(f"Error cargando credenciales desde ENV: {e}")

    # 2. Intentar desde Archivo (Local Dev)
    if not creds and os.path.exists(CREDENTIALS_FILE):
        try:
            creds = service_account.Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
        except Exception as e:
            print(f"Error cargando credenciales desde archivo: {e}")

    if not creds:
        print("⚠️ No se encontraron credenciales de Google Drive.")
        return None

    return build('drive', 'v3', credentials=creds)

async def upload_file_to_drive(file: UploadFile, folder_id: str = None) -> dict:
    """
    Sube un archivo (UploadFile de FastAPI) a Google Drive.
    Hace el archivo público para que Airtable pueda descargarlo como attachment.
    Retorna dict con url directa de descarga (para Airtable attachments).
    """
    service = get_drive_service()
    if not service:
        return None

    target_folder = folder_id or FOLDER_ID
    if not target_folder:
        print("⚠️ No se especificó GOOGLE_DRIVE_FOLDER_ID")
        return None

    try:
        # Leer contenido del archivo en memoria
        content = await file.read()
        file_metadata = {
            'name': file.filename,
            'parents': [target_folder]
        }
        
        media = MediaIoBaseUpload(io.BytesIO(content), mimetype=file.content_type, resumable=True)
        
        # Ejecutar subida
        file_drive = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink, webContentLink'
        ).execute()
        
        file_id = file_drive.get('id')
        print(f"✅ Archivo subido a Drive ID: {file_id}")
        
        # Hacer el archivo público (necesario para que Airtable descargue la imagen)
        try:
            service.permissions().create(
                fileId=file_id,
                body={'type': 'anyone', 'role': 'reader'},
                fields='id'
            ).execute()
            print(f"🔓 Archivo {file_id} hecho público")
        except Exception as e:
            print(f"⚠️ No se pudo hacer público el archivo: {e}")
        
        # URL directa de descarga (Airtable la usa para crear el attachment real)
        direct_url = f"https://drive.google.com/uc?id={file_id}&export=download"
        
        return {
            "url": direct_url,
            "filename": file.filename
        }

    except Exception as e:
        print(f"❌ Error subiendo a Drive: {e}")
        return None
