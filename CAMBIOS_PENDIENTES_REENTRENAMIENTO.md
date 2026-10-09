# Cambios pendientes de revertir al re-entrenar el modelo

> **Estado 2026-10-07:** el modelo **v10** (entrega `hrnet_final_seed42`,
> sin `BIAS_CORRECTION`, contrato ch6-8 P2-P98) ya esta desplegado en
> `apuguard-endpoint` (`apuguard-hrnet-v10`, config
> `apuguard-endpoint-config-v10`) y validado E2E (ver `infra/README.md`
> seccion 7). El punto 1 de este documento ya quedo RESUELTO. Los puntos
> 2-4 siguen vigentes como decisiones pendientes del pipeline.

Este documento lista todos los cambios temporales aplicados para compensar
las deficiencias del modelo actual. Al re-entrenar HRNet correctamente
(con class weighting, focal loss, y datos balanceados), estos cambios
deben REVERTIRSE.

---

## 1. Bias correction en inferencia — RESUELTO (v10)

**Archivo:** `model_inspect/code/inference.py:35`
**Cambio:** `BIAS_CORRECTION = 36.0`
**Estado:** ya no existe. El `inference.py` de la entrega final
(`model_source/inference.py`) no tiene ningun desplazamiento de logits
(`0.0` implicito) y es el que corre en el endpoint v10 desde 2026-10-07.

**Razon:** El modelo entrenado produce logits extremadamente negativos
(-95 a -18) debido a class imbalance severo en el dataset de entrenamiento.
Al re-entrenar con balanceo de clases, los logits deberian distribuirse
normalmente alrededor de 0, haciendo innecesario el bias.

---

## 2. Stride de tiling

**Archivo:** `backend/ml_engine/preprocessing.py:32`
**Cambio:** `STRIDE = 128` (sin solapamiento)
**Revertir a:** `STRIDE = 64` (50% solapamiento)

**Razon:** Se aumento el stride de 64 a 128 para reducir la cantidad de
parches de ~21,000 a ~6,600 por quincena, disminuyendo costos de SageMaker
y falsos positivos por falta de solapamiento. Con un modelo bien entrenado
que no produzca falsos positivos en bordes, volver a stride=64 es seguro
y recomendable (mejor cobertura, menos artefactos de borde).

---

## 3. Filtro de concentracion en bordes

**Archivo:** `backend/ml_engine/tasks.py` (~linea 655)
**Cambio:** Descartar detecciones con >75% de pixeles en margen de 8px
**Revertir a:** Eliminar el bloque completo (secciones 3b en adelante)

**Razon:** El stride=128 (sin solapamiento) produce artefactos de borde
porque el modelo tiene menos contexto en los bordes de cada parche.
Al volver a stride=64 con solapamiento, los parches adyacentes validan
o descartan las detecciones de borde, haciendo innecesario este filtro.

---

## 4. Filtro de area minima

**Archivo:** `backend/ml_engine/tasks.py` (~linea 670)
**Cambio:** Descartar detecciones con area < 3 hectareas (300 pixeles)
**Revertir a:** Eliminar el bloque completo

**Razon:** El bias correction (+36) produce pequenos clusters de falsos
positivos (1-3 Ha) en zonas de bosque sano. Con un modelo bien entrenado
(bias=0, logits normales), las detecciones pequenas deberian ser mas
precisas y este filtro no seria necesario. O se podria bajar a 0.5 Ha
como umbral minimo razonable sin sacrificar sensibilidad.

---

## 5. Versiones del endpoint SageMaker

Se crearon multiples versiones del modelo para iterar sobre el bias:

| Version | Bias | Resultado |
|---------|------|-----------|
| v2 | N/A (sin modelo) | Todo ceros |
| v5 | Sin bias, imagen corregida | Todo ceros |
| v7 | +50 | ~400 alertas, muchos falsos positivos |
| v8 | +44 | ~6,000+ alertas |
| v9 | +36 | Superado (contrato antiguo ch6-8 en [0,1]) |
| **v10** | **0 (sin BIAS_CORRECTION)** | **Actual desde 2026-10-07: modelo reentrenado de la entrega final, contrato ch6-8 estirado a [-1,1]** |

Al re-entrenar de nuevo: crear un modelo nuevo (v11+) con bias=0,
manteniendo el contrato P2-P98 y subirlo con `18_redeploy_sagemaker.py`.

---

## Resumen de archivos a revertir

| Archivo | Cambio | Revertir |
|---------|--------|----------|
| `model_source/inference.py` | Sin `BIAS_CORRECTION` (v10) | *ya resuelto* |
| `backend/ml_engine/preprocessing.py:32` | `STRIDE = 128` | `64` |
| `backend/ml_engine/tasks.py` ~655-670 | Filtro bordes + area minima | Eliminar ambos bloques |
| SageMaker endpoint | v10 (bias=0, actual) | Desplegar v11+ si se re-entrena |

---

## Pipeline de re-entrenamiento sugerido

1. Recolectar dataset balanceado (50% deforestacion, 50% bosque sano)
2. Usar focal loss o class weighting en el entrenamiento
3. Validar que los logits del nuevo modelo se distribuyan en [-2, +2]
4. Probar con bias=0 en ~100 parches de Tambopata
5. Si las detecciones son razonables, revertir los 4 cambios de codigo
6. Desplegar como nueva version del endpoint
