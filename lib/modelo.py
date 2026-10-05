"""Modelo de pronóstico de precios mensuales.

Idea: el precio de un mes se explica por (1) el nivel reciente del producto,
(2) la época del año y (3) qué tan lejos está hoy de ese nivel (inercia).
Todo se trabaja en logaritmos para hablar de cambios porcentuales.

No usa librerías de estadística: solo numpy y pandas.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

HORIZONTES = (1, 2, 3)
VENTANA_NIVEL = 12      # meses para calcular el nivel reciente
MIN_HISTORIA = 48       # meses mínimos para ajustar el modelo
RIDGE = 1.0             # regularización suave de los efectos por mes
UMBRAL_CAMBIO = 0.10    # cambio que consideramos relevante (10 %)
PROB_SENAL = 0.60       # probabilidad mínima para dar una señal


def _nivel(log_p: pd.Series) -> pd.Series:
    """Promedio de los últimos 12 meses disponibles (en logaritmos del promedio)."""
    p = np.exp(log_p)
    return np.log(p.rolling(VENTANA_NIVEL, min_periods=9).mean())


def _tabla(serie: pd.Series, h: int) -> pd.DataFrame:
    """Arma las filas de entrenamiento para el horizonte h.

    Cada fila usa solo información conocida en el mes de origen.
    """
    s = serie.asfreq("MS")
    log_p = np.log(s)
    nivel = _nivel(log_p)
    df = pd.DataFrame({
        "desvio": log_p - nivel,                 # qué tan lejos está hoy de su nivel
        "nivel": nivel,
        "log_ultimo": log_p,
        "objetivo": log_p.shift(-h) - nivel,     # precio futuro frente al nivel de hoy
    })
    df["mes_objetivo"] = (df.index + pd.DateOffset(months=h)).month
    return df


def _ajustar(df: pd.DataFrame) -> np.ndarray | None:
    d = df.dropna(subset=["desvio", "objetivo"])
    if len(d) < MIN_HISTORIA:
        return None
    x = np.zeros((len(d), 13))
    x[np.arange(len(d)), d["mes_objetivo"].to_numpy() - 1] = 1.0
    x[:, 12] = d["desvio"].to_numpy()
    y = d["objetivo"].to_numpy()
    pen = np.eye(13) * RIDGE
    pen[12, 12] = 0.0
    return np.linalg.solve(x.T @ x + pen, x.T @ y)


def _predecir(coef: np.ndarray, desvio: float, mes_objetivo: int) -> float:
    return float(coef[mes_objetivo - 1] + coef[12] * desvio)


@dataclass
class Pronostico:
    producto: str
    origen: pd.Timestamp          # último mes con dato
    ultimo: float                 # precio de ese mes
    nivel_12m: float              # promedio de los últimos 12 meses
    tabla: pd.DataFrame           # una fila por horizonte


def retroprueba(serie: pd.Series, desde: str = "2018-01-01") -> pd.DataFrame:
    """Simula el pasado: en cada mes ajusta con lo conocido hasta ahí y pronostica.

    Devuelve una fila por (mes de origen, horizonte) con el pronóstico del modelo,
    el de la regla simple "igual al último mes" y el valor real.
    """
    s = serie.dropna().asfreq("MS")
    filas = []
    for h in HORIZONTES:
        df = _tabla(s, h)
        origenes = df.index[(df.index >= pd.Timestamp(desde))]
        for o in origenes:
            fila = df.loc[o]
            if pd.isna(fila["desvio"]) or pd.isna(fila["objetivo"]):
                continue
            # Solo filas cuyo objetivo ya se conocía en el mes de origen.
            conocido = df.loc[: o - pd.DateOffset(months=h)]
            coef = _ajustar(conocido)
            if coef is None:
                continue
            pred = _predecir(coef, fila["desvio"], int(fila["mes_objetivo"])) + fila["nivel"]
            real = fila["objetivo"] + fila["nivel"]
            filas.append({
                "origen": o,
                "mes": o + pd.DateOffset(months=h),
                "h": h,
                "ultimo": float(np.exp(fila["log_ultimo"])),
                "modelo": float(np.exp(pred)),
                "real": float(np.exp(real)),
                "error_log": float(real - pred),
            })
    return pd.DataFrame(filas)


def metricas(rp: pd.DataFrame) -> pd.DataFrame:
    """Resume la retroprueba por horizonte."""
    out = []
    for h, g in rp.groupby("h"):
        err_m = (g["modelo"] - g["real"]).abs() / g["real"]
        err_s = (g["ultimo"] - g["real"]).abs() / g["real"]
        mov = (g["real"] / g["ultimo"] - 1).abs() >= UMBRAL_CAMBIO
        acierto_dir = (np.sign(g["modelo"] - g["ultimo"]) == np.sign(g["real"] - g["ultimo"]))
        out.append({
            "h": h,
            "meses": len(g),
            "error_modelo": float(err_m.median()),
            "error_simple": float(err_s.median()),
            "mejora": float(1 - err_m.mean() / err_s.mean()),
            "acierto_direccion": float(acierto_dir[mov].mean()) if mov.any() else np.nan,
            "meses_con_movimiento": int(mov.sum()),
        })
    return pd.DataFrame(out)


def pronosticar(serie: pd.Series, producto: str, rp: pd.DataFrame | None = None) -> Pronostico | None:
    """Pronóstico a 1, 2 y 3 meses con rango y probabilidades.

    El rango y las probabilidades salen de los errores que el modelo cometió
    en la retroprueba, no de una fórmula teórica.
    """
    s = serie.dropna().asfreq("MS")
    if s.dropna().shape[0] < MIN_HISTORIA + VENTANA_NIVEL:
        return None
    if rp is None:
        rp = retroprueba(s)
    origen = s.dropna().index[-1]
    filas = []
    nivel_hoy = np.nan
    for h in HORIZONTES:
        df = _tabla(s, h)
        coef = _ajustar(df)
        fila = df.loc[origen]
        if coef is None or pd.isna(fila["desvio"]):
            continue
        nivel_hoy = fila["nivel"]
        mes = origen + pd.DateOffset(months=h)
        centro = _predecir(coef, fila["desvio"], mes.month) + fila["nivel"]
        errores = rp.loc[rp["h"] == h, "error_log"].to_numpy()
        if len(errores) < 24:
            continue
        posibles = centro + errores
        log_ult = fila["log_ultimo"]
        filas.append({
            "mes": mes,
            "h": h,
            "pronostico": float(np.exp(centro)),
            "bajo": float(np.exp(np.quantile(posibles, 0.10))),
            "alto": float(np.exp(np.quantile(posibles, 0.90))),
            "cambio": float(np.exp(centro - log_ult) - 1),
            "prob_baja": float(np.mean(posibles < log_ult + np.log(1 - UMBRAL_CAMBIO))),
            "prob_sube": float(np.mean(posibles > log_ult + np.log(1 + UMBRAL_CAMBIO))),
        })
    if not filas:
        return None
    return Pronostico(
        producto=producto,
        origen=origen,
        ultimo=float(s.loc[origen]),
        nivel_12m=float(np.exp(nivel_hoy)),
        tabla=pd.DataFrame(filas),
    )


def senal(prob_baja: float, prob_sube: float) -> str:
    if prob_baja >= PROB_SENAL:
        return "Baja probable"
    if prob_sube >= PROB_SENAL:
        return "Sube probable"
    return "Sin señal clara"


def estacionalidad(serie: pd.Series) -> pd.DataFrame:
    """Cuánto se aleja cada mes del año del nivel de sus 12 meses alrededor."""
    s = serie.dropna().asfreq("MS")
    centro = s.rolling(13, center=True, min_periods=13).mean()
    rel = (s / centro).dropna()
    g = rel.groupby(rel.index.month)
    return pd.DataFrame({"mes": g.mean().index, "indice": g.mean().to_numpy(), "anios": g.count().to_numpy()})
