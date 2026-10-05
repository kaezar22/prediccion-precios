# Predicción de precios de hortalizas - Nutrienti (beta)

App en Streamlit que pronostica el precio mayorista de hortalizas en Corabastos
a uno, dos y tres meses, para decidir qué productos ofrecer.

## Secciones

- **Resumen**: señal del próximo mes por producto (baja probable, alza probable o sin señal clara).
- **Producto**: historia desde 2013, pronóstico con rango, época del año y últimas semanas.
- **Aciertos**: qué tan bien habría acertado el modelo desde 2018, comparado con la regla simple de "igual al último mes".
- **Clima**: lluvia reciente y pronosticada en Tenjo frente a lo normal, con alertas de helada y lluvia fuerte.
- **Datos**: fuentes, fechas, actualización desde el DANE y descarga.

## Cómo correrla en el computador

```
pip install -r requirements.txt
streamlit run app.py
```

Se abre en el navegador en `http://localhost:8501`.

## Cómo publicarla en Streamlit Cloud

1. Subir esta carpeta completa a un repositorio de GitHub.
2. En share.streamlit.io crear una app nueva apuntando a ese repositorio, con `app.py` como archivo principal.

No necesita claves ni secretos.

## Datos

Precio promedio por kilo de SIPSA (DANE), mercado Bogotá, D.C., Corabastos.

- `data/sipsa_corabastos_mensual.csv`: enero de 2013 a agosto de 2026, tomado de las series históricas del DANE.
- `data/sipsa_corabastos_semanal.csv`: octubre de 2025 a septiembre de 2026, tomado del servicio web de SIPSA.

Productos: cilantro, lechuga Batavia, lechuga crespa verde, espinaca, acelga, apio, perejil,
rábano rojo, tomate chonto, zanahoria y limón Tahití. SIPSA no publica cogollo europeo,
lechuga romana, rúgula ni mezclas.

Cuando el DANE aún no publica un mes, la app lo estima con el promedio de los precios semanales
y lo marca como provisional.

El botón de actualizar consulta `https://appweb.dane.gov.co/sipsaWS/SrvSipsaUpraBeanService`.
El lector de esa respuesta está probado con archivos reales; la consulta en vivo desde la app aún no se ha probado.

## Modelo

Para cada producto combina el nivel de los últimos 12 meses, la época del año y qué tan lejos
está hoy el precio de ese nivel. Los rangos y probabilidades salen de los errores cometidos al
simular el pasado. No usa clima. El código está en `lib/modelo.py`.

## Clima

La sección Clima consulta Open-Meteo (sin clave) para Tenjo, Cundinamarca: los últimos 92 días,
el pronóstico a 16 días y la lluvia diaria desde 2017 con el modelo ECMWF IFS. El plan gratuito de
Open-Meteo es para uso no comercial; conviene revisar sus condiciones antes de pasar de la beta.

El clima no entra en el pronóstico de precios: al comparar la lluvia con los precios usando tres
fuentes distintas (NASA POWER, ERA5 y ECMWF IFS), la relación no se sostuvo. El código está en `lib/clima.py`.

## Pruebas

```
pip install pytest
pytest
```

## Qué no incluye

Este repositorio no contiene datos de World Office (compras, ventas, clientes ni proveedores).
