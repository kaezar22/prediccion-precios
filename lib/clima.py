"""Clima de las fincas (Tenjo, Cundinamarca) con la API de Open-Meteo.

Dos consultas:
- reciente: últimos 92 días y pronóstico a 16 días.
- histórico: lluvia diaria desde 2017 con un solo modelo (ECMWF IFS, celda de 9 km),
  para calcular cuánto llueve normalmente en cada época.

Antes de 2017 Open-Meteo usa otro modelo con mucha más lluvia para este punto,
así que no se mezclan los dos periodos.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd

LATITUD = 4.87
LONGITUD = -74.15
LUGAR = "Tenjo, Cundinamarca"
ZONA = "America/Bogota"
INICIO_HISTORICO = "2017-01-01"
URL_RECIENTE = "https://api.open-meteo.com/v1/forecast"
URL_HISTORICO = "https://archive-api.open-meteo.com/v1/archive"
VARIABLES = "precipitation_sum,temperature_2m_max,temperature_2m_min"
DIAS_ATRAS = 92
DIAS_PRONOSTICO = 16
UMBRAL_HELADA = 2.0        # °C de mínima a partir del cual se avisa riesgo de helada
UMBRAL_LLUVIA_FUERTE = 20  # mm en un día


def _pedir(url: str, parametros: dict) -> dict:
    import requests

    r = requests.get(url, params=parametros, timeout=60)
    r.raise_for_status()
    return r.json()


def _tabla(respuesta: dict) -> pd.DataFrame:
    d = respuesta["daily"]
    t = pd.DataFrame({
        "fecha": pd.to_datetime(d["time"]),
        "lluvia": d["precipitation_sum"],
        "tmax": d["temperature_2m_max"],
        "tmin": d["temperature_2m_min"],
    })
    return t.set_index("fecha").astype(float)


def hoy_bogota() -> dt.date:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=5)).date()


def descargar_reciente() -> tuple[pd.DataFrame, dict]:
    """Últimos 92 días más pronóstico a 16 días. Devuelve la tabla y datos del punto."""
    j = _pedir(URL_RECIENTE, {
        "latitude": LATITUD, "longitude": LONGITUD, "daily": VARIABLES, "timezone": ZONA,
        "past_days": DIAS_ATRAS, "forecast_days": DIAS_PRONOSTICO,
    })
    punto = {"latitud": j.get("latitude"), "longitud": j.get("longitude"), "altura": j.get("elevation")}
    return _tabla(j), punto


def descargar_historico(hasta: dt.date | None = None) -> pd.DataFrame:
    hasta = hasta or (hoy_bogota() - dt.timedelta(days=1))
    j = _pedir(URL_HISTORICO, {
        "latitude": LATITUD, "longitude": LONGITUD, "daily": VARIABLES, "timezone": ZONA,
        "start_date": INICIO_HISTORICO, "end_date": hasta.isoformat(), "models": "ecmwf_ifs",
    })
    return _tabla(j).dropna(subset=["lluvia"])


def lluvia_normal(historico: pd.DataFrame, inicio: dt.date, fin: dt.date) -> pd.Series:
    """Lluvia total que cayó en las mismas fechas (inicio a fin) de cada año anterior."""
    dias = (fin - inicio).days + 1
    totales = {}
    for anio in sorted(set(historico.index.year)):
        try:
            a = pd.Timestamp(inicio.replace(year=anio))
        except ValueError:          # 29 de febrero
            a = pd.Timestamp(inicio.replace(year=anio, day=28))
        b = a + pd.Timedelta(days=dias - 1)
        if a >= pd.Timestamp(inicio):
            continue                # solo años anteriores a la ventana
        tramo = historico.loc[a:b, "lluvia"]
        if len(tramo) >= dias * 0.9:
            totales[anio] = float(tramo.sum())
    return pd.Series(totales, dtype=float)


def _comparar(total: float, normales: pd.Series) -> dict:
    if normales.empty:
        return {"total": total, "normal": float("nan"), "diferencia": float("nan"), "anios": 0, "puesto": 0}
    normal = float(normales.mean())
    return {
        "total": total,
        "normal": normal,
        "diferencia": total / normal - 1 if normal > 0 else float("nan"),
        "anios": int(len(normales)),
        "puesto": int((normales > total).sum()) + 1,   # 1 = más lluvioso que todos los años anteriores
    }


def resumen(reciente: pd.DataFrame, historico: pd.DataFrame, hoy: dt.date) -> dict:
    """Compara la lluvia reciente y la pronosticada con lo normal para esas fechas."""
    ayer = hoy - dt.timedelta(days=1)
    ini30 = ayer - dt.timedelta(days=29)
    obs = reciente.loc[pd.Timestamp(ini30):pd.Timestamp(ayer)]
    pro = reciente.loc[pd.Timestamp(hoy):].dropna(subset=["lluvia"])
    fin_pro = pro.index.max().date() if len(pro) else hoy
    return {
        "ultimos_30": _comparar(float(obs["lluvia"].sum()), lluvia_normal(historico, ini30, ayer)),
        "proximos": _comparar(float(pro["lluvia"].sum()), lluvia_normal(historico, hoy, fin_pro)),
        "dias_pronostico": int(len(pro)),
        "fin_pronostico": fin_pro,
        "tmin_prevista": float(pro["tmin"].min()) if len(pro) else float("nan"),
        "dia_tmin": pro["tmin"].idxmin().date() if len(pro) else None,
        "dias_helada": [f.date() for f in pro.index[pro["tmin"] <= UMBRAL_HELADA]],
        "dias_lluvia_fuerte": [f.date() for f in pro.index[pro["lluvia"] >= UMBRAL_LLUVIA_FUERTE]],
    }


def mensual_vs_normal(reciente: pd.DataFrame, historico: pd.DataFrame, hoy: dt.date, meses: int = 24) -> pd.DataFrame:
    """Lluvia de cada mes completo frente al promedio de ese mes en los demás años."""
    ayer = pd.Timestamp(hoy - dt.timedelta(days=1))
    diario = pd.concat([historico["lluvia"], reciente.loc[:ayer, "lluvia"]])
    diario = diario[~diario.index.duplicated(keep="first")].sort_index()
    por_mes = diario.resample("MS").agg(["sum", "count"])
    completos = por_mes[por_mes["count"] >= por_mes.index.days_in_month]["sum"]
    filas = []
    for mes, total in completos.tail(meses).items():
        otros = completos[(completos.index.month == mes.month) & (completos.index != mes)]
        filas.append({"mes": mes, "lluvia": float(total), "normal": float(otros.mean()) if len(otros) else float("nan")})
    return pd.DataFrame(filas)
