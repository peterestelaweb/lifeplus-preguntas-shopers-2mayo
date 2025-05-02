# Rutas del Webhook a n8n

Este documento describe las diferentes rutas y parámetros que se envían desde la aplicación Ultravox & Twilio Voice AI Agent a n8n.

## URL del Webhook

```
https://appn8n.peterestela.com/webhook/538b1cc6-abaf-4507-a73b-9ca127b37cff
```

## Rutas Disponibles

### Ruta 1: Inicio de Llamada Entrante

Cuando se recibe una llamada entrante, el sistema envía esta información para obtener el primer mensaje que el asistente dirá.

```json
{
  "route": "1",
  "number": "[número del llamante]",
  "data": "empty"
}
```

**Respuesta esperada de n8n:**
Un objeto JSON que contiene el primer mensaje que el asistente debe decir:

```json
{
  "firstMessage": "Mensaje inicial que el asistente dirá"
}
```

### Ruta 2: Finalización de Llamada (Transcripción)

Al finalizar una llamada, el sistema envía la transcripción completa de la conversación.

```json
{
  "route": "2",
  "number": "[número del llamante]",
  "data": "[transcripción completa de la conversación]"
}
```

### Ruta 3: Programación de Reuniones

Cuando el usuario solicita programar una reunión, el sistema envía los detalles necesarios.

```json
{
  "route": "3",
  "number": "[número del llamante]",
  "data": {
    "name": "[nombre del cliente]",
    "email": "[email del cliente]",
    "purpose": "[propósito de la reunión]",
    "datetime": "[fecha y hora de la reunión]",
    "calendar_id": "[ID del calendario según la ubicación]"
  }
}
```

**Respuesta esperada de n8n:**
Un objeto JSON que contiene un mensaje de confirmación:

```json
{
  "message": "Mensaje de confirmación o error sobre la programación"
}
```

## Implementación en el Código

Las funciones principales que manejan estas comunicaciones son:

1. `incoming_call` - Maneja las llamadas entrantes (Ruta 1)
2. `send_transcript_to_n8n` - Envía la transcripción al finalizar (Ruta 2)
3. `handle_schedule_meeting` - Maneja la programación de reuniones (Ruta 3)
4. `send_to_webhook` - Función general que envía los datos a n8n

Todas las comunicaciones se realizan mediante solicitudes POST con encabezados `Content-Type: application/json`.

## Actualización de la Ruta 2: Finalización de Llamada con Respuestas Específicas

A partir de la última actualización, la Ruta 2 ahora incluye las respuestas específicas a cada una de las 6 preguntas de la encuesta, además de la transcripción completa:

```python
await send_to_webhook({
    "route": "2",
    "number": session.get("callerNumber", "Unknown"),
    "data": session["transcript"],
    "respuesta_nombre": respuesta1,
    "respuesta_ultima_vez": respuesta2,
    "respuesta_aspectos_positivos": respuesta3,
    "respuesta_aspectos_mejorar": respuesta4,
    "respuesta_quien_recomendo": respuesta5,
    "respuesta_valoracion": respuesta6
})
```

Esto permite a n8n procesar tanto la transcripción completa como las respuestas individuales a cada pregunta de la encuesta.
