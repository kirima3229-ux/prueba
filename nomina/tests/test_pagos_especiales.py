from datetime import date
from decimal import Decimal as D

import pytest
from django.urls import reverse

from apps.licencias import servicios as licencias
from apps.licencias.models import BonoNavidad, MovimientoLicencia, saldo
from apps.nomina import servicios
from apps.nomina.models import PeriodoNomina

from .conftest import crear_empleado
from .test_nomina import compania_lista  # noqa: F401


@pytest.fixture
def empleados(compania_lista):  # noqa: F811
    ana = crear_empleado(compania_lista, numero="1", ssn="234567890", nombre="Ana", tarifa="12",
                         fecha_empleo=date(2020, 1, 6))
    beto = crear_empleado(compania_lista, numero="2", ssn="345678901", nombre="Beto", tarifa="15",
                          fecha_empleo=date(2020, 1, 6))
    return ana, beto


def _bonos(compania, empleados, usuario):
    ana, beto = empleados
    licencias.calcular_bonos(compania, 2026, {ana.pk: (D("1500"), D("20000")), beto.pk: (D("100"), D("1000"))},
                             usuario, guardar=True)
    return BonoNavidad.objects.get(empleado=ana), BonoNavidad.objects.get(empleado=beto)


@pytest.mark.django_db
def test_bono_por_nomina(compania_lista, empleados, preparador, admin):  # noqa: F811
    bono_ana, bono_beto = _bonos(compania_lista, empleados, preparador)
    assert bono_ana.elegible and bono_ana.monto > 0 and not bono_beto.elegible
    periodo = servicios.pagar_bonos(compania_lista, 2026, date(2026, 12, 15), preparador)
    assert periodo.tipo == "especial" and periodo.descripcion == "Bono de Navidad 2026"
    assert [e.empleado_id for e in periodo.entradas.all()] == [bono_ana.empleado_id]
    assert periodo.entradas.get().ingresos.get().monto == bono_ana.monto
    with pytest.raises(servicios.ErrorNomina, match="pendientes"):
        servicios.pagar_bonos(compania_lista, 2026, date(2026, 12, 15), preparador)
    # En nómina, el bono no se recalcula.
    filas, *_ = licencias.calcular_bonos(compania_lista, 2026, {bono_ana.empleado_id: (D("1500"), D("1"))},
                                         preparador, guardar=True)
    bono_ana.refresh_from_db()
    assert filas[0].pagado and bono_ana.salario == D("20000")

    servicios.calcular_periodo(periodo, preparador)
    r = periodo.resultados.get()
    assert r.bruto == bono_ana.monto
    servicios.cerrar_periodo(periodo, preparador)
    bono_ana.refresh_from_db()
    assert bono_ana.estado == "pagado"

    reverso = servicios.reversar_periodo(periodo, "Monto equivocado", admin)
    bono_ana.refresh_from_db()
    assert bono_ana.estado == "calculado" and bono_ana.periodo_nomina is None
    assert reverso.bonos_navidad.count() == 0


@pytest.mark.django_db
def test_liquidacion_por_nomina(compania_lista, empleados, preparador, admin):  # noqa: F811
    from apps.calculo.mesada import ResultadoMesada, liquidar

    ana, _ = empleados
    licencias.registrar_movimiento(empleado=ana, tipo="vacaciones", clase="saldo_inicial", horas=D("40"),
                                   fecha=date(2026, 1, 1), descripcion="", usuario=preparador)
    licencias.registrar_movimiento(empleado=ana, tipo="enfermedad", clase="saldo_inicial", horas=D("16"),
                                   fecha=date(2026, 1, 1), descripcion="", usuario=preparador)
    mesada = ResultadoMesada(True, D("5000.00"), D("6.7"), 6, "Mesada de prueba")
    liq = liquidar(mesada=mesada, horas_vacaciones=saldo(ana, "vacaciones"), horas_enfermedad=saldo(ana, "enfermedad"),
                   tarifa_hora=D("12"), texto_tarifa="$12", pagar_enfermedad=False)
    periodo = servicios.crear_liquidacion(empleado=ana, liquidacion=liq, fecha_despido=date(2026, 9, 30),
                                          fecha_pago=date(2026, 10, 2), incluir_mesada=True, usuario=preparador)
    entrada = periodo.entradas.get()
    assert sorted((i.concepto.codigo, i.monto) for i in entrada.ingresos.all()) == [
        ("mesada", D("5000.00")), ("vacaciones_liquidadas", D("480.00"))]
    assert entrada.horas_vacaciones_liquidadas == D("40") and entrada.horas_enfermedad_liquidadas == 0
    servicios.calcular_periodo(periodo, preparador)
    r = periodo.resultados.get()
    assert r.bruto == D("5480.00") and r.trib_pr == D("480.00")  # la mesada no tributa en PR (POR VERIFICAR)
    servicios.cerrar_periodo(periodo, preparador)
    assert saldo(ana, "vacaciones") == 0 and saldo(ana, "enfermedad") == D("16")
    assert MovimientoLicencia.objects.filter(empleado=ana, clase="liquidacion", periodo_nomina=periodo).count() == 1
    servicios.reversar_periodo(periodo, "Se reconsideró", admin)
    assert saldo(ana, "vacaciones") == D("40")

    # Renuncia: sin mesada, sólo licencias.
    periodo2 = servicios.crear_liquidacion(empleado=ana, liquidacion=liq, fecha_despido=date(2026, 9, 30),
                                           fecha_pago=date(2026, 10, 2), incluir_mesada=False, usuario=preparador)
    assert [i.concepto.codigo for i in periodo2.entradas.get().ingresos.all()] == ["vacaciones_liquidadas"]


@pytest.mark.django_db
def test_pantallas(cliente_preparador, compania_lista, empleados, preparador):  # noqa: F811
    ana, _ = empleados
    _bonos(compania_lista, empleados, preparador)
    url = reverse("licencias:bono") + "?anio=2026"
    assert "Crear nómina del bono" in cliente_preparador.get(url).content.decode()
    respuesta = cliente_preparador.post(reverse("licencias:bono"), {"anio": "2026", "accion": "pagar_nomina",
                                                                    "fecha_pago": "2026-12-15"})
    periodo = PeriodoNomina.objects.get(descripcion="Bono de Navidad 2026")
    assert respuesta["Location"] == reverse("nomina:detalle", args=[periodo.pk])
    assert "En nómina" in cliente_preparador.get(url).content.decode()

    licencias.registrar_movimiento(empleado=ana, tipo="vacaciones", clase="saldo_inicial", horas=D("8"),
                                   fecha=date(2026, 1, 1), descripcion="", usuario=preparador)
    datos = {"empleado": ana.pk, "fecha_despido": "09/30/2026", "salario_mensual": "2000"}
    html = cliente_preparador.post(reverse("calculo:mesada"), datos).content.decode()
    assert "Crear nómina final" in html
    respuesta = cliente_preparador.post(reverse("calculo:mesada"), {**datos, "accion": "pagar",
                                                                    "fecha_pago": "2026-10-02",
                                                                    "incluir_mesada": "on"})
    final = PeriodoNomina.objects.get(descripcion__startswith="Liquidación de Ana")
    assert respuesta["Location"] == reverse("nomina:detalle", args=[final.pk])
    codigos = {i.concepto.codigo for i in final.entradas.get().ingresos.all()}
    assert codigos == {"mesada", "vacaciones_liquidadas"}
