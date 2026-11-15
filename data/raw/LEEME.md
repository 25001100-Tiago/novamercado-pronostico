# Datos publicados (no versionados)

Coloca aquí los archivos publicados del laboratorio, con esta estructura exacta:

```
data/raw/
├── tiendas.csv
├── familias.csv
├── historico_ventas.csv
├── feriados.csv
├── costos.csv
├── catalogo_errores.md
├── ejemplos/
│   ├── prediccion_valida.json
│   └── observacion_valida.json
└── errores/
    ├── E01_tienda_texto.json
    ├── ...
    └── E10_numero_formato.json
```

Docker Compose monta esta carpeta en modo solo lectura (`/datos`) en los servicios
`bootstrap` y `api`; ninguna imagen contiene datos.
