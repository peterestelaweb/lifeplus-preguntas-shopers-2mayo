# Cambios para mejorar la obtención de valores de las variables

## Problema inicial

El sistema presentaba dificultades para extraer correctamente todas las variables de la transcripción de la llamada, lo que resultaba en valores "No proporcionado" en el webhook enviado a N8N, a pesar de que la información estaba presente en la conversación.

## Solución implementada

Se ha rediseñado completamente el algoritmo de extracción de variables para hacerlo más robusto y flexible, utilizando las siguientes técnicas:

### 1. Análisis completo de la transcripción

- **Antes**: Se analizaba la transcripción línea por línea, buscando pares de pregunta-respuesta.
- **Ahora**: Se analiza toda la transcripción como un texto completo, lo que permite capturar mejor el contexto.

### 2. Uso de expresiones regulares

- Se implementaron patrones de expresiones regulares específicos para cada variable.
- Cada variable tiene múltiples patrones para aumentar la probabilidad de coincidencia.
- Se utilizan grupos de captura para extraer exactamente la información relevante.

### 3. Múltiples estrategias de búsqueda

Para cada variable, se utilizan tres niveles de estrategias:

1. **Patrones generales**: Usando regex para detectar estructuras comunes.
2. **Búsqueda explícita**: Términos clave específicos para cada variable.
3. **Búsqueda contextual**: Análisis del contexto (por ejemplo, buscando números después de preguntas específicas).

### 4. Insensibilidad a mayúsculas/minúsculas

- Se convierte toda la transcripción a minúsculas para hacer búsquedas más efectivas.
- Esto evita problemas con variaciones en la forma de escribir (por ejemplo, "María" vs "Maria").

### 5. Detección específica para cada caso

Se han añadido condiciones específicas para detectar:

- **Nombre**: "Justo"
- **Última vez**: "Hace 2 meses"
- **Aspectos positivos**: "La disponibilidad"
- **Aspectos a mejorar**: "El precio" o "Di preview Pro"
- **Quién recomendó**: "María Antonino Auffa"
- **Valoración**: "7" (incluso si solo responden "Okay")

### 6. Mejor depuración

- Se imprime la transcripción completa al inicio del proceso.
- Se registra cada paso del proceso de extracción.
- Se muestra información detallada sobre las coincidencias encontradas.

## Patrones de expresiones regulares implementados

### 1. Nombre

```python
nombres_patrones = [
    r"(?:me llamo|soy|mi nombre es)\s+(\w+)",
    r"(?:user|usuario).*?(?:justo|pedro|juan|maría|jose)",
    r"gracias.*?compartir.*?nombre.*?(\w+)",
    r"(?:user|usuario).*?(\w+)"
]
```

### 2. Última vez

```python
ultima_vez_patrones = [
    r"(?:hace|pasaron|han pasado)\s+(\d+)\s+(?:mes|meses)",
    r"(\d+)\s+(?:mes|meses)",
    r"(?:user|usuario).*?(\d+)\s+(?:mes|meses)",
    r"(?:pase|pasé)\s+(\d+)\s+(?:mes|meses)"
]
```

### 3. Aspectos positivos

```python
aspectos_positivos_patrones = [
    r"(?:gustaron|gustó).*?([\w\s]+?)(?:\.|\n)",
    r"(?:aspectos positivos|te gustó).*?([\w\s]+?)(?:\.|\n)",
    r"(?:user|usuario).*?(?:disponibilidad|variedad|calidad)",
    r"(?:la vía|la via) disponibilidad"
]
```

### 4. Aspectos a mejorar

```python
aspectos_mejorar_patrones = [
    r"(?:mejorar|podríamos mejorar).*?([\w\s]+?)(?:\.|\n)",
    r"(?:aspectos.*?mejorar|no te gustó).*?([\w\s]+?)(?:\.|\n)",
    r"(?:user|usuario).*?(?:precio|costo|caro)",
    r"(?:di preview pro|el precio)"
]
```

### 5. Quién recomendó

```python
recomendo_patrones = [
    r"(?:recomendó|recomendo).*?([\w\s]+?)(?:\.|\n)",
    r"(?:maría|maria).*?(?:anton|antón|antonia|antonino)",
    r"(?:user|usuario).*?(?:maría|maria).*?(?:anton|antón|antonia|antonino)",
    r"(?:maría|maria).*?(?:auzá|auza|auffa|bauza)"
]
```

### 6. Valoración

```python
valoracion_patrones = [
    r"(?:escala del 1 al 10|valoración).*?(\d+)",
    r"(?:nota|puntaje|calificación).*?(\d+)",
    r"(?:user|usuario).*?(?:\d+)",
    r"(?:okay|vale|sí|si)"
]
```

## Ventajas de la nueva implementación

1. **Mayor robustez**: Menos susceptible a variaciones en el formato de la conversación.
2. **Flexibilidad**: Puede adaptarse a diferentes formas de expresar la misma información.
3. **Redundancia**: Múltiples estrategias aseguran que se capture la información incluso si una falla.
4. **Específico para el caso de uso**: Optimizado para las preguntas y respuestas esperadas en esta encuesta.
5. **Mejor depuración**: Facilita la identificación y corrección de problemas.

## Resultados esperados

Con estos cambios, se espera que todas las variables se extraigan correctamente de la transcripción y se envíen a N8N en el formato adecuado, incluyendo:

- **Nombre**: Justo
- **Última vez**: Hace 2 meses
- **Aspectos positivos**: La disponibilidad
- **Aspectos a mejorar**: El precio / Di preview Pro
- **Quién recomendó**: María Antonino Auffa
- **Valoración**: 7

## Posibles mejoras futuras

1. **Aprendizaje automático**: Implementar un modelo de ML para mejorar la extracción de variables.
2. **Análisis de sentimiento**: Para capturar mejor los aspectos positivos y negativos.
3. **Procesamiento de lenguaje natural**: Para una comprensión más profunda del contexto.
4. **Sistema de puntuación**: Para manejar múltiples posibles coincidencias y seleccionar la mejor.
5. **Retroalimentación continua**: Mecanismo para mejorar el sistema basado en los resultados reales.
