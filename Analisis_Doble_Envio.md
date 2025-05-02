# Análisis del Flujo ULTRAVOX FAST API OUTBOUND y Doble Envío de Transcripción

## 1. Resumen de las rutas en n8n y cómo se procesan

### Rutas del Webhook
- **Ruta 1**: Inicio de llamada entrante (obtención del primer mensaje)
- **Ruta 2**: Finalización de llamada (transcripción completa)
- **Ruta 3**: Programación de reuniones

### Cómo funciona el Switch en n8n
El nodo `Switch` en tu workflow de n8n deriva la ejecución según el valor de `route` que llega en el body del webhook:
- `"route": "1"` → Rama “Get Call History”
- `"route": "2"` → Rama “Add new call Summary”
- `"route": "3"` → Rama “Book a Call”

---

## 2. Qué hace cada camino en n8n

### Ruta 1: Get Call History
- Busca en Google Sheets si existe historial del número (`phone_number`).
- Genera el primer mensaje personalizado (o uno genérico si no hay historial).
- Devuelve el mensaje a la API para que lo lea el agente.

### Ruta 2: Add new call Summary
- Extrae el nombre y resume la transcripción usando LLM (nodo “Extract Name and Summarise”).
- Guarda el nombre, transcript y resumen en Google Sheets.
- Devuelve un 200 OK.

### Ruta 3: Book a Call
- Procesa los datos de la reunión (nombre, email, propósito, fecha/hora, calendar_id).
- Consulta disponibilidad, agenda la cita y responde con confirmación o alternativa.

---

## 3. Qué hace tu código Python (main.py y prompts.py)

### main.py
- **Al inicio de la llamada**:
  - Recibe el webhook de Twilio.
  - Envía `"route": "1"` a n8n para obtener el primer mensaje.
  - Guarda la sesión y comienza el streaming de audio.
- **Durante la llamada**:
  - Procesa el audio y la conversación.
- **Al finalizar la llamada**:
  - Llama a la función `send_transcript_to_n8n(session)`.
  - Esta función envía `"route": "2"`, el número y la transcripción completa a n8n.

### prompts.py
- Define los mensajes de sistema y plantillas para la IA.
- No controla directamente el envío de datos a n8n, pero sí cómo se formulan los mensajes y resúmenes.

---

## 4. Por qué se envía dos veces la información por la ruta 2

### Posibles causas:
1. **El código llama dos veces a la función de envío de transcripción**:
   - Puede haber dos puntos en el flujo donde se llama a `send_transcript_to_n8n(session)`.
   - Por ejemplo, uno al detectar el fin de llamada (evento de Twilio), y otro por lógica interna (timeout, error, etc).

2. **Twilio puede estar haciendo dos POST al endpoint de cierre de llamada**:
   - Si tienes configurado el webhook de status de llamada y el webhook de fin de llamada apuntando al mismo endpoint, ambos pueden disparar el mismo código.

3. **La función de cierre puede estar siendo llamada tanto por el evento WebSocket como por el evento HTTP**.

---

## 5. ¿Cómo confirmarlo?

- Busca todas las llamadas a `send_transcript_to_n8n` y revisa en qué condiciones se ejecutan.
- Busca si hay varios endpoints (por ejemplo, `/call_status`, `/media_stream`, etc.) que al cerrar la llamada ejecutan la función de envío.
- Añade logs para ver desde dónde se dispara cada llamada.
- En n8n, revisa si los dos envíos llegan con timestamps muy cercanos y si los headers de ambos POST son iguales.

---

## 6. Recomendaciones para evitar el doble envío

1. **En el código Python**:
   - Asegúrate de que solo se llama una vez a `send_transcript_to_n8n` por llamada.
   - Usa un flag en la sesión para marcar si ya se envió la transcripción.

2. **En Twilio**:
   - Revisa la configuración de webhooks para que solo uno dispare el cierre.

3. **En n8n**:
   - Puedes filtrar duplicados usando el `callSid` o un hash de la transcripción antes de guardar.

---

## 7. Resumen visual del flujo

```
Twilio llama a FastAPI
   ↓
FastAPI inicia llamada → route: "1" → n8n (primer mensaje)
   ↓
Conversación, streaming...
   ↓
Fin de llamada (evento) → route: "2" → n8n (transcripción)
   ↓
(¡Aquí puede estar el doble disparo!)
```

---

## 8. Checklist de solución

- [ ] ¿Hay más de una llamada a `send_transcript_to_n8n` por cada llamada de usuario?
- [ ] ¿Hay más de un evento de cierre de llamada en Twilio?
- [ ] ¿Puedes poner un print/log en cada llamada a la función para ver desde dónde se dispara?
- [ ] ¿Puedes guardar en la sesión un flag tipo `transcript_sent = True`?

---

**¿Quieres ayuda para buscar exactamente en tu código dónde ocurre el doble envío? Si me das permiso, puedo revisar el archivo main.py para localizar todas las llamadas y sugerir el fix exacto.**
