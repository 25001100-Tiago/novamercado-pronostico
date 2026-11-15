# Reporte de auditoría — NovaMercado

- Ejecutada: 2026-11-15 01:04:04 (duración 2 min)
- Arranque desde cero inmediatamente antes de esta auditoría (`docker compose down -v` y luego
  `docker compose up -d --build`): `GET /health` → 200 `{"estado":"ok"}` a los **70 s**
  (carga de 83 052 filas + entrenamiento y registro del primer modelo incluidos).
- API: `http://localhost:8000` · MLflow: `http://localhost:5000`
- Resultado: **85/85 chequeos aprobados** — **TODAS LAS PRUEBAS PASAN**

| # | Prueba | Resultado | Chequeos |
|---|---|---|---|
| 1 | Salud inicial y modelo | ✅ pasa | 4/4 |
| 2 | Contrato y defensa ante errores | ✅ pasa | 57/57 |
| 3 | Operación diaria e idempotencia de observaciones | ✅ pasa | 2/2 |
| 4 | Ciclo de reentrenamiento y hot-reload | ✅ pasa | 8/8 |
| 5 | Caída de MLflow | ✅ pasa | 4/4 |
| 6 | Persistencia de volúmenes (docker compose down / up -d) | ✅ pasa | 10/10 |

## 1. Salud inicial y modelo

- ✅ GET /health → 200 con estado == 'ok'
- ✅ GET /modelo → 200
- ✅ nombre, alias y version son str
- ✅ alias == 'champion'

Notas:
- /health respondió 'ok' tras 0 s de espera

<details><summary>Evidencia (JSON reales)</summary>

**Salud** — `GET /health` → HTTP 200 (2 ms)

Respuesta:
```json
{
  "estado": "ok"
}
```


**Modelo vigente** — `GET /modelo` → HTTP 200 (2 ms)

Respuesta:
```json
{
  "nombre": "novamercado-pronostico",
  "alias": "champion",
  "version": "1"
}
```


</details>

## 2. Contrato y defensa ante errores

- ✅ ejemplos/observacion_valida.json → 200 y calidad 'ok'
- ✅ ejemplos/prediccion_valida.json → 200 y calidad 'ok'
- ✅ ejemplos/prediccion_valida.json: version_modelo str, cantidad_sugerida int >= 0, calidad válida
- ✅ errores/E01_tienda_texto.json → 200 con calidad 'corregido'
- ✅ errores/E01_tienda_texto.json: version_modelo str, cantidad_sugerida int >= 0, calidad válida
- ✅ errores/E02_familia_otra_forma.json → 200 con calidad 'corregido'
- ✅ errores/E02_familia_otra_forma.json: version_modelo str, cantidad_sugerida int >= 0, calidad válida
- ✅ errores/E03_promocion_texto.json → 200 con calidad 'corregido'
- ✅ errores/E03_promocion_texto.json: version_modelo str, cantidad_sugerida int >= 0, calidad válida
- ✅ errores/E04_fecha_formato.json → 200 con calidad 'corregido'
- ✅ errores/E04_fecha_formato.json: version_modelo str, cantidad_sugerida int >= 0, calidad válida
- ✅ errores/E05_faltan_familias.json → 200 con calidad 'advertencia'
- ✅ errores/E05_faltan_familias.json: version_modelo str, cantidad_sugerida int >= 0, calidad válida
- ✅ errores/E06_familia_repetida.json → 200 con calidad 'advertencia'
- ✅ errores/E06_familia_repetida.json: version_modelo str, cantidad_sugerida int >= 0, calidad válida
- ✅ errores/E07_campo_renombrado.json → 200 con calidad 'corregido'
- ✅ errores/E07_campo_renombrado.json: version_modelo str, cantidad_sugerida int >= 0, calidad válida
- ✅ errores/E08_ventas_negativas.json → 422 con detail
- ✅ errores/E09_envio_repetido.json → 200 con calidad 'ok'
- ✅ errores/E10_numero_formato.json → 200 con calidad 'corregido'
- ✅ tienda como texto con prefijo 'tienda_05' → 200 con calidad 'corregido'
- ✅ tienda como texto con prefijo 'tienda_05': version_modelo str, cantidad_sugerida int >= 0, calidad válida
- ✅ tienda como texto ' 5 ' → 200 con calidad 'corregido'
- ✅ tienda como texto ' 5 ': version_modelo str, cantidad_sugerida int >= 0, calidad válida
- ✅ familia con mayúsculas y guion 'Cuidado-Personal' → 200 con calidad 'corregido'
- ✅ familia con mayúsculas y guion 'Cuidado-Personal': version_modelo str, cantidad_sugerida int >= 0, calidad válida
- ✅ familia con tilde 'PANADERÍA' → 200 con calidad 'corregido'
- ✅ familia con tilde 'PANADERÍA': version_modelo str, cantidad_sugerida int >= 0, calidad válida
- ✅ familia con error tipográfico 'Lacteso' → 200 con calidad 'corregido'
- ✅ familia con error tipográfico 'Lacteso': version_modelo str, cantidad_sugerida int >= 0, calidad válida
- ✅ fecha AAAA/MM/DD → 200 con calidad 'corregido'
- ✅ fecha AAAA/MM/DD: version_modelo str, cantidad_sugerida int >= 0, calidad válida
- ✅ fecha invertida MM/DD/AAAA '11/17/2025' → 200 con calidad 'corregido'
- ✅ fecha invertida MM/DD/AAAA '11/17/2025': version_modelo str, cantidad_sugerida int >= 0, calidad válida
- ✅ fecha ambigua DD/MM '05/11/2025' → 200 con calidad 'advertencia'
- ✅ fecha ambigua DD/MM '05/11/2025': version_modelo str, cantidad_sugerida int >= 0, calidad válida
- ✅ en_promocion nulo → 200 con calidad 'advertencia'
- ✅ en_promocion nulo: version_modelo str, cantidad_sugerida int >= 0, calidad válida
- ✅ en_promocion ausente → 200 con calidad 'advertencia'
- ✅ en_promocion ausente: version_modelo str, cantidad_sugerida int >= 0, calidad válida
- ✅ en_promocion '3,0' con coma decimal → 200 con calidad 'corregido'
- ✅ en_promocion '3,0' con coma decimal: version_modelo str, cantidad_sugerida int >= 0, calidad válida
- ✅ campo 'Fecha' con mayúscula → 200 con calidad 'corregido'
- ✅ campo 'Fecha' con mayúscula: version_modelo str, cantidad_sugerida int >= 0, calidad válida
- ✅ campo desconocido 'canal' → 200 con calidad 'advertencia'
- ✅ campo desconocido 'canal': version_modelo str, cantidad_sugerida int >= 0, calidad válida
- ✅ FATAL tienda inexistente 99 → 422 con detail
- ✅ FATAL tienda negativa -3 → 422 con detail
- ✅ FATAL familia irreconocible 'juguetes' → 422 con detail
- ✅ FATAL fecha inexistente 2025-02-30 → 422 con detail
- ✅ FATAL fecha anterior a la apertura (tienda 10) → 422 con detail
- ✅ FATAL en_promocion negativo → 422 con detail
- ✅ FATAL en_promocion decimal 2.5 → 422 con detail
- ✅ FATAL lista de familias vacía → 422 con detail
- ✅ FATAL falta tienda_id → 422 con detail
- ✅ cuerpo que no es JSON → 422 con detail
- ✅ observación con ventas 'abc' → 422 con detail

<details><summary>Evidencia (JSON reales)</summary>

**ejemplos/observacion_valida.json** — `POST /v1/observaciones` → HTTP 200 (249 ms)

Solicitud:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "ventas": [
    {
      "familia_id": "abarrotes",
      "ventas": 994
    },
    {
      "familia_id": "bebe",
      "ventas": 50
    },
    {
      "familia_id": "bebidas",
      "ventas": 1292
    },
    {
      "familia_id": "carnes",
      "ventas": 182
    },
    {
      "familia_id": "cuidado_personal",
      "ventas": 118
    },
    {
      "familia_id": "frutas_verduras",
      "ventas": 410
    },
    {
      "familia_id": "lacteos",
      "ventas": 358
    },
    {
      "familia_id": "licores",
      "ventas": 85
    },
    {
      "familia_id": "limpieza",
      "ventas": 202
    },
    {
      "familia_id": "mascotas",
      "ventas": 63
    },
    {
      "familia_id": "panaderia",
      "ventas": 213
    },
    {
      "familia_id": "snacks",
      "ventas": 386
    }
  ]
}
```

Respuesta:
```json
{
  "registros_guardados": 0,
  "calidad": {
    "estado": "ok",
    "observaciones": []
  }
}
```


**ejemplos/prediccion_valida.json** — `POST /v1/prediccion` → HTTP 200 (127 ms)

Solicitud:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "familias": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0
    },
    {
      "familia_id": "licores",
      "en_promocion": 0
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9
    }
  ]
}
```

Respuesta:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "1",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0,
      "venta_esperada": 1022.52,
      "cantidad_sugerida": 1237
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0,
      "venta_esperada": 61.49,
      "cantidad_sugerida": 79
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8,
      "venta_esperada": 989.43,
      "cantidad_sugerida": 1197
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0,
      "venta_esperada": 213.54,
      "cantidad_sugerida": 190
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0,
      "venta_esperada": 178.08,
      "cantidad_sugerida": 239
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0,
      "venta_esperada": 373.32,
      "cantidad_sugerida": 336
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0,
      "venta_esperada": 424.31,
      "cantidad_sugerida": 412
    },
    {
      "familia_id": "licores",
      "en_promocion": 0,
      "venta_esperada": 80.86,
      "cantidad_sugerida": 112
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0,
      "venta_esperada": 202.2,
      "cantidad_sugerida": 259
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0,
      "venta_esperada": 44.77,
      "cantidad_sugerida": 55
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0,
      "venta_esperada": 224.15,
      "cantidad_sugerida": 182
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9,
      "venta_esperada": 353.21,
      "cantidad_sugerida": 403
    }
  ],
  "calidad": {
    "estado": "ok",
    "observaciones": []
  }
}
```


**errores/E01_tienda_texto.json** — `POST /v1/prediccion` → HTTP 200 (83 ms)

Solicitud:
```json
{
  "tienda_id": "T05",
  "fecha": "2025-11-17",
  "familias": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0
    },
    {
      "familia_id": "licores",
      "en_promocion": 0
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9
    }
  ]
}
```

Respuesta:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "1",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0,
      "venta_esperada": 1022.52,
      "cantidad_sugerida": 1237
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0,
      "venta_esperada": 61.49,
      "cantidad_sugerida": 79
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8,
      "venta_esperada": 989.43,
      "cantidad_sugerida": 1197
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0,
      "venta_esperada": 213.54,
      "cantidad_sugerida": 190
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0,
      "venta_esperada": 178.08,
      "cantidad_sugerida": 239
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0,
      "venta_esperada": 373.32,
      "cantidad_sugerida": 336
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0,
      "venta_esperada": 424.31,
      "cantidad_sugerida": 412
    },
    {
      "familia_id": "licores",
      "en_promocion": 0,
      "venta_esperada": 80.86,
      "cantidad_sugerida": 112
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0,
      "venta_esperada": 202.2,
      "cantidad_sugerida": 259
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0,
      "venta_esperada": 44.77,
      "cantidad_sugerida": 55
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0,
      "venta_esperada": 224.15,
      "cantidad_sugerida": 182
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9,
      "venta_esperada": 353.21,
      "cantidad_sugerida": 403
    }
  ],
  "calidad": {
    "estado": "corregido",
    "observaciones": [
      {
        "campo": "tienda_id",
        "accion": "reparar",
        "detalle": "\"T05\" → 5 (identificador enviado como texto)"
      }
    ]
  }
}
```


**errores/E02_familia_otra_forma.json** — `POST /v1/prediccion` → HTTP 200 (85 ms)

Solicitud:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "familias": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0
    },
    {
      "familia_id": "Frutas y Verduras",
      "en_promocion": 0
    },
    {
      "familia_id": "LÁCTEOS",
      "en_promocion": 0
    },
    {
      "familia_id": "licores",
      "en_promocion": 0
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9
    }
  ]
}
```

Respuesta:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "1",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0,
      "venta_esperada": 1022.52,
      "cantidad_sugerida": 1237
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0,
      "venta_esperada": 61.49,
      "cantidad_sugerida": 79
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8,
      "venta_esperada": 989.43,
      "cantidad_sugerida": 1197
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0,
      "venta_esperada": 213.54,
      "cantidad_sugerida": 190
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0,
      "venta_esperada": 178.08,
      "cantidad_sugerida": 239
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0,
      "venta_esperada": 373.32,
      "cantidad_sugerida": 336
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0,
      "venta_esperada": 424.31,
      "cantidad_sugerida": 412
    },
    {
      "familia_id": "licores",
      "en_promocion": 0,
      "venta_esperada": 80.86,
      "cantidad_sugerida": 112
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0,
      "venta_esperada": 202.2,
      "cantidad_sugerida": 259
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0,
      "venta_esperada": 44.77,
      "cantidad_sugerida": 55
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0,
      "venta_esperada": 224.15,
      "cantidad_sugerida": 182
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9,
      "venta_esperada": 353.21,
      "cantidad_sugerida": 403
    }
  ],
  "calidad": {
    "estado": "corregido",
    "observaciones": [
      {
        "campo": "familias[5].familia_id",
        "accion": "reparar",
        "detalle": "\"Frutas y Verduras\" → 'frutas_verduras' (normalización de mayúsculas, tildes, espacios o separadores)"
      },
      {
        "campo": "familias[6].familia_id",
        "accion": "reparar",
        "detalle": "\"LÁCTEOS\" → 'lacteos' (normalización de mayúsculas, tildes, espacios o separadores)"
      }
    ]
  }
}
```


**errores/E03_promocion_texto.json** — `POST /v1/prediccion` → HTTP 200 (79 ms)

Solicitud:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "familias": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8.0
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0
    },
    {
      "familia_id": "licores",
      "en_promocion": 0
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0
    },
    {
      "familia_id": "snacks",
      "en_promocion": "9"
    }
  ]
}
```

Respuesta:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "1",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0,
      "venta_esperada": 1022.52,
      "cantidad_sugerida": 1237
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0,
      "venta_esperada": 61.49,
      "cantidad_sugerida": 79
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8,
      "venta_esperada": 989.43,
      "cantidad_sugerida": 1197
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0,
      "venta_esperada": 213.54,
      "cantidad_sugerida": 190
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0,
      "venta_esperada": 178.08,
      "cantidad_sugerida": 239
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0,
      "venta_esperada": 373.32,
      "cantidad_sugerida": 336
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0,
      "venta_esperada": 424.31,
      "cantidad_sugerida": 412
    },
    {
      "familia_id": "licores",
      "en_promocion": 0,
      "venta_esperada": 80.86,
      "cantidad_sugerida": 112
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0,
      "venta_esperada": 202.2,
      "cantidad_sugerida": 259
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0,
      "venta_esperada": 44.77,
      "cantidad_sugerida": 55
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0,
      "venta_esperada": 224.15,
      "cantidad_sugerida": 182
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9,
      "venta_esperada": 353.21,
      "cantidad_sugerida": 403
    }
  ],
  "calidad": {
    "estado": "corregido",
    "observaciones": [
      {
        "campo": "familias[2].en_promocion",
        "accion": "reparar",
        "detalle": "8.0 → 8 (decimal sin parte fraccionaria)"
      },
      {
        "campo": "familias[11].en_promocion",
        "accion": "reparar",
        "detalle": "\"9\" → 9 (número enviado como texto)"
      }
    ]
  }
}
```


**errores/E04_fecha_formato.json** — `POST /v1/prediccion` → HTTP 200 (86 ms)

Solicitud:
```json
{
  "tienda_id": 5,
  "fecha": "17/11/2025",
  "familias": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0
    },
    {
      "familia_id": "licores",
      "en_promocion": 0
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9
    }
  ]
}
```

Respuesta:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "1",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0,
      "venta_esperada": 1022.52,
      "cantidad_sugerida": 1237
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0,
      "venta_esperada": 61.49,
      "cantidad_sugerida": 79
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8,
      "venta_esperada": 989.43,
      "cantidad_sugerida": 1197
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0,
      "venta_esperada": 213.54,
      "cantidad_sugerida": 190
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0,
      "venta_esperada": 178.08,
      "cantidad_sugerida": 239
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0,
      "venta_esperada": 373.32,
      "cantidad_sugerida": 336
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0,
      "venta_esperada": 424.31,
      "cantidad_sugerida": 412
    },
    {
      "familia_id": "licores",
      "en_promocion": 0,
      "venta_esperada": 80.86,
      "cantidad_sugerida": 112
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0,
      "venta_esperada": 202.2,
      "cantidad_sugerida": 259
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0,
      "venta_esperada": 44.77,
      "cantidad_sugerida": 55
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0,
      "venta_esperada": 224.15,
      "cantidad_sugerida": 182
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9,
      "venta_esperada": 353.21,
      "cantidad_sugerida": 403
    }
  ],
  "calidad": {
    "estado": "corregido",
    "observaciones": [
      {
        "campo": "fecha",
        "accion": "reparar",
        "detalle": "\"17/11/2025\" → 2025-11-17 (formato DD/MM/AAAA)"
      }
    ]
  }
}
```


**errores/E05_faltan_familias.json** — `POST /v1/prediccion` → HTTP 200 (84 ms)

Solicitud:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "familias": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0
    },
    {
      "familia_id": "licores",
      "en_promocion": 0
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9
    }
  ]
}
```

Respuesta:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "1",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0,
      "venta_esperada": 1022.52,
      "cantidad_sugerida": 1237
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8,
      "venta_esperada": 989.43,
      "cantidad_sugerida": 1197
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0,
      "venta_esperada": 213.54,
      "cantidad_sugerida": 190
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0,
      "venta_esperada": 178.08,
      "cantidad_sugerida": 239
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0,
      "venta_esperada": 373.32,
      "cantidad_sugerida": 336
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0,
      "venta_esperada": 424.31,
      "cantidad_sugerida": 412
    },
    {
      "familia_id": "licores",
      "en_promocion": 0,
      "venta_esperada": 80.86,
      "cantidad_sugerida": 112
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0,
      "venta_esperada": 202.2,
      "cantidad_sugerida": 259
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0,
      "venta_esperada": 224.15,
      "cantidad_sugerida": 182
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9,
      "venta_esperada": 353.21,
      "cantidad_sugerida": 403
    }
  ],
  "calidad": {
    "estado": "advertencia",
    "observaciones": [
      {
        "campo": "familias",
        "accion": "advertir",
        "detalle": "faltan 2 familias que la tienda vende (bebe, mascotas); no se emitirá pronóstico para ellas"
      }
    ]
  }
}
```


**errores/E06_familia_repetida.json** — `POST /v1/prediccion` → HTTP 200 (90 ms)

Solicitud:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "familias": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0
    },
    {
      "familia_id": "licores",
      "en_promocion": 0
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9
    },
    {
      "familia_id": "abarrotes",
      "en_promocion": 3
    }
  ]
}
```

Respuesta:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "1",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 3,
      "venta_esperada": 1130.47,
      "cantidad_sugerida": 1368
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0,
      "venta_esperada": 61.49,
      "cantidad_sugerida": 79
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8,
      "venta_esperada": 989.43,
      "cantidad_sugerida": 1197
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0,
      "venta_esperada": 213.54,
      "cantidad_sugerida": 190
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0,
      "venta_esperada": 178.08,
      "cantidad_sugerida": 239
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0,
      "venta_esperada": 373.32,
      "cantidad_sugerida": 336
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0,
      "venta_esperada": 424.31,
      "cantidad_sugerida": 412
    },
    {
      "familia_id": "licores",
      "en_promocion": 0,
      "venta_esperada": 80.86,
      "cantidad_sugerida": 112
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0,
      "venta_esperada": 202.2,
      "cantidad_sugerida": 259
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0,
      "venta_esperada": 44.77,
      "cantidad_sugerida": 55
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0,
      "venta_esperada": 224.15,
      "cantidad_sugerida": 182
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9,
      "venta_esperada": 353.21,
      "cantidad_sugerida": 403
    }
  ],
  "calidad": {
    "estado": "advertencia",
    "observaciones": [
      {
        "campo": "familias",
        "accion": "advertir",
        "detalle": "la familia 'abarrotes' aparece 2 veces con valores distintos (posición 0: en_promocion=0; posición 12: en_promocion=3); se conservó la última (posición 12)"
      }
    ]
  }
}
```


**errores/E07_campo_renombrado.json** — `POST /v1/prediccion` → HTTP 200 (83 ms)

Solicitud:
```json
{
  "fecha": "2025-11-17",
  "familias": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0
    },
    {
      "familia_id": "licores",
      "en_promocion": 0
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9
    }
  ],
  "tienda": 5
}
```

Respuesta:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "1",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0,
      "venta_esperada": 1022.52,
      "cantidad_sugerida": 1237
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0,
      "venta_esperada": 61.49,
      "cantidad_sugerida": 79
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8,
      "venta_esperada": 989.43,
      "cantidad_sugerida": 1197
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0,
      "venta_esperada": 213.54,
      "cantidad_sugerida": 190
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0,
      "venta_esperada": 178.08,
      "cantidad_sugerida": 239
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0,
      "venta_esperada": 373.32,
      "cantidad_sugerida": 336
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0,
      "venta_esperada": 424.31,
      "cantidad_sugerida": 412
    },
    {
      "familia_id": "licores",
      "en_promocion": 0,
      "venta_esperada": 80.86,
      "cantidad_sugerida": 112
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0,
      "venta_esperada": 202.2,
      "cantidad_sugerida": 259
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0,
      "venta_esperada": 44.77,
      "cantidad_sugerida": 55
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0,
      "venta_esperada": 224.15,
      "cantidad_sugerida": 182
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9,
      "venta_esperada": 353.21,
      "cantidad_sugerida": 403
    }
  ],
  "calidad": {
    "estado": "corregido",
    "observaciones": [
      {
        "campo": "tienda_id",
        "accion": "reparar",
        "detalle": "el campo 'tienda' se renombró a 'tienda_id' según el contrato"
      }
    ]
  }
}
```


**errores/E08_ventas_negativas.json** — `POST /v1/observaciones` → HTTP 422 (7 ms)

Solicitud:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "ventas": [
    {
      "familia_id": "abarrotes",
      "ventas": 994
    },
    {
      "familia_id": "bebe",
      "ventas": 50
    },
    {
      "familia_id": "bebidas",
      "ventas": 1292
    },
    {
      "familia_id": "carnes",
      "ventas": 182
    },
    {
      "familia_id": "cuidado_personal",
      "ventas": 118
    },
    {
      "familia_id": "frutas_verduras",
      "ventas": -4
    },
    {
      "familia_id": "lacteos",
      "ventas": 358
    },
    {
      "familia_id": "licores",
      "ventas": 85
    },
    {
      "familia_id": "limpieza",
      "ventas": 202
    },
    {
      "familia_id": "mascotas",
      "ventas": 63
    },
    {
      "familia_id": "panaderia",
      "ventas": 213
    },
    {
      "familia_id": "snacks",
      "ventas": 386
    }
  ]
}
```

Respuesta:
```json
{
  "detail": [
    {
      "campo": "ventas[5].ventas",
      "accion": "rechazar",
      "detalle": "no puede ser negativo (se recibió -4); las devoluciones no se registran como ventas"
    }
  ]
}
```


**errores/E09_envio_repetido.json** — `POST /v1/observaciones` → HTTP 200 (11 ms)

Solicitud:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "ventas": [
    {
      "familia_id": "abarrotes",
      "ventas": 994
    },
    {
      "familia_id": "bebe",
      "ventas": 50
    },
    {
      "familia_id": "bebidas",
      "ventas": 1292
    },
    {
      "familia_id": "carnes",
      "ventas": 182
    },
    {
      "familia_id": "cuidado_personal",
      "ventas": 118
    },
    {
      "familia_id": "frutas_verduras",
      "ventas": 410
    },
    {
      "familia_id": "lacteos",
      "ventas": 358
    },
    {
      "familia_id": "licores",
      "ventas": 85
    },
    {
      "familia_id": "limpieza",
      "ventas": 202
    },
    {
      "familia_id": "mascotas",
      "ventas": 63
    },
    {
      "familia_id": "panaderia",
      "ventas": 213
    },
    {
      "familia_id": "snacks",
      "ventas": 386
    }
  ]
}
```

Respuesta:
```json
{
  "registros_guardados": 0,
  "calidad": {
    "estado": "ok",
    "observaciones": []
  }
}
```


**errores/E10_numero_formato.json** — `POST /v1/observaciones` → HTTP 200 (12 ms)

Solicitud:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "ventas": [
    {
      "familia_id": "abarrotes",
      "ventas": 994
    },
    {
      "familia_id": "bebe",
      "ventas": "50,0"
    },
    {
      "familia_id": "bebidas",
      "ventas": "1,292"
    },
    {
      "familia_id": "carnes",
      "ventas": 182
    },
    {
      "familia_id": "cuidado_personal",
      "ventas": 118
    },
    {
      "familia_id": "frutas_verduras",
      "ventas": 410
    },
    {
      "familia_id": "lacteos",
      "ventas": 358
    },
    {
      "familia_id": "licores",
      "ventas": 85
    },
    {
      "familia_id": "limpieza",
      "ventas": 202
    },
    {
      "familia_id": "mascotas",
      "ventas": 63
    },
    {
      "familia_id": "panaderia",
      "ventas": 213
    },
    {
      "familia_id": "snacks",
      "ventas": 386
    }
  ]
}
```

Respuesta:
```json
{
  "registros_guardados": 0,
  "calidad": {
    "estado": "corregido",
    "observaciones": [
      {
        "campo": "ventas[1].ventas",
        "accion": "reparar",
        "detalle": "\"50,0\" → 50 (coma decimal sin parte fraccionaria)"
      },
      {
        "campo": "ventas[2].ventas",
        "accion": "reparar",
        "detalle": "\"1,292\" → 1292 (coma como separador de miles)"
      }
    ]
  }
}
```


**Caso nuevo: tienda como texto con prefijo 'tienda_05'** — `POST /v1/prediccion` → HTTP 200 (103 ms)

Solicitud:
```json
{
  "tienda_id": "tienda_05",
  "fecha": "2025-11-17",
  "familias": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0
    },
    {
      "familia_id": "licores",
      "en_promocion": 0
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9
    }
  ]
}
```

Respuesta:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "1",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0,
      "venta_esperada": 1022.52,
      "cantidad_sugerida": 1237
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0,
      "venta_esperada": 61.49,
      "cantidad_sugerida": 79
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8,
      "venta_esperada": 989.43,
      "cantidad_sugerida": 1197
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0,
      "venta_esperada": 213.54,
      "cantidad_sugerida": 190
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0,
      "venta_esperada": 178.08,
      "cantidad_sugerida": 239
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0,
      "venta_esperada": 373.32,
      "cantidad_sugerida": 336
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0,
      "venta_esperada": 424.31,
      "cantidad_sugerida": 412
    },
    {
      "familia_id": "licores",
      "en_promocion": 0,
      "venta_esperada": 80.86,
      "cantidad_sugerida": 112
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0,
      "venta_esperada": 202.2,
      "cantidad_sugerida": 259
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0,
      "venta_esperada": 44.77,
      "cantidad_sugerida": 55
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0,
      "venta_esperada": 224.15,
      "cantidad_sugerida": 182
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9,
      "venta_esperada": 353.21,
      "cantidad_sugerida": 403
    }
  ],
  "calidad": {
    "estado": "corregido",
    "observaciones": [
      {
        "campo": "tienda_id",
        "accion": "reparar",
        "detalle": "\"tienda_05\" → 5 (identificador enviado como texto)"
      }
    ]
  }
}
```


**Caso nuevo: tienda como texto ' 5 '** — `POST /v1/prediccion` → HTTP 200 (86 ms)

Solicitud:
```json
{
  "tienda_id": " 5 ",
  "fecha": "2025-11-17",
  "familias": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0
    },
    {
      "familia_id": "licores",
      "en_promocion": 0
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9
    }
  ]
}
```

Respuesta:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "1",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0,
      "venta_esperada": 1022.52,
      "cantidad_sugerida": 1237
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0,
      "venta_esperada": 61.49,
      "cantidad_sugerida": 79
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8,
      "venta_esperada": 989.43,
      "cantidad_sugerida": 1197
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0,
      "venta_esperada": 213.54,
      "cantidad_sugerida": 190
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0,
      "venta_esperada": 178.08,
      "cantidad_sugerida": 239
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0,
      "venta_esperada": 373.32,
      "cantidad_sugerida": 336
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0,
      "venta_esperada": 424.31,
      "cantidad_sugerida": 412
    },
    {
      "familia_id": "licores",
      "en_promocion": 0,
      "venta_esperada": 80.86,
      "cantidad_sugerida": 112
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0,
      "venta_esperada": 202.2,
      "cantidad_sugerida": 259
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0,
      "venta_esperada": 44.77,
      "cantidad_sugerida": 55
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0,
      "venta_esperada": 224.15,
      "cantidad_sugerida": 182
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9,
      "venta_esperada": 353.21,
      "cantidad_sugerida": 403
    }
  ],
  "calidad": {
    "estado": "corregido",
    "observaciones": [
      {
        "campo": "tienda_id",
        "accion": "reparar",
        "detalle": "\" 5 \" → 5 (identificador enviado como texto)"
      }
    ]
  }
}
```


**Caso nuevo: familia con mayúsculas y guion 'Cuidado-Personal'** — `POST /v1/prediccion` → HTTP 200 (85 ms)

Solicitud:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "familias": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0
    },
    {
      "familia_id": "Cuidado-Personal",
      "en_promocion": 0
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0
    },
    {
      "familia_id": "licores",
      "en_promocion": 0
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9
    }
  ]
}
```

Respuesta:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "1",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0,
      "venta_esperada": 1022.52,
      "cantidad_sugerida": 1237
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0,
      "venta_esperada": 61.49,
      "cantidad_sugerida": 79
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8,
      "venta_esperada": 989.43,
      "cantidad_sugerida": 1197
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0,
      "venta_esperada": 213.54,
      "cantidad_sugerida": 190
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0,
      "venta_esperada": 178.08,
      "cantidad_sugerida": 239
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0,
      "venta_esperada": 373.32,
      "cantidad_sugerida": 336
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0,
      "venta_esperada": 424.31,
      "cantidad_sugerida": 412
    },
    {
      "familia_id": "licores",
      "en_promocion": 0,
      "venta_esperada": 80.86,
      "cantidad_sugerida": 112
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0,
      "venta_esperada": 202.2,
      "cantidad_sugerida": 259
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0,
      "venta_esperada": 44.77,
      "cantidad_sugerida": 55
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0,
      "venta_esperada": 224.15,
      "cantidad_sugerida": 182
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9,
      "venta_esperada": 353.21,
      "cantidad_sugerida": 403
    }
  ],
  "calidad": {
    "estado": "corregido",
    "observaciones": [
      {
        "campo": "familias[4].familia_id",
        "accion": "reparar",
        "detalle": "\"Cuidado-Personal\" → 'cuidado_personal' (normalización de mayúsculas, tildes, espacios o separadores)"
      }
    ]
  }
}
```


**Caso nuevo: familia con tilde 'PANADERÍA'** — `POST /v1/prediccion` → HTTP 200 (86 ms)

Solicitud:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "familias": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0
    },
    {
      "familia_id": "licores",
      "en_promocion": 0
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0
    },
    {
      "familia_id": "PANADERÍA",
      "en_promocion": 0
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9
    }
  ]
}
```

Respuesta:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "1",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0,
      "venta_esperada": 1022.52,
      "cantidad_sugerida": 1237
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0,
      "venta_esperada": 61.49,
      "cantidad_sugerida": 79
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8,
      "venta_esperada": 989.43,
      "cantidad_sugerida": 1197
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0,
      "venta_esperada": 213.54,
      "cantidad_sugerida": 190
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0,
      "venta_esperada": 178.08,
      "cantidad_sugerida": 239
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0,
      "venta_esperada": 373.32,
      "cantidad_sugerida": 336
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0,
      "venta_esperada": 424.31,
      "cantidad_sugerida": 412
    },
    {
      "familia_id": "licores",
      "en_promocion": 0,
      "venta_esperada": 80.86,
      "cantidad_sugerida": 112
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0,
      "venta_esperada": 202.2,
      "cantidad_sugerida": 259
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0,
      "venta_esperada": 44.77,
      "cantidad_sugerida": 55
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0,
      "venta_esperada": 224.15,
      "cantidad_sugerida": 182
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9,
      "venta_esperada": 353.21,
      "cantidad_sugerida": 403
    }
  ],
  "calidad": {
    "estado": "corregido",
    "observaciones": [
      {
        "campo": "familias[10].familia_id",
        "accion": "reparar",
        "detalle": "\"PANADERÍA\" → 'panaderia' (normalización de mayúsculas, tildes, espacios o separadores)"
      }
    ]
  }
}
```


**Caso nuevo: familia con error tipográfico 'Lacteso'** — `POST /v1/prediccion` → HTTP 200 (99 ms)

Solicitud:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "familias": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0
    },
    {
      "familia_id": "Lacteso",
      "en_promocion": 0
    },
    {
      "familia_id": "licores",
      "en_promocion": 0
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9
    }
  ]
}
```

Respuesta:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "1",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0,
      "venta_esperada": 1022.52,
      "cantidad_sugerida": 1237
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0,
      "venta_esperada": 61.49,
      "cantidad_sugerida": 79
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8,
      "venta_esperada": 989.43,
      "cantidad_sugerida": 1197
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0,
      "venta_esperada": 213.54,
      "cantidad_sugerida": 190
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0,
      "venta_esperada": 178.08,
      "cantidad_sugerida": 239
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0,
      "venta_esperada": 373.32,
      "cantidad_sugerida": 336
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0,
      "venta_esperada": 424.31,
      "cantidad_sugerida": 412
    },
    {
      "familia_id": "licores",
      "en_promocion": 0,
      "venta_esperada": 80.86,
      "cantidad_sugerida": 112
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0,
      "venta_esperada": 202.2,
      "cantidad_sugerida": 259
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0,
      "venta_esperada": 44.77,
      "cantidad_sugerida": 55
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0,
      "venta_esperada": 224.15,
      "cantidad_sugerida": 182
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9,
      "venta_esperada": 353.21,
      "cantidad_sugerida": 403
    }
  ],
  "calidad": {
    "estado": "corregido",
    "observaciones": [
      {
        "campo": "familias[6].familia_id",
        "accion": "reparar",
        "detalle": "\"Lacteso\" → 'lacteos' (corrección de error tipográfico leve)"
      }
    ]
  }
}
```


**Caso nuevo: fecha AAAA/MM/DD** — `POST /v1/prediccion` → HTTP 200 (80 ms)

Solicitud:
```json
{
  "tienda_id": 5,
  "fecha": "2025/11/17",
  "familias": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0
    },
    {
      "familia_id": "licores",
      "en_promocion": 0
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9
    }
  ]
}
```

Respuesta:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "1",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0,
      "venta_esperada": 1022.52,
      "cantidad_sugerida": 1237
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0,
      "venta_esperada": 61.49,
      "cantidad_sugerida": 79
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8,
      "venta_esperada": 989.43,
      "cantidad_sugerida": 1197
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0,
      "venta_esperada": 213.54,
      "cantidad_sugerida": 190
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0,
      "venta_esperada": 178.08,
      "cantidad_sugerida": 239
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0,
      "venta_esperada": 373.32,
      "cantidad_sugerida": 336
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0,
      "venta_esperada": 424.31,
      "cantidad_sugerida": 412
    },
    {
      "familia_id": "licores",
      "en_promocion": 0,
      "venta_esperada": 80.86,
      "cantidad_sugerida": 112
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0,
      "venta_esperada": 202.2,
      "cantidad_sugerida": 259
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0,
      "venta_esperada": 44.77,
      "cantidad_sugerida": 55
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0,
      "venta_esperada": 224.15,
      "cantidad_sugerida": 182
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9,
      "venta_esperada": 353.21,
      "cantidad_sugerida": 403
    }
  ],
  "calidad": {
    "estado": "corregido",
    "observaciones": [
      {
        "campo": "fecha",
        "accion": "reparar",
        "detalle": "\"2025/11/17\" → 2025-11-17 (formato AAAA/MM/DD)"
      }
    ]
  }
}
```


**Caso nuevo: fecha invertida MM/DD/AAAA '11/17/2025'** — `POST /v1/prediccion` → HTTP 200 (89 ms)

Solicitud:
```json
{
  "tienda_id": 5,
  "fecha": "11/17/2025",
  "familias": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0
    },
    {
      "familia_id": "licores",
      "en_promocion": 0
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9
    }
  ]
}
```

Respuesta:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "1",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0,
      "venta_esperada": 1022.52,
      "cantidad_sugerida": 1237
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0,
      "venta_esperada": 61.49,
      "cantidad_sugerida": 79
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8,
      "venta_esperada": 989.43,
      "cantidad_sugerida": 1197
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0,
      "venta_esperada": 213.54,
      "cantidad_sugerida": 190
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0,
      "venta_esperada": 178.08,
      "cantidad_sugerida": 239
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0,
      "venta_esperada": 373.32,
      "cantidad_sugerida": 336
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0,
      "venta_esperada": 424.31,
      "cantidad_sugerida": 412
    },
    {
      "familia_id": "licores",
      "en_promocion": 0,
      "venta_esperada": 80.86,
      "cantidad_sugerida": 112
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0,
      "venta_esperada": 202.2,
      "cantidad_sugerida": 259
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0,
      "venta_esperada": 44.77,
      "cantidad_sugerida": 55
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0,
      "venta_esperada": 224.15,
      "cantidad_sugerida": 182
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9,
      "venta_esperada": 353.21,
      "cantidad_sugerida": 403
    }
  ],
  "calidad": {
    "estado": "corregido",
    "observaciones": [
      {
        "campo": "fecha",
        "accion": "reparar",
        "detalle": "\"11/17/2025\" → 2025-11-17 (formato MM/DD/AAAA: el segundo número solo puede ser el día)"
      }
    ]
  }
}
```


**Caso nuevo: fecha ambigua DD/MM '05/11/2025'** — `POST /v1/prediccion` → HTTP 200 (87 ms)

Solicitud:
```json
{
  "tienda_id": 5,
  "fecha": "05/11/2025",
  "familias": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0
    },
    {
      "familia_id": "licores",
      "en_promocion": 0
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9
    }
  ]
}
```

Respuesta:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-05",
  "version_modelo": "1",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0,
      "venta_esperada": 997.25,
      "cantidad_sugerida": 1207
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0,
      "venta_esperada": 71.46,
      "cantidad_sugerida": 92
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8,
      "venta_esperada": 950.48,
      "cantidad_sugerida": 1150
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0,
      "venta_esperada": 225.79,
      "cantidad_sugerida": 201
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0,
      "venta_esperada": 173.4,
      "cantidad_sugerida": 232
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0,
      "venta_esperada": 348.16,
      "cantidad_sugerida": 313
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0,
      "venta_esperada": 451.22,
      "cantidad_sugerida": 438
    },
    {
      "familia_id": "licores",
      "en_promocion": 0,
      "venta_esperada": 92.66,
      "cantidad_sugerida": 129
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0,
      "venta_esperada": 208.96,
      "cantidad_sugerida": 267
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0,
      "venta_esperada": 46.36,
      "cantidad_sugerida": 57
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0,
      "venta_esperada": 236.08,
      "cantidad_sugerida": 191
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9,
      "venta_esperada": 366.12,
      "cantidad_sugerida": 417
    }
  ],
  "calidad": {
    "estado": "advertencia",
    "observaciones": [
      {
        "campo": "fecha",
        "accion": "advertir",
        "detalle": "\"05/11/2025\" → 2025-11-05: el orden día/mes es ambiguo; se interpretó como DD/MM/AAAA (convención local)"
      }
    ]
  }
}
```


**Caso nuevo: en_promocion nulo** — `POST /v1/prediccion` → HTTP 200 (92 ms)

Solicitud:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "familias": [
    {
      "familia_id": "abarrotes",
      "en_promocion": null
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0
    },
    {
      "familia_id": "licores",
      "en_promocion": 0
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9
    }
  ]
}
```

Respuesta:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "1",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0,
      "venta_esperada": 1022.52,
      "cantidad_sugerida": 1237
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0,
      "venta_esperada": 61.49,
      "cantidad_sugerida": 79
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8,
      "venta_esperada": 989.43,
      "cantidad_sugerida": 1197
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0,
      "venta_esperada": 213.54,
      "cantidad_sugerida": 190
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0,
      "venta_esperada": 178.08,
      "cantidad_sugerida": 239
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0,
      "venta_esperada": 373.32,
      "cantidad_sugerida": 336
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0,
      "venta_esperada": 424.31,
      "cantidad_sugerida": 412
    },
    {
      "familia_id": "licores",
      "en_promocion": 0,
      "venta_esperada": 80.86,
      "cantidad_sugerida": 112
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0,
      "venta_esperada": 202.2,
      "cantidad_sugerida": 259
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0,
      "venta_esperada": 44.77,
      "cantidad_sugerida": 55
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0,
      "venta_esperada": 224.15,
      "cantidad_sugerida": 182
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9,
      "venta_esperada": 353.21,
      "cantidad_sugerida": 403
    }
  ],
  "calidad": {
    "estado": "advertencia",
    "observaciones": [
      {
        "campo": "familias[0].en_promocion",
        "accion": "advertir",
        "detalle": "llegó nulo; se asumió 0"
      }
    ]
  }
}
```


**Caso nuevo: en_promocion ausente** — `POST /v1/prediccion` → HTTP 200 (80 ms)

Solicitud:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "familias": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0
    },
    {
      "familia_id": "bebe"
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0
    },
    {
      "familia_id": "licores",
      "en_promocion": 0
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9
    }
  ]
}
```

Respuesta:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "1",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0,
      "venta_esperada": 1022.52,
      "cantidad_sugerida": 1237
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0,
      "venta_esperada": 61.49,
      "cantidad_sugerida": 79
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8,
      "venta_esperada": 989.43,
      "cantidad_sugerida": 1197
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0,
      "venta_esperada": 213.54,
      "cantidad_sugerida": 190
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0,
      "venta_esperada": 178.08,
      "cantidad_sugerida": 239
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0,
      "venta_esperada": 373.32,
      "cantidad_sugerida": 336
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0,
      "venta_esperada": 424.31,
      "cantidad_sugerida": 412
    },
    {
      "familia_id": "licores",
      "en_promocion": 0,
      "venta_esperada": 80.86,
      "cantidad_sugerida": 112
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0,
      "venta_esperada": 202.2,
      "cantidad_sugerida": 259
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0,
      "venta_esperada": 44.77,
      "cantidad_sugerida": 55
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0,
      "venta_esperada": 224.15,
      "cantidad_sugerida": 182
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9,
      "venta_esperada": 353.21,
      "cantidad_sugerida": 403
    }
  ],
  "calidad": {
    "estado": "advertencia",
    "observaciones": [
      {
        "campo": "familias[1].en_promocion",
        "accion": "advertir",
        "detalle": "no se envió; se asumió 0"
      }
    ]
  }
}
```


**Caso nuevo: en_promocion '3,0' con coma decimal** — `POST /v1/prediccion` → HTTP 200 (83 ms)

Solicitud:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "familias": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0
    },
    {
      "familia_id": "bebidas",
      "en_promocion": "3,0"
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0
    },
    {
      "familia_id": "licores",
      "en_promocion": 0
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9
    }
  ]
}
```

Respuesta:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "1",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0,
      "venta_esperada": 1022.52,
      "cantidad_sugerida": 1237
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0,
      "venta_esperada": 61.49,
      "cantidad_sugerida": 79
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 3,
      "venta_esperada": 907.28,
      "cantidad_sugerida": 1098
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0,
      "venta_esperada": 213.54,
      "cantidad_sugerida": 190
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0,
      "venta_esperada": 178.08,
      "cantidad_sugerida": 239
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0,
      "venta_esperada": 373.32,
      "cantidad_sugerida": 336
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0,
      "venta_esperada": 424.31,
      "cantidad_sugerida": 412
    },
    {
      "familia_id": "licores",
      "en_promocion": 0,
      "venta_esperada": 80.86,
      "cantidad_sugerida": 112
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0,
      "venta_esperada": 202.2,
      "cantidad_sugerida": 259
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0,
      "venta_esperada": 44.77,
      "cantidad_sugerida": 55
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0,
      "venta_esperada": 224.15,
      "cantidad_sugerida": 182
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9,
      "venta_esperada": 353.21,
      "cantidad_sugerida": 403
    }
  ],
  "calidad": {
    "estado": "corregido",
    "observaciones": [
      {
        "campo": "familias[2].en_promocion",
        "accion": "reparar",
        "detalle": "\"3,0\" → 3 (coma decimal sin parte fraccionaria)"
      }
    ]
  }
}
```


**Caso nuevo: campo 'Fecha' con mayúscula** — `POST /v1/prediccion` → HTTP 200 (98 ms)

Solicitud:
```json
{
  "tienda_id": 5,
  "familias": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0
    },
    {
      "familia_id": "licores",
      "en_promocion": 0
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9
    }
  ],
  "Fecha": "2025-11-17"
}
```

Respuesta:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "1",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0,
      "venta_esperada": 1022.52,
      "cantidad_sugerida": 1237
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0,
      "venta_esperada": 61.49,
      "cantidad_sugerida": 79
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8,
      "venta_esperada": 989.43,
      "cantidad_sugerida": 1197
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0,
      "venta_esperada": 213.54,
      "cantidad_sugerida": 190
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0,
      "venta_esperada": 178.08,
      "cantidad_sugerida": 239
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0,
      "venta_esperada": 373.32,
      "cantidad_sugerida": 336
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0,
      "venta_esperada": 424.31,
      "cantidad_sugerida": 412
    },
    {
      "familia_id": "licores",
      "en_promocion": 0,
      "venta_esperada": 80.86,
      "cantidad_sugerida": 112
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0,
      "venta_esperada": 202.2,
      "cantidad_sugerida": 259
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0,
      "venta_esperada": 44.77,
      "cantidad_sugerida": 55
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0,
      "venta_esperada": 224.15,
      "cantidad_sugerida": 182
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9,
      "venta_esperada": 353.21,
      "cantidad_sugerida": 403
    }
  ],
  "calidad": {
    "estado": "corregido",
    "observaciones": [
      {
        "campo": "fecha",
        "accion": "reparar",
        "detalle": "el campo 'Fecha' se renombró a 'fecha' según el contrato"
      }
    ]
  }
}
```


**Caso nuevo: campo desconocido 'canal'** — `POST /v1/prediccion` → HTTP 200 (354 ms)

Solicitud:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "familias": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0
    },
    {
      "familia_id": "licores",
      "en_promocion": 0
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9
    }
  ],
  "canal": "pos"
}
```

Respuesta:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "1",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0,
      "venta_esperada": 1022.52,
      "cantidad_sugerida": 1237
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0,
      "venta_esperada": 61.49,
      "cantidad_sugerida": 79
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8,
      "venta_esperada": 989.43,
      "cantidad_sugerida": 1197
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0,
      "venta_esperada": 213.54,
      "cantidad_sugerida": 190
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0,
      "venta_esperada": 178.08,
      "cantidad_sugerida": 239
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0,
      "venta_esperada": 373.32,
      "cantidad_sugerida": 336
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0,
      "venta_esperada": 424.31,
      "cantidad_sugerida": 412
    },
    {
      "familia_id": "licores",
      "en_promocion": 0,
      "venta_esperada": 80.86,
      "cantidad_sugerida": 112
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0,
      "venta_esperada": 202.2,
      "cantidad_sugerida": 259
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0,
      "venta_esperada": 44.77,
      "cantidad_sugerida": 55
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0,
      "venta_esperada": 224.15,
      "cantidad_sugerida": 182
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9,
      "venta_esperada": 353.21,
      "cantidad_sugerida": 403
    }
  ],
  "calidad": {
    "estado": "advertencia",
    "observaciones": [
      {
        "campo": "canal",
        "accion": "advertir",
        "detalle": "el campo 'canal' no forma parte del contrato; se ignoró"
      }
    ]
  }
}
```


**Caso nuevo: FATAL tienda inexistente 99** — `POST /v1/prediccion` → HTTP 422 (9 ms)

Solicitud:
```json
{
  "tienda_id": 99,
  "fecha": "2025-11-17",
  "familias": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0
    },
    {
      "familia_id": "licores",
      "en_promocion": 0
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9
    }
  ]
}
```

Respuesta:
```json
{
  "detail": [
    {
      "campo": "tienda_id",
      "accion": "rechazar",
      "detalle": "la tienda 99 no existe en el catálogo de tiendas (válidas: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10)"
    }
  ]
}
```


**Caso nuevo: FATAL tienda negativa -3** — `POST /v1/prediccion` → HTTP 422 (10 ms)

Solicitud:
```json
{
  "tienda_id": -3,
  "fecha": "2025-11-17",
  "familias": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0
    },
    {
      "familia_id": "licores",
      "en_promocion": 0
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9
    }
  ]
}
```

Respuesta:
```json
{
  "detail": [
    {
      "campo": "tienda_id",
      "accion": "rechazar",
      "detalle": "debe ser un entero positivo; se recibió -3"
    }
  ]
}
```


**Caso nuevo: FATAL familia irreconocible 'juguetes'** — `POST /v1/prediccion` → HTTP 422 (7 ms)

Solicitud:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "familias": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8
    },
    {
      "familia_id": "juguetes",
      "en_promocion": 0
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0
    },
    {
      "familia_id": "licores",
      "en_promocion": 0
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9
    }
  ]
}
```

Respuesta:
```json
{
  "detail": [
    {
      "campo": "familias[3].familia_id",
      "accion": "rechazar",
      "detalle": "\"juguetes\" no corresponde a ninguna familia del catálogo (válidas: abarrotes, bebe, bebidas, carnes, cuidado_personal, frutas_verduras, lacteos, licores, limpieza, mascotas, panaderia, snacks)"
    }
  ]
}
```


**Caso nuevo: FATAL fecha inexistente 2025-02-30** — `POST /v1/prediccion` → HTTP 422 (10 ms)

Solicitud:
```json
{
  "tienda_id": 5,
  "fecha": "2025-02-30",
  "familias": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0
    },
    {
      "familia_id": "licores",
      "en_promocion": 0
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9
    }
  ]
}
```

Respuesta:
```json
{
  "detail": [
    {
      "campo": "fecha",
      "accion": "rechazar",
      "detalle": "\"2025-02-30\" no es una fecha válida del calendario"
    }
  ]
}
```


**Caso nuevo: FATAL fecha anterior a la apertura (tienda 10)** — `POST /v1/prediccion` → HTTP 422 (9 ms)

Solicitud:
```json
{
  "tienda_id": 10,
  "fecha": "2025-01-05",
  "familias": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0
    },
    {
      "familia_id": "licores",
      "en_promocion": 0
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9
    }
  ]
}
```

Respuesta:
```json
{
  "detail": [
    {
      "campo": "fecha",
      "accion": "rechazar",
      "detalle": "la tienda 10 abrió el 2025-03-15; no puede haber operación el 2025-01-05"
    }
  ]
}
```


**Caso nuevo: FATAL en_promocion negativo** — `POST /v1/prediccion` → HTTP 422 (9 ms)

Solicitud:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "familias": [
    {
      "familia_id": "abarrotes",
      "en_promocion": -1
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0
    },
    {
      "familia_id": "licores",
      "en_promocion": 0
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9
    }
  ]
}
```

Respuesta:
```json
{
  "detail": [
    {
      "campo": "familias[0].en_promocion",
      "accion": "rechazar",
      "detalle": "no puede ser negativo (se recibió -1)"
    }
  ]
}
```


**Caso nuevo: FATAL en_promocion decimal 2.5** — `POST /v1/prediccion` → HTTP 422 (7 ms)

Solicitud:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "familias": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 2.5
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0
    },
    {
      "familia_id": "licores",
      "en_promocion": 0
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9
    }
  ]
}
```

Respuesta:
```json
{
  "detail": [
    {
      "campo": "familias[0].en_promocion",
      "accion": "rechazar",
      "detalle": "2.5 no es un número entero"
    }
  ]
}
```


**Caso nuevo: FATAL lista de familias vacía** — `POST /v1/prediccion` → HTTP 422 (7 ms)

Solicitud:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "familias": []
}
```

Respuesta:
```json
{
  "detail": [
    {
      "campo": "familias",
      "accion": "rechazar",
      "detalle": "la lista está vacía; se requiere al menos una familia"
    }
  ]
}
```


**Caso nuevo: FATAL falta tienda_id** — `POST /v1/prediccion` → HTTP 422 (7 ms)

Solicitud:
```json
{
  "fecha": "2025-11-17",
  "familias": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0
    },
    {
      "familia_id": "licores",
      "en_promocion": 0
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9
    }
  ]
}
```

Respuesta:
```json
{
  "detail": [
    {
      "campo": "tienda_id",
      "accion": "rechazar",
      "detalle": "falta el campo obligatorio 'tienda_id'"
    }
  ]
}
```


**FATAL cuerpo que no es JSON** — `POST /v1/prediccion` → HTTP 422 (7 ms)

Respuesta:
```json
{
  "detail": [
    {
      "campo": "cuerpo",
      "accion": "rechazar",
      "detalle": "el cuerpo no es JSON válido"
    }
  ]
}
```


**FATAL ventas no numéricas** — `POST /v1/observaciones` → HTTP 422 (7 ms)

Solicitud:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "ventas": [
    {
      "familia_id": "abarrotes",
      "ventas": "abc"
    },
    {
      "familia_id": "bebe",
      "ventas": 50
    },
    {
      "familia_id": "bebidas",
      "ventas": 1292
    },
    {
      "familia_id": "carnes",
      "ventas": 182
    },
    {
      "familia_id": "cuidado_personal",
      "ventas": 118
    },
    {
      "familia_id": "frutas_verduras",
      "ventas": 410
    },
    {
      "familia_id": "lacteos",
      "ventas": 358
    },
    {
      "familia_id": "licores",
      "ventas": 85
    },
    {
      "familia_id": "limpieza",
      "ventas": 202
    },
    {
      "familia_id": "mascotas",
      "ventas": 63
    },
    {
      "familia_id": "panaderia",
      "ventas": 213
    },
    {
      "familia_id": "snacks",
      "ventas": 386
    }
  ]
}
```

Respuesta:
```json
{
  "detail": [
    {
      "campo": "ventas[0].ventas",
      "accion": "rechazar",
      "detalle": "\"abc\" no es un número reconocible"
    }
  ]
}
```


</details>

## 3. Operación diaria e idempotencia de observaciones

- ✅ 70 pares de envíos: 1º registros_guardados > 0 y 2º idéntico → 200 con 0
- ✅ 70 pronósticos diarios → 200 con version_modelo str y cantidades int >= 0

<details><summary>Evidencia (JSON reales)</summary>

| Día pronosticado | Observaciones enviadas de | registros_guardados (1er envío) | tiendas |
|---|---|---|---|
| 2026-03-02 | 2026-03-01 | 120 | 10 |
| 2026-03-03 | 2026-03-02 | 120 | 10 |
| 2026-03-04 | 2026-03-03 | 120 | 10 |
| 2026-03-05 | 2026-03-04 | 120 | 10 |
| 2026-03-06 | 2026-03-05 | 120 | 10 |
| 2026-03-07 | 2026-03-06 | 120 | 10 |
| 2026-03-08 | 2026-03-07 | 120 | 10 |

Costo de negocio real de las cantidades sugeridas en la simulación (60 tienda-días evaluados): **19,075.50**


**Observaciones 2026-03-01 tienda 1 (1er envío)** — `POST /v1/observaciones` → HTTP 200 (18 ms)

Solicitud:
```json
{
  "tienda_id": 1,
  "fecha": "2026-03-01",
  "ventas": [
    {
      "familia_id": "abarrotes",
      "ventas": 637
    },
    {
      "familia_id": "bebe",
      "ventas": 98
    },
    {
      "familia_id": "bebidas",
      "ventas": 681
    },
    {
      "familia_id": "carnes",
      "ventas": 247
    },
    {
      "familia_id": "cuidado_personal",
      "ventas": 259
    },
    {
      "familia_id": "frutas_verduras",
      "ventas": 408
    },
    {
      "familia_id": "lacteos",
      "ventas": 395
    },
    {
      "familia_id": "licores",
      "ventas": 107
    },
    {
      "familia_id": "limpieza",
      "ventas": 356
    },
    {
      "familia_id": "mascotas",
      "ventas": 81
    },
    {
      "familia_id": "panaderia",
      "ventas": 330
    },
    {
      "familia_id": "snacks",
      "ventas": 396
    }
  ]
}
```

Respuesta:
```json
{
  "registros_guardados": 12,
  "calidad": {
    "estado": "ok",
    "observaciones": []
  }
}
```


**Observaciones 2026-03-01 tienda 1 (2º envío idéntico)** — `POST /v1/observaciones` → HTTP 200 (11 ms)

Solicitud:
```json
{
  "tienda_id": 1,
  "fecha": "2026-03-01",
  "ventas": [
    {
      "familia_id": "abarrotes",
      "ventas": 637
    },
    {
      "familia_id": "bebe",
      "ventas": 98
    },
    {
      "familia_id": "bebidas",
      "ventas": 681
    },
    {
      "familia_id": "carnes",
      "ventas": 247
    },
    {
      "familia_id": "cuidado_personal",
      "ventas": 259
    },
    {
      "familia_id": "frutas_verduras",
      "ventas": 408
    },
    {
      "familia_id": "lacteos",
      "ventas": 395
    },
    {
      "familia_id": "licores",
      "ventas": 107
    },
    {
      "familia_id": "limpieza",
      "ventas": 356
    },
    {
      "familia_id": "mascotas",
      "ventas": 81
    },
    {
      "familia_id": "panaderia",
      "ventas": 330
    },
    {
      "familia_id": "snacks",
      "ventas": 396
    }
  ]
}
```

Respuesta:
```json
{
  "registros_guardados": 0,
  "calidad": {
    "estado": "ok",
    "observaciones": []
  }
}
```


**Pronóstico 2026-03-02 tienda 1** — `POST /v1/prediccion` → HTTP 200 (82 ms)

Solicitud:
```json
{
  "tienda_id": 1,
  "fecha": "2026-03-02",
  "familias": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 5
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 1
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 6
    },
    {
      "familia_id": "licores",
      "en_promocion": 6
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0
    },
    {
      "familia_id": "snacks",
      "en_promocion": 0
    }
  ]
}
```

Respuesta:
```json
{
  "tienda_id": 1,
  "fecha": "2026-03-02",
  "version_modelo": "1",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0,
      "venta_esperada": 567.8,
      "cantidad_sugerida": 687
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0,
      "venta_esperada": 67.29,
      "cantidad_sugerida": 87
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 5,
      "venta_esperada": 664.82,
      "cantidad_sugerida": 804
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0,
      "venta_esperada": 219.55,
      "cantidad_sugerida": 195
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 1,
      "venta_esperada": 230.86,
      "cantidad_sugerida": 309
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0,
      "venta_esperada": 318.86,
      "cantidad_sugerida": 287
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 6,
      "venta_esperada": 343.55,
      "cantidad_sugerida": 333
    },
    {
      "familia_id": "licores",
      "en_promocion": 6,
      "venta_esperada": 122.48,
      "cantidad_sugerida": 170
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0,
      "venta_esperada": 229.21,
      "cantidad_sugerida": 293
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0,
      "venta_esperada": 51.07,
      "cantidad_sugerida": 63
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0,
      "venta_esperada": 290.17,
      "cantidad_sugerida": 235
    },
    {
      "familia_id": "snacks",
      "en_promocion": 0,
      "venta_esperada": 279.15,
      "cantidad_sugerida": 318
    }
  ],
  "calidad": {
    "estado": "ok",
    "observaciones": []
  }
}
```


</details>

## 4. Ciclo de reentrenamiento y hot-reload

- ✅ POST /admin/reentrenar → 202 con id (texto)
- ✅ el estado pasa de 'en_curso' a 'exitoso'
- ✅ incluye promovido (bool), version (str) y motivo (str)
- ✅ GET /admin/reentrenar/{id inexistente} → 404
- ✅ hot-reload: GET /modelo pasa a v2 en < 2 min
- ✅ POST /v1/prediccion usa la nueva versión
- ✅ hot-reload de vuelta a v1 en < 2 min
- ✅ el contenedor api no se reinició

Notas:
- La compuerta no promovió (motivo: el candidato no redujo el costo de validación (90924.70 frente a 90471.60 del vigente) en la ventana 2026-02-08..2026-03-07; se conserva v1 como @champion). Se verificó el hot-reload moviendo @champion al challenger v2 directamente en MLflow y restaurando v1.

<details><summary>Evidencia (JSON reales)</summary>

**Modelo antes del reentrenamiento** — `GET /modelo` → HTTP 200 (2 ms)

Respuesta:
```json
{
  "nombre": "novamercado-pronostico",
  "alias": "champion",
  "version": "1"
}
```


**Disparo del reentrenamiento** — `POST /admin/reentrenar` → HTTP 202 (185 ms)

Respuesta:
```json
{
  "id": "4df7b257ce324b4cb22774dca96fba93"
}
```


**Estado final de la ejecución (30 s)** — `GET /admin/reentrenar/4df7b257ce324b4cb22774dca96fba93` → HTTP 200 (14 ms)

Respuesta:
```json
{
  "id": "4df7b257ce324b4cb22774dca96fba93",
  "estado": "exitoso",
  "promovido": false,
  "version": "1",
  "motivo": "el candidato no redujo el costo de validación (90924.70 frente a 90471.60 del vigente) en la ventana 2026-02-08..2026-03-07; se conserva v1 como @champion"
}
```


**Id inexistente** — `GET /admin/reentrenar/id-que-no-existe` → HTTP 404 (14 ms)

Respuesta:
```json
{
  "detail": "no existe la ejecución id-que-no-existe"
}
```


**Predicción tras la promoción controlada a v2** — `POST /v1/prediccion` → HTTP 200 (95 ms)

Solicitud:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "familias": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0
    },
    {
      "familia_id": "licores",
      "en_promocion": 0
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9
    }
  ]
}
```

Respuesta:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "2",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0,
      "venta_esperada": 999.55,
      "cantidad_sugerida": 1209
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0,
      "venta_esperada": 62.28,
      "cantidad_sugerida": 84
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8,
      "venta_esperada": 1003.18,
      "cantidad_sugerida": 1264
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0,
      "venta_esperada": 223.32,
      "cantidad_sugerida": 203
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0,
      "venta_esperada": 175.32,
      "cantidad_sugerida": 238
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0,
      "venta_esperada": 362.77,
      "cantidad_sugerida": 330
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0,
      "venta_esperada": 422.04,
      "cantidad_sugerida": 418
    },
    {
      "familia_id": "licores",
      "en_promocion": 0,
      "venta_esperada": 80.28,
      "cantidad_sugerida": 118
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0,
      "venta_esperada": 203.07,
      "cantidad_sugerida": 266
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0,
      "venta_esperada": 44.18,
      "cantidad_sugerida": 57
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0,
      "venta_esperada": 223.03,
      "cantidad_sugerida": 183
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9,
      "venta_esperada": 353.08,
      "cantidad_sugerida": 403
    }
  ],
  "calidad": {
    "estado": "ok",
    "observaciones": []
  }
}
```


**Modelo al terminar la sección** — `GET /modelo` → HTTP 200 (2 ms)

Respuesta:
```json
{
  "nombre": "novamercado-pronostico",
  "alias": "champion",
  "version": "1"
}
```


</details>

## 5. Caída de MLflow

- ✅ GET /health → 200 con estado 'degradado' y motivo en <= 30 s
- ✅ POST /v1/prediccion sigue respondiendo 200 con el modelo en memoria
- ✅ predicción con MLflow detenido: version_modelo str, cantidad_sugerida int >= 0, calidad válida
- ✅ GET /health vuelve a 'ok' en < 2 min

<details><summary>Evidencia (JSON reales)</summary>

**Salud con MLflow detenido (6 s)** — `GET /health` → HTTP 200 (2 ms)

Respuesta:
```json
{
  "estado": "degradado",
  "motivo": "mlflow no disponible (TimeoutError:)"
}
```


**Predicción con MLflow detenido** — `POST /v1/prediccion` → HTTP 200 (95 ms)

Solicitud:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "familias": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0
    },
    {
      "familia_id": "licores",
      "en_promocion": 0
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9
    }
  ]
}
```

Respuesta:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "1",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "en_promocion": 0,
      "venta_esperada": 1022.52,
      "cantidad_sugerida": 1237
    },
    {
      "familia_id": "bebe",
      "en_promocion": 0,
      "venta_esperada": 61.49,
      "cantidad_sugerida": 79
    },
    {
      "familia_id": "bebidas",
      "en_promocion": 8,
      "venta_esperada": 989.43,
      "cantidad_sugerida": 1197
    },
    {
      "familia_id": "carnes",
      "en_promocion": 0,
      "venta_esperada": 213.54,
      "cantidad_sugerida": 190
    },
    {
      "familia_id": "cuidado_personal",
      "en_promocion": 0,
      "venta_esperada": 178.08,
      "cantidad_sugerida": 239
    },
    {
      "familia_id": "frutas_verduras",
      "en_promocion": 0,
      "venta_esperada": 373.32,
      "cantidad_sugerida": 336
    },
    {
      "familia_id": "lacteos",
      "en_promocion": 0,
      "venta_esperada": 424.31,
      "cantidad_sugerida": 412
    },
    {
      "familia_id": "licores",
      "en_promocion": 0,
      "venta_esperada": 80.86,
      "cantidad_sugerida": 112
    },
    {
      "familia_id": "limpieza",
      "en_promocion": 0,
      "venta_esperada": 202.2,
      "cantidad_sugerida": 259
    },
    {
      "familia_id": "mascotas",
      "en_promocion": 0,
      "venta_esperada": 44.77,
      "cantidad_sugerida": 55
    },
    {
      "familia_id": "panaderia",
      "en_promocion": 0,
      "venta_esperada": 224.15,
      "cantidad_sugerida": 182
    },
    {
      "familia_id": "snacks",
      "en_promocion": 9,
      "venta_esperada": 353.21,
      "cantidad_sugerida": 403
    }
  ],
  "calidad": {
    "estado": "ok",
    "observaciones": []
  }
}
```


**Salud tras reiniciar MLflow (15 s)** — `GET /health` → HTTP 200 (4 ms)

Respuesta:
```json
{
  "estado": "ok"
}
```


</details>

## 6. Persistencia de volúmenes (docker compose down / up -d)

- ✅ tras up -d, GET /health vuelve a 200 'ok'
- ✅ se conservan las filas de observaciones (840)
- ✅ se conservan las filas de historico (83052)
- ✅ se conservan las filas de predicciones (1114)
- ✅ se conservan las filas de solicitudes (248)
- ✅ se conservan las filas de ejecuciones (2)
- ✅ se conservan las versiones del modelo en MLflow sin entrenar de nuevo
- ✅ GET /modelo mantiene la misma versión @champion
- ✅ el bootstrap detectó datos y modelo existentes (no recargó ni reentrenó)
- ✅ reenviar una observación ya guardada tras el reinicio → registros_guardados 0

Notas:
- `docker compose down` y `up -d` ejecutados; up tardó 24 s.

<details><summary>Evidencia (JSON reales)</summary>

**Modelo antes de down** — `GET /modelo` → HTTP 200 (5 ms)

Respuesta:
```json
{
  "nombre": "novamercado-pronostico",
  "alias": "champion",
  "version": "1"
}
```


Antes de `down`:
```json
{
  "conteos": {
    "observaciones": "840",
    "historico": "83052",
    "predicciones": "1114",
    "solicitudes": "248",
    "ejecuciones": "2"
  },
  "versiones_mlflow": [
    "1",
    "2"
  ]
}
```


**Modelo después de up** — `GET /modelo` → HTTP 200 (2 ms)

Respuesta:
```json
{
  "nombre": "novamercado-pronostico",
  "alias": "champion",
  "version": "1"
}
```


Después de `up -d`:
```json
{
  "conteos": {
    "observaciones": "840",
    "historico": "83052",
    "predicciones": "1114",
    "solicitudes": "248",
    "ejecuciones": "2"
  },
  "versiones_mlflow": [
    "1",
    "2"
  ]
}
```


Log del bootstrap tras `up -d`:
```
bootstrap-1  | 2026-11-15 07:06:02,074 INFO novamercado.bootstrap: catálogos ya cargados (10 tiendas, 12 familias): se conservan
bootstrap-1  | 2026-11-15 07:06:02,074 INFO novamercado.bootstrap: histórico ya cargado (83052 filas) y 840 observaciones: se conservan
bootstrap-1  | 2026-11-15 07:06:02,100 INFO novamercado.bootstrap: datos listos: {'tiendas': 10, 'familias': 12, 'historico': 83052, 'observaciones': 840}
bootstrap-1  | 2026-11-15 07:06:04,202 INFO novamercado.bootstrap: MLflow disponible
bootstrap-1  | 2026-11-15 07:06:04,283 INFO novamercado.bootstrap: ya existe novamercado-pronostico@champion (v1): no se reentrena
bootstrap-1  | 2026-11-15 07:06:04,284 INFO novamercado.bootstrap: bootstrap completo: @champion = v1
```


**Reenvío de una observación ya guardada tras el reinicio** — `POST /v1/observaciones` → HTTP 200 (289 ms)

Solicitud:
```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "ventas": [
    {
      "familia_id": "abarrotes",
      "ventas": 994
    },
    {
      "familia_id": "bebe",
      "ventas": 50
    },
    {
      "familia_id": "bebidas",
      "ventas": 1292
    },
    {
      "familia_id": "carnes",
      "ventas": 182
    },
    {
      "familia_id": "cuidado_personal",
      "ventas": 118
    },
    {
      "familia_id": "frutas_verduras",
      "ventas": 410
    },
    {
      "familia_id": "lacteos",
      "ventas": 358
    },
    {
      "familia_id": "licores",
      "ventas": 85
    },
    {
      "familia_id": "limpieza",
      "ventas": 202
    },
    {
      "familia_id": "mascotas",
      "ventas": 63
    },
    {
      "familia_id": "panaderia",
      "ventas": 213
    },
    {
      "familia_id": "snacks",
      "ventas": 386
    }
  ]
}
```

Respuesta:
```json
{
  "registros_guardados": 0,
  "calidad": {
    "estado": "ok",
    "observaciones": []
  }
}
```


</details>
