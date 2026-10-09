"""
21_smoke_dedup_alertas.py
==========================
Verifica la logica de deduplicacion entre pasadas (Fase G):

  T1   INCERTIDUMBRE: misma zona en dos pasadas -> UN solo caso
  T2   INCERTIDUMBRE sin geometria -> no crea caso
  T3   INCERTIDUMBRE no enmascara deforestacion real (.exclude obligatorio)
  T4   Diferencia espacial: misma geometria -> None (dedup geometrico)
  T5   Umbral de 3 Ha sobre el DELTA neta (sliver descartado)
  T6   _aplicar_logica_ecologica: una sola vez por captura (captura_ultimo_ciclo)
  T6b  ...pero avanza en la pasada siguiente
  T7   _aplicar_logica_ecologica: no toca casos INCERTIDUMBRE
  T8   cerrar_incertidumbres_obsoletas: cierra tras N pasadas
  T8b  ...idempotente (2a ejecucion no cambia nada)
  T9   Tras RECUPERADO, re-deteccion crea UN CASO NUEVO (decision 2)
  T10  Caso nuevo vinculado a su captura de nacimiento
  T11  Captura get_or_create idempotente en re-ejecucion (Fase G5)
  T12  Parche get_or_create idempotente en re-ejecucion (Fase G5)
  T13  GET /api/alertas/ expone es_nueva / veces_detectado / fechas
  T14  GET /api/alertas/?solo_nuevas=true devuelve SOLO las nuevas
  T15  GET /api/alertas/?zona__icontains filtra de verdad
  T16  GET /api/dashboard/stats/ con los 6 KPIs nuevos
  T17  KPI alertas_nuevas_pasada cuadra con la tabla filtrada

Cada test usa una zona geografica propia para no interferir con los demas.
Todo corre dentro de una transaccion que se revierte: no deja rastro en BD.

Uso (dentro del contenedor web):
    docker compose exec web python /app/scripts/21_smoke_dedup_alertas.py
"""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _template_python import setup
setup()

import django
django.setup()

from datetime import date, timedelta

from django.contrib.gis.geos import Polygon
from django.db import transaction

from core.models import (
    CasoAuditoria, CapturaSatelital, ConfiguracionGlobal,
    ParcheProcesamiento,
)
from ml_engine.tasks import (
    AREA_MINIMA_HA,
    _a_multipoligono,
    _aplicar_logica_ecologica,
    _area_ha,
    _buscar_caso_abierto,
    _calcular_diferencia_espacial,
    _crear_o_actualizar_caso,
    cerrar_incertidumbres_obsoletas,
)

INC = CasoAuditoria.TipoCaso.INCERTIDUMBRE
DET = CasoAuditoria.TipoCaso.DETECCION

RESULTADOS = []


def check(nombre, ok, detalle=""):
    estado = "PASA" if ok else "FALLA"
    RESULTADOS.append((estado, nombre))
    print(f"[{estado}] {nombre}" + (f" — {detalle}" if detalle else ""))
    return ok


def mk_captura(fecha, idx, estado=CapturaSatelital.EstadoLiberacion.AUDITORIA):
    return CapturaSatelital.objects.create(
        fecha_adquisicion=fecha,
        s3_path_raw=f"s3://smoke/raw/{fecha.isoformat()}",
        cobertura_nubes=0.0,
        estado_liberacion=estado,
    )


def mk_parche(captura, fila, col, geom):
    return ParcheProcesamiento.objects.create(
        captura=captura,
        fila_idx=fila,
        col_idx=col,
        s3_path_tensor=f"s3://smoke/in/{captura.pk}/{fila}_{col}.npy",
        estado_sagemaker=ParcheProcesamiento.EstadoSageMaker.PROCESADO,
        geom=geom,
    )


def mk_caso(parche, tipo, geom, captura=None,
            estado_caso=CasoAuditoria.EstadoCaso.PENDIENTE_REVISION,
            veces=1, ciclos=0):
    cap = captura or parche.captura
    return CasoAuditoria.objects.create(
        parche=parche,
        tipo_caso=tipo,
        estado_caso=estado_caso,
        score_confianza=0.8,
        geom_afectada=_a_multipoligono(geom),
        estado_ecologico=CasoAuditoria.EstadoEcologico.PERTURBADO,
        ciclos_limpios_consecutivos=ciclos,
        captura_nacimiento=cap,
        captura_ultima_deteccion=cap,
        captura_ultimo_ciclo=cap,
        veces_detectado=veces,
    )


def caja(lon, lat, size=0.01):
    """Caja wgs84 de `size` grados en (lon, lat)."""
    return Polygon.from_bbox((lon, lat, lon + size, lat + size))


def sandbox(lon, lat, c0, c1, fila, size=0.01):
    """Parche de la misma geometria en c0 y en c1 (dos pasadas)."""
    g = caja(lon, lat, size)
    return mk_parche(c0, fila, fila, g), mk_parche(c1, fila, fila, g)


def main():
    with transaction.atomic():
        c0 = mk_captura(date(2030, 1, 1), 0)
        c1 = mk_captura(date(2030, 1, 16), 1)

        # ── T1/T2/T3/T7: zona G1 ───────────────────────────────────────────
        ZONA_G1 = caja(-69.60, -13.10)
        pa1, pb1 = sandbox(-69.60, -13.10, c0, c1, 1)

        caso1, nuevo1 = _crear_o_actualizar_caso(
            parche=pa1, captura=c0, tipo_caso=INC,
            score_confianza=0.7, geom_nuevo=ZONA_G1, alertar=False,
        )
        caso2, nuevo2 = _crear_o_actualizar_caso(
            parche=pb1, captura=c1, tipo_caso=INC,
            score_confianza=0.9, geom_nuevo=ZONA_G1, alertar=False,
        )
        caso1.refresh_from_db()
        check(
            "T1 INCERTIDUMBRE deduplicada entre pasadas",
            nuevo1 and not nuevo2 and caso1.pk == caso2.pk
            and caso1.veces_detectado == 2
            and caso1.captura_ultima_deteccion_id == c1.pk
            and caso1.captura_nacimiento_id == c0.pk,
            f"veces={caso1.veces_detectado} nacimiento={caso1.captura_nacimiento_id} "
            f"ultima={caso1.captura_ultima_deteccion_id}",
        )

        res_t2 = _crear_o_actualizar_caso(
            parche=pa1, captura=c1, tipo_caso=INC,
            score_confianza=0.4, geom_nuevo=None, alertar=False,
        )
        check("T2 INCERTIDUMBRE sin geometria no crea caso",
              res_t2 == (None, False), f"retorno={res_t2}")

        delta_g1 = _calcular_diferencia_espacial([ZONA_G1])
        check(
            "T3 INCERTIDUMBRE no enmascara deforestacion nueva",
            delta_g1 is not None and not delta_g1.empty,
            f"delta={'None' if delta_g1 is None else 'geometria devuelta'}",
        )

        # ── T4: zona G2 ────────────────────────────────────────────────────
        HIST_G2 = caja(-69.55, -13.10)
        pa2, _ = sandbox(-69.55, -13.10, c0, c1, 2)
        mk_caso(pa2, DET, HIST_G2, captura=c0)
        delta_g2 = _calcular_diferencia_espacial([HIST_G2])
        check("T4 Resta espacial devuelve None con geometria identica",
              delta_g2 is None or delta_g2.empty,
              f"delta={'None' if delta_g2 is None else 'geometria devuelta'}")

        # ── T5: zona G3 (sliver) ───────────────────────────────────────────
        HIST_G3  = Polygon.from_bbox((-69.50, -13.10, -69.49, -13.09001))
        NUEVO_G3 = Polygon.from_bbox((-69.50, -13.10, -69.49, -13.09))
        pa3, _ = sandbox(-69.50, -13.10, c0, c1, 3)
        mk_caso(pa3, DET, HIST_G3, captura=c0)
        delta_g3 = _calcular_diferencia_espacial([NUEVO_G3])
        area_g3 = _area_ha(delta_g3) if delta_g3 is not None else 0.0
        check(
            "T5 Umbral de 3 Ha aplicado sobre el DELTA neta",
            delta_g3 is not None and 0.0 < area_g3 < AREA_MINIMA_HA,
            f"delta={area_g3:.4f} Ha (umbral {AREA_MINIMA_HA} Ha)",
        )

        # ── T6/T6b/T7: zona G4 ─────────────────────────────────────────────
        # parche y pa4b comparten geometria (simula el solapamiento de dos
        # tiles adyacentes si STRIDE < PATCH_SIZE): cada caso vive en un
        # parche distinto porque parche es OneToOne.
        pa4, pb4 = sandbox(-69.45, -13.10, c0, c1, 4)
        pa4b = mk_parche(c0, 41, 41, pa4.geom)
        ciclo_a = mk_caso(pa4, DET, caja(-69.450, -13.100, 0.005), captura=c0)
        ciclo_b = mk_caso(pa4b, DET, caja(-69.445, -13.095, 0.005), captura=c0)
        # ningun caso ha pasado todavia por la logica ecologica en esta captura
        for c in (ciclo_a, ciclo_b):
            c.captura_ultimo_ciclo = None
            c.save(update_fields=["captura_ultimo_ciclo"])

        _aplicar_logica_ecologica(pa4, [])
        _aplicar_logica_ecologica(pa4, [])
        ciclo_a.refresh_from_db()
        ciclo_b.refresh_from_db()
        check(
            "T6 Ciclo limpio contado UNA vez por captura",
            ciclo_a.ciclos_limpios_consecutivos == 1
            and ciclo_b.ciclos_limpios_consecutivos == 1
            and ciclo_a.captura_ultimo_ciclo_id == c0.pk
            and ciclo_b.captura_ultimo_ciclo_id == c0.pk,
            f"ciclos={ciclo_a.ciclos_limpios_consecutivos}/"
            f"{ciclo_b.ciclos_limpios_consecutivos}",
        )

        _aplicar_logica_ecologica(pb4, [])
        ciclo_a.refresh_from_db()
        ciclo_b.refresh_from_db()
        check(
            "T6b Ciclo avanza en la pasada siguiente",
            ciclo_a.ciclos_limpios_consecutivos == 2
            and ciclo_b.ciclos_limpios_consecutivos == 2
            and ciclo_a.captura_ultimo_ciclo_id == c1.pk,
            f"ciclos={ciclo_a.ciclos_limpios_consecutivos}/"
            f"{ciclo_b.ciclos_limpios_consecutivos}",
        )

        ciclos_antes = caso1.ciclos_limpios_consecutivos
        caso1.captura_ultimo_ciclo = None   # desactiva el guarda-captura
        caso1.save(update_fields=["captura_ultimo_ciclo"])
        _aplicar_logica_ecologica(pa1, [])
        caso1.refresh_from_db()
        check("T7 INCERTIDUMBRE no participa en ciclos ecologicos",
              caso1.ciclos_limpios_consecutivos == ciclos_antes,
              f"ciclos={caso1.ciclos_limpios_consecutivos}")

        # ── T9: zona G5 ────────────────────────────────────────────────────
        ZONA_G5 = caja(-69.40, -13.10)
        pa5, pb5 = sandbox(-69.40, -13.10, c0, c1, 5)
        caso_rec = mk_caso(pa5, DET, ZONA_G5, captura=c0,
                           estado_caso=CasoAuditoria.EstadoCaso.RECUPERADO)
        encontrado = _buscar_caso_abierto(DET, ZONA_G5)
        nuevo_rec, es_nuevo_rec = _crear_o_actualizar_caso(
            parche=pb5, captura=c1, tipo_caso=DET,
            score_confianza=0.85, geom_nuevo=ZONA_G5, alertar=False,
        )
        check("T9 Tras RECUPERADO se crea un caso NUEVO",
              encontrado is None and es_nuevo_rec
              and nuevo_rec.pk != caso_rec.pk
              and nuevo_rec.captura_nacimiento_id == c1.pk,
              f"nuevo #{nuevo_rec.pk} nace en captura "
              f"{nuevo_rec.captura_nacimiento_id}")

        # ── T10 ────────────────────────────────────────────────────────────
        check("T10 Caso re-detectado conserva su captura de nacimiento",
              caso1.captura_nacimiento_id == c0.pk
              and caso1.veces_detectado == 2,
              f"nacimiento={caso1.captura_nacimiento_id} "
              f"veces={caso1.veces_detectado}")

        # ── T8/T8b: cierre automatico ──────────────────────────────────────
        cfg = ConfiguracionGlobal.get()
        umbral_previo = cfg.umbral_cierre_incertidumbre_quincenas
        cfg.umbral_cierre_incertidumbre_quincenas = 3
        cfg.save(update_fields=["umbral_cierre_incertidumbre_quincenas"])

        ultima = c1
        for i in range(3):
            ultima = mk_captura(date(2030, 2, 1) + timedelta(days=15 * i), 10 + i)

        # lleva 3 pasadas sin verse -> debe cerrarse
        pa6, _ = sandbox(-69.35, -13.10, c0, c1, 6)
        caso_cerrar = mk_caso(pa6, INC, caja(-69.35, -13.10), captura=c1)

        # visto en la ultima pasada -> no debe cerrarse
        pa7 = mk_parche(ultima, 7, 7, caja(-69.30, -13.10))
        caso_vivo = mk_caso(pa7, INC, caja(-69.30, -13.10), captura=ultima)

        res1 = cerrar_incertidumbres_obsoletas()
        caso_cerrar.refresh_from_db()
        caso_vivo.refresh_from_db()
        t8 = (caso_cerrar.estado_caso == CasoAuditoria.EstadoCaso.RECUPERADO
              and caso_vivo.estado_caso == CasoAuditoria.EstadoCaso.PENDIENTE_REVISION
              and res1.get("cerrados", 0) >= 1)

        res2 = cerrar_incertidumbres_obsoletas()
        caso_cerrar.refresh_from_db()
        t8b = (res2.get("cerrados") == 0
               and caso_cerrar.estado_caso == CasoAuditoria.EstadoCaso.RECUPERADO)

        check("T8 Cierre de INCERTIDUMBRE tras N pasadas", t8,
              f"cerrados={res1.get('cerrados')} umbral={res1.get('umbral')}")
        check("T8b Cierre idempotente (2a ejecucion sin cambios)", t8b,
              f"cerrados={res2.get('cerrados')}")

        cfg.umbral_cierre_incertidumbre_quincenas = umbral_previo
        cfg.save(update_fields=["umbral_cierre_incertidumbre_quincenas"])

        # ── T11/T12: idempotencia del re-run (Fase G5) ─────────────────────
        f = date(2031, 1, 1)
        cap_a, creada_a = CapturaSatelital.objects.get_or_create(
            fecha_adquisicion=f,
            defaults={"s3_path_raw": "",
                      "estado_liberacion": CapturaSatelital.EstadoLiberacion.PROCESANDO},
        )
        cap_b, creada_b = CapturaSatelital.objects.get_or_create(
            fecha_adquisicion=f,
            defaults={"s3_path_raw": "",
                      "estado_liberacion": CapturaSatelital.EstadoLiberacion.PROCESANDO},
        )
        doble_create_falla = False
        try:
            # savepoint anidado: en Postgres un error deja la transaccion
            # exterior abortada, hay que aislarlo
            with transaction.atomic():
                CapturaSatelital.objects.create(
                    fecha_adquisicion=f, s3_path_raw="",
                    estado_liberacion=CapturaSatelital.EstadoLiberacion.PROCESANDO,
                )
        except Exception:
            doble_create_falla = True
        check("T11 Captura reutilizada en re-ejecucion (sin IntegrityError)",
              creada_a and not creada_b and cap_a.pk == cap_b.pk
              and doble_create_falla,
              f"pk={cap_a.pk} creada={creada_a}/{creada_b}")

        g = caja(-69.25, -13.10)
        parche_a, hecho_a = ParcheProcesamiento.objects.get_or_create(
            captura=cap_a, fila_idx=1, col_idx=1,
            defaults={"s3_path_tensor": "s3://smoke/x.npy",
                      "estado_sagemaker": ParcheProcesamiento.EstadoSageMaker.PENDIENTE,
                      "geom": g},
        )
        parche_b, hecho_b = ParcheProcesamiento.objects.get_or_create(
            captura=cap_a, fila_idx=1, col_idx=1,
            defaults={"s3_path_tensor": "s3://smoke/y.npy",
                      "estado_sagemaker": ParcheProcesamiento.EstadoSageMaker.PENDIENTE,
                      "geom": g},
        )
        check("T12 Parche reutilizado en re-ejecucion (sin IntegrityError)",
              hecho_a and not hecho_b and parche_a.pk == parche_b.pk
              and parche_b.s3_path_tensor == "s3://smoke/x.npy",
              f"pk={parche_a.pk} creado={hecho_a}/{hecho_b}")

        # ── T13-T17: API (Fase G6) ─────────────────────────────────────────
        # caso nacido en la ultima pasada (cap_a es la de fecha mas reciente)
        mk_caso(parche_a, DET, caja(-69.25, -13.10), captura=cap_a)

        from django.contrib.auth.models import User as DjangoUser
        from django.test import Client
        from rest_framework_simplejwt.tokens import RefreshToken

        admin_user = (DjangoUser.objects.filter(is_superuser=True).first()
                      or DjangoUser.objects.filter(is_staff=True).first())
        cli = Client(SERVER_NAME="localhost")   # 'testserver' no esta en ALLOWED_HOSTS
        AUTH = {"HTTP_AUTHORIZATION": f"Bearer {RefreshToken.for_user(admin_user).access_token}"}

        def _pag(resp):
            """Lista de filas tanto si hay paginacion como si no."""
            if resp.status_code != 200:
                return []
            j = resp.json()
            if isinstance(j, dict):
                return j.get("results", [])
            return j if isinstance(j, list) else []

        r_todo = cli.get("/api/alertas/", **AUTH)
        filas = _pag(r_todo)
        campos_ok = all(
            k in (filas[0] if filas else {})
            for k in ("es_nueva", "veces_detectado", "fecha_nacimiento",
                      "fecha_ultima_deteccion")
        )
        check("T13 GET /api/alertas/ expone los campos nuevos",
              r_todo.status_code == 200 and filas and campos_ok,
              f"status={r_todo.status_code} filas={len(filas)} campos_ok={campos_ok}")

        r_nuevas = cli.get("/api/alertas/", {"solo_nuevas": "true"}, **AUTH)
        filas_n = _pag(r_nuevas)
        check(
            "T14 GET /api/alertas/?solo_nuevas=true devuelve SOLO las nuevas",
            r_nuevas.status_code == 200
            and len(filas_n) == 1
            and all(f["es_nueva"] for f in filas_n)
            and len(filas_n) < len(filas),
            f"total={len(filas)} solo_nuevas={len(filas_n)}",
        )

        from core.models import SectorReserva
        sector = SectorReserva.objects.first()
        if sector:
            r_zona = cli.get("/api/alertas/",
                             {"zona__icontains": sector.nombre[:6]}, **AUTH)
            filas_z = _pag(r_zona)
            zonas_ok = all(sector.nombre[:6].lower() in (f["zona"] or "").lower()
                           for f in filas_z)
            check("T15 GET /api/alertas/?zona__icontains filtra de verdad",
                  r_zona.status_code == 200 and zonas_ok,
                  f"status={r_zona.status_code} filas={len(filas_z)} "
                  f"sector={sector.nombre[:6]!r}")
        else:
            check("T15 GET /api/alertas/?zona__icontains filtra de verdad",
                  False, "no hay sectores en BD")

        r_dash = cli.get("/api/dashboard/stats/", **AUTH)
        d = r_dash.json() if r_dash.status_code == 200 else {}
        claves = ("alertas_activas", "alertas_nuevas_pasada", "alertas_totales",
                  "area_afectada_ha", "area_nueva_pasada_ha", "usuarios_activos",
                  "ultima_captura")
        tipos_ok = all(
            k in d and (isinstance(d[k], (int, float)) or isinstance(d[k], dict))
            for k in claves
        )
        check("T16 GET /api/dashboard/stats/ con los 6 KPIs nuevos",
              r_dash.status_code == 200 and tipos_ok,
              f"status={r_dash.status_code} claves_ok={tipos_ok}")

        # coherencia: lo que dice el KPI debe cuadrar con la tabla filtrada
        abiertas_nuevas = sum(1 for f in filas_n if f["estado"] == "Pendiente")
        check(
            "T17 KPI alertas_nuevas_pasada cuadra con ?solo_nuevas=true",
            d.get("alertas_nuevas_pasada") == abiertas_nuevas
            and d.get("alertas_activas", 0) <= d.get("alertas_totales", -1),
            f"kpi={d.get('alertas_nuevas_pasada')} "
            f"tabla_abiertas={abiertas_nuevas} "
            f"activas={d.get('alertas_activas')} totales={d.get('alertas_totales')}",
        )

        transaction.set_rollback(True)

    print()
    fallas = [n for e, n in RESULTADOS if e == "FALLA"]
    print(f"Resultado: {len(RESULTADOS) - len(fallas)}/{len(RESULTADOS)} PASAN")
    if fallas:
        print("FALLAS: " + "; ".join(fallas))
        return 1
    print("VEREDICTO: PASA")
    return 0


if __name__ == "__main__":
    sys.exit(main())
