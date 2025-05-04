from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Response
from pinecone_plugins.assistant.models.chat import Message
from fastapi.responses import Response
from prompts import SYSTEM_MESSAGE
from dotenv import load_dotenv
from twilio.rest import Client
from datetime import datetime
from pinecone import Pinecone
import websockets
import traceback
import requests
import audioop
import asyncio
import base64
import json
import os
import pytz
from datetime import timedelta, timezone
import dateutil.parser

# Añadir esta función para formatear la hora de manera natural
def format_hour_naturally(hour):
    """Convierte horas en formato 24h a formato natural."""
    hour = int(hour)
    if 13 <= hour <= 19:
        return f"{hour-12} de la tarde"
    elif 20 <= hour <= 23:
        return f"{hour-12} de la noche"
    elif hour == 12:
        return "12 del mediodía"
    else:
        return f"{hour} de la mañana"

# Improve the format_datetime_for_calendar function to be even more robust
def format_datetime_for_calendar(datetime_str):
    """
    Limpia y formatea adecuadamente una fecha para Google Calendar.
    Elimina dobles zonas horarias y asegura formato ISO8601 correcto.
    """
    print(f"[DEBUG] Cleaning datetime format: input = '{datetime_str}'")
    
    # Handle null or empty strings
    if not datetime_str:
        from datetime import datetime
        # Default to tomorrow at noon if no datetime provided
        tomorrow = datetime.now() + timedelta(days=1)
        tomorrow_noon = tomorrow.replace(hour=12, minute=0, second=0, microsecond=0)
        return tomorrow_noon.strftime("%Y-%m-%dT%H:%M:%S")
    
    # Limpiar el string
    clean_datetime = datetime_str.strip().replace("\n", "")
    
    # Eliminar cualquier zona horaria existente para evitar problemas
    if '+' in clean_datetime:
        clean_datetime = clean_datetime.split('+')[0]
    if 'Z' in clean_datetime:
        clean_datetime = clean_datetime.replace('Z', '')
    
    try:
        # Intentar convertir a objeto datetime para asegurar validez
        from datetime import datetime
        
        # Si tiene formato ISO con T
        if 'T' in clean_datetime:
            # Normalizar el formato
            parts = clean_datetime.split('T')
            date_part = parts[0].strip()
            time_part = parts[1].strip()
                
            # Asegurar que tiene segundos
            if time_part.count(':') == 1:
                time_part += ':00'
            clean_datetime = f"{date_part}T{time_part}"
        else:
            # Formato con espacio - convertir a formato ISO
            parts = clean_datetime.split(' ')
            if len(parts) >= 2:
                date_part = parts[0].strip()
                time_part = parts[1].strip()
                
                # Asegurar que tiene segundos
                if time_part.count(':') == 1:
                    time_part += ':00'
                
                # Construir formato ISO
                clean_datetime = f"{date_part}T{time_part}"
            else:
                # Solo fecha sin tiempo
                clean_datetime = f"{clean_datetime}T12:00:00"
        
        # Verificación final - convertir a objeto datetime y volver a formatear
        # para asegurar un formato 100% compatible con Google Calendar
        dt_obj = datetime.fromisoformat(clean_datetime)
        final_datetime = dt_obj.strftime("%Y-%m-%dT%H:%M:%S")
            
        print(f"[DEBUG] Cleaned datetime format: output = '{final_datetime}'")
        return final_datetime
        
    except Exception as e:
        print(f"[ERROR] Error formatting datetime: {e}, input was '{datetime_str}'")
        # En caso de error, devolver el formato predeterminado
        from datetime import datetime
        tomorrow = datetime.now() + timedelta(days=1)
        tomorrow_noon = tomorrow.replace(hour=12, minute=0, second=0, microsecond=0)
        return tomorrow_noon.strftime("%Y-%m-%dT%H:%M:%S")

load_dotenv(override=True)

# Get environment variables
ULTRAVOX_API_KEY = os.environ.get('ULTRAVOX_API_KEY')
PINECONE_API_KEY = os.environ.get('PINECONE_API_KEY')
N8N_WEBHOOK_URL = os.environ.get('N8N_WEBHOOK_URL')
PUBLIC_URL = os.environ.get('PUBLIC_URL')
PORT = int(os.environ.get('PORT', '8000'))
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.environ.get('TWILIO_PHONE_NUMBER')

# *** AÑADE ESTA LÍNEA TEMPORALMENTE ***
print(f"DEBUG: FastAPI cargó PUBLIC_URL: {PUBLIC_URL}")
# **************************************
# Ultravox defaults
ULTRAVOX_MODEL         = "fixie-ai/ultravox-70B"
ULTRAVOX_VOICE         = "Alex-Spanish"   # or “Mark”
ULTRAVOX_SAMPLE_RATE   = 8000        
ULTRAVOX_BUFFER_SIZE   = 60        

CALENDARS_LIST = {
            "LOCATION1": "peluqueriaconvoz@gmail.com",
            
        }
CALENDAR_EMAIL = "peluqueriaconvoz@gmail.com"
                 
app = FastAPI()

# Keep the same session store
sessions = {}

# Just for debugging specific event types
LOG_EVENT_TYPES = [
    'response.content.done',
    'response.done',
    'session.created',
    'conversation.item.input_audio_transcription.completed',
    'call_connected',
]


@app.get("/")
async def root():
    return {"message": "Twilio + Ultravox Media Stream Server is running!"}

@app.post("/incoming-call")
async def incoming_call(request: Request):
    """
    Handle the inbound call from Twilio. 
    - Fetch firstMessage from N8N
    - Store session data
    - Respond with TwiML containing <Stream> to /media-stream
    """
    form_data = await request.form()
    twilio_params = dict(form_data)
    print('Incoming call')
    # print('Twilio Inbound Details:', json.dumps(twilio_params, indent=2))

    caller_number = twilio_params.get('From', 'Unknown')
    session_id = twilio_params.get('CallSid')
    print('Caller Number:', caller_number)
    print('Session ID (CallSid):', session_id)

    # Fetch first message from N8N
    first_message = "Hey, this is Sara from Agenix AI solutions. How can I assist you today?"
    print("Fetching N8N ...")
    try:
        webhook_response = requests.post(
            N8N_WEBHOOK_URL,
            headers={"Content-Type": "application/json"},
            json={
                "route": "1",
                "number": caller_number,
                "data": "empty"
            },
            # verify=False  # Uncomment if using self-signed certs (not recommended)
        )
        if webhook_response.ok:
            response_text = webhook_response.text
            try:
                response_data = json.loads(response_text)
                if response_data and response_data.get('firstMessage'):
                    first_message = response_data['firstMessage']
                    print('Parsed firstMessage from N8N:', first_message)
            except json.JSONDecodeError:
                # If response is not JSON, treat it as raw text
                first_message = response_text.strip()
        else:
            print(f"Failed to send data to N8N webhook: {webhook_response.status_code}")
    except Exception as e:
        print(f"Error sending data to N8N webhook: {e}")

    # Save session
    session = {
        "transcript": "",
        "callerNumber": caller_number,
        "callDetails": twilio_params,
        "firstMessage": first_message,
        "streamSid": None
    }
    sessions[session_id] = session

    # Respond with TwiML to connect to /media-stream
    host = PUBLIC_URL
    # Normalizar host: quitar barra final y cambiar esquema
    normalized_host = host.rstrip('/')
    stream_url = f"{normalized_host.replace('https://', 'wss://').replace('http://', 'ws://')}/media-stream"

    twiml_response = f"""<?xml version="1.0" encoding="UTF-8"?>
        <Response>
            <Connect>
                <Stream url="{stream_url}">
                    <Parameter name="firstMessage" value="{first_message}" />
                    <Parameter name="callerNumber" value="{caller_number}" />
                    <Parameter name="callSid" value="{{{{CallSid}}}}" />
                </Stream>
            </Connect>
        </Response>"""

    return Response(content=twiml_response, media_type="text/xml")


@app.post("/outgoing-call")
async def outgoing_call(request: Request):
    try:
        log_start = datetime.now()
        print(f"[PERF] [outgoing-call] Llamada recibida en /outgoing-call a las {log_start.isoformat()}")
        # Get request data
        data = await request.json() 
        print("[DEBUG] Payload recibido en /outgoing-call:", data)  
        
        # --- MEJORA: Captura de parámetros desde la estructura n8n ---
        # Buscar en la estructura de parámetros que usa n8n
        parameters = data.get('parameters', [])
        parameter_dict = {}
        
        # Si parameters es un array de objetos {name, value}, convertirlo a diccionario
        if isinstance(parameters, list):
            for param in parameters:
                if isinstance(param, dict) and 'name' in param and 'value' in param:
                    parameter_dict[param['name']] = param['value']
            print(f"[DEBUG] Parámetros extraídos del array: {parameter_dict}")
        
        # Obtener valores, priorizando el formato de parameters, luego directos del json
        phone_number = parameter_dict.get('phoneNumber') or data.get('phoneNumber')
        first_message = parameter_dict.get('firstMessage') or data.get('firstMessage')
        name = parameter_dict.get('NAME') or parameter_dict.get('name') or data.get('NAME') or data.get('name') or None
        
        # Obtener PIN_LIFEPLUS de la estructura de parámetros
        pin_lifeplus = parameter_dict.get('PIN_LIFEPLUS') or data.get('PIN_LIFEPLUS') or data.get('pin_lifeplus') or "No especificado"
        
        print("[DEBUG] Mensaje inicial recibido:", first_message)
        print(f"[DEBUG] PIN_LIFEPLUS extraído: {pin_lifeplus}")
        
        if not phone_number:
            return {"error": "Phone number is required"}, 400
        
        # --- COMPATIBILIDAD DEL MENSAJE ---
        # Si el mensaje contiene {{ $json.NAME }} y hay un nombre, reemplazarlo
        if first_message and "{{ $json.NAME }}" in first_message and name:
            print(f"[DEBUG] Reemplazando {{ $json.NAME }} por {name}")  
            first_message = first_message.replace("{{ $json.NAME }}", str(name))
        # Si no hay nombre, dejar el placeholder o poner 'el destinatario'
        elif first_message and "{{ $json.NAME }}" in first_message:
            first_message = first_message.replace("{{ $json.NAME }}", "el destinatario")

        print(f"[PERF] [outgoing-call] Mensaje inicial preparado a las {datetime.now().isoformat()}")
        print("[DEBUG] Mensaje final que se usará en la llamada:", first_message)  
        # --- Normaliza el mensaje inicial para evitar fragmentación y repeticiones ---
        if first_message:
            first_message = ' '.join(first_message.split())
        # -------------------------------------------------------------

        print('📞 Initiating outbound call to:', phone_number)
        print('📝 With the following first message:', first_message)
        
        # Initialize Twilio client
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

        # Store call data with timestamp
        madrid_tz = pytz.timezone('Europe/Madrid')
        start_time = datetime.now(madrid_tz).isoformat()
        print(f"[PERF] [outgoing-call] Timestamp de inicio de llamada guardado a las {datetime.now().isoformat()}")
        
        call_data = {
            "originalRequest": data,
            "startTime": start_time,
            "pin_lifeplus": pin_lifeplus,  # MEJORA: Guardar PIN_LIFEPLUS en call_data
            "parameters": parameter_dict   # MEJORA: Guardar también el dictionary de parámetros
        }

         # Respond with TwiML to connect to /media-stream
        host = PUBLIC_URL
        # Nueva lógica robusta para la URL del WebSocket
        if not host:
            print("[ERROR] PUBLIC_URL is not set, cannot build stream URL.")
            # Aquí podrías lanzar una excepción o retornar un error, según la lógica de tu app
        normalized_host = host.rstrip('/')
        stream_url = f"{normalized_host.replace('https://', 'wss://').replace('http://', 'ws://')}/media-stream"
        print(f"[DEBUG] Stream URL: {stream_url}")
        
        print('📱 Creating Twilio call with TWIML...')
        
        # Volver al enfoque original con <Connect> y <Stream>
        call = client.calls.create(
            twiml=f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect timeout="300">
        <Stream url="{stream_url}">
            <Parameter name="firstMessage" value="{first_message}" />
            <Parameter name="callerNumber" value="{phone_number}" />
            <Parameter name="callSid" value="{{{{CallSid}}}}" />
        </Stream>
    </Connect>
</Response>''',
            to=phone_number,
            from_=TWILIO_PHONE_NUMBER,
            status_callback=f"{PUBLIC_URL}/call-status",
            status_callback_event=['initiated', 'ringing', 'answered', 'completed'],
            machine_detection="Enable"
        )

        print('📱 Twilio call created:', call.sid)
        # Store call data in sessions
        sessions[call.sid] = {
            "transcript": "",
            "callerNumber": phone_number,
            "callDetails": call_data,
            "firstMessage": first_message,
            "streamSid": None,
            "transcript_sent": False,
            "start_time": start_time,  # MEJORA: Guardar hora de inicio ISO
            "pin_lifeplus": pin_lifeplus,  # MEJORA: Guardar PIN_LIFEPLUS directamente en la sesión
            "http_request_data": data,  # MEJORA: Guardar todo el payload para acceso posterior
            "call_id": call.sid,  # MEJORA: Guardar call_id explícitamente
            "call_sid": call.sid  # Guardar también como call_sid para compatibilidad
        }

        return {
            "success": True,
            "callSid": call.sid
        }

    except Exception as error:
        print('❌ Error creating call:', str(error))
        traceback.print_exc()
        return {"error": str(error)}, 500
    

@app.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    print(f"[PERF] [media-stream] Conexión WebSocket recibida a las {datetime.now().isoformat()}")
    print(f"[LOG] Handler media_stream ACTIVADO. Esperando mensajes de Twilio...")
    try:
        await websocket.accept()
        print('Client connected to /media-stream (Twilio)')
    except Exception as e:
        print(f"[ERROR] No se pudo aceptar la conexión WebSocket: {e}")
        return
    """
    Handles the Twilio <Stream> WebSocket and connects to Ultravox via WebSocket.
    Includes transcoding audio between Twilio's G.711 µ-law and Ultravox's s16 PCM.
    
    NOTA SOBRE LATENCIA: El retraso inicial de 3-4 segundos antes de la primera respuesta
    del agente es una característica inherente del modelo de Ultravox y no puede reducirse
    significativamente desde este código Python. Es parte del tiempo que el modelo necesita
    para procesar el contexto inicial y generar la primera respuesta.
    """
    # Initialize session variables
    call_sid = None
    session = None
    stream_sid = ''
    uv_ws = None  # Ultravox WebSocket connection
    twilio_task = None  # Store the Twilio handler task

    # Define handler for Ultravox messages
    async def handle_ultravox():
        nonlocal uv_ws, session, stream_sid, call_sid, twilio_task
        try:
            async for raw_message in uv_ws:
                if isinstance(raw_message, bytes):
                    # Agent audio in PCM s16le
                    try:
                        mu_law_bytes = audioop.lin2ulaw(raw_message, 2)
                        payload_base64 = base64.b64encode(mu_law_bytes).decode('ascii')
                    except Exception as e:
                        print(f"Error transcoding PCM to µ-law: {e}")
                        continue  # Skip this audio frame

                    # Send to Twilio as media payload
                    try:
                        await websocket.send_text(json.dumps({
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {
                                "payload": payload_base64
                            }
                        }))
                    except Exception as e:
                        print(f"Error sending media to Twilio: {e}")

                else:
                    # Text data message from Ultravox
                    try:
                        msg_data = json.loads(raw_message)
                        # Capturar el UUID de Ultravox si está presente
                        if msg_data.get("eventType") == "call_connected" and msg_data.get("callId"):
                            ultravox_call_id = msg_data.get("callId")
                            print(f"[INFO] UUID de Ultravox capturado: {ultravox_call_id}")
                            session["ultravox_call_id"] = ultravox_call_id
                        # print(f"Received data message from Ultravox: {json.dumps(msg_data)}")
                    except Exception as e:
                        print(f"Ultravox non-JSON data: {raw_message}")
                        continue

                    msg_type = msg_data.get("type") or msg_data.get("eventType")

                    if msg_type == "transcript":
                        role = msg_data.get("role")
                        text = msg_data.get("text") or msg_data.get("delta")
                        final = msg_data.get("final", False)

                        if role and text:
                            role_cap = role.capitalize()
                            session['transcript'] += f"{role_cap}: {text}\n"
                            print(f"{role_cap} says: {text}")

                            # Detección secundaria de contestador automático en transcripción
                            def contiene_frase_contestador(transcripcion):
                                frases = [
                                    "deje su mensaje después de oír la señal",
                                    "por favor, deje su mensaje",
                                    "si desea volver a grabar su mensaje",
                                    "está ocupado. por favor, deja tu mensaje",
                                    "deje su mensaje tras la señal",
                                    "deje su mensaje después de la señal",
                                    "deje su mensaje"
                                ]
                                transcripcion = transcripcion.lower()
                                return any(frase in transcripcion for frase in frases)

                            # Solo analizamos si es el usuario quien habla
                            if role_cap == "User" and contiene_frase_contestador(text):
                                call_sid = session.get("call_sid") or session.get("call_id")
                                print(f"[INFO] Frase típica de contestador detectada en la transcripción. Colgando llamada...")
                                try:
                                    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
                                    if call_sid:
                                        client.calls(call_sid).update(status='completed')
                                        print(f"[INFO] Llamada finalizada automáticamente por frase de contestador: {call_sid}")
                                except Exception as e:
                                    print(f"[ERROR] No se pudo finalizar la llamada automáticamente: {e}")

                            if final:
                                print(f"Transcript for {role_cap} finalized.")

                    elif msg_type == "client_tool_invocation":
                        toolName = msg_data.get("toolName")
                        invocationId = msg_data.get("invocationId")
                        parameters = msg_data.get("parameters", {})
                        print(f"Invoking tool: {toolName} with invocationId: {invocationId} and parameters: {parameters}")

                        if toolName == "question_and_answer":
                            question = parameters.get('question')
                            print(f'Arguments passed to question_and_answer tool: {parameters}')
                            await handle_question_and_answer(uv_ws, invocationId, question)
                        elif toolName == "schedule_meeting":
                            print(f'Arguments passed to schedule_meeting tool: {parameters}')
                            # Validate required parameters
                            required_params = ["name", "purpose", "datetime", "location"]
                            missing_params = [param for param in required_params if not parameters.get(param)]

                            if missing_params:
                                print(f"Missing parameters for schedule_meeting: {missing_params}")

                                # Inform the agent to prompt the user for missing parameters
                                prompt_message = f"Please provide the following information to schedule your meeting: {', '.join(missing_params)}."
                                tool_result = {
                                    "type": "client_tool_result",
                                    "invocationId": invocationId,
                                    "result": prompt_message,
                                    "response_type": "tool-response"
                                }
                                await uv_ws.send(json.dumps(tool_result))
                            else:
                                await handle_schedule_meeting(uv_ws, session, invocationId, parameters)
                        
                        elif toolName == "hangUp":
                            print("Received hangUp tool invocation")
                            # Send success response back to the agent
                            tool_result = {
                                "type": "client_tool_result",
                                "invocationId": invocationId,
                                "result": "Call ended successfully",
                                "response_type": "tool-response"
                            }
                            await uv_ws.send(json.dumps(tool_result))
                            
                            # End the call process:
                            print(f"Ending call (CallSid={call_sid})")
    
                            # Close Ultravox WebSocket
                            if uv_ws and uv_ws.state == websockets.protocol.State.OPEN:
                                await uv_ws.close()
                            
                            # End Twilio call
                            try:
                                client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
                                client.calls(call_sid).update(status='completed')
                                print(f"Successfully ended Twilio call: {call_sid}")
                            except Exception as e:
                                print(f"Error ending Twilio call: {e}")
                            
                            # Send transcript to N8N and cleanup session
                            if session:
                                if not session.get("transcript_sent", False):
                                    await send_transcript_to_n8n(session)
                                    session["transcript_sent"] = True
                                else:
                                    print(f"[INFO] Transcript already sent for CallSid={call_sid}, skipping duplicate send")
                                sessions.pop(call_sid, None)
                            return  # Exit the Ultravox handler

                    elif msg_type == "state":
                        # Handle state messages
                        state = msg_data.get("state")
                        if state:
                            print(f"Agent state: {state}")

                    elif msg_type == "debug":
                        # Handle debug messages
                        debug_message = msg_data.get("message")
                        print(f"Ultravox debug message: {debug_message}")
                        # Attempt to parse nested messages within the debug message
                        try:
                            nested_msg = json.loads(debug_message)
                            nested_type = nested_msg.get("type")

                            if nested_type == "toolResult":
                                tool_name = nested_msg.get("toolName")
                                output = nested_msg.get("output")
                                print(f"Tool '{tool_name}' result: {output}")


                            else:
                                print(f"Unhandled nested message type within debug: {nested_type}")
                        except json.JSONDecodeError as e:
                            print(f"Failed to parse nested message within debug message: {e}. Message: {debug_message}")

                    elif msg_type in LOG_EVENT_TYPES:
                        print(f"Ultravox event: {msg_type} - {msg_data}")
                    else:
                        print(f"Unhandled Ultravox message type: {msg_type} - {msg_data}")

        except Exception as e:
            print(f"Error in handle_ultravox: {e}")
            traceback.print_exc()

    # Define handler for Twilio messages
    async def handle_twilio():
        nonlocal call_sid, session, stream_sid, uv_ws
        try:
            while True:
                message = await websocket.receive_text()
                data = json.loads(message)

                if data.get('event') == 'start':
                    stream_sid = data['start']['streamSid']
                    call_sid = data['start']['callSid']
                    custom_parameters = data['start'].get('customParameters', {})

                    print("Twilio event: start")
                    print("CallSid:", call_sid)
                    print("StreamSid:", stream_sid)
                    print("Custom Params:", custom_parameters)

                    # Extract first_message and caller_number
                    first_message = custom_parameters.get('firstMessage', "Hello, how can I assist you?")
                    caller_number = custom_parameters.get('callerNumber', 'Unknown')

                    if call_sid and call_sid in sessions:
                        session = sessions[call_sid]
                        session['callerNumber'] = caller_number
                        session['streamSid'] = stream_sid
                    else:
                        print(f"Session not found for CallSid: {call_sid}")
                        await websocket.close()
                        return

                    print("Caller Number:", caller_number)
                    print("First Message:", first_message)

                    # PERF: Marca de tiempo justo antes de crear la llamada Ultravox
                    print(f"[PERF] [media-stream] Antes de crear Ultravox call a las {datetime.now().isoformat()}")
                    # Create Ultravox call with first_message
                    uv_join_url = await create_ultravox_call(
                        system_prompt=SYSTEM_MESSAGE,
                        first_message=first_message,  # Pass the actual first_message here
                        session=session
                    )

                    print(f"[PERF] [media-stream] Ultravox joinUrl recibido a las {datetime.now().isoformat()}")

                    if not uv_join_url:
                        print("Ultravox joinUrl is empty. Cannot establish WebSocket connection.")
                        await websocket.close()
                        return

                    # Connect to Ultravox WebSocket
                    try:
                        uv_ws = await websockets.connect(
                            uv_join_url,
                            ping_interval=20,  # Enviar ping cada 20 segundos
                            ping_timeout=10,   # Timeout de 10 segundos para el ping
                            close_timeout=10   # Timeout de 10 segundos para el cierre
                        )
                        print(f"[PERF] [media-stream] Ultravox WebSocket conectado a las {datetime.now().isoformat()}")
                    except Exception as e:
                        print(f"Error connecting to Ultravox WebSocket: {e}")
                        traceback.print_exc()
                        await websocket.close()
                        return

                    # PERF: Marca de tiempo justo antes de lanzar el handler de Ultravox
                    print(f"[PERF] [media-stream] Lanzando handler de Ultravox a las {datetime.now().isoformat()}")
                    # Start handling Ultravox messages as a separate task
                    uv_task = asyncio.create_task(handle_ultravox())
                    print("Started Ultravox handler task.")

                elif data.get('event') == 'media':
                    # Twilio sends media from user
                    payload_base64 = data['media']['payload']

                    try:
                        # Decode base64 to get raw µ-law bytes
                        mu_law_bytes = base64.b64decode(payload_base64)

                    except Exception as e:
                        print(f"Error decoding base64 payload: {e}")
                        continue  # Skip this payload

                    try:
                        # Transcode µ-law to PCM (s16le)
                        pcm_bytes = audioop.ulaw2lin(mu_law_bytes, 2)
                        
                    except Exception as e:
                        print(f"Error transcoding µ-law to PCM: {e}")
                        continue  # Skip this payload

                    # Send PCM bytes to Ultravox
                    if uv_ws and uv_ws.state == websockets.protocol.State.OPEN:
                        try:
                            await uv_ws.send(pcm_bytes)
                       
                        except Exception as e:
                            print(f"Error sending PCM to Ultravox: {e}")

        except WebSocketDisconnect:
            print(f"Twilio WebSocket disconnected (CallSid={call_sid}).")
            # Attempt to close Ultravox ws
            if uv_ws and hasattr(uv_ws, 'state') and uv_ws.state == websockets.protocol.State.OPEN:
                try:
                    await uv_ws.close()
                    print(f"[DEBUG] Ultravox WebSocket cerrado correctamente para CallSid={call_sid}")
                except Exception as e:
                    print(f"[ERROR] Error al cerrar Ultravox WebSocket: {e}")
            
            # End Twilio call
            try:
                client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
                client.calls(call_sid).update(status='completed')
                print(f"Successfully ended Twilio call: {call_sid}")
            except Exception as e:
                print(f"Error ending Twilio call: {e}")
            
            # Send transcript to N8N and cleanup session
            if session:
                if not session.get("transcript_sent", False):
                    await send_transcript_to_n8n(session)
                    session["transcript_sent"] = True
                else:
                    print(f"[INFO] Transcript already sent for CallSid={call_sid}, skipping duplicate send")
                sessions.pop(call_sid, None)

        except Exception as e:
            print(f"Error in handle_twilio: {e}")
            traceback.print_exc()

    # Start handling Twilio media as a separate task
    twilio_task = asyncio.create_task(handle_twilio())

    try:
        # Wait for the Twilio handler to complete
        await twilio_task
    except asyncio.CancelledError:
        print("Twilio handler task cancelled")
    finally:
        # Ensure everything is cleaned up
        if session and call_sid:
            sessions.pop(call_sid, None)


#
# Handle Twilio call status updates
#
@app.post("/call-status")
async def call_status(request: Request):
    """
    Endpoint for Twilio call status callbacks.
    Used to track call lifecycle and detect answering machines.
    """
    try:
        # Get the form data
        request_data = await request.form()
        form_data = {key: request_data[key] for key in request_data}
        
        # Convert form data to dict and log
        call_sid = form_data.get('CallSid')
        call_status = form_data.get('CallStatus')
        
        print(f"📞 Call status update for {call_sid}: {call_status}")
        
        # Check for Answering Machine Detection
        answered_by = form_data.get('AnsweredBy')
        if answered_by == 'machine_start' or answered_by == 'machine_end_beep' or answered_by == 'machine_end_silence' or answered_by == 'machine_end_other':
            print(f"🤖 Answering machine detected: {answered_by}")
            
            # Actualizar el end_reason en la sesión para que se envíe a N8N correctamente
            if call_sid in sessions:
                sessions[call_sid]["end_reason"] = f"Answering machine: {answered_by}"
                print(f"[INFO] End reason actualizado: {sessions[call_sid]['end_reason']}")
            
            # Reactivar colgado automático por contestador
            client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
            try:
                # Hang up the call
                client.calls(call_sid).update(status='completed')
                print(f"📞 Call {call_sid} automatically hung up due to answering machine detection")
                return {"status": "success", "message": "Call terminated due to answering machine detection"}
            except Exception as e:
                print(f"❌ Error hanging up call: {e}")
                return {"status": "error", "message": f"Error hanging up call: {e}"}
                
        # If call is completed, update session with final status
        if call_status == 'completed':
            if call_sid in sessions:
                # Guardar la fecha de finalización y el motivo en la sesión
                import pytz
                madrid_tz = pytz.timezone('Europe/Madrid')
                sessions[call_sid]["end_time"] = datetime.now(madrid_tz).isoformat()
                sessions[call_sid]["end_reason"] = form_data.get('CallStatus', 'completed')
                print(f"[INFO] Call {call_sid} marked as completed at {sessions[call_sid]['end_time']}")
                
                # Calcular duración como diferencia entre inicio y fin
                try:
                    start_time = sessions[call_sid].get("start_time")
                    end_time = sessions[call_sid]["end_time"]
                    
                    if start_time:
                        start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                        end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
                        duration_seconds = (end_dt - start_dt).total_seconds()
                        
                        # Formato min:sec
                        minutes = int(duration_seconds // 60)
                        seconds = int(duration_seconds % 60)
                        sessions[call_sid]["duration"] = f"{minutes}m {seconds}s"
                        print(f"[INFO] Call duration calculated: {sessions[call_sid]['duration']}")
                except Exception as e:
                    print(f"[ERROR] Error calculating call duration: {e}")
                    sessions[call_sid]["duration"] = "Error calculando"
            else:
                print(f"⚠️ Call {call_sid} completed but not found in sessions")
                
        # Return success
        return {"status": "success", "message": "Call status updated"}
    except Exception as e:
        print(f"❌ Error processing call status: {e}")
        traceback.print_exc()
        return {"status": "error", "message": str(e)}


#
# Create an Ultravox serverWebSocket call
#
async def create_ultravox_call(system_prompt: str, first_message: str, session=None) -> str:
    """
    Creates a new Ultravox call in serverWebSocket mode and returns the joinUrl.
    """
    url = "https://api.ultravox.ai/api/calls"
    headers = {
        "X-API-Key": ULTRAVOX_API_KEY,
        "Content-Type": "application/json"
    }

    # Construye el systemPrompt combinando directrices y la frase inicial personalizada
    from datetime import datetime as dt
    madrid_tz = None
    try:
        import pytz
        madrid_tz = pytz.timezone('Europe/Madrid')
        now = dt.now(madrid_tz).strftime('%Y-%m-%d %H:%M:%S %z')
    except Exception:
        now = dt.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # Obtener la fecha actual para el prompt
    current_date = dt.now().strftime('%Y-%m-%d')
    
    system_prompt_with_intro = (
        f"{system_prompt}\n\nIMPORTANTE: Inicia la llamada diciendo exactamente y como primera frase: '{first_message}'. "
        f"Después, sigue TODAS las instrucciones y preguntas del prompt anterior, en el orden y forma indicados. "
        f"No improvises, no añadas preguntas ni repitas tu presentación. Espera SIEMPRE respuesta antes de pasar a la siguiente pregunta. "
        f"Recuerda: tu objetivo es obtener toda la información clave y cumplir todas las directrices de comunicación, tono y objeciones que aparecen en el prompt. "
        f"IMPORTANTE PARA AGENDAR: Interpreta días como 'lunes', 'martes', etc., siempre como el próximo día de la semana que venga después de la fecha actual. "
        f"La fecha actual del servidor es: {current_date}. Por ejemplo, si hoy es sábado 3 de mayo de 2025 y el cliente dice 'lunes', "
        f"debes interpretar eso como lunes 5 de mayo de 2025, NO como martes 6 de mayo. Usa siempre la fecha correcta para el día de la semana mencionado."
    )
    payload = {
        "systemPrompt": system_prompt_with_intro,
        "model": ULTRAVOX_MODEL,
        "voice": ULTRAVOX_VOICE,
        "temperature":0.1,
        "recordingEnabled": True,  # CORRECTO para habilitar grabación
        "initialMessages": [
            {
                "role": "MESSAGE_ROLE_USER",
                "text": "[La llamada ha sido conectada]"
            }
        ],
        "medium": {
            "serverWebSocket": {
                "inputSampleRate": ULTRAVOX_SAMPLE_RATE,   
                "outputSampleRate": ULTRAVOX_SAMPLE_RATE,   
                "clientBufferSizeMs": ULTRAVOX_BUFFER_SIZE
            }
        },
        "selectedTools": [  # Herramientas temporales para la sesión
            {
                "temporaryTool": {
                    "modelToolName": "question_and_answer",
                    "description": "Get answers to customer questions especially about AI employees",
                    "dynamicParameters": [
                        {
                            "name": "question",
                            "location": "PARAMETER_LOCATION_BODY",
                            "schema": {
                                "type": "string",
                                "description": "Question to be answered"
                            },
                            "required": True
                        }
                    ],
                    "timeout": "20s",
                    "client": {},
                },
            },
            {
                "temporaryTool": {
                    "modelToolName": "schedule_meeting",
                    "description": "Schedule a meeting for a customer. Returns a message indicating whether the booking was successful or not.",
                    "dynamicParameters": [
                        {
                            "name": "name",
                            "location": "PARAMETER_LOCATION_BODY",
                            "schema": {
                                "type": "string",
                                "description": "Customer's name"
                            },
                            "required": True
                        },
                        {
                            "name": "datetime",
                            "location": "PARAMETER_LOCATION_BODY",
                            "schema": {
                                "type": "string",
                                "description": "Meeting Datetime"
                            },
                            "required": True
                        },
                        {
                            "name": "location",
                            "location": "PARAMETER_LOCATION_BODY",
                            "schema": {
                                "type": "string",
                                "description": "Calendar ID"
                            },
                            "required": True
                        },
                        {
                            "name": "purpose",
                            "location": "PARAMETER_LOCATION_BODY",
                            "schema": {
                                "type": "string",
                                "description": "Meeting purpose"
                            },
                            "required": True
                        }
                    ],
                    "timeout": "20s",
                    "client": {},
                },
            }
        ]
    }

    print("Creating Ultravox call with payload:", json.dumps(payload, indent=2))  # Enhanced logging

    try:
        print(f"[DEBUG] Enviando solicitud a Ultravox API: {url}")
        print(f"[DEBUG] Headers: {headers}")
        resp = requests.post(url, headers=headers, json=payload, timeout=30)  # Aumenta timeout
        resp.raise_for_status()
        body = resp.json()
        print(f"[DEBUG] Respuesta de Ultravox API: {body}")
        call_id = body.get("callId")
        if session is not None and call_id:
            session["ultravox_call_id"] = call_id
            print(f"[DEBUG] Ultravox callId almacenado en session: {call_id}")
        join_url = body.get("joinUrl", "")
        return join_url
    except Exception as e:
        print(f"[ERROR] Error creando llamada Ultravox: {e}")
        return ""


def get_ultravox_recording_url(session, call_id):
    """
    Construye la URL correcta para la grabación de Ultravox.
    SOLO utiliza el UUID de Ultravox (ultravox_call_id o call_id si es UUID válido).
    NUNCA usa el CallSid de Twilio (CAxxxxxx) para la URL de grabación.
    """
    import re
    import uuid
    try:
        # 1. Buscar el UUID de Ultravox en la sesión (más fiable)
        ultravox_uuid = session.get("ultravox_call_id", None)
        print(f"[DEBUG] get_ultravox_recording_url: ultravox_call_id extraído de session: {ultravox_uuid}")
        
        # 2. Si no está en la sesión, verificar si call_id es un UUID válido
        if not ultravox_uuid and call_id:
            try:
                # Verificar si es un UUID válido
                uuid_obj = uuid.UUID(call_id)
                ultravox_uuid = str(uuid_obj)
                print(f"[DEBUG] get_ultravox_recording_url: call_id es un UUID válido: {ultravox_uuid}")
            except ValueError:
                # No es un UUID válido, probablemente es un CallSid de Twilio
                print(f"[DEBUG] get_ultravox_recording_url: call_id no es un UUID válido: {call_id}")
                ultravox_uuid = None
        
        # 3. Construir la URL solo si tenemos un UUID válido
        if ultravox_uuid:
            # CORRECCIÓN: Cambiar /recordings/ a /calls/ en la URL
            recording_url = f"https://app.ultravox.ai/calls/{ultravox_uuid}"
            print(f"[DEBUG] get_ultravox_recording_url: URL de grabación construida: {recording_url}")
            return recording_url
        else:
            print("[WARN] get_ultravox_recording_url: No se pudo obtener un UUID válido para la grabación")
            return ""
    except Exception as e:
        print(f"[ERROR] Error en get_ultravox_recording_url: {e}")
        return ""


#
# Handle "question_and_answer" via Pinecone
#
async def handle_question_and_answer(uv_ws, invocationId: str, question: str):
    try:
        pc = Pinecone(api_key=PINECONE_API_KEY)
        assistant = pc.assistant.Assistant(assistant_name="rag-tool")

        msg = Message(content=question)
        chunks = assistant.chat(messages=[msg], stream=True)

        # Collect entire answer
        answer_message = ""
        for chunk in chunks:
            if chunk and chunk.type == "content_chunk":
                answer_message += chunk.delta.content

        # Respond back to Ultravox
        tool_result = {
            "type": "client_tool_result",
            "invocationId": invocationId,
            "result": answer_message,
            "response_type": "tool-response"
        }
        await uv_ws.send(json.dumps(tool_result))
    except Exception as e:
        print(f"Error in Q&A tool: {e}")
        # Send error result back to the agent
        error_result = {
            "type": "client_tool_result",
            "invocationId": invocationId,
            "error_type": "implementation-error",
            "error_message": "An error occurred while processing your request."
        }
        await uv_ws.send(json.dumps(error_result))


#
# Handle "schedule_meeting" calls
#
async def handle_schedule_meeting(uv_ws, session, invocationId: str, parameters):
    """
    Uses N8N to finalize a meeting schedule.
    
    NOTA SOBRE EXTRACCIÓN DE FECHAS: El problema de que Ultravox extraiga un día incorrecto 
    (por ejemplo, martes en lugar de lunes) es una limitación del sistema de extracción de 
    entidades de Ultravox, no de este código Python. Cuando Ultravox envía "2025-05-06 15:00:00" 
    (Martes) a pesar de que el usuario dijo "lunes", este código procesa correctamente el valor 
    recibido. No hay una solución simple desde Python para forzar a Ultravox a extraer el día 
    correcto si su sistema de extracción se equivoca. La única mitigación es la nota en el prompt 
    del sistema que intenta guiar la interpretación de fechas relativas.
    """
    try:
        name = parameters.get("name")
        purpose = parameters.get("purpose")
        datetime_str = parameters.get("datetime")
        location = parameters.get("location")
        
        # Email es opcional, si no está presente usamos el teléfono
        email = parameters.get("email", "")
        
        print(f"[DEBUG RUTA 3] Received schedule_meeting parameters: name={name}, purpose={purpose}, datetime={datetime_str}, location={location}, email={email}")
        print(f"[DEBUG] handle_schedule_meeting: Raw datetime received from Ultravox: {datetime_str}")

        # Validate parameters
        if not all([name, purpose, datetime_str, location]):
            missing_params = []
            if not name: missing_params.append("name")
            if not purpose: missing_params.append("purpose")
            if not datetime_str: missing_params.append("datetime")
            if not location: missing_params.append("location")
            print(f"[ERROR RUTA 3] Missing parameters for schedule_meeting: {missing_params}")
            raise ValueError(f"Missing parameters for schedule_meeting: {missing_params}")
        
        # Usar la nueva función para limpiar y formatear la fecha
        formatted_datetime = format_datetime_for_calendar(datetime_str)
        print(f"[DEBUG] handle_schedule_meeting: After format_datetime_for_calendar: {formatted_datetime}")
        print(f"[DEBUG RUTA 3] Formatted datetime for calendar: {formatted_datetime}")
        
        # Calcular end_datetime (30 minutos después) con mismo formato y zona horaria
        from datetime import datetime, timedelta
        
        try:
            # Parsear start_time y añadir 30 minutos
            dt_obj = datetime.fromisoformat(formatted_datetime)
            end_dt_obj = dt_obj + timedelta(minutes=30)
            
            # Mantener el mismo formato de timezone que el start_time
            end_formatted = end_dt_obj.strftime("%Y-%m-%dT%H:%M:%S")
            
            print(f"[DEBUG RUTA 3] Calculated end time: {end_formatted}")
            
            # Extraer hora para mensajes en formato natural
            hour = dt_obj.hour
            minute = dt_obj.minute
            day = dt_obj.day
            month = dt_obj.month
            
            # Formatear hora natural (ej: "5 de la tarde")
            natural_hour = format_hour_naturally(hour)
            time_string = f"{natural_hour}"
            if minute != 0:
                time_string += f" y {minute} minutos"
                
            # Fecha en formato natural
            months = ["enero", "febrero", "marzo", "abril", "mayo", "junio", 
                      "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
            date_string = f"{day} de {months[month-1]}"
            
            natural_datetime = f"{date_string} a las {time_string}"
            print(f"[INFO] Fecha y hora en formato natural: {natural_datetime}")
        except Exception as e:
            print(f"[WARNING] Error procesando fecha y hora: {e}")
            natural_datetime = datetime_str  # Fallback en caso de error
            end_formatted = formatted_datetime  # Fallback sin sumar 30 min
            
        # Usar CALENDAR_EMAIL directamente como ID del calendario
        calendar_id = CALENDAR_EMAIL

        # IMPORTANTE: Preparar ambas fechas con la misma zona horaria
        
        # Añadir explícitamente la zona horaria de España (+02:00 en verano)
        # El problema era que al no especificar zona horaria, Google Calendar sumaba 2 horas extra
        
        # Asegurarse de que no tenga ya una zona horaria
        clean_datetime = formatted_datetime
        if '+' in clean_datetime:
            clean_datetime = clean_datetime.split('+')[0]
        if 'Z' in clean_datetime:
            clean_datetime = clean_datetime.replace('Z', '')
            
        # Añadir explícitamente zona horaria Madrid
        formatted_datetime_with_tz = f"{clean_datetime}+02:00" 
        
        # Hacer lo mismo con la fecha de fin
        clean_end = end_formatted
        if '+' in clean_end:
            clean_end = clean_end.split('+')[0]
        if 'Z' in clean_end:
            clean_end = clean_end.replace('Z', '')
            
        end_formatted_with_tz = f"{clean_end}+02:00"
        print(f"[DEBUG] handle_schedule_meeting: Final datetime and end_datetime for n8n payload: start={formatted_datetime_with_tz}, end={end_formatted_with_tz}")
        
        data = {
            "name": name,
            "email": email or session.get("callerEmail", ""),
            "phone": session.get("callerNumber", ""),
            "datetime": formatted_datetime_with_tz,  # Con zona horaria explícita
            "end_datetime": end_formatted_with_tz,   # Con zona horaria explícita
            "location": location,
            "purpose": purpose
        }
        
        # Fire off the scheduling request to N8N
        payload = {
            "route": "3",
            "number": session.get("callerNumber", "Unknown"),
            "data": data
        }
        print(f"[DEBUG RUTA 3] Sending payload to N8N: {json.dumps(payload, indent=2)}")
        
        # Asegurarse de que el webhook está configurado
        if not N8N_WEBHOOK_URL:
            print("[ERROR RUTA 3] N8N_WEBHOOK_URL no está configurado.")
            booking_message = "Lo siento, pero no podemos agendar la llamada en este momento por un problema técnico. ¿Te gustaría que te diera el número de contacto directo para que puedas llamar cuando te convenga?"
            success = False
        else:
            # Enviar la solicitud a N8N
            try:
                response = requests.post(N8N_WEBHOOK_URL, json=payload)
                response.raise_for_status()  # Lanzar excepción para códigos de error HTTP
                
                # Validar respuesta
                if response.status_code == 200:
                    try:
                        # Intentar parsear como JSON
                        booking_response = response.json()
                        message = booking_response.get("message")
                        
                        if message and "confirmed" in message.lower():
                            # Éxito: agendar cita con formato de hora natural
                            booking_message = f"¡Perfecto! Ya he dejado agendada tu llamada con María del Carmen Centeno para el {natural_datetime}. Ella te explicará todos los detalles del programa premium."
                            success = True
                        else:
                            # Error o no disponible
                            booking_message = f"Lo siento, pero parece que ese horario no está disponible. ¿Te gustaría probar con otro horario o prefieres que te dé el número de María del Carmen para que la llames directamente cuando te venga bien?"
                            success = False
                    except Exception as e:
                        # Error parseando JSON
                        print(f"[ERROR RUTA 3] Error parseando respuesta: {e}")
                        booking_message = "Lo siento, no pudimos completar la reserva debido a un problema técnico. ¿Te gustaría que te diera el número de contacto de María del Carmen Centeno para que la contactes directamente?"
                        success = False
                else:
                    # Error de respuesta no 200
                    print(f"[ERROR RUTA 3] Error en respuesta de N8N: {response.status_code} - {response.text}")
                    booking_message = "Lo siento, no pudimos completar la reserva debido a un problema técnico. ¿Te gustaría que te diera el número de contacto de María del Carmen Centeno para que la contactes directamente?"
                    success = False
            except Exception as e:
                # Error de conexión
                print(f"[ERROR RUTA 3] Error conectando con N8N: {e}")
                booking_message = "Lo siento, no pudimos completar la reserva debido a un problema técnico. ¿Te gustaría que te diera el número de contacto de María del Carmen Centeno para que la contactes directamente?"
                success = False
        
        # Send the result back to the Ultravox agent
        tool_result = {
            "type": "client_tool_result",
            "invocationId": invocationId,
            "result": booking_message,
            "response_type": "tool-response"
        }
        await uv_ws.send(json.dumps(tool_result))
        print(f"[DEBUG RUTA 3] Sent schedule_meeting result to Ultravox: {booking_message}")
        
        return success
    except Exception as e:
        # En caso de error, manejo global
        error_message = f"Lo siento, ha habido un problema al intentar agendar la llamada. ¿Te gustaría que te diera el contacto de María del Carmen Centeno para que puedas contactarla directamente cuando te venga bien?"
        tool_result = {
            "type": "client_tool_result",
            "invocationId": invocationId,
            "result": error_message,
            "response_type": "tool-response"
        }
        if uv_ws:
            await uv_ws.send(json.dumps(tool_result))
        print("Sent error message for schedule_meeting to Ultravox.")
        print(f"Error in schedule_meeting: {e}")
        traceback.print_exc()
        return False

#
# Send entire transcript to N8N (end of call)
#
async def send_transcript_to_n8n(session):
    print("[DEBUG] Entering send_transcript_to_n8n function")
    try:
        print("[DEBUG RUTA 2] Iniciando envío de transcripción a N8N")
        print("[DEBUG RUTA 2] Contenido de la sesión:", session)
        
        # 1. Obtener valores de los sistemas internos
        telefono = session.get("callerNumber", "Unknown")
        pin_lifeplus = session.get("pin_lifeplus", "No respondido")
        if pin_lifeplus == "No respondido" or not pin_lifeplus:
            if session.get("callDetails", {}).get("parameters", {}).get("PIN_LIFEPLUS"):
                pin_lifeplus = session.get("callDetails").get("parameters").get("PIN_LIFEPLUS")
            elif session.get("http_request_data", {}).get("parameters", []):
                parameters = session.get("http_request_data").get("parameters", [])
                for param in parameters:
                    if isinstance(param, dict) and param.get("name") == "PIN_LIFEPLUS":
                        pin_lifeplus = param.get("value")
                        break
            elif session.get("callDetails", {}).get("originalRequest", {}).get("PIN_LIFEPLUS"):
                pin_lifeplus = session.get("callDetails").get("originalRequest").get("PIN_LIFEPLUS")
            elif session.get("callDetails", {}).get("pin_lifeplus"):
                pin_lifeplus = session.get("callDetails").get("pin_lifeplus")
        print(f"[DEBUG RUTA 2] PIN_LIFEPLUS extraído: {pin_lifeplus}")

        from datetime import datetime, timezone
        import re

        start_time = session.get("start_time") or session.get("callDetails", {}).get("startTime", "No respondido")
        end_time = session.get("end_time")
        if not end_time:
            # Always use timezone-aware now (UTC)
            end_time = datetime.now(timezone.utc).isoformat()
        print(f"[DEBUG RUTA 2] START_TIME: {start_time}")
        print(f"[DEBUG RUTA 2] END_TIME: {end_time}")
        duration = session.get("duration", "No respondido")
        if duration == "No respondido":
            try:
                # Usar dateutil.parser para un parsing más robusto de fechas
                import dateutil.parser
                
                # Ensure both times are strings
                st = start_time
                et = end_time
                
                # Parse dates with dateutil for better robustness
                if isinstance(st, str):
                    try:
                        start_dt = dateutil.parser.parse(st)
                    except Exception as e:
                        print(f"[ERROR] Error parsing start_time: {e}")
                        start_dt = datetime.now(timezone.utc) - timedelta(minutes=1)  # Fallback
                else:
                    start_dt = st
                
                if isinstance(et, str):
                    try:
                        end_dt = dateutil.parser.parse(et)
                    except Exception as e:
                        print(f"[ERROR] Error parsing end_time: {e}")
                        end_dt = datetime.now(timezone.utc)  # Fallback
                else:
                    end_dt = et
                
                # Ensure both datetimes are timezone-aware
                if start_dt.tzinfo is None:
                    start_dt = start_dt.replace(tzinfo=timezone.utc)
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=timezone.utc)
                
                duration_seconds = (end_dt - start_dt).total_seconds()
                
                # Formato min:sec
                minutes = int(duration_seconds // 60)
                seconds = int(duration_seconds % 60)
                duration = f"{minutes}m {seconds}s"
                
                # Guardar duración en la sesión
                session["duration"] = duration
                session["duration_seconds"] = duration_seconds
                
                print(f"[DEBUG RUTA 2] Duración calculada: {duration} ({duration_seconds} segundos)")
            except Exception as e:
                print(f"[ERROR] Error calculando duración: {e}")
                traceback.print_exc()
                duration = "Error calculando duración"
        
        # Obtener end_reason si existe, o usar un valor por defecto
        end_reason = session.get("end_reason", "completed")
        print(f"[DEBUG RUTA 2] END_REASON: {end_reason}")
        
        call_id = session.get("call_id") or session.get("ultravox_call_id") or session.get("call_sid", "desconocido")
        print(f"[DEBUG RUTA 2] CALL_ID: {call_id}")
        ultravox_url = get_ultravox_recording_url(session, call_id)
        if ultravox_url is None:
            print("[WARN RUTA 2] ULTRAVOX_RECORDING_URL es None, se asignará cadena vacía.")
            ultravox_url = ""
        else:
            ultravox_url = ultravox_url.rstrip(";")
        print(f"[DEBUG RUTA 2] ULTRAVOX_RECORDING_URL: {ultravox_url}")
        
        summary = session.get("summary", "") or session.get("ultravox_data", {}).get("summary", "")
        nombre_persona = session.get("nombre_persona", "") or "No extraído"
        payload = {
            "route": "2",
            "number": telefono,
            "TRANSCRIPCION_FINAL": session.get("transcript", ""),
            "TELEFONO": telefono,
            "PIN_LIFEPLUS": pin_lifeplus,
            "START_TIME": start_time,
            "END_TIME": end_time,
            "DURACION": duration,
            "CALL_ID": call_id,
            "ULTRAVOX_RECORDING_URL": ultravox_url,
            "End_Reason": end_reason,
            "SUMMARY": summary,
            "NOMBRE_PERSONA": nombre_persona
        }
        print("[DEBUG RUTA 2] Payload completo a enviar a n8n:")
        import json
        print(json.dumps(payload, indent=2))
        if N8N_WEBHOOK_URL:
            try:
                print(f"[DEBUG RUTA 2] Attempting POST to N8N: {N8N_WEBHOOK_URL}")
                import requests
                response = requests.post(N8N_WEBHOOK_URL, json=payload)
                print(f"[DEBUG RUTA 2] N8N webhook response status code: {response.status_code}")
                if response.status_code == 200:
                    print("[DEBUG RUTA 2] Envío completado con éxito")
                    print("[DEBUG] Exiting send_transcript_to_n8n function with success")
                    return True
                else:
                    print(f"[ERROR RUTA 2] La respuesta no fue 200 OK: {response.status_code}")
                    print(f"[ERROR RUTA 2] Respuesta completa: {response.text}")
                    print("[DEBUG] Exiting send_transcript_to_n8n function with POST error")
                    return False
            except Exception as e:
                print(f"[ERROR RUTA 2] Error al hacer POST a n8n: {str(e)}")
                import traceback
                traceback.print_exc()
                print("[DEBUG] Exiting send_transcript_to_n8n function with exception")
                return False
        else:
            print("[ERROR RUTA 2] N8N_WEBHOOK_URL no está configurado")
            print("[DEBUG] Exiting send_transcript_to_n8n function with missing URL")
            return False
    except Exception as e:
        print(f"[ERROR RUTA 2] Unhandled exception in send_transcript_to_n8n: {e}")
        import traceback
        traceback.print_exc()
        print("[DEBUG] Exiting send_transcript_to_n8n function with unhandled exception")
        return False

#
# Send data to N8N webhook
#
async def send_to_webhook(payload):
    print("[DEBUG] Entering send_to_webhook function")
    import json
    if not N8N_WEBHOOK_URL:
        print("Error: N8N_WEBHOOK_URL is not set")
        print("[DEBUG] Exiting send_to_webhook function with missing URL")
        return json.dumps({"error": "N8N_WEBHOOK_URL not configured"})
    try:
        print(f"[DEBUG] Sending payload to N8N webhook: {N8N_WEBHOOK_URL}")
        print(f"[DEBUG] Payload: {json.dumps(payload, indent=2)}")
        if 'data' in payload and isinstance(payload['data'], str):
            try:
                payload['data'] = json.loads(payload['data'])
                print(f"[DEBUG] Deserializado campo 'data' de JSON string a objeto: {json.dumps(payload['data'], indent=2)}")
            except json.JSONDecodeError:
                print(f"[DEBUG] El campo 'data' no es JSON válido, se enviará como string")
        import requests
        response = requests.post(
            N8N_WEBHOOK_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        print(f"[DEBUG] N8N webhook response status code: {response.status_code}")
        print(f"[DEBUG] N8N webhook response headers: {response.headers}")
        print(f"[DEBUG] N8N webhook response text: {response.text}")
        if response.status_code != 200:
            print(f"[DEBUG] N8N webhook returned status code {response.status_code}")
            print(f"[DEBUG] Response: {response.text}")
            print("[DEBUG] Exiting send_to_webhook function with POST error")
            return json.dumps({"error": f"N8N webhook returned status {response.status_code}", "response": response.text})
        print("[DEBUG] Exiting send_to_webhook function with success")
        return response.text
    except Exception as e:
        error_msg = f"Error sending data to N8N webhook: {str(e)}"
        print(f"[DEBUG] {error_msg}")
        import traceback
        traceback.print_exc()
        print("[DEBUG] Exiting send_to_webhook function with exception")
        return json.dumps({"error": error_msg})

#
# Gather input from Twilio
#
@app.post("/gather-input")
async def gather_input(request: Request):
    """
    Endpoint para manejar la respuesta del usuario cuando usa <Gather> en TwiML.
    Recibe la entrada del usuario y puede continuar la conversación.
    """
    try:
        # Obtener datos del formulario
        form_data = await request.form()
        data = {key: form_data[key] for key in form_data}
        
        # Obtener información clave
        call_sid = data.get('CallSid')
        speech_result = data.get('SpeechResult')
        digits = data.get('Digits')
        
        print(f"📞 Gather input received for call {call_sid}")
        print(f"🗣️ Speech result: {speech_result}")
        print(f"🔢 Digits: {digits}")
        
        # Guardar la respuesta en la sesión si existe
        if call_sid in sessions:
            if speech_result:
                sessions[call_sid]["user_response"] = speech_result
            elif digits:
                sessions[call_sid]["user_response"] = digits
                
            # Actualizar transcripción
            if speech_result:
                sessions[call_sid]["transcript"] += f"\nUsuario: {speech_result}\n"
        
        # Responder con TwiML para mantener la llamada abierta más tiempo
        twiml_response = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice" language="es-ES">Gracias por su respuesta. Manteniendo la llamada activa.</Say>
    <Pause length="60"/>
</Response>"""
        
        return Response(content=twiml_response, media_type="text/xml")
        
    except Exception as e:
        print(f"❌ Error processing gather input: {e}")
        traceback.print_exc()
        
        # En caso de error, mantener la llamada abierta
        twiml_response = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Pause length="30"/>
</Response>"""
        return Response(content=twiml_response, media_type="text/xml")

#
# Run app via Uvicorn
#
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
print("Cambio visible para commit")
